"""
Yahoo Finance access: shared ``requests`` session (User-Agent), retries with backoff,
and defensive empty structures so the Streamlit UI never dies on rate limits or gaps.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
import yfinance as yf

T = TypeVar("T")

# Reduce basic bot blocking / empty JSON responses from Yahoo edge.
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_tls = threading.local()


def _thread_session() -> requests.Session:
    """One Session per worker thread (safe with ThreadPoolExecutor)."""
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": _DEFAULT_UA,
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "application/json,text/html,*/*;q=0.8",
                "Referer": "https://finance.yahoo.com/",
                "Origin": "https://finance.yahoo.com",
            }
        )
        _tls.session = s
    return s


def yfinance_ticker(symbol: str) -> yf.Ticker:
    """``yf.Ticker`` bound to our session (fresh symbol normalization each call)."""
    sym = str(symbol).upper().strip()
    return yf.Ticker(sym, session=_thread_session())


def yf_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 1.25,
    backoff: float = 1.85,
    retry_on_none: bool = True,
) -> Optional[T]:
    """
    Call ``fn`` with exponential backoff. Retries on exceptions; optionally when
    the result is ``None`` (legacy behaviour for history calls that return no rows).
    """
    last: Optional[T] = None
    for i in range(attempts):
        try:
            out = fn()
            last = out
            if not retry_on_none or out is not None:
                return out
        except Exception:
            last = None
        if i < attempts - 1:
            time.sleep(base_delay * (backoff**i))
    return last


def yf_retry_exceptions(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 1.25,
    backoff: float = 1.85,
    default: T,
) -> T:
    """Retry only on exceptions; return ``default`` if all attempts fail."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i < attempts - 1:
                time.sleep(base_delay * (backoff**i))
    return default


def fetch_stock(ticker: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    def _once() -> Optional[pd.DataFrame]:
        df = yfinance_ticker(ticker).history(period=period, interval=interval)
        if df is None or df.empty:
            return None
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df

    out = yf_retry(_once, retry_on_none=True, attempts=6, base_delay=1.8, backoff=1.65)
    if out is not None and not out.empty:
        return out
    fb = fetch_stock_chart_api(ticker, period, interval)
    if fb is not None and not fb.empty:
        return fb
    return None


def ticker_pct_change_1d(symbol: str) -> Optional[float]:
    def _once() -> Optional[float]:
        sym = str(symbol).upper().strip()
        df = yfinance_ticker(sym).history(period="10d", interval="1d")
        if df is None or df.empty or len(df) < 2 or "Close" not in df.columns:
            return None
        c = pd.to_numeric(df["Close"], errors="coerce")
        if c.isna().iloc[-1] or c.isna().iloc[-2]:
            return None
        return float((c.iloc[-1] / c.iloc[-2] - 1.0) * 100.0)

    sym_u = str(symbol).upper().strip()
    out = yf_retry(_once, retry_on_none=True, attempts=5, base_delay=1.5, backoff=1.6)
    if out is not None:
        return out
    df = fetch_stock_chart_api(sym_u, "1mo", "1d")
    if df is None or len(df) < 2 or "Close" not in df.columns:
        return None
    c = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(c) < 2:
        return None
    return float((c.iloc[-1] / c.iloc[-2] - 1.0) * 100.0)


def fetch_intraday_series(symbol: str, period: str = "5d", interval: str = "1h") -> pd.Series:
    def _once() -> pd.Series:
        hist = yfinance_ticker(symbol).history(period=period, interval=interval)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return pd.Series(dtype=float)
        s = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        return s

    return yf_retry_exceptions(_once, default=pd.Series(dtype=float))


def fetch_info(ticker: str) -> dict[str, Any]:
    def _once() -> dict[str, Any]:
        data = yfinance_ticker(ticker).info
        return data if isinstance(data, dict) else {}

    return yf_retry_exceptions(_once, default={})


def _frames_from_chain(chain_obj: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    if chain_obj is None:
        return pd.DataFrame(), pd.DataFrame()
    try:
        c_raw = getattr(chain_obj, "calls", None)
        p_raw = getattr(chain_obj, "puts", None)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()
    try:
        calls_df = c_raw.copy() if c_raw is not None and not getattr(c_raw, "empty", True) else pd.DataFrame()
        puts_df = p_raw.copy() if p_raw is not None and not getattr(p_raw, "empty", True) else pd.DataFrame()
    except Exception:
        return pd.DataFrame(), pd.DataFrame()
    if not isinstance(calls_df, pd.DataFrame):
        calls_df = pd.DataFrame()
    if not isinstance(puts_df, pd.DataFrame):
        puts_df = pd.DataFrame()
    return calls_df, puts_df


def fetch_options(ticker: str, exp: Optional[str] = None) -> tuple[tuple[pd.DataFrame, pd.DataFrame], list[str]]:
    """
    Returns ``((calls_df, puts_df), exps)``. Always safe to unpack; frames may be empty.
    """
    empty: tuple[pd.DataFrame, pd.DataFrame] = (pd.DataFrame(), pd.DataFrame())

    def _load() -> tuple[tuple[pd.DataFrame, pd.DataFrame], list[str]]:
        t = yfinance_ticker(ticker)
        raw_exps = getattr(t, "options", None)
        if raw_exps is None:
            return empty, []
        exps = [str(x) for x in list(raw_exps)]
        if not exps:
            return empty, []
        if exp is None:
            return empty, exps
        primary = exp if exp in exps else exps[0]
        candidates = [primary]
        for e in exps:
            if e not in candidates:
                candidates.append(e)
            if len(candidates) >= 8:
                break
        last_empty = empty
        for pick in candidates:
            try:
                chain = t.option_chain(pick)
                calls_df, puts_df = _frames_from_chain(chain)
                if not calls_df.empty or not puts_df.empty:
                    return (calls_df, puts_df), exps
                last_empty = (calls_df, puts_df)
            except Exception:
                continue
        return last_empty, exps

    return yf_retry_exceptions(_load, default=(empty, []))


def compute_iv_rank_proxy(sym: str, spot: float, ref_iv_pct: float) -> Optional[dict[str, Any]]:
    if ref_iv_pct is None or spot is None or spot <= 0:
        return None

    def _run() -> Optional[dict[str, Any]]:
        t = yfinance_ticker(sym)
        exps = list(getattr(t, "options", None) or [])[:14]
        if len(exps) < 2:
            return None
        samples: list[float] = []
        for exp in exps:
            try:
                chain = t.option_chain(exp)
                c = getattr(chain, "calls", None)
                if c is None or not isinstance(c, pd.DataFrame) or c.empty:
                    continue
                if "impliedVolatility" not in c.columns or "strike" not in c.columns:
                    continue
                c2 = c[c["impliedVolatility"].notna() & (c["impliedVolatility"] > 0)]
                if c2.empty:
                    continue
                strikes = pd.to_numeric(c2["strike"], errors="coerce")
                if strikes.isna().all():
                    continue
                ix = (strikes - spot).abs().idxmin()
                iv = float(c2.loc[ix, "impliedVolatility"]) * 100.0
                if iv > 0:
                    samples.append(iv)
            except Exception:
                continue
        if len(samples) < 2:
            return None
        lo, hi = min(samples), max(samples)
        if hi <= lo + 0.25:
            return {"rank": 50.0, "lo": lo, "hi": hi}
        rank = (float(ref_iv_pct) - lo) / (hi - lo) * 100.0
        rank = max(0.0, min(100.0, rank))
        return {"rank": rank, "lo": lo, "hi": hi}

    return yf_retry(_run, attempts=3, retry_on_none=True)


def fetch_news(ticker: str) -> list[dict[str, str]]:
    def _once() -> list[dict[str, str]]:
        raw = yfinance_ticker(ticker).news or []
        items: list[dict[str, str]] = []
        for n in raw[:8]:
            title = n.get("title") or n.get("content", {}).get("title", "")
            link = n.get("link") or n.get("content", {}).get("canonicalUrl", {}).get("url", "")
            pub = n.get("publisher") or n.get("content", {}).get("provider", {}).get("displayName", "")
            pt = ""
            try:
                ts = n.get("providerPublishTime") or n.get("content", {}).get("pubDate", "")
                if isinstance(ts, (int, float)):
                    pt = datetime.fromtimestamp(ts).strftime("%b %d, %H:%M")
                elif isinstance(ts, str) and ts:
                    pt = ts[:16]
            except Exception:
                pass
            if title:
                items.append({"title": title, "link": link, "pub": pub, "time": pt})
        return items

    return yf_retry_exceptions(_once, default=[])


def _chart_range_interval(period: str, interval: str) -> tuple[str, str]:
    """Map yfinance-style period/interval to v8 chart ``range`` + ``interval`` query params."""
    p = (period or "1y").strip().lower()
    iv = (interval or "1d").strip().lower()
    ranges_ok = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    iv_ok = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    rng = p if p in ranges_ok else "1y"
    iv2 = iv if iv in iv_ok else "1d"
    return rng, iv2


def _frame_from_chart_result(res: dict) -> Optional[pd.DataFrame]:
    ts = res.get("timestamp")
    if not ts:
        return None
    quotes = (res.get("indicators") or {}).get("quote")
    if not quotes or not isinstance(quotes, list):
        return None
    q = quotes[0]
    o = q.get("open")
    h = q.get("high")
    low = q.get("low")
    c = q.get("close")
    v = q.get("volume")
    if c is None or not isinstance(c, list) or len(c) != len(ts):
        return None
    idx = pd.to_datetime(ts, unit="s")
    df = pd.DataFrame(
        {
            "Open": o,
            "High": h,
            "Low": low,
            "Close": c,
            "Volume": v if isinstance(v, list) and len(v) == len(ts) else [np.nan] * len(ts),
        },
        index=idx,
    )
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.dropna(subset=["Close"], how="any")
    if df.empty:
        return None
    for col in ("Open", "High", "Low", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch_stock_chart_api(symbol: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """
    Direct Yahoo ``v8/finance/chart`` fetch (requests). Often works when ``yfinance`` returns
    empty rows on cloud/datacenter IPs (throttling / curl stack differences).
    Retries on HTTP 429 with ``Retry-After`` / backoff.
    """
    sym = str(symbol).upper().strip()
    rng, iv = _chart_range_interval(period, interval)
    path = quote(sym, safe="")
    sess = _thread_session()
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{path}"
        for attempt in range(4):
            js = None
            try:
                r = sess.get(url, params={"range": rng, "interval": iv}, timeout=45)
                if r.status_code == 429:
                    ra = r.headers.get("Retry-After")
                    try:
                        wait_s = float(ra) if ra else 0.0
                    except ValueError:
                        wait_s = 0.0
                    wait_s = max(wait_s, 2.0 + attempt * 2.5)
                    time.sleep(min(wait_s, 60.0))
                    continue
                r.raise_for_status()
                js = r.json()
            except Exception:
                time.sleep(1.4 + attempt * 1.8)
                continue
            if not isinstance(js, dict):
                continue
            chart = js.get("chart") or {}
            err = chart.get("error")
            if err:
                if isinstance(err, dict):
                    desc = str(err.get("description", "")).lower()
                else:
                    desc = str(err).lower()
                if "rate" in desc or "too many" in desc or "429" in desc:
                    time.sleep(3.0 + attempt * 2.0)
                    continue
                break
            results = chart.get("result")
            if not results:
                break
            df = _frame_from_chart_result(results[0])
            if df is not None and not df.empty:
                return df
            break
    return None


def fetch_earnings_date(ticker: str) -> Any:
    def _once() -> Any:
        cal = yfinance_ticker(ticker).calendar
        if cal is None:
            return None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, (list, tuple)) and ed:
                return ed[0]
            return ed if ed else None
        if isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.columns:
                return cal["Earnings Date"].iloc[0]
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"]
                return val.iloc[0] if hasattr(val, "iloc") else val
        return None

    return yf_retry_exceptions(_once, default=None)


def _earnings_ts_normalize(x: Any) -> pd.Timestamp:
    if isinstance(x, str) and len(x) >= 10:
        t = pd.Timestamp(x[:10])
    else:
        t = pd.Timestamp(x)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t.normalize()


def _earnings_float_or_none(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        if isinstance(x, str) and not x.strip():
            return None
        v = float(x)
        if np.isnan(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _earnings_find_col(df: pd.DataFrame, *candidates: str) -> Optional[str]:
    cols = list(df.columns)
    norm = {str(c).strip().lower().replace(" ", ""): c for c in cols}
    for cand in candidates:
        key = cand.strip().lower().replace(" ", "")
        if key in norm:
            return norm[key]
        if cand in cols:
            return cand
    return None


def fetch_earnings_calendar_display(ticker: str) -> tuple[pd.DataFrame, Optional[int]]:
    """Build earnings calendar rows for the desk table. Returns (df, highlight_row_index | None)."""
    today_d = datetime.now().date()

    def _build() -> tuple[pd.DataFrame, Optional[int]]:
        rows: list[dict[str, Any]] = []
        t = yfinance_ticker(ticker)
        ed = getattr(t, "earnings_dates", None)
        if isinstance(ed, pd.DataFrame) and not ed.empty:
            ed = ed.copy()
            ed.index = [_earnings_ts_normalize(i) for i in ed.index]
            ed = ed.sort_index(ascending=True)
            cutoff = pd.Timestamp(today_d) - pd.Timedelta(days=800)
            ed = ed[ed.index >= cutoff]
            if len(ed) > 18:
                ed = ed.iloc[-18:]

            c_est = _earnings_find_col(ed, "EPS Estimate", "eps estimate")
            c_rep = _earnings_find_col(ed, "Reported EPS", "Reported Eps")
            c_sur = _earnings_find_col(ed, "Surprise(%)", "Surprise (%)", "Surprise %")

            for dt_ts, row in ed.iterrows():
                d = dt_ts.date() if hasattr(dt_ts, "date") else pd.Timestamp(dt_ts).date()
                est = row[c_est] if c_est else np.nan
                rep = row[c_rep] if c_rep else np.nan
                sur = row[c_sur] if c_sur else np.nan
                has_rep = pd.notna(rep) and str(rep).strip() != ""
                if has_rep:
                    status = "Reported"
                elif d >= today_d:
                    status = "Upcoming"
                else:
                    status = "Past"
                rows.append(
                    {
                        "Earnings date": d,
                        "EPS estimate": _earnings_float_or_none(est),
                        "Reported EPS": _earnings_float_or_none(rep),
                        "Surprise (%)": _earnings_float_or_none(sur),
                        "Status": status,
                    }
                )

        if not rows:
            raw = fetch_earnings_date(ticker)
            if raw is not None:
                try:
                    dt_ts = _earnings_ts_normalize(raw)
                    d = dt_ts.date()
                    status = "Upcoming" if d >= today_d else "Past"
                    rows.append(
                        {
                            "Earnings date": d,
                            "EPS estimate": None,
                            "Reported EPS": None,
                            "Surprise (%)": None,
                            "Status": status,
                        }
                    )
                except Exception:
                    pass

        if not rows:
            return pd.DataFrame(), None

        df = pd.DataFrame(rows)
        df = df.sort_values("Earnings date", ascending=False, kind="mergesort").reset_index(drop=True)

        future_df = df[df["Earnings date"] >= today_d]
        highlight_idx = None
        if not future_df.empty:
            next_d = future_df["Earnings date"].min()
            hit = df.index[df["Earnings date"] == next_d]
            if len(hit):
                highlight_idx = int(hit[0])

        return df, highlight_idx

    return yf_retry_exceptions(_build, default=(pd.DataFrame(), None))


def fetch_macro() -> dict[str, dict[str, float]]:
    data: dict[str, dict[str, float]] = {}
    for label, sym in {
        "VIX": "^VIX",
        "10Y Yield": "^TNX",
        "DXY (UUP)": "UUP",
        "SPY": "SPY",
        "QQQ": "QQQ",
    }.items():

        def _point() -> Optional[dict[str, float]]:
            df = yfinance_ticker(sym).history(period="5d")
            if df is None or df.empty or "Close" not in df.columns:
                return None
            close = pd.to_numeric(df["Close"], errors="coerce").dropna()
            if close.empty:
                return None
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else last
            return {"price": last, "chg": (last / prev - 1) * 100}

        got = yf_retry(_point, attempts=3, retry_on_none=True)
        if got is not None:
            data[label] = got

    if "10Y Yield" not in data:
        data["10Y Yield"] = {"price": 4.5, "chg": 0.0}
    if "VIX" not in data:
        data["VIX"] = {"price": 20.0, "chg": 0.0}
    return data
