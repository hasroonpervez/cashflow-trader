"""
Data layer — yfinance fetchers with retry/backoff, caching, macro dashboard.
"""
from __future__ import annotations

import os
import sys
import streamlit as st
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import time
from curl_cffi import requests as curl_requests
from datetime import datetime, timedelta
from typing import NamedTuple, Optional

from .utils import log_warn

# ~90 trading sessions RS vs SPY (growth-factor ratio) on date-aligned closes from the batch panel.
_RS_SPY_LOOKBACK_SESSIONS = 90

# yfinance 0.2+ requires curl_cffi sessions for Yahoo (TLS fingerprinting). One shared
# session for all Tickers, ``yf.download``, and direct JSON calls — connection reuse and
# consistent cookies. Community Cloud empty bars + “possibly delisted” are usually
# throttling on shared egress, not actual delistings.
#
# yfinance’s ``YfData._make_request`` passes an explicit ``timeout`` (often 30) into
# ``session.get``; ``curl_cffi`` uses that value over ``Session``’s default ``self.timeout``,
# so a plain short session default is not enough. We (1) subclass ``Session.request`` to
# force ``_YAHOO_YF_TIMEOUT`` and (2) monkey-patch ``YfData`` to clamp timeouts and bind the
# singleton to ``_YAHOO_SESSION`` before any ticker touches a default chrome session.
_YAHOO_YF_TIMEOUT = 5.0


class _ForcedTimeoutSession(curl_requests.Session):
    """``curl_cffi`` session that always uses ``_YAHOO_YF_TIMEOUT`` regardless of caller."""

    def request(self, method, url, **kwargs):
        kwargs["timeout"] = _YAHOO_YF_TIMEOUT
        return super().request(method, url, **kwargs)


_YAHOO_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.5 Safari/605.1.15"
)
_YAHOO_SESSION = _ForcedTimeoutSession(impersonate="safari15_5", timeout=_YAHOO_YF_TIMEOUT)
_YAHOO_SESSION.headers.update({"Accept-Language": "en-US,en;q=0.9"})

# Idempotency marker lives on ``YfData`` so ``importlib.reload(modules.data)`` cannot stack
# wrappers on an already-patched class in the same process.
_YFIN_PATCH_MARKER = "_cashflow_trader_yahoo_timeout_v1"


def _clamp_yahoo_http_timeout(timeout) -> float:
    try:
        if timeout is None:
            return float(_YAHOO_YF_TIMEOUT)
        return min(float(timeout), float(_YAHOO_YF_TIMEOUT))
    except (TypeError, ValueError):
        return float(_YAHOO_YF_TIMEOUT)


def _bind_yfdata_session() -> None:
    """Always safe: point the ``YfData`` singleton at our session (handles races / reloads)."""
    try:
        from yfinance.data import YfData

        YfData(session=_YAHOO_SESSION)
    except Exception as e:
        log_warn("YfData session bind", e)


def _patch_yfinance_data_layer_timeout() -> None:
    """Cap ``YfData`` HTTP timeouts and bind singleton. Never raises — import must not fail."""
    try:
        from yfinance.data import YfData
    except Exception as e:
        print(
            f"[cashflow-trader] WARNING: yfinance.data import failed ({type(e).__name__}: {e}).",
            file=sys.stderr,
            flush=True,
        )
        _bind_yfdata_session()
        return

    if getattr(YfData, _YFIN_PATCH_MARKER, False):
        _bind_yfdata_session()
        return

    try:
        _orig_make = YfData._make_request
        _orig_crumb = YfData._get_cookie_and_crumb

        def _make_request_cap(self, url, request_method, body=None, params=None, timeout=30):
            t = _clamp_yahoo_http_timeout(timeout)
            return _orig_make(self, url, request_method, body=body, params=params, timeout=t)

        def _get_cookie_and_crumb_cap(self, timeout=30):
            t = _clamp_yahoo_http_timeout(timeout)
            return _orig_crumb(self, t)

        YfData._make_request = _make_request_cap
        YfData._get_cookie_and_crumb = _get_cookie_and_crumb_cap
        setattr(YfData, _YFIN_PATCH_MARKER, True)
    except Exception as e:
        print(
            f"[cashflow-trader] WARNING: yfinance YfData timeout patch failed ({type(e).__name__}: {e}); "
            "relying on _ForcedTimeoutSession only.",
            file=sys.stderr,
            flush=True,
        )
    _bind_yfdata_session()


_patch_yfinance_data_layer_timeout()

# Yahoo JSON API (same family yfinance uses) — fallback when Ticker.options is transiently empty.
_YAHOO_OPTIONS_HEADERS = {
    "User-Agent": _YAHOO_BROWSER_UA,
    "Accept": "application/json",
}

# ─────────────────────────────────────────────────────────────────────────
# RETRY WRAPPER — handles yfinance throttling gracefully
# ─────────────────────────────────────────────────────────────────────────
def _is_yahoo_timeout_error(exc: BaseException) -> bool:
    """True for curl tar-pit / read timeouts — do not burn extra retries + sleeps."""
    if type(exc).__name__ == "Timeout":
        return True
    msg = str(exc)
    return "curl: (28)" in msg or "Operation timed out" in msg


def retry_fetch(fn, retries=3, delay=2):
    """Call fn() up to `retries` times with exponential backoff on *exceptions* only.

    A normal return value (including ``None``) is returned immediately. Retrying on
    ``None`` would triple-call Yahoo for empty history (rate limits / Cloud blocks)
    and can push script runs past Streamlit health-check timeouts.

    Timeout / curl (28) returns immediately (no retries) so one slow Yahoo response
    cannot stack into tens of seconds per ticker.
    """
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if _is_yahoo_timeout_error(e):
                return None
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    return None


def _yfinance_ticker(symbol: str):
    """New ``yf.Ticker`` per symbol; HTTP uses ``_YAHOO_SESSION``. Raises ``ValueError`` if symbol empty."""
    sym = str(symbol).upper().strip()
    if not sym:
        raise ValueError("ticker symbol is empty")
    return yf.Ticker(sym, session=_YAHOO_SESSION)


def _option_expirations_yahoo_http(symbol: str) -> list[str]:
    """List YYYY-MM-DD expiries from Yahoo's v7 options endpoint (same session as yfinance)."""
    sym = str(symbol).upper().strip()
    if not sym:
        return []
    url = f"https://query2.finance.yahoo.com/v7/finance/options/{sym}"
    try:
        r = _YAHOO_SESSION.get(url, headers=_YAHOO_OPTIONS_HEADERS)
        if r.status_code != 200:
            return []
        payload = r.json()
        results = (payload.get("optionChain") or {}).get("result") or []
        if not results:
            return []
        exp_unix = results[0].get("expirationDates") or []
        out: list[str] = []
        for u in exp_unix:
            try:
                ts = int(u)
                if ts > 1e9:
                    out.append(datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"))
            except (TypeError, ValueError, OSError):
                continue
        return sorted(set(out))
    except Exception:
        return []


def _norm_option_expiry_str(x) -> str:
    """Normalize any yfinance / API value to YYYY-MM-DD for stable lookups."""
    if x is None:
        return ""
    s = str(x).strip()
    return s[:10] if len(s) >= 10 else s


def _option_expirations_yfinance(symbol: str, attempts: int = 5) -> list[str]:
    """Read Ticker.options with backoff; prime with a small history pull on first try."""
    sym = str(symbol).upper().strip()
    for attempt in range(attempts):
        try:
            t = _yfinance_ticker(sym)
            if attempt == 0:
                try:
                    t.history(period="5d", interval="1d", timeout=_YAHOO_YF_TIMEOUT)
                except Exception as e:
                    log_warn(f"option expirations history prime ({sym})", e)
            raw = getattr(t, "options", None)
            if raw is not None:
                lst = [_norm_option_expiry_str(x) for x in list(raw)]
                lst = [e for e in lst if len(e) >= 10]
                if lst:
                    return lst
        except Exception as e:
            log_warn(f"option expirations yfinance attempt {attempt + 1}/{attempts} ({sym})", e)
        if attempt < attempts - 1:
            time.sleep(0.12 * (2**attempt))
    return []


def _resolve_option_expiration_strings(symbol: str) -> list[str]:
    """Merge yfinance listing + HTTP fallback; de-dupe and sort (chronological)."""
    seen: list[str] = []
    for src in (_option_expirations_yfinance(symbol), _option_expirations_yahoo_http(symbol)):
        for e in src:
            n = _norm_option_expiry_str(e)
            if len(n) >= 10 and n not in seen:
                seen.append(n)
    if not seen:
        return []
    try:
        seen.sort(key=lambda s: datetime.strptime(s[:10], "%Y-%m-%d"))
    except Exception:
        seen.sort()
    return seen


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


def _alphavantage_api_key() -> Optional[str]:
    k = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if k:
        return k
    try:
        s = st.secrets.get("ALPHAVANTAGE_API_KEY", "")
        return str(s).strip() or None
    except Exception:
        return None


def _coerce_finite_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return v


def _alphavantage_query(params: dict) -> Optional[dict]:
    key = _alphavantage_api_key()
    if not key:
        return None
    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={**params, "apikey": key},
            timeout=20,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("Error Message") or payload.get("Note") or payload.get("Information"):
        return None
    return payload


def _fcf_from_av_cash_flow_report(report: dict) -> Optional[float]:
    if not isinstance(report, dict):
        return None
    ocf = _coerce_finite_float(report.get("operatingCashflow"))
    if ocf is None:
        return None
    capex = _coerce_finite_float(report.get("capitalExpenditures"))
    if capex is None:
        return ocf
    # Alpha Vantage typically reports capex as a negative cash outflow.
    if capex <= 0:
        return ocf + capex
    return ocf - capex


def _merge_alphavantage_fundamentals_into_info(sym: str, info: dict) -> None:
    """Fill ``freeCashflow``, ``enterpriseValue``, ``ebitda`` from OVERVIEW / CASH_FLOW when Yahoo omits them."""
    need_fcf = _coerce_finite_float(info.get("freeCashflow")) is None
    need_ev = _coerce_finite_float(info.get("enterpriseValue")) is None
    need_ebitda = _coerce_finite_float(info.get("ebitda")) is None
    if not (need_fcf or need_ev or need_ebitda):
        return

    overview = _alphavantage_query({"function": "OVERVIEW", "symbol": sym})
    if isinstance(overview, dict) and overview.get("Symbol"):
        if need_ebitda:
            eb = _coerce_finite_float(overview.get("EBITDA"))
            if eb is not None:
                info["ebitda"] = eb
        if need_ev:
            ev_direct = _coerce_finite_float(overview.get("EnterpriseValue"))
            if ev_direct is not None and ev_direct > 0:
                info["enterpriseValue"] = ev_direct
            else:
                ev_ratio = _coerce_finite_float(overview.get("EVToEBITDA"))
                eb2 = _coerce_finite_float(info.get("ebitda"))
                if ev_ratio is not None and eb2 is not None and ev_ratio > 0 and eb2 != 0:
                    ev_est = ev_ratio * eb2
                    if ev_est > 0:
                        info["enterpriseValue"] = ev_est

    if _coerce_finite_float(info.get("freeCashflow")) is None:
        cf = _alphavantage_query({"function": "CASH_FLOW", "symbol": sym})
        reports = cf.get("annualReports") if isinstance(cf, dict) else None
        if isinstance(reports, list) and reports:
            fcf = _fcf_from_av_cash_flow_report(reports[0])
            if fcf is not None:
                info["freeCashflow"] = fcf


@st.cache_data(ttl=3600, show_spinner=False)
def _alphavantage_efficiency_yoy(sym: str) -> Optional[tuple]:
    """Most recent YoY growth: EBITDA and total assets (annual), for efficiency ratio."""
    s = str(sym).upper().strip()
    if not s:
        return None
    inc = _alphavantage_query({"function": "INCOME_STATEMENT", "symbol": s})
    bal = _alphavantage_query({"function": "BALANCE_SHEET", "symbol": s})
    if not isinstance(inc, dict) or not isinstance(bal, dict):
        return None
    ar = inc.get("annualReports")
    br = bal.get("annualReports")
    if not isinstance(ar, list) or len(ar) < 2:
        return None
    if not isinstance(br, list) or len(br) < 2:
        return None

    e0 = _coerce_finite_float(ar[0].get("ebitda"))
    e1 = _coerce_finite_float(ar[1].get("ebitda"))
    a0 = _coerce_finite_float(br[0].get("totalAssets"))
    a1 = _coerce_finite_float(br[1].get("totalAssets"))

    if e0 is None or e1 is None or a0 is None or a1 is None:
        return None
    if abs(e1) < 1e-9 or abs(a1) < 1e-9:
        return None
    ebitda_yoy = (e0 - e1) / abs(e1)
    asset_yoy = (a0 - a1) / abs(a1)
    if not np.isfinite(ebitda_yoy) or not np.isfinite(asset_yoy):
        return None
    if abs(asset_yoy) < 1e-12:
        return None
    return (float(ebitda_yoy), float(asset_yoy))


def _fetch_stock_alphavantage(sym: str, period: str, interval: str) -> Optional[pd.DataFrame]:
    """Fallback daily bars when Yahoo throttles; needs ``ALPHAVANTAGE_API_KEY`` (env or Streamlit secrets)."""
    if interval != "1d":
        return None
    key = _alphavantage_api_key()
    if not key:
        return None
    av_sym = sym.replace("^", "").strip()
    if not av_sym:
        return None
    output = "compact" if period in ("1d", "5d", "1mo", "3mo", "6mo") else "full"
    try:
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": av_sym,
                "outputsize": output,
                "apikey": key,
            },
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return None
    if not isinstance(payload, dict) or "Time Series (Daily)" not in payload:
        return None
    ts = payload["Time Series (Daily)"]
    if not isinstance(ts, dict) or not ts:
        return None
    idx_list: list = []
    rows: list = []
    for date_s in sorted(ts.keys()):
        bar = ts[date_s]
        try:
            rows.append(
                {
                    "Open": float(bar["1. open"]),
                    "High": float(bar["2. high"]),
                    "Low": float(bar["3. low"]),
                    "Close": float(bar["4. close"]),
                    "Volume": float(bar.get("5. volume", 0) or 0),
                }
            )
            idx_list.append(date_s)
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows, index=pd.to_datetime(idx_list))
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    tail_map = {
        "1d": 5,
        "5d": 8,
        "1mo": 24,
        "3mo": 66,
        "6mo": 128,
        "1y": 270,
        "2y": 540,
        "5y": 1300,
        "10y": 2600,
        "max": len(df),
    }
    n = int(tail_map.get(period, 270))
    df = df.tail(max(60, min(n, len(df))))
    return df if not df.empty else None


@st.cache_data(ttl=300)
def fetch_stock(ticker, period="1y", interval="1d"):
    """Yahoo daily/intraday bars; never raises — returns ``None`` on any failure."""
    try:
        sym = str(ticker).upper().strip()
        if not sym:
            return None

        def _fetch():
            try:
                df = _yfinance_ticker(sym).history(
                    period=period, interval=interval, timeout=_YAHOO_YF_TIMEOUT
                )
            except Exception:
                return None
            if df is None or df.empty:
                if df is not None and df.empty:
                    print(
                        f"[cashflow-trader] WARNING: fetch_stock empty DataFrame "
                        f"ticker={sym!r} period={period!r} interval={interval!r}",
                        file=sys.stderr,
                        flush=True,
                    )
                return None
            try:
                df.index = pd.to_datetime(df.index)
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
            except Exception:
                return None
            return df

        out = retry_fetch(_fetch)
        if out is not None:
            return out
        return _fetch_stock_alphavantage(sym, period, interval)
    except Exception:
        return None


# Macro strip symbols (unioned with the watchlist for a single desk snapshot download).
_MACRO_PANEL_TICKERS = ("^VIX", "^TNX", "UUP", "SPY", "QQQ")
_MACRO_TICKER_TO_LABEL = {
    "^VIX": "VIX",
    "^TNX": "10Y Yield",
    "UUP": "DXY (UUP)",
    "SPY": "SPY",
    "QQQ": "QQQ",
}


def _macro_defaults_tuple() -> tuple[dict, Optional[pd.DataFrame]]:
    d = {
        "10Y Yield": {"price": 4.5, "chg": 0.0},
        "VIX": {"price": 20.0, "chg": 0.0},
    }
    return d, None


def _yf_close_matrix_from_raw(raw, download_syms: list) -> Optional[pd.DataFrame]:
    if raw is None or getattr(raw, "empty", True):
        return None
    try:
        close = raw["Close"]
    except (KeyError, TypeError, ValueError):
        return None
    if isinstance(close, pd.Series):
        name = download_syms[0] if len(download_syms) == 1 else "Close"
        close = close.to_frame(name=name)
    return close if isinstance(close, pd.DataFrame) else None


def rs_spy_ratio_map_from_close_matrix(
    close: Optional[pd.DataFrame],
    symbols: tuple,
    *,
    sessions: int = _RS_SPY_LOOKBACK_SESSIONS,
) -> dict[str, Optional[float]]:
    """
    For each symbol: (Close_t / Close_{t-n}) / (SPY_t / SPY_{t-n}) on **inner-aligned** dates.
    Values **> 1** mean the stock outperformed SPY over the window. **SPY** and unknown columns → ``None``.
    """
    out: dict[str, Optional[float]] = {}
    if close is None or getattr(close, "empty", True) or "SPY" not in close.columns:
        for sym in symbols:
            su = str(sym).upper().strip()
            if su:
                out[su] = None
        return out
    spy_all = pd.to_numeric(close["SPY"], errors="coerce")
    for sym in symbols:
        su = str(sym).upper().strip()
        if not su:
            continue
        if su == "SPY":
            out[su] = None
            continue
        if su not in close.columns:
            out[su] = None
            continue
        st_all = pd.to_numeric(close[su], errors="coerce")
        j = pd.concat([spy_all.rename("_spy"), st_all.rename("_stk")], axis=1, join="inner").dropna()
        if len(j) < sessions + 1:
            out[su] = None
            continue
        try:
            spy_b = float(j["_spy"].iloc[-1 - sessions])
            spy_e = float(j["_spy"].iloc[-1])
            stk_b = float(j["_stk"].iloc[-1 - sessions])
            stk_e = float(j["_stk"].iloc[-1])
        except (TypeError, ValueError, IndexError):
            out[su] = None
            continue
        if spy_b <= 0 or stk_b <= 0 or not all(np.isfinite(x) for x in (spy_b, spy_e, stk_b, stk_e)):
            out[su] = None
            continue
        spy_f = spy_e / spy_b
        stk_f = stk_e / stk_b
        if spy_f <= 0 or not np.isfinite(spy_f) or not np.isfinite(stk_f):
            out[su] = None
            continue
        out[su] = float(stk_f / spy_f)
    return out


def _tape_pcts_from_close_matrix(close: pd.DataFrame, syms: tuple) -> dict:
    out = {s: None for s in syms}
    for sym in syms:
        if sym not in close.columns:
            continue
        c = pd.to_numeric(close[sym], errors="coerce").dropna()
        if len(c) >= 2 and float(c.iloc[-2]) != 0:
            out[sym] = float((float(c.iloc[-1]) / float(c.iloc[-2]) - 1.0) * 100.0)
    return out


def _macro_bundle_from_close_matrix(close: pd.DataFrame) -> tuple[dict, Optional[pd.DataFrame]]:
    data: dict = {}
    vix_hist = None
    syms = list(_MACRO_PANEL_TICKERS)
    for sym in syms:
        label = _MACRO_TICKER_TO_LABEL.get(sym)
        if not label or sym not in close.columns:
            continue
        s = pd.to_numeric(close[sym], errors="coerce").dropna()
        if len(s) < 1:
            continue
        last = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) >= 2 else last
        prev_f = float(prev) if prev else 0.0
        chg = (last / prev_f - 1.0) * 100.0 if prev_f else 0.0
        data[label] = {"price": last, "chg": chg}
    if "^VIX" in close.columns:
        vx = pd.to_numeric(close["^VIX"], errors="coerce").dropna()
        if len(vx) >= 1:
            vix_hist = pd.DataFrame({"Close": vx.astype(float)})
    if "10Y Yield" not in data:
        data["10Y Yield"] = {"price": 4.5, "chg": 0.0}
    if "VIX" not in data:
        data["VIX"] = {"price": 20.0, "chg": 0.0}
    return data, vix_hist


class DeskMarketSnapshot(NamedTuple):
    """Single ``yf.download`` worth of sidebar tape + macro/VIX glance data."""

    tape_pcts: dict
    macro: dict
    vix_1mo_df: Optional[pd.DataFrame]


def _ticker_daily_ohlcv_from_raw(raw, sym: str) -> Optional[pd.DataFrame]:
    """One symbol's OHLCV from multi-ticker ``yf.download`` output (``Price`` × ``Ticker`` columns)."""
    if raw is None or getattr(raw, "empty", True):
        return None
    sym = str(sym).upper().strip()
    if not sym:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw.xs(sym, axis=1, level="Ticker")
        else:
            sub = raw
    except (KeyError, TypeError, ValueError):
        return None
    need = ("Open", "High", "Low", "Close")
    if not all(c in sub.columns for c in need):
        return None
    cols = list(need) + [c for c in ("Volume",) if c in sub.columns]
    out = sub[cols].copy()
    try:
        out.index = pd.to_datetime(out.index)
        if out.index.tz is not None:
            out.index = out.index.tz_localize(None)
    except Exception:
        return None
    out = out.apply(pd.to_numeric, errors="coerce")
    out = out.dropna(how="all")
    return out if len(out) >= 2 else None


def _weekly_ohlcv_from_daily(df: pd.DataFrame) -> pd.DataFrame:
    o = df["Open"].resample("W-FRI").first()
    h = df["High"].resample("W-FRI").max()
    lo = df["Low"].resample("W-FRI").min()
    c = df["Close"].resample("W-FRI").last()
    w = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c}).dropna(how="any")
    return w


def active_ticker_frames_from_panel(
    raw: Optional[pd.DataFrame], act: str
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """From a shared panel: (~1y daily, ~2y weekly-resampled, ~1mo daily) for the active symbol."""
    if raw is None:
        return None, None, None
    full = _ticker_daily_ohlcv_from_raw(raw, act)
    if full is None or len(full) < 5:
        return None, None, None
    ad = full.iloc[-260:].copy()
    am = full.iloc[-28:].copy()
    wfull = _weekly_ohlcv_from_daily(full)
    aw = wfull.iloc[-110:].copy() if len(wfull) >= 5 else None
    return ad, aw, am


class GlobalMarketSnapshot(NamedTuple):
    """One ``yf.download`` for watchlist ∪ macro ∪ risk ∪ active — desk, risk matrix, and scanner panel."""

    desk: DeskMarketSnapshot
    risk_closes_df: pd.DataFrame
    active_daily_df: Optional[pd.DataFrame]
    active_weekly_df: Optional[pd.DataFrame]
    active_1mo_df: Optional[pd.DataFrame]
    raw_panel: Optional[pd.DataFrame]
    universe_syms: tuple
    risk_syms: tuple
    rs_spy_ratio_map: dict
    fundamental_sieve_map: dict


@st.cache_data(ttl=120)
def fetch_global_market_bundle(watch_syms: tuple, active_ticker: str) -> GlobalMarketSnapshot:
    """Single Yahoo batch for tape, macro, portfolio risk closes, active-ticker OHLC, and scanner reuse.

    Uses **2y** daily bars (not 5d): the command center, correlation block, and scanner need ~1y+ of
    structure; weekly series are resampled from this panel to avoid a second interval per symbol.
    """
    wl = tuple(str(s).upper().strip() for s in watch_syms if str(s).strip())
    act = str(active_ticker).upper().strip() or "PLTR"
    risk = list(dict.fromkeys([x for x in wl if x]))[:20]
    if act not in risk:
        risk.append(act)
    universe = sorted(set(wl) | set(_MACRO_PANEL_TICKERS) | set(risk))
    out_tape = {s: None for s in wl}
    m0, v0 = _macro_defaults_tuple()
    empty_desk = DeskMarketSnapshot(out_tape, m0, v0)
    empty = GlobalMarketSnapshot(
        empty_desk,
        pd.DataFrame(),
        None,
        None,
        None,
        None,
        tuple(universe),
        tuple(risk),
        {},
        {},
    )
    try:
        raw = yf.download(
            universe,
            period="2y",
            interval="1d",
            threads=False,
            progress=False,
            auto_adjust=True,
            session=_YAHOO_SESSION,
            timeout=_YAHOO_YF_TIMEOUT,
        )
    except Exception:
        return empty
    if raw is None or getattr(raw, "empty", True):
        return empty

    close = _yf_close_matrix_from_raw(raw, universe)
    if close is None:
        return GlobalMarketSnapshot(
            DeskMarketSnapshot(out_tape, m0, v0),
            pd.DataFrame(),
            None,
            None,
            None,
            raw,
            tuple(universe),
            tuple(risk),
            {},
            {},
        )
    tape = _tape_pcts_from_close_matrix(close, wl)
    macro, vix_df = _macro_bundle_from_close_matrix(close)
    desk = DeskMarketSnapshot(tape, macro, vix_df)

    risk_cols = [c for c in risk if c in close.columns]
    risk_df = pd.DataFrame()
    if risk_cols:
        risk_df = close[risk_cols].iloc[-260:].apply(pd.to_numeric, errors="coerce").dropna(how="all")

    rs_syms = tuple(sorted(set(risk) | set(wl)))
    rs_map = rs_spy_ratio_map_from_close_matrix(close, rs_syms, sessions=_RS_SPY_LOOKBACK_SESSIONS)

    ad, aw, am = active_ticker_frames_from_panel(raw, act)
    sieve_map: dict = {}
    for sym in risk:
        try:
            sieve_map[str(sym).upper().strip()] = evaluate_fundamental_sieve(sym)
        except Exception:
            sieve_map[str(sym).upper().strip()] = None
    return GlobalMarketSnapshot(
        desk, risk_df, ad, aw, am, raw, tuple(universe), tuple(risk), rs_map, sieve_map
    )


def fetch_desk_market_snapshot(watch_syms: tuple) -> DeskMarketSnapshot:
    """Sidebar/macro slice of ``fetch_global_market_bundle`` (cached on the bundle key)."""
    act = watch_syms[0] if watch_syms else "PLTR"
    return fetch_global_market_bundle(watch_syms, act).desk


@st.cache_data(ttl=300)
def fetch_equity_daily_closes_wide(symbols: tuple, period: str = "1y") -> pd.DataFrame:
    """Multi-ticker daily closes in **one** ``yf.download`` (portfolio risk / correlation block)."""
    syms = tuple(str(s).upper().strip() for s in symbols if str(s).strip())
    if not syms:
        return pd.DataFrame()
    try:
        raw = yf.download(
            list(syms),
            period=period,
            interval="1d",
            threads=False,
            progress=False,
            auto_adjust=True,
            session=_YAHOO_SESSION,
            timeout=_YAHOO_YF_TIMEOUT,
        )
    except Exception:
        return pd.DataFrame()
    close = _yf_close_matrix_from_raw(raw, list(syms))
    if close is None:
        return pd.DataFrame()
    out: dict = {}
    for sym in syms:
        if sym not in close.columns:
            continue
        s = pd.to_numeric(close[sym], errors="coerce").dropna()
        if len(s) >= 1:
            out[sym] = s
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).dropna(how="all")


def watchlist_tape_pct_changes(symbols: tuple) -> dict:
    """Tape % changes; uses ``fetch_desk_market_snapshot`` (same batch as macro when watchlist non-empty)."""
    return fetch_desk_market_snapshot(symbols).tape_pcts


@st.cache_data(ttl=120)
def _ticker_pct_change_1d(symbol: str):
    """Approximate last session % change (cached). Prefer ``watchlist_tape_pct_changes`` for lists."""
    sym = str(symbol).upper().strip()
    if not sym:
        return None
    batch = watchlist_tape_pct_changes((sym,))
    return batch.get(sym)


@st.cache_data(ttl=300)
def fetch_intraday_series(symbol, period="5d", interval="1h"):
    """Cached intraday close series; never raises."""
    try:
        sym = str(symbol).upper().strip()
        if not sym:
            return pd.Series(dtype=float)
        try:
            hist = _yfinance_ticker(sym).history(
                period=period, interval=interval, timeout=_YAHOO_YF_TIMEOUT
            )
        except Exception:
            return pd.Series(dtype=float)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return pd.Series(dtype=float)
        s = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        return s
    except Exception:
        return pd.Series(dtype=float)

@st.cache_data(ttl=300)
def fetch_info(ticker):
    """Yahoo quote summary fields, with Alpha Vantage gap-fill for cash/EV/EBITDA; never raises."""
    try:
        sym = str(ticker).upper().strip()
        if not sym:
            return {}
        raw_info = _yfinance_ticker(sym).info
        info = dict(raw_info) if isinstance(raw_info, dict) else {}
        _merge_alphavantage_fundamentals_into_info(sym, info)
        return info
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def evaluate_fundamental_sieve(ticker: str) -> Optional[dict]:
    """FCF yield vs EV and EBITDA/asset efficiency; ``None`` if inputs missing (no synthetic zeros).

    **10x guard:** ``ten_x_candidate`` when FCF yield > 10% and efficiency ratio (EBITDA YoY / asset YoY) > 1.
    """
    sym = str(ticker).upper().strip()
    if not sym:
        return None
    try:
        info = fetch_info(sym)
        if not info:
            info = {}
        fcf = _coerce_finite_float(info.get("freeCashflow"))
        ev = _coerce_finite_float(info.get("enterpriseValue"))
        if fcf is None or ev is None or ev <= 0:
            return None
        fcf_yield = float(fcf / ev)
        if not np.isfinite(fcf_yield):
            return None

        yoy = _alphavantage_efficiency_yoy(sym)
        if yoy is None:
            return None
        ebitda_yoy, asset_yoy = yoy
        efficiency_ratio = float(ebitda_yoy / asset_yoy)
        if not np.isfinite(efficiency_ratio):
            return None

        ten_x = bool(fcf_yield > 0.10 and efficiency_ratio > 1.0)
        return {
            "fcf_yield": fcf_yield,
            "fcf_yield_pct": round(fcf_yield * 100.0, 2),
            "efficiency_ratio": efficiency_ratio,
            "ebitda_yoy": ebitda_yoy,
            "asset_yoy": asset_yoy,
            "ten_x_candidate": ten_x,
        }
    except Exception:
        return None

@st.cache_data(ttl=90)
def list_option_expiration_dates(ticker: str) -> tuple:
    """Expiry strings only (short TTL); never raises."""
    try:
        sym = str(ticker).upper().strip()
        if not sym:
            return tuple()
        return tuple(_resolve_option_expiration_strings(sym))
    except Exception:
        return tuple()


@st.cache_data(ttl=300)
def fetch_options(ticker, exp=None):
    """Fetch options chain. Always returns ((calls_df, puts_df), exps) for stable unpacking.

    Expiration list comes from ``list_option_expiration_dates`` (yfinance retries + Yahoo v7 HTTP
    fallback + 90s cache). When ``exp`` is None, returns empty frames and only exps (no chain pull).

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
        sym = str(ticker).upper().strip()
        if not sym:
            return empty, []
        exps = list(list_option_expiration_dates(sym))
        if not exps:
            return empty, []
        if exp is None:
            return empty, exps
        t = _yfinance_ticker(sym)
        exp_s = str(exp)[:10] if exp else ""
        primary = exp_s if exp_s in exps else exps[0]
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
        exps = list(list_option_expiration_dates(sym))[:14]
        if len(exps) < 2:
            return None
        t = _yfinance_ticker(sym)
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
            except Exception as e:
                log_warn("fetch_news item timestamp", e)
            if title:
                items.append({"title": title, "link": link, "pub": pub, "time": pt})
        return items
    except Exception as e:
        log_warn("fetch_news", e, ticker=str(ticker))
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_news_headlines(symbol: str):
    """Latest 5–8 Yahoo headlines for NLP bias (longer TTL than general news to protect rate limits)."""
    try:
        sym = str(symbol).upper().strip()
        if not sym:
            return []
        raw = _yfinance_ticker(sym).news or []
        out = []
        for n in raw[:8]:
            title = (n.get("title") or n.get("content", {}).get("title", "") or "").strip()
            link = n.get("link") or n.get("content", {}).get("canonicalUrl", {}).get("url", "")
            pub = n.get("publisher") or n.get("content", {}).get("provider", {}).get("displayName", "")
            pt = ""
            try:
                ts = n.get("providerPublishTime") or n.get("content", {}).get("pubDate", "")
                if isinstance(ts, (int, float)):
                    pt = datetime.fromtimestamp(ts).strftime("%b %d, %H:%M")
                elif isinstance(ts, str) and ts:
                    pt = ts[:16]
            except Exception as e:
                log_warn("fetch_news_headlines item timestamp", e)
            if title:
                out.append({"title": title, "link": link, "pub": pub, "time": pt})
        return out[:8] if out else []
    except Exception as e:
        log_warn("fetch_news_headlines", e, ticker=str(symbol))
        return []


def avg_post_earnings_vol_crush_proxy_pct(df: pd.DataFrame, symbol: str, n_cycles: int = 4):
    """
    Average % change in short-window realized vol after vs before past earnings (proxy for IV crush).
    Uses up to ``n_cycles`` prior earnings dates from Yahoo ``earnings_dates``.
    """
    try:
        if df is None or df.empty or "Close" not in df.columns or len(df) < 80:
            return None
        sym = str(symbol).upper().strip()
        if not sym:
            return None
        ed = getattr(_yfinance_ticker(sym), "earnings_dates", None)
        if ed is None or getattr(ed, "empty", True):
            return None
        now = pd.Timestamp.now().normalize()
        past = sorted(
            [pd.Timestamp(x).normalize() for x in ed.index if pd.Timestamp(x).normalize() < now],
            reverse=True,
        )
        if not past:
            return None
        idx = pd.DatetimeIndex(pd.to_datetime(df.index))
        crushes = []
        for edate in past:
            if len(crushes) >= n_cycles:
                break
            pos = int(idx.searchsorted(edate))
            if pos >= len(df):
                pos = len(df) - 1
            while pos > 0 and idx[pos] > edate:
                pos -= 1
            if pos < 15 or pos + 12 >= len(df):
                continue
            pre = df["Close"].iloc[pos - 12 : pos - 1]
            post = df["Close"].iloc[pos + 1 : pos + 12]
            if len(pre) < 5 or len(post) < 5:
                continue
            r_pre = pre.astype(float).pct_change().dropna()
            r_post = post.astype(float).pct_change().dropna()
            if r_pre.empty or r_post.empty:
                continue
            v_pre = float(r_pre.std() * np.sqrt(252) * 100.0)
            v_post = float(r_post.std() * np.sqrt(252) * 100.0)
            if not np.isfinite(v_pre) or v_pre <= 1e-9:
                continue
            crushes.append((v_post - v_pre) / v_pre * 100.0)
        if not crushes:
            return None
        return float(np.mean(crushes))
    except Exception:
        return None


def compute_iv_earnings_chart_overlay(
    df: pd.DataFrame,
    symbol: str,
    days_to_earnings,
    current_iv_pct,
    spot_price: float,
):
    """
    Text overlay for price chart: avg post-earnings vol crush (when earnings in 14d) + vega risk flag.
    Vega risk: IV rank proxy ≥ 90, else current IV vs 90th pct of 20d realized vol (1y window).
    """
    out = {
        "show_crush": False,
        "avg_crush_pct": None,
        "vega_risk": False,
    }
    try:
        dte = int(days_to_earnings) if days_to_earnings is not None else None
    except (TypeError, ValueError):
        dte = None
    if dte is not None and 0 <= dte <= 14:
        crush = avg_post_earnings_vol_crush_proxy_pct(df, symbol, n_cycles=4)
        if crush is not None and np.isfinite(crush):
            out["show_crush"] = True
            out["avg_crush_pct"] = float(crush)
    try:
        iv = float(current_iv_pct) if current_iv_pct is not None else 0.0
    except (TypeError, ValueError):
        iv = 0.0
    if iv > 0 and df is not None and not df.empty and "Close" in df.columns:
        try:
            rk = compute_iv_rank_proxy(str(symbol).upper().strip(), float(spot_price), iv)
            if rk is not None and float(rk.get("rank", 0)) >= 90.0:
                out["vega_risk"] = True
        except Exception as e:
            log_warn("compute_iv_earnings_chart_overlay iv_rank branch", e, ticker=str(symbol))
        if not out["vega_risk"]:
            try:
                rv20 = (
                    df["Close"].astype(float).pct_change().rolling(20).std() * np.sqrt(252) * 100.0
                )
                win = rv20.dropna().tail(252)
                if len(win) >= 40:
                    p90 = float(win.quantile(0.9))
                    if p90 > 0 and iv > p90:
                        out["vega_risk"] = True
            except Exception as e:
                log_warn("compute_iv_earnings_chart_overlay rv20 quantile", e, ticker=str(symbol))
    return out

def _earnings_date_from_quote_info(info: dict):
    """Next earnings as YYYY-MM-DD from yfinance ``.info``-style flat dict (unix ms/s or nested)."""
    if not info:
        return None
    keys = (
        "earningsTimestamp",
        "earningsTimestampStart",
        "earningsCallTimestampStart",
    )
    for k in keys:
        ts = info.get(k)
        if ts is None:
            continue
        try:
            if isinstance(ts, dict):
                raw = ts.get("raw")
                if isinstance(raw, (int, float)) and raw > 1e9:
                    return datetime.utcfromtimestamp(int(raw)).strftime("%Y-%m-%d")
                fmt = ts.get("fmt") or ts.get("longFmt")
                if fmt and len(str(fmt)) >= 10:
                    return str(fmt)[:10]
            if isinstance(ts, (int, float)) and ts > 1e12:
                return datetime.utcfromtimestamp(int(ts / 1000)).strftime("%Y-%m-%d")
            if isinstance(ts, (int, float)) and ts > 1e9:
                return datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            continue
    return None


def _coerce_earnings_to_yyyy_mm_dd(raw) -> str | None:
    """Normalize calendar/earnings row values to YYYY-MM-DD."""
    if raw is None:
        return None
    try:
        if isinstance(raw, float) and np.isnan(raw):
            return None
    except Exception as e:
        log_warn("_coerce_earnings_to_yyyy_mm_dd nan check", e)
    try:
        if isinstance(raw, str):
            s = raw.strip()
            if len(s) >= 10 and s[4] == "-" and s[7] == "-":
                return s[:10]
        ts = pd.Timestamp(raw)
        if pd.isna(ts):
            return None
        return ts.strftime("%Y-%m-%d")
    except Exception:
        return None


def _earnings_next_from_yahoo_quotesummary(symbol: str) -> str | None:
    """Yahoo v10 quoteSummary calendarEvents — works when yfinance ``calendar`` is empty (common on Cloud)."""
    sym = str(symbol).upper().strip()
    if not sym:
        return None
    url = (
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
        "?modules=calendarEvents"
    )
    try:
        r = _YAHOO_SESSION.get(url, headers=_YAHOO_OPTIONS_HEADERS)
        if r.status_code != 200:
            return None
        js = r.json()
        res = (js.get("quoteSummary") or {}).get("result") or []
        if not res:
            return None
        ce = res[0].get("calendarEvents") or {}
        earn = ce.get("earnings") or {}
        dates = earn.get("earningsDate")
        if dates is None:
            return None
        items = dates if isinstance(dates, list) else [dates]
        parsed: list = []
        today = datetime.utcnow().date()
        for item in items:
            if item is None:
                continue
            if isinstance(item, dict):
                raw = item.get("raw")
                fmt = item.get("fmt")
                d = None
                if isinstance(raw, (int, float)) and raw > 1e9:
                    try:
                        d = datetime.utcfromtimestamp(int(raw)).date()
                    except (TypeError, ValueError, OSError):
                        pass
                if d is None and fmt:
                    try:
                        d = datetime.strptime(str(fmt)[:10], "%Y-%m-%d").date()
                    except Exception as e:
                        log_warn("_earnings_next_from_yahoo_quotesummary fmt parse", e, ticker=sym)
                if d is not None:
                    parsed.append(d)
            elif isinstance(item, (int, float)) and item > 1e9:
                try:
                    parsed.append(datetime.utcfromtimestamp(int(item)).date())
                except (TypeError, ValueError, OSError):
                    pass
        if not parsed:
            return None
        future = [d for d in parsed if d >= today]
        pick = min(future) if future else max(parsed)
        return pick.strftime("%Y-%m-%d")
    except Exception:
        return None


def _earnings_from_yfinance_calendar(symbol: str, attempts: int = 4) -> str | None:
    """yfinance ``Ticker.calendar`` with retries; tolerates dict/DataFrame and alternate key names."""
    sym = str(symbol).upper().strip()
    for attempt in range(attempts):
        try:
            cal = _yfinance_ticker(sym).calendar
            raw = None
            if isinstance(cal, dict):
                for k in ("Earnings Date", "earningsDate", "Earnings date"):
                    if k not in cal:
                        continue
                    ed = cal[k]
                    if isinstance(ed, (list, tuple)) and ed:
                        raw = ed[0]
                    elif ed is not None and not (isinstance(ed, float) and pd.isna(ed)):
                        raw = ed
                    if raw is not None:
                        break
                if raw is None:
                    for k, ed in cal.items():
                        lk = str(k).lower().replace(" ", "")
                        if "earnings" in lk and "date" in lk:
                            if isinstance(ed, (list, tuple)) and ed:
                                raw = ed[0]
                            elif ed is not None and not (
                                isinstance(ed, float) and pd.isna(ed)
                            ):
                                raw = ed
                            break
            elif isinstance(cal, pd.DataFrame) and not cal.empty:
                raw = None
                if "Earnings Date" in cal.columns:
                    v = cal["Earnings Date"].iloc[0]
                    if pd.notna(v):
                        raw = v
                if raw is None and "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    v = val.iloc[0] if hasattr(val, "iloc") else val
                    if pd.notna(v):
                        raw = v
                if raw is None:
                    for col in cal.columns:
                        cl = str(col).lower()
                        if "earnings" in cl and "date" in cl:
                            v = cal[col].iloc[0]
                            if pd.notna(v):
                                raw = v
                                break
            s = _coerce_earnings_to_yyyy_mm_dd(raw)
            if s:
                return s
        except Exception as e:
            log_warn(f"_earnings_from_yfinance_calendar attempt {attempt + 1}/{attempts}", e, ticker=sym)
        if attempt < attempts - 1:
            time.sleep(0.1 * (2**attempt))
    return None


def _earnings_from_yfinance_earnings_dates(symbol: str) -> str | None:
    """Next or most recent earnings from ``Ticker.earnings_dates`` table (separate Yahoo scrape path)."""
    sym = str(symbol).upper().strip()
    try:
        ed = _yfinance_ticker(sym).earnings_dates
        if ed is None or not isinstance(ed, pd.DataFrame) or ed.empty:
            return None
        ed = ed.copy()
        ed.index = [_earnings_ts_normalize(i) for i in ed.index]
        ed = ed.sort_index()
        today = pd.Timestamp(datetime.now().date()).normalize()
        future = ed[ed.index.normalize() >= today]
        if not future.empty:
            pick = future.index.min()
        else:
            pick = ed.index.max()
        return _coerce_earnings_to_yyyy_mm_dd(pick)
    except Exception:
        return None


def _resolve_next_earnings_yyyy_mm_dd(symbol: str) -> str | None:
    """Merge all sources (HTTP first, then yfinance paths). Uncached — wrap with ``fetch_earnings_date``."""
    sym = str(symbol).upper().strip()
    if not sym:
        return None

    got = _earnings_next_from_yahoo_quotesummary(sym)
    if got:
        return got

    got = _earnings_from_yfinance_calendar(sym)
    if got:
        return got

    got = _earnings_from_yfinance_earnings_dates(sym)
    if got:
        return got

    try:
        info = _yfinance_ticker(sym).info
        got = _earnings_date_from_quote_info(info or {})
        if got:
            return got
    except Exception as e:
        log_warn("_resolve_next_earnings .info path", e, ticker=sym)

    try:
        got = _earnings_date_from_quote_info(fetch_info(sym))
        if got:
            return got
    except Exception as e:
        log_warn("_resolve_next_earnings fetch_info path", e, ticker=sym)

    return None


@st.cache_data(ttl=600)
def fetch_earnings_date(ticker):
    """Next earnings date as YYYY-MM-DD — multi-source (Yahoo quoteSummary, calendar, earnings_dates, .info)."""
    return _resolve_next_earnings_yyyy_mm_dd(str(ticker).upper().strip())


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


@st.cache_data(ttl=900, show_spinner=False)
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
                except Exception as e:
                    log_warn("fetch_earnings_calendar_display fallback row", e, ticker=str(ticker))

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
    except Exception as e:
        log_warn("fetch_earnings_calendar_display", e, ticker=str(ticker))
        return pd.DataFrame(), None


def fetch_macro():
    """Macro strip + VIX glance history via the macro-only desk snapshot (watchlist empty)."""
    s = fetch_desk_market_snapshot(tuple())
    return s.macro, s.vix_1mo_df

