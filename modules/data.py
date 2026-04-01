"""
Data layer — yfinance fetchers with retry/backoff, caching, macro dashboard.
"""
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import time
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────────
# RETRY WRAPPER — handles yfinance throttling gracefully
# ─────────────────────────────────────────────────────────────────────────
def retry_fetch(fn, retries=3, delay=2):
    """Call fn() up to `retries` times with exponential backoff."""
    for attempt in range(retries):
        try:
            result = fn()
            if result is not None:
                return result
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    return None


def _yfinance_ticker(symbol: str):
    """Fresh ``yf.Ticker`` per call — avoids stale sessions and unbounded cached connections on large watchlists."""
    return yf.Ticker(str(symbol).upper().strip())


def _client_suggests_mobile_chart():
    """Best-effort mobile UA hint for tighter Plotly margins (server-side; no layout jank)."""
    try:
        _hdrs = st.context.headers
        h = _hdrs.to_dict() if _hdrs is not None else {}
        lk = {str(k).lower(): v for k, v in h.items()}
        ua = str(lk.get("user-agent") or lk.get("user_agent") or "").lower()
        return any(tok in ua for tok in ("iphone", "ipad", "ipod", "android", "mobile"))
    except Exception:
        return False


# Plotly toolbar: vertical mode bar avoids clashing with the legend
_PLOTLY_UI_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "modeBarOrientation": "v",
    "scrollZoom": False,
}

# Dashboard theme — transparent canvases, faint grids, premium palette (blues / green / red)
_PLOTLY_PAPER_BG = "rgba(0,0,0,0)"
_PLOTLY_PLOT_BG = "rgba(0,0,0,0)"
_PLOTLY_GRID = "rgba(128,128,128,0.2)"
_PLOTLY_FONT_MAIN = dict(family="Inter, system-ui, JetBrains Mono, monospace", size=11, color="#cbd5e1")
_PLOTLY_AXIS_TITLE = dict(title_font=dict(size=11, color="#94a3b8"))
_PLOTLY_CASH_UP = "#34d399"
_PLOTLY_CASH_DOWN = "#f87171"
_PLOTLY_BLUE = "#3b82f6"
_PLOTLY_BLUE_DEEP = "#2563eb"
_PLOTLY_BLUE_DEEPER = "#1e40af"
_PLOTLY_SLATE = "#64748b"


def fetch_stock(ticker, period="1y", interval="1d"):
    def _fetch():
        df = _yfinance_ticker(ticker).history(period=period, interval=interval)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    return retry_fetch(_fetch)


@st.cache_data(ttl=120)
def _ticker_pct_change_1d(symbol: str):
    """Approximate last session % change for watchlist tape (cached per symbol)."""
    try:
        sym = str(symbol).upper().strip()
        df = _yfinance_ticker(sym).history(period="10d", interval="1d")
        if df is None or df.empty or len(df) < 2:
            return None
        c = df["Close"]
        return float((c.iloc[-1] / c.iloc[-2] - 1.0) * 100.0)
    except Exception:
        return None


@st.cache_data(ttl=300)
def fetch_intraday_series(symbol, period="5d", interval="1h"):
    """Cached intraday close series for compact UI sparklines."""
    try:
        hist = _yfinance_ticker(symbol).history(period=period, interval=interval)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return pd.Series(dtype=float)
        s = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        return s
    except Exception:
        return pd.Series(dtype=float)

@st.cache_data(ttl=300)
def fetch_info(ticker):
    try:
        return _yfinance_ticker(ticker).info
    except Exception:
        return {}

@st.cache_data(ttl=300)
def fetch_options(ticker, exp=None):
    """Fetch options chain. Always returns ((calls_df, puts_df), exps) for stable unpacking.

    When ``exp`` is None, returns empty dataframes and only the expiration list (no ``option_chain``
    download). Call again with a concrete expiry when you need strikes. This avoids pulling the
    nearest expiry chain twice on every dashboard load.

    If the requested expiry returns empty frames (illiquid / API gap), we walk forward through
    nearby listed expiries so BLUF and the Execution Strip never assume non-empty strikes."""
    empty = (pd.DataFrame(), pd.DataFrame())

    def _frames_from_chain(chain_obj):
        if chain_obj is None:
            return pd.DataFrame(), pd.DataFrame()
        c_raw, p_raw = chain_obj.calls, chain_obj.puts
        calls_df = c_raw.copy() if c_raw is not None and not c_raw.empty else pd.DataFrame()
        puts_df = p_raw.copy() if p_raw is not None and not p_raw.empty else pd.DataFrame()
        return calls_df, puts_df

    try:
        t = _yfinance_ticker(ticker)
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
    except Exception:
        return empty, []


@st.cache_data(ttl=900)
def compute_iv_rank_proxy(sym: str, spot: float, ref_iv_pct: float):
    """Where ``ref_iv_pct`` sits between min/max ATM call IV sampled across visible expiries.

    Yahoo does not expose a true 52-week ATM IV series per equity; this **term-structure proxy**
    compares your reference IV (e.g. prop-desk strike) to the cheapest vs richest ATM IV across
    listed expirations. Returns ``dict`` with ``rank`` (0–100), ``lo``, ``hi``, or ``None``."""
    if ref_iv_pct is None or spot is None or spot <= 0:
        return None
    try:
        t = _yfinance_ticker(sym)
        exps = list(getattr(t, "options", None) or [])[:14]
        if len(exps) < 2:
            return None
        samples = []
        for exp in exps:
            try:
                chain = t.option_chain(exp)
                c = chain.calls
                if c is None or c.empty or "impliedVolatility" not in c.columns:
                    continue
                c = c[c["impliedVolatility"].notna() & (c["impliedVolatility"] > 0)]
                if c.empty or "strike" not in c.columns:
                    continue
                ix = (pd.to_numeric(c["strike"], errors="coerce") - spot).abs().idxmin()
                iv = float(c.loc[ix, "impliedVolatility"]) * 100.0
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
    except Exception:
        return None


@st.cache_data(ttl=600)
def fetch_news(ticker):
    try:
        raw = _yfinance_ticker(ticker).news or []
        items = []
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
    except Exception:
        return []

def _earnings_date_from_quote_info(info: dict):
    """Fallback when ``calendar`` is empty: next earnings unix timestamp from quote summary."""
    if not info:
        return None
    ts = info.get("earningsTimestamp") or info.get("earningsCallTimestampStart")
    try:
        if ts is None:
            return None
        if isinstance(ts, (int, float)) and ts > 1e9:
            return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        pass
    return None


@st.cache_data(ttl=3600)
def fetch_earnings_date(ticker):
    """Fetch next earnings date from yfinance corporate calendar, then quote-summary timestamps."""
    try:
        cal = _yfinance_ticker(ticker).calendar
        if cal is not None:
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, (list, tuple)) and ed:
                    return ed[0]
                if ed:
                    return ed
            elif isinstance(cal, pd.DataFrame):
                if "Earnings Date" in cal.columns:
                    v = cal["Earnings Date"].iloc[0]
                    if pd.notna(v):
                        return v
                if "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    v = val.iloc[0] if hasattr(val, "iloc") else val
                    if pd.notna(v):
                        return v
    except Exception:
        pass
    try:
        from_info = _earnings_date_from_quote_info(fetch_info(ticker))
        if from_info:
            return from_info
    except Exception:
        pass
    return None


def _earnings_ts_normalize(x):
    """Naive midnight timestamp for calendar / earnings_dates index values."""
    if isinstance(x, str) and len(x) >= 10:
        t = pd.Timestamp(x[:10])
    else:
        t = pd.Timestamp(x)
    if t.tzinfo is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t.normalize()


def _earnings_float_or_none(x):
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


def _earnings_find_col(df: pd.DataFrame, *candidates: str):
    cols = list(df.columns)
    norm = {str(c).strip().lower().replace(" ", ""): c for c in cols}
    for cand in candidates:
        key = cand.strip().lower().replace(" ", "")
        if key in norm:
            return norm[key]
        if cand in cols:
            return cand
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings_calendar_display(ticker: str):
    """Build earnings calendar rows for the desk table. Returns (df, highlight_row_index | None)."""
    today_d = datetime.now().date()
    rows = []
    try:
        t = _yfinance_ticker(ticker)
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
    except Exception:
        return pd.DataFrame(), None


@st.cache_data(ttl=300)
def fetch_macro():
    data = {}
    for label, sym in {"VIX": "^VIX", "10Y Yield": "^TNX", "DXY (UUP)": "UUP", "SPY": "SPY", "QQQ": "QQQ"}.items():
        try:
            df = _yfinance_ticker(sym).history(period="5d")
            if not df.empty:
                last = df["Close"].iloc[-1]
                prev = df["Close"].iloc[-2] if len(df) >= 2 else last
                data[label] = {"price": last, "chg": (last / prev - 1) * 100}
        except Exception:
            pass
    if "10Y Yield" not in data:
        data["10Y Yield"] = {"price": 4.5, "chg": 0.0}
    if "VIX" not in data:
        data["VIX"] = {"price": 20.0, "chg": 0.0}
    return data

