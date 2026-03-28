"""
╔══════════════════════════════════════════════════════════════════════════╗
║  CASHFLOW COMMAND CENTER v14.1 · INSTITUTIONAL EDITION                   ║
║  Glanceable execution desk plus Diamond, Gold Zone, and Quant            ║
║  Hurst · Kelly · Black Scholes engines unchanged in this release          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="CashFlow Command Center v14.1",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

import html as _html_mod
import threading
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx
from datetime import datetime, timedelta
import plotly.graph_objects as go
import math, warnings, json
from pathlib import Path

import data.yf_engine as yf_engine

warnings.filterwarnings("ignore")


def _submit_with_script_ctx(executor, fn, /, *args, **kwargs):
    """Run ``fn`` in a pool thread with the active ScriptRunContext (needed for ``st.cache_data``)."""
    ctx = get_script_run_ctx()

    def _run():
        if ctx is not None:
            add_script_run_ctx(threading.current_thread(), ctx)
        return fn(*args, **kwargs)

    return executor.submit(_run)


# ─────────────────────────────────────────────────────────────────────────
# CONFIG — watchlist, scanner, strategy, chart overlays (session_state only; no disk writes)
# Legacy ``config.json`` is read once per browser session if present (migration).
# ─────────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"
_CF_APP_CONFIG_KEY = "_cf_app_config"
DEFAULT_CONFIG = {
    "watchlist": "PLTR,BMNR,AAPL,AMZN,NVDA,AMD,TSLA,SPY,QQQ",
    "scanner_sort_mode": "Custom watchlist order",
    "strat_focus": "Hybrid",
    "strat_horizon": "30 DTE",
    "mini_mode": False,
    "overlay_ema": True,
    "overlay_fib": True,
    "overlay_gann": True,
    "overlay_sr": True,
    "overlay_ichi": False,
    "overlay_super": False,
    "overlay_diamonds": True,
    "overlay_gold": True,
}
_LEGACY_CONFIG_KEYS = frozenset({
    "acct", "pltr_sh", "pltr_cost", "max_risk",
    "whatsapp_phone", "whatsapp_apikey", "alert_threshold", "last_alert_date",
})
# Anonymous reference only — used for Kelly / ATR example math (not user portfolio data).
REF_NOTIONAL = 100_000.0
RISK_PCT_EXAMPLE = 3.0
# Kelly math can suggest aggressive fractions; UI never shows above this for portfolio-heat safety.
KELLY_DISPLAY_CAP_PCT = 5.0
# Warn when price is stretched vs 20-EMA (gap / blow-off; Fib & Gold Zone lag).
EMA_EXTENSION_WARN_PCT = 10.0

def _streamlit_secrets_flat():
    """Scalar top-level keys from st.secrets (Streamlit Cloud). Skips nested tables."""
    try:
        if not hasattr(st, "secrets"):
            return {}
        sec = st.secrets
        if sec is None or len(sec) == 0:
            return {}
        out = {}
        for k in sec:
            v = sec[k]
            if isinstance(v, (dict, list)):
                continue
            out[k] = v
        return out
    except Exception:
        return {}


def _normalize_config_value(key: str, val):
    sample = DEFAULT_CONFIG[key]
    if isinstance(sample, bool):
        return bool(val)
    if isinstance(sample, str):
        return str(val) if val is not None else sample
    return val if val is not None else sample


def _coerce_full_config(raw: dict) -> dict:
    """Keep only known keys; normalize types to match ``DEFAULT_CONFIG``."""
    out = {}
    for k in DEFAULT_CONFIG:
        out[k] = _normalize_config_value(k, raw.get(k, DEFAULT_CONFIG[k]))
    return out


def _ensure_app_config() -> None:
    """Hydrate ``_cf_app_config`` once: defaults + secrets + optional legacy ``config.json``."""
    if _CF_APP_CONFIG_KEY in st.session_state:
        return
    merged = {**DEFAULT_CONFIG, **_streamlit_secrets_flat()}
    legacy_failed = False
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = json.load(f)
            merged = {**merged, **saved}
            for k in _LEGACY_CONFIG_KEYS:
                merged.pop(k, None)
    except Exception:
        legacy_failed = True
    st.session_state[_CF_APP_CONFIG_KEY] = _coerce_full_config(merged)
    if legacy_failed:
        st.toast("Could not read legacy config.json; using defaults.", icon="⚠️")


def load_config():
    """Current desk settings from ``st.session_state`` (defaults + secrets + one-time file import)."""
    _ensure_app_config()
    return dict(st.session_state[_CF_APP_CONFIG_KEY])


def save_config(cfg: dict) -> bool:
    """Merge ``cfg`` into session-backed settings. Never writes to disk."""
    try:
        _ensure_app_config()
        cur = st.session_state[_CF_APP_CONFIG_KEY]
        merged = {**cur}
        for k in DEFAULT_CONFIG:
            if k in cfg:
                merged[k] = _normalize_config_value(k, cfg[k])
        st.session_state[_CF_APP_CONFIG_KEY] = merged
        return True
    except Exception:
        st.toast("Failed to save settings", icon="⚠️")
        return False


def _overlay_prefs_from_session():
    """Chart overlay keys as stored in session_state (sb_* toggles)."""
    return {
        "overlay_ema": bool(st.session_state.get("sb_ema", True)),
        "overlay_fib": bool(st.session_state.get("sb_fib", True)),
        "overlay_gann": bool(st.session_state.get("sb_gann", True)),
        "overlay_sr": bool(st.session_state.get("sb_sr", True)),
        "overlay_ichi": bool(st.session_state.get("sb_ichi", False)),
        "overlay_super": bool(st.session_state.get("sb_super", False)),
        "overlay_diamonds": bool(st.session_state.get("sb_diamonds", True)),
        "overlay_gold": bool(st.session_state.get("sb_gold_zone", True)),
    }


def _persist_overlay_prefs():
    """Persist overlay toggles from session state (used inside chart fragment). Merges onto latest session config."""
    base = load_config()
    o = _overlay_prefs_from_session()
    upd = {**base, **o}
    if any(upd.get(k) != base.get(k) for k in o):
        save_config(upd)
        return upd
    return base


def _hydrate_sidebar_prefs(cfg):
    """Load Strategy / Chart overlay widget state from config when session has no value yet."""
    if "sb_strat_radio" not in st.session_state:
        opts = ("Sell premium", "Hybrid", "Growth")
        v = cfg.get("strat_focus", DEFAULT_CONFIG["strat_focus"])
        st.session_state["sb_strat_radio"] = v if v in opts else DEFAULT_CONFIG["strat_focus"]
    if "sb_horizon_radio" not in st.session_state:
        opts = ("Weekly", "30 DTE", "45 DTE")
        v = cfg.get("strat_horizon", DEFAULT_CONFIG["strat_horizon"])
        st.session_state["sb_horizon_radio"] = v if v in opts else DEFAULT_CONFIG["strat_horizon"]
    if "sb_mini_mode" not in st.session_state:
        st.session_state["sb_mini_mode"] = bool(cfg.get("mini_mode", DEFAULT_CONFIG["mini_mode"]))
    for wkey, ckey, default in (
        ("sb_ema", "overlay_ema", True),
        ("sb_fib", "overlay_fib", True),
        ("sb_gann", "overlay_gann", True),
        ("sb_sr", "overlay_sr", True),
        ("sb_ichi", "overlay_ichi", False),
        ("sb_super", "overlay_super", False),
        ("sb_diamonds", "overlay_diamonds", True),
        ("sb_gold_zone", "overlay_gold", True),
    ):
        if wkey not in st.session_state:
            st.session_state[wkey] = bool(cfg.get(ckey, default))


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

# ─────────────────────────────────────────────────────────────────────────
# Static assets (CSS + JS) — see ``assets/styles.css`` and ``assets/routing.js``
# ─────────────────────────────────────────────────────────────────────────
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_CF_MINI_START = "/* CF_MINI_MODE_START"
_CF_MINI_END = "/* CF_MINI_MODE_END */"


def _read_asset(rel: str) -> str:
    return (_ASSETS_DIR / rel).read_text(encoding="utf-8")


def _split_styles_css(full: str) -> tuple[str, str]:
    """Return (base_css, mini_density_css) from the bundled stylesheet."""
    s = full.find(_CF_MINI_START)
    e = full.find(_CF_MINI_END)
    if s == -1 or e == -1 or e <= s:
        return full.strip(), ""
    base = full[:s].strip()
    mid = full[s:e]
    lines = mid.splitlines()
    if lines and "CF_MINI_MODE_START" in lines[0]:
        lines = lines[1:]
    mini = "\n".join(lines).strip()
    return base, mini


def inject_assets() -> None:
    """Load ``assets/styles.css`` and ``assets/routing.js``; inject theme, chrome, nav, and boot script."""
    full_css = _read_asset("styles.css")
    base_css, _mini = _split_styles_css(full_css)
    st.markdown(f"<style>{base_css}</style>", unsafe_allow_html=True)
    st.markdown(
        """
<button type="button" class="cf-vip-fab" id="sob" data-cf-hamburger="1" aria-label="Open or close settings" title="Settings">&#9776;</button>
<nav class="sticky-nav">
<div class="sticky-nav-track">
<a href="#execution">Execution</a>
<a href="#charts">Charts</a>
<a href="#setup">Setup</a>
<a href="#quant-dashboard">Quant Dashboard</a>
<a href="#strategies">Strategies</a>
<a href="#risk">Risk</a>
<a href="#scanner">Scanner</a>
<a href="#news">News</a>
<a href="#guide">Guide</a>
</div>
</nav>
""",
        unsafe_allow_html=True,
    )
    routing = _read_asset("routing.js")
    components.html(
        f"<script>{routing}</script>",
        height=0,
        scrolling=False,
    )


def inject_mini_mode_density_css() -> None:
    """Second-pass density rules when Mini mode is enabled (session / sidebar toggle)."""
    full_css = _read_asset("styles.css")
    _, mini = _split_styles_css(full_css)
    if mini:
        st.markdown(f"<style>{mini}</style>", unsafe_allow_html=True)


inject_assets()

# ═════════════════════════════════════════════════════════════════════════
#  DATA LAYER
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def fetch_stock(ticker, period="1y", interval="1d"):
    return yf_engine.fetch_stock(ticker, period, interval)


@st.cache_data(ttl=120, show_spinner=False)
def _tape_pct_changes(symbols: tuple):
    """One cache entry per watchlist lineup; avoids N× “Running _ticker_pct_change_1d…” on the tape."""
    return {sym: yf_engine.ticker_pct_change_1d(sym) for sym in symbols}


@st.cache_data(ttl=300)
def fetch_intraday_series(symbol, period="5d", interval="1h"):
    return yf_engine.fetch_intraday_series(symbol, period, interval)


@st.cache_data(ttl=300)
def fetch_info(ticker):
    return yf_engine.fetch_info(ticker)


@st.cache_data(ttl=300)
def fetch_options(ticker, exp=None):
    return yf_engine.fetch_options(ticker, exp)


@st.cache_data(ttl=900)
def compute_iv_rank_proxy(sym: str, spot: float, ref_iv_pct: float):
    return yf_engine.compute_iv_rank_proxy(sym, spot, ref_iv_pct)


@st.cache_data(ttl=600)
def fetch_news(ticker):
    return yf_engine.fetch_news(ticker)


@st.cache_data(ttl=3600)
def fetch_earnings_date(ticker):
    return yf_engine.fetch_earnings_date(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_earnings_calendar_display(ticker: str):
    return yf_engine.fetch_earnings_calendar_display(ticker)


@st.cache_data(ttl=300)
def fetch_macro():
    return yf_engine.fetch_macro()


# ═════════════════════════════════════════════════════════════════════════
#  TECHNICAL ANALYSIS ENGINE
# ═════════════════════════════════════════════════════════════════════════

class TA:
    @staticmethod
    def ema(s, p): return s.ewm(span=p, adjust=False).mean()
    @staticmethod
    def sma(s, p): return s.rolling(window=p).mean()

    @staticmethod
    def rsi(s, p=14):
        d = s.diff()
        g = d.where(d > 0, 0).rolling(p).mean()
        l = (-d.where(d < 0, 0)).rolling(p).mean()
        return 100 - 100 / (1 + g / l)

    @staticmethod
    def rsi2(s): return TA.rsi(s, 2)

    @staticmethod
    def macd(s, fast=12, slow=26, sig=9):
        ef = s.ewm(span=fast, adjust=False).mean()
        es = s.ewm(span=slow, adjust=False).mean()
        ml = ef - es; sl = ml.ewm(span=sig, adjust=False).mean()
        return ml, sl, ml - sl

    @staticmethod
    def bollinger(s, p=20, sd=2):
        m = s.rolling(p).mean(); st = s.rolling(p).std()
        return m + st * sd, m, m - st * sd

    @staticmethod
    def atr(df, p=14):
        hl = df["High"] - df["Low"]
        hc = abs(df["High"] - df["Close"].shift())
        lc = abs(df["Low"] - df["Close"].shift())
        return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(p).mean()

    @staticmethod
    def stoch(df, k=14, d=3):
        lo = df["Low"].rolling(k).min(); hi = df["High"].rolling(k).max()
        kv = 100 * (df["Close"] - lo) / (hi - lo)
        return kv, kv.rolling(d).mean()

    @staticmethod
    def vwap(df):
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        return (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()

    @staticmethod
    def ichimoku(df):
        t = (df["High"].rolling(9).max() + df["Low"].rolling(9).min()) / 2
        k = (df["High"].rolling(26).max() + df["Low"].rolling(26).min()) / 2
        sa = ((t + k) / 2).shift(26)
        sb = ((df["High"].rolling(52).max() + df["Low"].rolling(52).min()) / 2).shift(26)
        return t, k, sa, sb, df["Close"].shift(-26)

    @staticmethod
    def supertrend(df, period=10, mult=3.0):
        """Supertrend — FIXED: uses numpy arrays to avoid pandas chained indexing warnings."""
        atr_v = TA.atr(df, period).values
        hl2 = ((df["High"] + df["Low"]) / 2).values
        close = df["Close"].values
        n = len(df)
        up = hl2 + mult * atr_v
        dn = hl2 - mult * atr_v
        direction = np.empty(n)
        st_line = np.empty(n)
        direction[0] = 1
        st_line[0] = dn[0] if not np.isnan(dn[0]) else close[0]
        for i in range(1, n):
            if np.isnan(up[i]) or np.isnan(dn[i]):
                direction[i] = direction[i-1]
                st_line[i] = st_line[i-1]
                continue
            if close[i] > up[i-1]:
                direction[i] = 1
            elif close[i] < dn[i-1]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]
            if direction[i] == 1:
                st_line[i] = max(dn[i], st_line[i-1]) if direction[i-1] == 1 else dn[i]
            else:
                st_line[i] = min(up[i], st_line[i-1]) if direction[i-1] == -1 else up[i]
        return pd.Series(st_line, index=df.index), pd.Series(direction, index=df.index)

    @staticmethod
    def adx(df, p=14):
        atr_v = TA.atr(df, p)
        dm_p = df["High"].diff(); dm_n = -df["Low"].diff()
        dm_p = dm_p.where((dm_p > dm_n) & (dm_p > 0), 0)
        dm_n = dm_n.where((dm_n > dm_p) & (dm_n > 0), 0)
        di_p = 100 * dm_p.rolling(p).mean() / atr_v
        di_n = 100 * dm_n.rolling(p).mean() / atr_v
        dx = 100 * abs(di_p - di_n) / (di_p + di_n)
        return dx.rolling(p).mean(), di_p, di_n

    @staticmethod
    def cci(df, p=20):
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        sma_tp = tp.rolling(p).mean()
        mad = tp.rolling(p).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma_tp) / (0.015 * mad)

    @staticmethod
    def obv(df):
        return (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()

    @staticmethod
    def volume_profile(df, bins=20):
        pr = np.linspace(df["Low"].min(), df["High"].max(), bins + 1)
        rows = []
        for i in range(len(pr) - 1):
            mask = (df["Close"] >= pr[i]) & (df["Close"] < pr[i+1])
            rows.append({"mid": (pr[i]+pr[i+1])/2, "volume": df.loc[mask, "Volume"].sum()})
        return pd.DataFrame(rows)

    @staticmethod
    def detect_divergences(price_series, indicator_series, lookback=30):
        divs = []
        p = price_series.iloc[-lookback:]
        ind = indicator_series.iloc[-lookback:]
        for i in range(5, len(p) - 1):
            if p.iloc[i] < p.iloc[i-5:i].min() and ind.iloc[i] > ind.iloc[i-5:i].min():
                divs.append({"type": "bullish", "idx": p.index[i], "price": p.iloc[i]})
            if p.iloc[i] > p.iloc[i-5:i].max() and ind.iloc[i] < ind.iloc[i-5:i].max():
                divs.append({"type": "bearish", "idx": p.index[i], "price": p.iloc[i]})
        return divs[-5:]

    @staticmethod
    def fib_retracement(high, low):
        d = high - low
        return {f"{r:.1%}": high - d * r for r in [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]}

    @staticmethod
    def gann_sq9(price):
        sqrt_p = math.sqrt(price); levels = {}
        for i in range(-4, 5):
            if i == 0: continue
            levels[f"Card {'+'if i>0 else ''}{i*180} deg"] = round((sqrt_p + i * 0.5) ** 2, 2)
            levels[f"Ord {'+'if i>0 else ''}{i*90} deg"] = round((sqrt_p + i * 0.25) ** 2, 2)
        return dict(sorted(levels.items(), key=lambda x: x[1]))

    @staticmethod
    def gann_angles(df, lookback=60):
        recent = df.iloc[-lookback:]
        si = recent["Low"].idxmin(); sp = recent.loc[si, "Low"]
        sb = list(recent.index).index(si)
        av = TA.atr(df).iloc[-1]
        if pd.isna(av) or av <= 0: av = sp * 0.02
        bs = len(recent) - 1 - sb
        return {n: round(sp + av * r * bs, 2) for n, r in {"1x1":1,"2x1":2,"1x2":.5,"3x1":3,"1x3":1/3}.items()}, sp

    @staticmethod
    def gann_time_cycles(df):
        recent = df.iloc[-120:]
        si = recent["Low"].idxmin(); sp = list(df.index).index(si)
        results = []
        for c in [30, 60, 90, 120, 180, 360]:
            tp = sp + c
            if tp < len(df):
                results.append({"cycle": c, "date": df.index[tp], "status": "PAST"})
            else:
                results.append({"cycle": c, "date": df.index[-1] + timedelta(days=tp - len(df) + 1), "status": "UPCOMING"})
        return results

    @staticmethod
    def find_sr(df, window=20):
        highs = df["High"].rolling(window, center=True).max()
        lows = df["Low"].rolling(window, center=True).min()
        res_l, sup_l = [], []
        for i in range(window, len(df) - window):
            if df["High"].iloc[i] == highs.iloc[i]: res_l.append(df["High"].iloc[i])
            if df["Low"].iloc[i] == lows.iloc[i]: sup_l.append(df["Low"].iloc[i])
        def cluster(lv, thr=0.02):
            if not lv: return []
            lv = sorted(set(lv)); cs = [[lv[0]]]
            for v in lv[1:]:
                if (v - cs[-1][-1]) / cs[-1][-1] < thr: cs[-1].append(v)
                else: cs.append([v])
            return [np.mean(c) for c in cs]
        return cluster(sup_l), cluster(res_l)

    @staticmethod
    def fvg(df):
        gaps = []
        for i in range(2, len(df)):
            if df["Low"].iloc[i] > df["High"].iloc[i-2]:
                gaps.append({"type":"bullish","top":df["Low"].iloc[i],"bottom":df["High"].iloc[i-2],"date":df.index[i]})
            elif df["High"].iloc[i] < df["Low"].iloc[i-2]:
                gaps.append({"type":"bearish","top":df["Low"].iloc[i-2],"bottom":df["High"].iloc[i],"date":df.index[i]})
        return gaps[-10:]

    @staticmethod
    def market_structure(df, lb=5):
        sh, sl = [], []
        for i in range(lb, len(df) - lb):
            seg = df.iloc[i-lb:i+lb+1]
            if df["High"].iloc[i] == seg["High"].max(): sh.append((df.index[i], df["High"].iloc[i]))
            if df["Low"].iloc[i] == seg["Low"].min(): sl.append((df.index[i], df["Low"].iloc[i]))
        if len(sh) >= 2 and len(sl) >= 2:
            if sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1]: return "BULLISH", sh, sl
            if sh[-1][1] < sh[-2][1] and sl[-1][1] < sl[-2][1]: return "BEARISH", sh, sl
        return "RANGING", sh, sl

    @staticmethod
    def hurst(series):
        """Hurst exponent via variance ratio (aggregated variance method).
        Uses log returns. Var(q-period returns) scales as q^(2H).
        H > 0.55 = trending, H < 0.45 = mean-reverting, ~0.5 = random walk."""
        ts = series.dropna().values
        if len(ts) < 100:
            return 0.5
        rets = np.diff(np.log(ts))
        rets = rets[np.isfinite(rets)]
        if len(rets) < 80:
            return 0.5
        lags = [2, 4, 8, 16, 32, 64]
        lags = [q for q in lags if q < len(rets) // 4]
        if len(lags) < 3:
            return 0.5
        log_lags, log_vars = [], []
        for q in lags:
            agg = np.array([rets[i:i + q].sum() for i in range(0, len(rets) - q + 1, q)])
            if len(agg) < 5:
                continue
            v = np.var(agg, ddof=1)
            if v > 0:
                log_lags.append(np.log(q))
                log_vars.append(np.log(v))
        if len(log_lags) < 3:
            return 0.5
        slope = np.polyfit(log_lags, log_vars, 1)[0]
        H = slope / 2.0
        return round(float(np.clip(H, 0, 1)), 3)


# ═════════════════════════════════════════════════════════════════════════
#  BLACK-SCHOLES ENGINE — Greeks & fair value pricing
# ═════════════════════════════════════════════════════════════════════════

from math import log, sqrt, exp
try:
    from scipy.stats import norm as _norm
    _cdf = _norm.cdf; _pdf = _norm.pdf
except ImportError:
    # Fallback if scipy not installed — rational approximation of CDF
    def _cdf(x):
        a1,a2,a3,a4,a5 = 0.254829592,-0.284496736,1.421413741,-1.453152027,1.061405429
        sign = 1 if x >= 0 else -1; x = abs(x)/sqrt(2)
        t = 1.0/(1.0+0.3275911*x)
        y = 1.0-(((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*exp(-x*x)
        return 0.5*(1.0+sign*y)
    def _pdf(x):
        return exp(-0.5*x*x)/sqrt(2*3.14159265359)

def bs_price(S, K, T, r, sigma, option_type="call"):
    """Black-Scholes option price. S=spot, K=strike, T=years, r=risk-free rate, sigma=IV."""
    S, K = float(S), float(K)
    if S <= 0 or K <= 0 or not math.isfinite(S) or not math.isfinite(K):
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
    sigma = max(sigma, 0.001)
    if T <= 0:
        return max(0, S - K) if option_type == "call" else max(0, K - S)
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    if option_type == "call":
        return S*_cdf(d1) - K*exp(-r*T)*_cdf(d2)
    return K*exp(-r*T)*_cdf(-d2) - S*_cdf(-d1)

def bs_greeks(S, K, T, r, sigma, option_type="call"):
    """Calculate Delta, Gamma, Theta (per day), Vega (per 1% IV move)."""
    S, K = float(S), float(K)
    if S <= 0 or K <= 0 or not math.isfinite(S) or not math.isfinite(K):
        return {"delta": 1.0 if option_type == "call" else -1.0, "gamma": 0, "theta": 0, "vega": 0}
    sigma = max(sigma, 0.001)
    if T <= 0:
        return {"delta": 1.0 if option_type == "call" else -1.0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    gamma = _pdf(d1) / (S * sigma * sqrt(T))
    vega = S * _pdf(d1) * sqrt(T) / 100  # per 1% move
    if option_type == "call":
        delta = _cdf(d1)
        theta = (-S*_pdf(d1)*sigma/(2*sqrt(T)) - r*K*exp(-r*T)*_cdf(d2)) / 365
    else:
        delta = _cdf(d1) - 1
        theta = (-S*_pdf(d1)*sigma/(2*sqrt(T)) + r*K*exp(-r*T)*_cdf(-d2)) / 365
    return {"delta": round(delta, 3), "gamma": round(gamma, 4), "theta": round(theta, 3), "vega": round(vega, 3)}


# ═════════════════════════════════════════════════════════════════════════
#  EXPECTED VALUE (EV) CALCULATOR
# ═════════════════════════════════════════════════════════════════════════

def calc_ev(premium, max_loss, pop_pct):
    """Calculate Expected Value: EV = (POP * premium) - ((1-POP) * max_loss).
    Returns EV per contract. Positive = edge, negative = avoid."""
    pop = pop_pct / 100
    ev = (pop * premium) - ((1 - pop) * max_loss)
    return round(ev, 2)


def kelly_criterion(win_prob_pct, win_amount, loss_amount):
    """Kelly Criterion: optimal bankroll fraction.
    f* = W - (1-W)/R where W = win probability, R = win/loss payout ratio.
    Returns (full_kelly_pct, half_kelly_pct) as percentages."""
    if loss_amount <= 0 or win_amount <= 0 or win_prob_pct <= 0 or win_prob_pct >= 100:
        return 0.0, 0.0
    W = win_prob_pct / 100
    R = win_amount / loss_amount
    if R < 1e-12:
        return 0.0, 0.0
    full = W - (1 - W) / R
    half = full / 2
    return round(max(0.0, full) * 100, 1), round(max(0.0, half) * 100, 1)


# ═════════════════════════════════════════════════════════════════════════
#  VOLATILITY SKEW — detects institutional hedging
# ═════════════════════════════════════════════════════════════════════════

def calc_vol_skew(price, calls_df, puts_df, otm_pct=0.10):
    """Compare IV of 10% OTM put vs 10% OTM call. Positive = put skew (bearish hedging)."""
    if calls_df is None or puts_df is None or calls_df.empty or puts_df.empty:
        return None, None, None
    target_put_strike = price * (1 - otm_pct)
    target_call_strike = price * (1 + otm_pct)
    # Find nearest strikes
    put_row = puts_df.iloc[(puts_df["strike"] - target_put_strike).abs().argsort()[:1]]
    call_row = calls_df.iloc[(calls_df["strike"] - target_call_strike).abs().argsort()[:1]]
    put_iv = put_row["impliedVolatility"].values[0] * 100 if not put_row.empty and put_row["impliedVolatility"].values[0] else None
    call_iv = call_row["impliedVolatility"].values[0] * 100 if not call_row.empty and call_row["impliedVolatility"].values[0] else None
    if put_iv and call_iv:
        skew = put_iv - call_iv
        return round(skew, 1), round(put_iv, 1), round(call_iv, 1)
    return None, put_iv, call_iv


# ═════════════════════════════════════════════════════════════════════════
#  QUANT EDGE SCORE — DE-CORRELATED (no double-counting momentum)
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def quant_edge_score(df, vix_val=None):
    """Composite 0-100 using five de-correlated dimensions (no Supertrend here — that
    belongs in confluence/diamond context, not double-counted with EMA trend):
    1. Trend — EMA stack only (structure of moving averages)
    2. Momentum — RSI only (single oscillator)
    3. Volume — OBV vs its own history
    4. Volatility — ATR regime + optional VIX
    5. Structure — market-structure label (not redundant with EMA slope)
    Equal 20% weights.
    """
    sc = {}; close = df["Close"].iloc[-1]
    # 1. TREND (equal 20% weight in composite; important for premium sellers)
    if len(df) >= 200:
        e20, e50, e200 = [TA.ema(df["Close"], p).iloc[-1] for p in (20, 50, 200)]
        sc["trend"] = 95 if close > e20 > e50 > e200 else (75 if close > e50 > e200 else (55 if close > e200 else 25))
    else: sc["trend"] = 60
    # 2. MOMENTUM (single indicator: RSI — avoids collinearity with MACD/CCI)
    rv = TA.rsi(df["Close"]).iloc[-1]
    sc["momentum"] = 85 if 40 <= rv <= 60 else (65 if 30 <= rv <= 70 else 25)
    # 3. VOLUME (OBV — measures accumulation/distribution, orthogonal to price momentum)
    obv_s = TA.obv(df)
    sc["volume"] = (85 if obv_s.iloc[-1] > obv_s.iloc[-20] else 35) if len(obv_s) >= 20 else 50
    # 4. VOLATILITY (ATR regime + VIX — for premium sellers, higher = better)
    if len(df) >= 20:
        atr_s = TA.atr(df)
        cur_atr = atr_s.iloc[-1]
        avg_atr = atr_s.iloc[-60:].mean() if len(df) >= 60 else cur_atr
        atr_ratio = cur_atr / avg_atr if avg_atr > 0 else 1
        vol_score = min(100, max(20, 50 + (atr_ratio - 1) * 30))
        if vix_val and vix_val > 0:
            vix_score = min(100, max(20, 30 + (vix_val - 12) * 3))
            vol_score = (vol_score + vix_score) / 2
        sc["volatility"] = vol_score
    else:
        sc["volatility"] = 50
    # 5. STRUCTURE (BOS/CHOCH — pattern-based, not derived from moving averages)
    struct, _, _ = TA.market_structure(df)
    sc["structure"] = 90 if struct == "BULLISH" else (50 if struct == "RANGING" else 20)

    composite = round(np.mean(list(sc.values())), 1)
    return composite, sc


def weekly_trend_label(df_wk):
    """Weekly bias using MACD(12,26,9) and EMA(20) on weekly closes."""
    try:
        if df_wk is None:
            return "UNKNOWN", "#64748b"
        if not isinstance(df_wk, pd.DataFrame):
            return "UNKNOWN", "#64748b"
        if len(df_wk) < 26:
            return "UNKNOWN", "#64748b"
        if "Close" not in df_wk.columns:
            return "UNKNOWN", "#64748b"
        close = pd.to_numeric(df_wk["Close"], errors="coerce").dropna()
        if len(close) < 26:
            return "UNKNOWN", "#64748b"
        ml, sl, _ = TA.macd(close, 12, 26, 9)
        e20 = TA.ema(close, 20).iloc[-1]
        above_ema = close.iloc[-1] > e20
        macd_bull = ml.iloc[-1] > sl.iloc[-1]
        if above_ema and macd_bull:
            return "BULLISH", "#10b981"
        if not above_ema and not macd_bull:
            return "BEARISH", "#ef4444"
        return "MIXED", "#f59e0b"
    except Exception:
        return "UNKNOWN", "#64748b"


# ═════════════════════════════════════════════════════════════════════════
#  GOLD ZONE — dynamic confluence support/resistance
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def calc_gold_zone(df, df_wk=None):
    """Gold Zone: mean of POC, Fib 61.8%, Gann Sq9, and 200-day SMA (institutional anchor).
    ``df_wk`` is accepted for API compatibility; SMA 200 replaces weekly S/R in the blend."""
    price = df["Close"].iloc[-1]
    components = {}

    vp = TA.volume_profile(df)
    if not vp.empty:
        components["POC"] = vp.loc[vp["volume"].idxmax(), "mid"]

    if len(df) >= 60:
        rec = df.iloc[-60:]
        hi, lo = rec["High"].max(), rec["Low"].min()
        components["Fib 61.8%"] = hi - (hi - lo) * 0.618

    if len(df) >= 200:
        components["SMA 200"] = float(df["Close"].rolling(200).mean().iloc[-1])

    gann = TA.gann_sq9(price)
    if gann:
        nearest = min(gann.values(), key=lambda x: abs(x - price))
        components["Gann Sq9"] = nearest

    if components:
        gold_zone = round(np.mean(list(components.values())), 2)
        return gold_zone, components
    return round(price, 2), {}


# ═════════════════════════════════════════════════════════════════════════
#  CONFLUENCE POINTS — 0-to-9 scoring (Startup.io-inspired, enhanced)
# ═════════════════════════════════════════════════════════════════════════

def _calc_confluence_points_core(df, df_wk=None, vix_val=None, gold_zone_price=None):
    """Same scoring as the dashboard confluence meter — not cached.
    Safe to call on ``df.iloc[:i+1]`` for point-in-time diamond detection.
    Pass ``gold_zone_price`` when the caller already computed Gold Zone on the same frame to avoid duplicate work."""
    score = 0
    breakdown = {}
    price = df["Close"].iloc[-1]

    st_l, st_d = TA.supertrend(df)
    bull = st_d.iloc[-1] == 1
    pts = 2 if bull else 0
    score += pts
    breakdown["Supertrend"] = {"pts": pts, "max": 2, "detail": "Bullish" if bull else "Bearish"}

    _, _, sa, sb, _ = TA.ichimoku(df)
    above_cloud = (not pd.isna(sa.iloc[-1]) and not pd.isna(sb.iloc[-1])
                   and price > max(sa.iloc[-1], sb.iloc[-1]))
    pts = 2 if above_cloud else 0
    score += pts
    breakdown["Ichimoku"] = {"pts": pts, "max": 2, "detail": "Above Cloud" if above_cloud else "In/Below Cloud"}

    adx_v, dip, din = TA.adx(df)
    adx_val = adx_v.iloc[-1] if not pd.isna(adx_v.iloc[-1]) else 0
    dip_val = dip.iloc[-1] if not pd.isna(dip.iloc[-1]) else 0
    din_val = din.iloc[-1] if not pd.isna(din.iloc[-1]) else 0
    adx_bull = adx_val > 25 and dip_val > din_val
    pts = 1 if adx_bull else 0
    score += pts
    breakdown["ADX DI"] = {"pts": pts, "max": 1, "detail": f"ADX {adx_val:.0f}, plus DI leading minus DI" if adx_bull else f"ADX {adx_val:.0f}"}

    obv_s = TA.obv(df)
    obv_up = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else False
    pts = 1 if obv_up else 0
    score += pts
    breakdown["OBV"] = {"pts": pts, "max": 1, "detail": "Accumulation" if obv_up else "Distribution"}

    rsi_s = TA.rsi(df["Close"])
    divs = TA.detect_divergences(df["Close"], rsi_s)
    bull_div = any(d["type"] == "bullish" for d in divs[-3:])
    pts = 1 if bull_div else 0
    score += pts
    breakdown["Divergence"] = {"pts": pts, "max": 1, "detail": "Bullish Div Found" if bull_div else "None"}

    if gold_zone_price is None:
        gold_zone, _ = calc_gold_zone(df, df_wk)
    else:
        gold_zone = gold_zone_price
    above_gz = price > gold_zone
    pts = 1 if above_gz else 0
    score += pts
    breakdown["Gold Zone"] = {"pts": pts, "max": 1, "detail": f"{'Above' if above_gz else 'Below'} ${gold_zone:.2f}"}

    struct, _, _ = TA.market_structure(df)
    pts = 1 if struct == "BULLISH" else 0
    score += pts
    breakdown["Structure"] = {"pts": pts, "max": 1, "detail": struct}

    bearish = 9 - score
    return score, 9, breakdown, bearish


@st.cache_data(ttl=300)
def calc_confluence_points(df, df_wk=None, vix_val=None, gold_zone_price=None):
    """Compute 0-9 bullish confluence score with per-component breakdown.
    Returns (score, max_score, breakdown_dict, bearish_score)."""
    return _calc_confluence_points_core(df, df_wk, vix_val, gold_zone_price)


# ═════════════════════════════════════════════════════════════════════════
#  DIAMOND SIGNAL DETECTION — Blue (buy) & Pink (exit/take-profit)
# ═════════════════════════════════════════════════════════════════════════

def _blue_diamond_volume_gate(sub):
    """Blue Diamond participation: last bar volume at or above 90% of the 20-day volume SMA."""
    if len(sub) < 20 or "Volume" not in sub.columns:
        return False
    vol = float(sub["Volume"].iloc[-1])
    vma = float(sub["Volume"].iloc[-20:].mean())
    if vma <= 0:
        return False
    return vol >= 0.9 * vma


def _blue_diamond_institutional_ok(sub):
    """Filter manic blue entries: skip only true blow-offs (ATR in top ~1% of its window)
    with weak participation. Normal trend days often sit near rolling ATR highs — those
    were incorrectly blocked before, so blues never matched the chart while pinks could still fire."""
    if len(sub) < 22:
        return False
    if not _blue_diamond_volume_gate(sub):
        return False
    vol = float(sub["Volume"].iloc[-1])
    vma = float(sub["Volume"].iloc[-20:].mean())

    atr = TA.atr(sub)
    ai = float(atr.iloc[-1])
    if pd.isna(ai) or ai <= 0:
        return True
    win = min(252, len(atr))
    atr_clean = atr.iloc[-win:].dropna()
    if atr_clean.empty:
        return True
    # Rank of today's ATR in the window (1.0 = at/above everyone) — block only top-tier expansion + weak vol
    rank = float((atr_clean <= ai).sum()) / len(atr_clean)
    if rank >= 0.99 and vol < 1.05 * vma:
        return False
    return True


def _index_pos(idx_obj):
    """Normalize df.index.get_loc result to a single integer position."""
    if isinstance(idx_obj, (int, np.integer)):
        return int(idx_obj)
    if isinstance(idx_obj, slice):
        return idx_obj.start
    arr = np.asarray(idx_obj)
    return int(arr.flat[-1])


@st.cache_data(ttl=300)
def detect_diamonds(df, df_wk=None, lookback=None):
    """Blue Diamond (strict): point-in-time **daily** confluence **crosses** to 7+ (was <7 prior bar),
    **daily structure BULLISH**, **weekly trend not BEARISH**, **volume ≥ 90% of 20-day volume SMA**,
    plus ATR blow-off guard inside the institutional filter.

    Pink Diamond: confluence collapse (≤3 after ≥5) **or** RSI > 75 with fading score;
    weekly bias can be **BULLISH** too (take-profit / de-risk in extended runs)."""
    diamonds = []
    n = len(df)
    if n < 55:
        return diamonds

    rsi_series = TA.rsi(df["Close"])

    wk_bias = "UNKNOWN"
    if df_wk is not None and len(df_wk) >= 26:
        wk_bias, _ = weekly_trend_label(df_wk)

    # First index where slice has 55 rows (need stable Ichimoku / gold / structure).
    start = 54
    prev_score = 0

    for i in range(start, n):
        sub = df.iloc[: i + 1]
        sc, _, _, _ = _calc_confluence_points_core(sub, df_wk, None)
        struct_i, _, _ = TA.market_structure(sub)

        rsi_i = float(rsi_series.iloc[i]) if not pd.isna(rsi_series.iloc[i]) else 50.0
        pi = float(df["Close"].iloc[i])

        # Blue: 7+ cross + daily BULLISH + weekly not BEARISH + explicit 90% vol SMA gate + ATR filter
        if (
            sc >= 7
            and prev_score < 7
            and struct_i == "BULLISH"
            and wk_bias != "BEARISH"
            and _blue_diamond_volume_gate(sub)
        ):
            if _blue_diamond_institutional_ok(sub):
                diamonds.append({"date": df.index[i], "price": pi, "type": "blue",
                                 "score": sc, "rsi": rsi_i, "weekly": wk_bias})

        # Pink: collapse or RSI exhaustion — allow BULLISH weeks too (fade / de-risk in extended runs)
        if (sc <= 3 and prev_score >= 5) or (rsi_i > 75 and sc <= 4 and prev_score > 4):
            if wk_bias in ("BEARISH", "MIXED", "UNKNOWN", "BULLISH"):
                diamonds.append({"date": df.index[i], "price": pi, "type": "pink",
                                 "score": sc, "rsi": rsi_i, "weekly": wk_bias})

        prev_score = sc

    return diamonds


def diamond_win_rate(df, diamonds, forward_bars=10):
    """Backtest diamond signals: for Blue, check if price rose; for Pink, check
    if price fell.  Returns (win_rate_pct, avg_return_pct, sample_count)."""
    if not diamonds:
        return 0.0, 0.0, 0

    wins, total = 0, 0
    returns = []

    for d in diamonds:
        try:
            loc = df.index.get_loc(d["date"])
            idx = _index_pos(loc)
        except KeyError:
            continue
        if idx + forward_bars >= len(df):
            continue

        entry = d["price"]
        exit_p = df["Close"].iloc[idx + forward_bars]

        if d["type"] == "blue":
            ret = (exit_p - entry) / entry * 100
            if exit_p > entry:
                wins += 1
        else:
            ret = (entry - exit_p) / entry * 100
            if exit_p < entry:
                wins += 1

        returns.append(ret)
        total += 1

    if total == 0:
        return 0.0, 0.0, 0
    return round(wins / total * 100, 1), round(float(np.mean(returns)), 2), total


def latest_diamond_status(diamonds):
    """Return the most recent diamond or None."""
    if not diamonds:
        return None
    return diamonds[-1]


# ═════════════════════════════════════════════════════════════════════════
#  MARKET SCANNER — batch-scan a watchlist
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def scan_single_ticker(tkr):
    """Fetch data and compute all scores for a single ticker (for the scanner)."""
    try:
        df = fetch_stock(tkr, "1y", "1d")
        if df is None or len(df) < 60:
            return None
        df_wk = fetch_stock(tkr, "2y", "1wk")
        price = df["Close"].iloc[-1]
        prev = df["Close"].iloc[-2] if len(df) >= 2 else price
        chg_pct = (price / prev - 1) * 100

        qs, _ = quant_edge_score(df)
        gold_zone, _ = calc_gold_zone(df, df_wk)
        cp_score, cp_max, cp_bd, _ = calc_confluence_points(df, df_wk, None, gold_zone_price=gold_zone)
        diamonds = detect_diamonds(df, df_wk)
        latest_d = latest_diamond_status(diamonds)
        dist_gz = (price / gold_zone - 1) * 100 if gold_zone else 0

        struct, _, _ = TA.market_structure(df)
        wk_lbl, _ = weekly_trend_label(df_wk)

        d_status = "None"
        d_class = "badge-none"
        if latest_d:
            age = (df.index[-1] - latest_d["date"]).days
            if age <= 5:
                d_status = "🔷 BLUE" if latest_d["type"] == "blue" else "💎 PINK"
                d_class = "badge-blue" if latest_d["type"] == "blue" else "badge-pink"

        if cp_score >= 7:
            summary = "Strong bullish setup. High confluence buy zone."
        elif cp_score >= 5:
            summary = "Moderate bullish lean. Watch for confirmation."
        elif cp_score >= 3:
            summary = "Mixed signals. Neutral stance recommended."
        else:
            summary = "Bearish pressure. Defensive posture advised."

        return {"ticker": tkr, "price": price, "chg_pct": chg_pct, "qs": qs,
                "cp_score": cp_score, "cp_max": cp_max, "d_status": d_status,
                "d_class": d_class, "gold_zone": gold_zone, "dist_gz": dist_gz,
                "struct": struct, "wk_trend": wk_lbl, "summary": summary}
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════
#  OPTIONS ENGINE
# ═════════════════════════════════════════════════════════════════════════

class Opt:
    DELTA_TARGET = 0.16
    DELTA_LOW, DELTA_HIGH = 0.15, 0.20
    MIN_OI, MIN_VOL = 100, 10

    @staticmethod
    def _sc(otm, py, ann, vol, delta=None):
        base = py * .25 + min(otm, 15) * .15 + min(ann, 50) * .15 + (1 if vol and vol > 100 else 0) * .05
        if delta is not None:
            d = abs(delta)
            if Opt.DELTA_LOW <= d <= Opt.DELTA_HIGH:
                base += (1.0 - abs(d - Opt.DELTA_TARGET) / 0.05) * 5
            elif d < 0.10 or d > 0.30:
                base *= 0.5
        return base

    @staticmethod
    def covered_calls(price, calls_df, dte=30, rfr=0.045):
        if calls_df is None or calls_df.empty: return []
        rows = []; T_y = max(dte, 1) / 365
        for _, r in calls_df.iterrows():
            s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
            iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
            mid = (b + a) / 2 if b > 0 and a > 0 else 0
            if s <= price or mid <= .01: continue
            if oi < Opt.MIN_OI or vol < Opt.MIN_VOL: continue
            otm = (s - price) / price * 100; py = mid / price * 100; ann = py * 365 / max(dte, 1)
            iv_dec = iv if iv > 0 else 0.5
            greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "call")
            delta = greeks["delta"]
            rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                         "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                         "prem_100": mid * 100, "breakeven": price - mid,
                         "delta": round(delta, 3), "optimal": False,
                         "score": Opt._sc(otm, py, ann, vol, delta)})
        rows.sort(key=lambda x: x["score"], reverse=True)
        if rows:
            best = min(range(len(rows)), key=lambda i: abs(rows[i]["delta"] - Opt.DELTA_TARGET))
            rows[best]["optimal"] = True
        return rows[:8]

    @staticmethod
    def cash_secured_puts(price, puts_df, dte=30, rfr=0.045):
        if puts_df is None or puts_df.empty: return []
        rows = []; T_y = max(dte, 1) / 365
        for _, r in puts_df.iterrows():
            s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
            iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
            mid = (b + a) / 2 if b > 0 and a > 0 else 0
            if s >= price or mid <= .01: continue
            if oi < Opt.MIN_OI or vol < Opt.MIN_VOL: continue
            otm = (price - s) / price * 100; py = mid / s * 100; ann = py * 365 / max(dte, 1)
            iv_dec = iv if iv > 0 else 0.5
            greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "put")
            delta = greeks["delta"]
            rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                         "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                         "prem_100": mid * 100, "eff_buy": s - mid, "cash_req": s * 100,
                         "delta": round(delta, 3), "optimal": False,
                         "score": Opt._sc(otm, py, ann, vol, delta)})
        rows.sort(key=lambda x: x["score"], reverse=True)
        if rows:
            best = min(range(len(rows)), key=lambda i: abs(abs(rows[i]["delta"]) - Opt.DELTA_TARGET))
            rows[best]["optimal"] = True
        return rows[:8]

    @staticmethod
    def credit_spreads(price, opts_df, stype="put_credit"):
        if opts_df is None or opts_df.empty: return []
        rows = []; strikes = sorted(opts_df["strike"].unique())
        for i in range(len(strikes)):
            for j in range(i + 1, min(i + 6, len(strikes))):
                ss = strikes[i] if stype == "call_credit" else strikes[j]
                ls = strikes[j] if stype == "call_credit" else strikes[i]
                sr, lr = opts_df[opts_df["strike"] == ss], opts_df[opts_df["strike"] == ls]
                if sr.empty or lr.empty: continue
                s_oi = (sr["openInterest"].values[0] or 0) if "openInterest" in sr.columns else 0
                s_vol = (sr["volume"].values[0] or 0) if "volume" in sr.columns else 0
                l_oi = (lr["openInterest"].values[0] or 0) if "openInterest" in lr.columns else 0
                l_vol = (lr["volume"].values[0] or 0) if "volume" in lr.columns else 0
                if s_oi < Opt.MIN_OI or s_vol < Opt.MIN_VOL: continue
                if l_oi < Opt.MIN_OI or l_vol < Opt.MIN_VOL: continue
                sm = (sr["bid"].values[0] + sr["ask"].values[0]) / 2
                lm = (lr["bid"].values[0] + lr["ask"].values[0]) / 2
                cr = sm - lm; w = abs(ss - ls)
                if cr <= 0 or w <= cr: continue
                ml = (w - cr) * 100
                otm = ((price - ss) / price * 100) if stype == "put_credit" else ((ss - price) / price * 100)
                if otm < 0: continue
                pop = max(30, min(95, (1 - cr / w) * 100))
                rows.append({"short": ss, "long": ls, "credit": cr, "credit_100": cr * 100,
                             "max_loss": ml, "width": w, "rr": cr / (w - cr), "pop": pop, "otm_pct": otm,
                             "be": ss - cr if stype == "put_credit" else ss + cr})
        rows.sort(key=lambda x: x["rr"] * x["pop"], reverse=True)
        return rows[:8]


# ═════════════════════════════════════════════════════════════════════════
#  SENTIMENT, BACKTEST, ALERTS
# ═════════════════════════════════════════════════════════════════════════

class Sentiment:
    @staticmethod
    def fear_greed(df, vix_val=None):
        sc = [min(100, max(0, TA.rsi(df["Close"]).iloc[-1]))]
        sma200 = df["Close"].rolling(200).mean().iloc[-1] if len(df) >= 200 else df["Close"].mean()
        sc.append(min(100, max(0, 50 + (df["Close"].iloc[-1]/sma200-1)*500)))
        if len(df) >= 20:
            sc.append(min(100, max(0, 50 + (df["Close"].iloc[-1]/df["Close"].iloc[-20]-1)*300)))
            cv = df["Close"].pct_change().iloc[-20:].std()*np.sqrt(252)*100
            hv = df["Close"].pct_change().std()*np.sqrt(252)*100
            sc.append(max(0, min(100, 100-cv/max(hv,1)*50)))
        if vix_val and vix_val > 0: sc.append(max(0, min(100, 100-(vix_val-12)*3)))
        return np.mean(sc)

    @staticmethod
    def interpret(s):
        if s >= 80: return "Extreme Greed","🔴","Everyone is euphoric. Sell calls aggressively and collect the hype premium."
        if s >= 60: return "Greed","🟠","Market is confident. Sell covered calls at higher strikes to ride the wave."
        if s >= 40: return "Neutral","🟡","Market is calm. Standard premium selling works great here."
        if s >= 20: return "Fear","🟢","Fear is elevated. Premiums are fat. Sell aggressively and collect extra cash."
        return "Extreme Fear","💚","Maximum panic. Premiums are huge. Sell puts at deep discounts and get paid."

class Backtest:
    @staticmethod
    def cc_sim(df, otm_pct=.05, hold=30, iv_m=1.0):
        results = []; rvol = df["Close"].pct_change().rolling(20).std()*np.sqrt(252)
        i = 20
        while i < len(df) - hold:
            entry = df["Close"].iloc[i]; strike = entry*(1+otm_pct)
            iv = rvol.iloc[i]
            if pd.isna(iv) or iv <= 0: iv = 0.5
            iv *= iv_m; tf = math.sqrt(hold/365)
            d1a = otm_pct/(iv*tf) if iv*tf > 0 else 1
            prem = entry*iv*tf*max(.05,.4-.3*min(d1a,2)); prem = max(prem, entry*.003)
            exit_p = df["Close"].iloc[i+hold]
            if exit_p >= strike: profit = (strike-entry)+prem; out = "Called Away"
            else: profit = prem+(exit_p-entry); out = "Expired OTM"
            results.append({"entry_date":df.index[i],"exit_date":df.index[i+hold],
                "entry":entry,"strike":strike,"exit":exit_p,"iv_est":iv*100,
                "premium":prem,"profit":profit,"ret_pct":profit/entry*100,"outcome":out})
            i += hold
        return pd.DataFrame(results)


@st.cache_data(ttl=120, show_spinner=False)
def run_cc_sim_cached(ticker: str, period: str, otm_pct: float, hold_days: int, iv_mult: float) -> pd.DataFrame:
    """Premium simulator: reuse cached OHLC; avoids recomputing the same sweep on every interaction."""
    df_bt = fetch_stock(ticker, period, "1d")
    if df_bt is None or len(df_bt) < hold_days + 20:
        return pd.DataFrame()
    return Backtest.cc_sim(df_bt, otm_pct, hold_days, iv_mult)


class Alerts:
    @staticmethod
    def scan(df, ticker, vix_val=None):
        alerts = []; close = df["Close"].iloc[-1]; rv = TA.rsi(df["Close"]).iloc[-1]
        if rv < 30: alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} RSI is {rv:.1f}. Stock is oversold. Great time to sell puts and collect cash."})
        elif rv > 70: alerts.append({"t":"bearish","p":"MEDIUM","m":f"{ticker} RSI is {rv:.1f}. Stock is overbought. Sell covered calls now."})
        ml, sl, _ = TA.macd(df["Close"])
        if len(ml) >= 2:
            if ml.iloc[-1] > sl.iloc[-1] and ml.iloc[-2] <= sl.iloc[-2]:
                alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} MACD just crossed bullish. Buyers are taking over."})
            elif ml.iloc[-1] < sl.iloc[-1] and ml.iloc[-2] >= sl.iloc[-2]:
                alerts.append({"t":"bearish","p":"MEDIUM","m":f"{ticker} MACD just crossed bearish. Sellers are gaining control."})
        u, _, lo = TA.bollinger(df["Close"])
        if len(u)>1:
            bw = (u.iloc[-1]-lo.iloc[-1])/((u.iloc[-1]+lo.iloc[-1])/2)*100
            if bw < 5: alerts.append({"t":"neutral","p":"HIGH","m":f"{ticker} Bollinger squeeze detected. A big move is coming soon."})
        if vix_val and vix_val > 30: alerts.append({"t":"bullish","p":"HIGH","m":f"VIX is {vix_val:.1f}. Extreme fear. Premiums are huge right now."})
        elif vix_val and vix_val > 25: alerts.append({"t":"bullish","p":"MEDIUM","m":f"VIX is {vix_val:.1f}. Fear is elevated. Good time to sell options."})
        st_l, st_d = TA.supertrend(df)
        if len(st_d) >= 2:
            if st_d.iloc[-1]==1 and st_d.iloc[-2]==-1: alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} Supertrend just flipped BULLISH. The price floor is rising."})
            elif st_d.iloc[-1]==-1 and st_d.iloc[-2]==1: alerts.append({"t":"bearish","p":"HIGH","m":f"{ticker} Supertrend just flipped BEARISH. The price ceiling is falling."})
        rsi_s = TA.rsi(df["Close"]); divs = TA.detect_divergences(df["Close"], rsi_s)
        for d in divs[-2:]:
            alerts.append({"t":d["type"],"p":"MEDIUM","m":f"{ticker} RSI {d['type']} divergence near ${d['price']:.2f}. Early warning of a reversal."})
        return alerts


# ═════════════════════════════════════════════════════════════════════════
#  CHART BUILDER
# ═════════════════════════════════════════════════════════════════════════

def _levels_nearest(levels, price, n):
    """Pick the n prices closest to `price` (clearest S/R vs far-away clusters)."""
    if not levels:
        return []
    return sorted(set(levels), key=lambda x: abs(float(x) - price))[:n]


def _chart_hoverlabel():
    return dict(
        bgcolor="rgba(15, 23, 42, 0.96)",
        bordercolor="rgba(100, 116, 139, 0.45)",
        font=dict(size=12, family="Inter, system-ui, sans-serif", color="#f8fafc"),
        align="left",
    )


def build_chart(df, ticker, show_ind=True, show_fib=True, show_gann=True, show_sr=True,
                show_ichi=False, show_super=False, diamonds=None, gold_zone=None,
                mobile_layout=False):
    """Build four separate figures: price (+ overlays), volume, RSI, MACD — easier to read than one stacked chart.

    When ``mobile_layout`` is True (narrow UA / phone), the price panel drops the legend, tightens margins,
    fixes height, and pins Fib / Gann / Gold annotations to the left so labels do not sit on the candles."""
    last_px = float(df["Close"].iloc[-1])
    ann_side = "left" if mobile_layout else "right"
    _legend_font = dict(size=11, color="#f1f5f9", family="Inter, system-ui, sans-serif")
    _legend_title_font = dict(size=12, color="#e2e8f0", family="Inter, system-ui, sans-serif")
    uirev = f"{ticker}_tech"
    _tk = _html_mod.escape(str(ticker))

    fig_p = go.Figure()
    fig_p.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            increasing_line_color=_PLOTLY_CASH_UP, decreasing_line_color=_PLOTLY_CASH_DOWN,
            increasing_fillcolor=_PLOTLY_CASH_UP, decreasing_fillcolor=_PLOTLY_CASH_DOWN,
            increasing_line_width=1.35, decreasing_line_width=1.35,
            name="Price",
            hovertemplate=(
                "<b>" + _tk + "</b> · %{x|%Y-%m-%d}<br>"
                "O <span style='color:#94a3b8'>$%{open:,.2f}</span> &nbsp;H <span style='color:#94a3b8'>$%{high:,.2f}</span><br>"
                "L <span style='color:#94a3b8'>$%{low:,.2f}</span> &nbsp;C <span style='color:#94a3b8'>$%{close:,.2f}</span><extra></extra>"
            ),
        )
    )
    if show_ind:
        for p, c in [(20, "#60a5fa"), (50, _PLOTLY_BLUE), (200, _PLOTLY_BLUE_DEEPER)]:
            if len(df) >= p:
                fig_p.add_trace(
                    go.Scatter(
                        x=df.index, y=TA.ema(df["Close"], p), mode="lines",
                        line=dict(color=c, width=1.1), name=f"EMA {p}", opacity=0.92,
                        hovertemplate=f"EMA {p}: $%{{y:,.2f}}<extra></extra>",
                    )
                )
        u, _m, lo = TA.bollinger(df["Close"])
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=u, line=dict(color="rgba(100,116,139,0.55)", width=1),
                name="Bollinger", legendgroup="bb", showlegend=True,
                hovertemplate="BB upper: $%{y:,.2f}<extra></extra>",
            )
        )
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=lo, line=dict(color="rgba(100,116,139,0.55)", width=1),
                fill="tonexty", fillcolor="rgba(59,130,246,0.06)",
                name="BB lower", legendgroup="bb", showlegend=False,
                hovertemplate="BB lower: $%{y:,.2f}<extra></extra>",
            )
        )
    if show_ichi:
        t, k, sa, sb, _ = TA.ichimoku(df)
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=t, line=dict(color="#38bdf8", width=1.1), name="Tenkan", opacity=0.85,
                hovertemplate="Tenkan: $%{y:,.2f}<extra></extra>",
            )
        )
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=k, line=dict(color="#818cf8", width=1.1), name="Kijun", opacity=0.85,
                hovertemplate="Kijun: $%{y:,.2f}<extra></extra>",
            )
        )
        fig_p.add_trace(
            go.Scatter(x=df.index, y=sa, line=dict(color="rgba(16,185,129,0.25)", width=0),
                       name="Senkou A", showlegend=False)
        )
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=sb, line=dict(color="rgba(248,113,113,0.22)", width=0),
                fill="tonexty", fillcolor="rgba(52,211,153,0.06)", name="Ichimoku cloud",
                hovertemplate="Ichimoku cloud<extra></extra>",
            )
        )
    if show_super:
        st_l, _st_d = TA.supertrend(df)
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=st_l, mode="lines",
                line=dict(color=_PLOTLY_BLUE_DEEP, width=2), name="Supertrend",
                hovertemplate="Supertrend: $%{y:,.2f}<extra></extra>",
            )
        )
    if show_fib and len(df) >= 50:
        rec = df.iloc[-60:]
        fl = TA.fib_retracement(rec["High"].max(), rec["Low"].min())
        fib_draw_order = ["0.0%", "38.2%", "50.0%", "61.8%", "100.0%"]
        fib_labeled = {"38.2%", "50.0%", "61.8%"}
        fib_short = {"0.0%": "0%", "100.0%": "100%"}
        for lab in fib_draw_order:
            if lab not in fl:
                continue
            lev = fl[lab]
            ann = ""
            if lab in fib_labeled:
                ann = f"{lab.split('.')[0]}% · ${lev:.2f}"
            elif lab in fib_short:
                ann = f"{fib_short[lab]} ${lev:.2f}"
            lw = 1.9 if lab in fib_labeled else 1.1
            op = 0.62 if lab in fib_labeled else 0.38
            fig_p.add_hline(
                y=lev, line_dash="dot", line_color="rgba(59,130,246,0.5)", line_width=lw,
                opacity=op, annotation_text=ann, annotation_position=ann_side,
                annotation_font=dict(size=10, color="rgba(147,197,253,0.95)"),
            )
    if show_gann:
        gl = TA.gann_sq9(last_px)
        near = sorted(gl.items(), key=lambda x: abs(x[1] - last_px))[:3]
        for i, (_lab, lev) in enumerate(near, start=1):
            fig_p.add_hline(
                y=lev, line_dash="dash", line_color="rgba(250,204,21,0.42)", line_width=1.2,
                opacity=0.55, annotation_text=f"G{i} ${lev:.0f}", annotation_position=ann_side,
                annotation_font=dict(size=9, color="rgba(253,224,71,0.9)"),
            )
    if show_sr:
        sups, ress = TA.find_sr(df)
        for s in _levels_nearest(sups, last_px, 2):
            fig_p.add_hline(
                y=s, line_dash="solid", line_color="rgba(34,197,94,0.45)", line_width=1.2,
                opacity=0.55, annotation_text=f"S {s:.2f}", annotation_position="left",
                annotation_font=dict(size=9, color="rgba(134,239,172,0.95)"),
            )
        for r in _levels_nearest(ress, last_px, 2):
            fig_p.add_hline(
                y=r, line_dash="solid", line_color="rgba(248,113,113,0.45)", line_width=1.2,
                opacity=0.55, annotation_text=f"R {r:.2f}", annotation_position="left",
                annotation_font=dict(size=9, color="rgba(254,202,202,0.95)"),
            )
    if gold_zone is not None:
        fig_p.add_hline(
            y=gold_zone, line_dash="solid", line_color="#eab308", line_width=3, opacity=0.9,
            annotation_text=f"Gold ${gold_zone:.2f}", annotation_position=ann_side,
            annotation_font=dict(color="#fde047", size=11, family="JetBrains Mono"),
        )

    if diamonds is not None:
        blue_d = [d for d in diamonds if d["type"] == "blue"]
        pink_d = [d for d in diamonds if d["type"] == "pink"]
        # Slightly smaller markers: legend row height matches line swatches better than size 17.
        _dm = dict(symbol="diamond", size=13, line=dict(color="rgba(248,250,252,0.95)", width=1.5))
        if blue_d:
            fig_p.add_trace(
                go.Scatter(
                    x=[d["date"] for d in blue_d],
                    y=[d["price"] * 0.985 for d in blue_d],
                    mode="markers",
                    marker={**_dm, "color": "#2563eb"},
                    name="Blue diamond",
                    legendgroup="diamond_blue",
                    hovertemplate="<b>Blue diamond</b><br>%{x|%Y-%m-%d}<br><b>$%{customdata:,.2f}</b><br>7+ confluence cross up (buy / add zone)<extra></extra>",
                    customdata=[d["price"] for d in blue_d],
                )
            )
        else:
            # Legend key only when no blue in history: tiny marker off last close so the chart matches the key.
            fig_p.add_trace(
                go.Scatter(
                    x=[df.index[-1]],
                    y=[last_px * 1.004],
                    mode="markers",
                    marker={**_dm, "color": "#2563eb", "size": 8, "opacity": 0.35},
                    name="Blue diamond",
                    legendgroup="diamond_blue",
                    hovertemplate="<b>Blue diamond</b><br>Same marker as on chart when a buy signal fires.<br>"
                    "Fires on <b>7+ confluence cross up</b>, <b>daily BULLISH structure</b>, weekly trend <b>not BEARISH</b>, "
                    "<b>volume ≥ 90% of 20d vol SMA</b>, plus ATR participation filter.<br>"
                    "<i>No blue diamond in loaded history yet.</i><extra></extra>",
                )
            )
        if pink_d:
            fig_p.add_trace(
                go.Scatter(
                    x=[d["date"] for d in pink_d],
                    y=[d["price"] * 1.015 for d in pink_d],
                    mode="markers",
                    marker={**_dm, "color": "#e11d48"},
                    name="Pink diamond",
                    legendgroup="diamond_pink",
                    hovertemplate="<b>Pink diamond</b><br>%{x|%Y-%m-%d}<br><b>$%{customdata:,.2f}</b><br>Exit / de-risk (confluence fade or RSI exhaustion)<extra></extra>",
                    customdata=[d["price"] for d in pink_d],
                )
            )
        else:
            fig_p.add_trace(
                go.Scatter(
                    x=[df.index[-1]],
                    y=[last_px * 0.996],
                    mode="markers",
                    marker={**_dm, "color": "#e11d48", "size": 8, "opacity": 0.35},
                    name="Pink diamond",
                    legendgroup="diamond_pink",
                    hovertemplate="<b>Pink diamond</b><br>Same marker as on chart for take-profit / defensive posture.<br>"
                    "<i>No pink diamond in loaded history yet.</i><extra></extra>",
                )
            )

    _p_height = 450 if mobile_layout else 540
    _p_margin = dict(l=5, r=5, t=52, b=40) if mobile_layout else dict(l=56, r=88, t=56, b=44)
    _p_show_legend = not mobile_layout
    fig_p.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        title=dict(
            text=f"<b>{ticker}</b> · price & overlays",
            x=0.01, xanchor="left", y=0.98, yanchor="top",
            font=dict(size=15, color="#f1f5f9", family="Inter, system-ui, sans-serif"),
        ),
        height=_p_height,
        margin=_p_margin,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=_p_show_legend,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            font=_legend_font,
            bgcolor="rgba(15, 23, 42, 0.78)",
            bordercolor="rgba(100,116,139,0.45)",
            borderwidth=1,
            traceorder="normal",
            itemwidth=34,
            itemsizing="constant",
            title_text="Overlays",
            title_font=_legend_title_font,
        ),
        hoverlabel=_chart_hoverlabel(),
    )
    fig_p.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_p.update_yaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        title_text="Price",
        tickprefix="$",
        tickformat=",.2f",
        **_PLOTLY_AXIS_TITLE,
    )

    vc = [_PLOTLY_CASH_UP if c >= o else _PLOTLY_CASH_DOWN for c, o in zip(df["Close"], df["Open"])]
    fig_v = go.Figure(
        data=[
            go.Bar(
                x=df.index, y=df["Volume"], marker_color=vc, name="Volume", opacity=0.58,
                hovertemplate="Volume: %{y:,.0f} shares<extra></extra>",
            )
        ]
    )
    _vm = dict(l=5, r=5, t=24, b=36) if mobile_layout else dict(l=56, r=28, t=28, b=44)
    fig_v.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        height=200 if mobile_layout else 240,
        margin=_vm,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=False,
        hoverlabel=_chart_hoverlabel(),
    )
    fig_v.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_v.update_yaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        title_text="Volume (shares)",
        tickformat=",.0f",
        **_PLOTLY_AXIS_TITLE,
    )

    fig_r = go.Figure()
    fig_r.add_trace(
        go.Scatter(
            x=df.index, y=TA.rsi(df["Close"]), line=dict(color=_PLOTLY_BLUE_DEEP, width=2), name="RSI",
            hovertemplate="<b>RSI (14)</b><br>%{y:.1f}<extra></extra>",
        )
    )
    fig_r.add_hline(y=70, line_dash="dot", line_color="rgba(248,113,113,0.35)")
    fig_r.add_hline(y=50, line_dash="dot", line_color=_PLOTLY_GRID)
    fig_r.add_hline(y=30, line_dash="dot", line_color="rgba(52,211,153,0.35)")
    if diamonds:
        rsi_track = TA.rsi(df["Close"])
        bx, by, px, py = [], [], [], []
        for d in diamonds:
            try:
                ix = _index_pos(df.index.get_loc(d["date"]))
            except (KeyError, TypeError, IndexError):
                continue
            rv = float(rsi_track.iloc[ix]) if not pd.isna(rsi_track.iloc[ix]) else 50.0
            if d["type"] == "blue":
                bx.append(d["date"])
                by.append(rv)
            else:
                px.append(d["date"])
                py.append(rv)
        _dm_rsi = dict(symbol="diamond", size=15, line=dict(color="rgba(248,250,252,0.95)", width=2))
        if bx:
            fig_r.add_trace(
                go.Scatter(
                    x=bx, y=by, mode="markers",
                    marker={**_dm_rsi, "color": "#2563eb"},
                    name="Blue diamond", showlegend=False,
                    hovertemplate="<b>Blue diamond</b><br>%{x|%Y-%m-%d}<br>RSI %{y:.1f}<extra></extra>",
                )
            )
        if px:
            fig_r.add_trace(
                go.Scatter(
                    x=px, y=py, mode="markers",
                    marker={**_dm_rsi, "color": "#e11d48"},
                    name="Pink diamond", showlegend=False,
                    hovertemplate="<b>Pink diamond</b><br>%{x|%Y-%m-%d}<br>RSI %{y:.1f}<extra></extra>",
                )
            )
    _rm = dict(l=5, r=5, t=24, b=36) if mobile_layout else dict(l=56, r=28, t=28, b=44)
    fig_r.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        height=220 if mobile_layout else 260,
        margin=_rm,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=False,
        hoverlabel=_chart_hoverlabel(),
    )
    fig_r.update_yaxes(
        range=[0, 100],
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        title_text="RSI",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_r.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )

    ml, sl, hist = TA.macd(df["Close"])
    hc = [_PLOTLY_CASH_UP if v >= 0 else _PLOTLY_CASH_DOWN for v in hist]
    fig_m = go.Figure()
    fig_m.add_trace(
        go.Scatter(
            x=df.index, y=ml, line=dict(color=_PLOTLY_BLUE_DEEP, width=1.6), name="MACD",
            hovertemplate="<b>MACD</b><br>%{y:.4f}<extra></extra>",
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=df.index, y=sl, line=dict(color=_PLOTLY_SLATE, width=1.1), name="Signal",
            hovertemplate="<b>Signal</b><br>%{y:.4f}<extra></extra>",
        )
    )
    fig_m.add_trace(
        go.Bar(
            x=df.index, y=hist, marker_color=hc, name="Histogram", opacity=0.58,
            hovertemplate="<b>Histogram</b><br>%{y:+.4f}<extra></extra>",
        )
    )
    _mm = dict(l=5, r=5, t=28, b=36) if mobile_layout else dict(l=56, r=28, t=36, b=44)
    fig_m.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        height=240 if mobile_layout else 280,
        margin=_mm,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=not mobile_layout,
        legend=dict(
            orientation="h",
            bgcolor="rgba(15,23,42,0.78)",
            bordercolor="rgba(148,163,184,0.35)",
            borderwidth=1,
            x=0.99, xanchor="right", y=0.99, yanchor="top",
            font=dict(size=10, color="#94a3b8"),
        ),
        hoverlabel=_chart_hoverlabel(),
    )
    fig_m.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_m.update_yaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=True,
        zerolinecolor="rgba(128,128,128,0.25)",
        zerolinewidth=1,
        title_text="MACD",
        **_PLOTLY_AXIS_TITLE,
    )

    return fig_p, fig_v, fig_r, fig_m


# ═════════════════════════════════════════════════════════════════════════
#  UI HELPERS — reusable explanation cards and section dividers
# ═════════════════════════════════════════════════════════════════════════

def _factor_checklist_labels():
    return {
        "Supertrend": "Supertrend supports buyers",
        "Ichimoku": "Price above the cloud",
        "ADX DI": "Strong trend with buyers in front",
        "OBV": "Big money accumulation",
        "Divergence": "Bullish divergence hint",
        "Gold Zone": "Above Gold Zone",
        "Structure": "Higher highs and higher lows",
    }


def _confluence_why_trade_plain(cp_breakdown):
    """One-line copy for Recommended Trade tooltip — same 7 headline rows as Diamond checklist."""
    head = (
        "7/9 Diamond headline checklist: Supertrend (2), Ichimoku cloud (2), ADX DI (1), OBV (1), "
        "Divergence (1), Gold Zone (1), Structure (1). "
    )
    if not cp_breakdown:
        return (
            head
            + "Live factor scores are not on this row yet — the strike comes from the options desk path "
            "and regime text until confluence hydrates."
        )
    flabels = _factor_checklist_labels()
    greens = [nice for k, nice in flabels.items() if cp_breakdown.get(k, {}).get("pts", 0) > 0]
    passed = len(greens)
    if passed == 0:
        return (
            head
            + "Right now 0/7 of those headline rows are green — lean smaller; this pick leans on premium "
            "selling context rather than a stacked confluence entry."
        )
    tail = ", ".join(greens[:5])
    if len(greens) > 5:
        tail += ", …"
    return head + f"Currently {passed}/7 green: {tail}."


def _iv_rank_qualitative_words(rank):
    if rank >= 70:
        return "Rich premium"
    if rank < 25:
        return "Lean premium"
    return "Fair premium"


def _iv_rank_pill_html(ticker, price, ref_iv_pct=None, *, stub=None):
    """Recommended Trade card: always show an IV rank pill — numeric proxy, or a clear stub."""
    pill_open = (
        "<div style='display:inline-flex;align-items:center;flex-wrap:wrap;gap:8px;margin:4px 0 12px 0;"
        "padding:6px 14px;border-radius:999px;border:1px solid rgba(34,211,238,.45);"
        "background:rgba(6,182,212,.12)'>"
    )
    label = "<span style='font-size:.72rem;font-weight:700;color:#a5f3fc;letter-spacing:.07em'>IV RANK (PROXY)</span>"
    if stub == "offline":
        return (
            pill_open
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>chain offline</span></div>"
        )
    if stub == "no_strike":
        return (
            pill_open
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>no desk strike yet</span></div>"
        )
    try:
        ref = float(ref_iv_pct) if ref_iv_pct is not None else 0.0
    except (TypeError, ValueError):
        ref = 0.0
    if ref <= 0 or price is None or float(price) <= 0:
        return (
            pill_open
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>no reference IV</span></div>"
        )
    info = compute_iv_rank_proxy(ticker, float(price), ref)
    if info is not None:
        rnk = info["rank"]
        rk_color = "#fbbf24" if rnk > 70 else ("#34d399" if rnk < 25 else "#94a3b8")
        qual = _iv_rank_qualitative_words(rnk)
        return (
            pill_open
            + f"<span class='mono' style='font-weight:800;color:{rk_color};font-size:1.05rem'>IV Rank: {rnk:.0f}%</span>"
            + f"<span style='font-size:.78rem;color:#e2e8f0;font-weight:600'> — {qual}</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>vs listed expiries</span></div>"
        )
    return (
        pill_open
        + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
        + label
        + "<span style='font-size:.68rem;color:#64748b'>curve too thin to rank</span></div>"
    )


def _explain(title, body, mood="neutral"):
    """Render an explanation card with color-coded border."""
    colors = {"bull": ("#10b981", "rgba(16,185,129,.08)"),
              "bear": ("#ef4444", "rgba(239,68,68,.08)"),
              "neutral": ("#06b6d4", "rgba(6,182,212,.08)")}
    c, bg = colors.get(mood, colors["neutral"])
    st.markdown(
        f"<div class='explain' style='background:{bg};border-left-color:{c}'>"
        f"<div style='font-size:.8rem;font-weight:700;color:{c};text-transform:uppercase;"
        f"letter-spacing:.05em;margin-bottom:8px'>{title}</div>"
        f"<div style='color:#e2e8f0;font-size:.95rem;line-height:1.7'>{body}</div></div>",
        unsafe_allow_html=True)

def _section(title, subtitle="", tip_plain=""):
    """Render a prominent section divider. Optional tip_plain: short plain text shown on (i) hover."""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    tip_el = ""
    if tip_plain:
        ta = _html_mod.escape(tip_plain.strip().replace("\n", " "))
        tip_el = f"<span class='cf-tip' tabindex='0'>i<span class='cf-tiptext'>{ta}</span></span>"
    st.markdown(f"<div class='section-hdr'><h2>{title}</h2>{tip_el}{sub}</div>", unsafe_allow_html=True)

def _mini_sparkline(series, color="#00E5FF"):
    """Compact sparkline for glance cards."""
    def _to_rgba(c, alpha=0.14):
        c = (c or "").strip()
        if c.startswith("#") and len(c) == 7:
            r = int(c[1:3], 16)
            g = int(c[3:5], 16)
            b = int(c[5:7], 16)
            return f"rgba({r},{g},{b},{alpha})"
        return f"rgba(0,229,255,{alpha})"

    s = pd.Series(series).dropna()
    if s.empty:
        s = pd.Series([0.0, 0.0])
    # Light smoothing for noisy intraday prints while preserving direction.
    if len(s) >= 5:
        s = s.rolling(3, min_periods=1).mean()
    min_v = float(s.min())
    max_v = float(s.max())
    pad = max(0.001, (max_v - min_v) * 0.15)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(s))), y=s.tolist(), mode="lines",
        line=dict(color=color, width=3), hoverinfo="skip",
        fill="tozeroy", fillcolor=_to_rgba(color, 0.14)
    ))
    fig.update_layout(
        template=None, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=2, r=2, t=2, b=2), height=62,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(
            visible=False, fixedrange=True, range=[min_v - pad, max_v + pad]
        ),
        showlegend=False
    )
    return fig


def _glance_sparkline_svg(series, color="#00E5FF", w=112, h=44):
    """Single SVG path sparkline for glance cards (sidebar-safe; no Plotly iframe)."""
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 2:
        s = pd.Series([0.0, 1.0] if s.empty else [float(s.iloc[0]), float(s.iloc[0]) + 1e-6])
    vals = s.tolist()
    n = len(vals)
    vmin, vmax = min(vals), max(vals)
    pad = max(1e-9, (vmax - vmin) * 0.12)
    lo, hi = vmin - pad, vmax + pad
    span = hi - lo or 1.0
    pts = []
    for i, v in enumerate(vals):
        x = 2 + (i / max(1, n - 1)) * (w - 4)
        y = h - 2 - ((v - lo) / span) * (h - 4)
        pts.append(f"{x:.1f},{y:.1f}")
    d = "M " + " L ".join(pts)
    esc_color = _html_mod.escape(color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" class="glance-spark-svg" aria-hidden="true">'
        f'<path d="{d}" fill="none" stroke="{esc_color}" stroke-width="2.25" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def _glance_metric_card(label, value_html, caption_html, series, line_color):
    """One self-contained glass card: text left, SVG sparkline right (works with sidebar open)."""
    spark = _glance_sparkline_svg(series, line_color)
    return (
        "<div class='tc glass-card glance-card glance-card-whole'>"
        "<div class='glance-row-flex'>"
        "<div class='glance-text-col'>"
        f"<div class='glance-label'>{label}</div>"
        f"{value_html}"
        f"{caption_html}"
        "</div>"
        f"<div class='glance-spark-col'>{spark}</div>"
        "</div></div>"
    )


def _parse_watchlist_string(s):
    """Split user paste (commas, newlines, semicolons) into unique uppercase tickers."""
    if not s:
        return []
    s = str(s).replace("\n", ",").replace(";", ",")
    items, seen = [], set()
    for raw in s.split(","):
        t = raw.strip().upper()
        if t and t not in seen:
            items.append(t)
            seen.add(t)
    return items


@st.fragment
def _fragment_technical_zone(
    df,
    df_wk,
    ticker,
    gold_zone_price,
    gold_zone_components,
    price,
    diamonds,
    latest_d,
    cp_breakdown,
    d_wr,
    d_n,
    struct,
    mini_mode,
    mobile_chart_layout,
):
    """Charts + overlay toggles + diamond cards + gold zone copy. Reruns without refetching Yahoo data."""
    if mini_mode:
        chg_pct = 0.0
        if len(df) >= 2:
            try:
                chg_pct = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[-2]) - 1.0) * 100.0
            except Exception:
                chg_pct = 0.0
        gz_line = "—"
        gz_pct = 0.0
        try:
            if gold_zone_price:
                gz_pct = (float(price) / float(gold_zone_price) - 1.0) * 100.0
                gz_line = f"${float(gold_zone_price):.2f} ({gz_pct:+.1f}% from spot)"
        except Exception:
            gz_line = "—"
        spark7 = _glance_sparkline_svg(df["Close"].tail(7), "#00E5FF", w=220, h=56)
        chg_c = "#10b981" if chg_pct >= 0 else "#ef4444"
        tk_e = _html_mod.escape(ticker)
        st.markdown(
            f"<div class='glass-card' style='margin-bottom:12px;padding:14px 16px'>"
            f"<div style='font-size:.68rem;font-weight:800;color:#00e5ff;letter-spacing:.14em;margin-bottom:8px'>"
            f"TURBO · MOBILE STATUS</div>"
            f"<div style='display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:12px'>"
            f"<div style='flex:1;min-width:140px'>"
            f"<div class='mono' style='font-size:1.42rem;font-weight:800;color:#e2e8f0'>{tk_e} ${price:.2f}</div>"
            f"<div style='font-size:.92rem;font-weight:700;color:{chg_c};margin-top:4px'>{chg_pct:+.2f}% vs prior close</div>"
            f"<div style='font-size:.8rem;color:#94a3b8;margin-top:10px;line-height:1.5'>"
            f"<strong style='color:#cbd5e1'>Structure:</strong> {_html_mod.escape(str(struct))}<br>"
            f"<strong style='color:#cbd5e1'>Distance to Gold Zone:</strong> {gz_line}</div></div>"
            f"<div style='flex:0 0 auto;min-width:180px;text-align:right'>"
            f"<div style='font-size:.62rem;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px'>"
            f"7-DAY CLOSE SPARK</div>{spark7}</div></div>"
            f"<p style='color:#64748b;font-size:.74rem;margin:12px 0 0 0;line-height:1.45'>"
            f"No Plotly stack in Turbo — flip <strong>Turbo mode</strong> off in Mission Control for full charts.</p>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _persist_overlay_prefs()
        return

    st.markdown('<div id="charts" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section(
        "Technical Chart",
        f"{ticker} gets four dedicated panels: price, volume, RSI, and MACD. Zoom each one on its own. "
        "Tweak layers below; those toggles refresh the visuals without another Yahoo pull.",
        tip_plain="Candles show OHLC. EMA and Bollinger frame trend and volatility. Fib, Gann, and S/R are reference rails you can mute. Diamonds flag confluence. Gold line is the Gold Zone. Volume shows participation. RSI shows heat. MACD shows momentum versus its signal.",
    )
    st.markdown("##### Chart layers")
    o1, o2 = st.columns(2)
    with o1:
        show_ind = st.toggle("EMAs & Bollinger", key="sb_ema")
        show_gann = st.toggle("Gann Sq9", key="sb_gann")
        show_ichi = st.toggle("Ichimoku", key="sb_ichi")
        show_diamonds = st.toggle("Diamonds", key="sb_diamonds")
    with o2:
        show_fib = st.toggle("Fibonacci", key="sb_fib")
        show_sr = st.toggle("S/R levels", key="sb_sr")
        show_super = st.toggle("Supertrend", key="sb_super")
        show_gold_zone = st.toggle("Gold zone", key="sb_gold_zone")

    fig_p, fig_v, fig_r, fig_m = build_chart(
        df,
        ticker,
        show_ind,
        show_fib,
        show_gann,
        show_sr,
        show_ichi,
        show_super,
        diamonds=diamonds if show_diamonds else None,
        gold_zone=gold_zone_price if show_gold_zone else None,
        mobile_layout=bool(mobile_chart_layout),
    )
    st.plotly_chart(fig_p, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    st.divider()
    st.markdown("#### Volume")
    st.plotly_chart(fig_v, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    st.divider()
    st.markdown("#### RSI (14)")
    st.plotly_chart(fig_r, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    st.divider()
    st.markdown("#### MACD")
    st.plotly_chart(fig_m, use_container_width=True, config=_PLOTLY_UI_CONFIG)

    chart_mood = "bull" if struct == "BULLISH" else ("bear" if struct == "BEARISH" else "neutral")

    if show_diamonds and diamonds:
        recent_diamonds = [d for d in diamonds if (df.index[-1] - d["date"]).days <= 30]
        if recent_diamonds:
            st.markdown("#### Recent Diamond Signals")
            d_cols = st.columns(min(len(recent_diamonds), 4))
            for idx_d, d in enumerate(recent_diamonds[-4:]):
                with d_cols[idx_d]:
                    cls = "diamond-blue" if d["type"] == "blue" else "diamond-pink"
                    icon = "🔷" if d["type"] == "blue" else "💎"
                    label = "BLUE DIAMOND: Strong Buy" if d["type"] == "blue" else "PINK DIAMOND: Take Profit"
                    age = (df.index[-1] - d["date"]).days
                    prob_txt = f"Historical win rate: {d_wr:.0f}% over {d_n} signals" if d_n > 0 else "Insufficient history"
                    st.markdown(
                        f"<div class='{cls}'>"
                        f"<div style='font-size:1.1rem;font-weight:700;margin-bottom:4px'>{icon} {label}</div>"
                        f"<div style='color:#94a3b8;font-size:.85rem'>Date: {d['date'].strftime('%b %d, %Y')} ({age}d ago)<br>"
                        f"Price: ${d['price']:.2f} | Score: {d['score']}/9 | RSI: {d['rsi']:.0f}<br>"
                        f"<span style='color:#fbbf24;font-size:.8rem'>📊 {prob_txt}</span></div></div>",
                        unsafe_allow_html=True,
                    )

            if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
                why_type = "BLUE DIAMOND" if latest_d["type"] == "blue" else "PINK DIAMOND"
                why_color = "#3b82f6" if latest_d["type"] == "blue" else "#ec4899"
                why_action = (
                    "Strong confluence aligned bullish. The market gave a high probability buy signal."
                    if latest_d["type"] == "blue"
                    else "Confluence collapsed or momentum exhausted. Time to protect gains."
                )
                flabels = _factor_checklist_labels()
                factor_lines = ""
                passed = 0
                for key, nice in flabels.items():
                    info = cp_breakdown.get(key)
                    if not info:
                        continue
                    ok = info["pts"] > 0
                    if ok:
                        passed += 1
                    mark = "&#10003;" if ok else ""
                    row_col = "#34d399" if ok else "#64748b"
                    factor_lines += (
                        f"<div style='padding:5px 0;display:flex;align-items:flex-start;gap:10px;color:{row_col};font-size:.9rem'>"
                        f"<span style='color:#34d399;font-weight:800;min-width:1.2em'>{mark}</span>"
                        f"<span><strong style='color:#e2e8f0'>{nice}</strong>"
                        f"<span style='color:#64748b;font-size:.8rem'> ({info['pts']}/{info['max']})</span></span></div>"
                    )
                wk_confirm = latest_d.get("weekly", "N/A")
                win_badge = (
                    f"<div style='margin:12px 0 8px 0'><span class='diamond-win-badge'>HISTORICAL WIN RATE: {d_wr:.0f}%</span>"
                    f"<span style='color:#94a3b8;font-size:.8rem;margin-left:10px'>({d_n} past signals)</span></div>"
                    if d_n > 0
                    else "<div style='color:#64748b;font-size:.85rem;margin:8px 0'>Not enough history for a win rate badge yet.</div>"
                )
                st.markdown(
                    f"<div style='background:rgba(15,23,42,.95);border:1px solid {why_color};border-radius:12px;padding:18px 20px;margin:12px 0'>"
                    f"<div style='font-size:.8rem;color:{why_color};text-transform:uppercase;letter-spacing:.1em;font-weight:700;margin-bottom:6px'>"
                    f"Why This {why_type}?</div>"
                    f"<div style='color:#e2e8f0;font-size:.95rem;margin-bottom:6px'>Signal fired at <strong>{latest_d['score']}/9</strong> confluence. "
                    f"Live checklist now shows <strong>{passed}/7</strong> headline factors green.</div>"
                    f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px;line-height:1.5'>{why_action}</div>"
                    f"{win_badge}"
                    f"<div style='font-size:.72rem;color:#64748b;text-transform:uppercase;margin-bottom:6px'>Diamond checklist</div>"
                    f"<div>{factor_lines}</div>"
                    f"<div style='margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,.06);font-size:.8rem;color:#94a3b8'>"
                    f"Weekly filter at signal: <strong style='color:{why_color}'>{wk_confirm}</strong>. "
                    f"RSI at signal: {latest_d['rsi']:.0f}.</div></div>",
                    unsafe_allow_html=True,
                )

    if show_gold_zone:
        show_gz_detail = st.checkbox("Show Gold Zone Breakdown", value=False, key="chk_gold_zone_detail")
        if show_gz_detail:
            st.markdown(
                f"**Gold Zone Price: ${gold_zone_price:.2f}**. This is the weighted average of multiple key levels that institutional traders watch."
            )
            for comp_name, comp_val in gold_zone_components.items():
                dist = (comp_val / price - 1) * 100
                st.markdown(f"* **{comp_name}**: ${comp_val:.2f} ({dist:+.1f}% from spot)")
            _explain(
                "Why the Gold Zone matters",
                "The Gold Zone fuses four institutional magnets into one line: Volume Profile POC where the crowd traded most, "
                "the 61.8% Fibonacci anchor, the 200 day simple moving average, and the nearest Gann Square of 9 pivot. "
                "Above it, buyers still own the narrative. Below it, respect the air pocket. "
                "Treat it as the headline level on your chart.",
                "neutral",
            )

    if latest_d and latest_d["type"] == "blue" and (df.index[-1] - latest_d["date"]).days <= 3:
        next_gz = gold_zone_price
        st.markdown(
            f"<div class='ac'>🔔 <strong>Alert Suggestion:</strong> Set an alert for next Blue Diamond at <strong>${next_gz:.2f}</strong> (Gold Zone). "
            f"If {ticker} pulls back to the Gold Zone and confluence rebuilds above 7/9, that is your next high probability entry.</div>",
            unsafe_allow_html=True,
        )
    elif latest_d and latest_d["type"] == "pink" and (df.index[-1] - latest_d["date"]).days <= 3:
        st.markdown(
            f"<div class='ac'>🔔 <strong>Alert Suggestion:</strong> Pink Diamond fired at ${latest_d['price']:.2f}. "
            f"Consider taking partial profits. Set alert if {ticker} drops below Gold Zone ${gold_zone_price:.2f} for a full exit.</div>",
            unsafe_allow_html=True,
        )

    _explain(
        "\U0001f9e0 Quick read",
        "Tap the <strong>i</strong> on any section header when you want the full story. "
        "Green candles with a climbing short EMA say buyers are steering. Diamonds and the Gold Zone are your runway lights.",
        chart_mood,
    )
    _persist_overlay_prefs()


# ═════════════════════════════════════════════════════════════════════════
#  DATAFRAME PRESENTATION — column_config, numeric types, row highlights
# ═════════════════════════════════════════════════════════════════════════

_KEY_FIB_LEVEL_NAMES = frozenset({"50.0%", "61.8%"})


def _df_price_levels(levels: dict, spot: float) -> pd.DataFrame:
    """Build a numeric table for Fib / Gann level maps (label → price)."""
    rows = [
        {
            "Level": k,
            "Price": float(v),
            "vs spot (%)": (float(v) / spot - 1.0) * 100.0,
        }
        for k, v in levels.items()
    ]
    return pd.DataFrame(rows)


def _style_price_levels_table(df: pd.DataFrame, *, mode: str, spot: float):
    """Highlight key Fib retracements or the Gann level nearest spot."""
    if df.empty:
        return df
    if mode == "fib":
        def _fib_row(row):
            if row["Level"] in _KEY_FIB_LEVEL_NAMES:
                return ["background-color: rgba(245, 158, 11, 0.22); font-weight: 700"] * len(row)
            return [""] * len(row)

        sty = df.style.apply(_fib_row, axis=1)
    else:
        nearest_label = (df["Price"] - float(spot)).abs().idxmin()

        def _gann_row(row):
            if row.name == nearest_label:
                return ["background-color: rgba(34, 211, 238, 0.16); font-weight: 700"] * len(row)
            return [""] * len(row)

        sty = df.style.apply(_gann_row, axis=1)
    try:
        return sty.hide(axis="index")
    except (TypeError, ValueError, AttributeError):
        return sty.hide_index()


def _earnings_calendar_column_config():
    return {
        "Earnings date": st.column_config.DateColumn("Earnings date", format="MMM DD, YYYY"),
        "EPS estimate": st.column_config.NumberColumn("EPS estimate", format="$%.2f"),
        "Reported EPS": st.column_config.NumberColumn("Reported EPS", format="$%.2f"),
        "Surprise (%)": st.column_config.NumberColumn("Surprise (%)", format="%.2f%%"),
        "Status": st.column_config.TextColumn("Status"),
    }


def _style_earnings_next_highlight(df: pd.DataFrame, highlight_idx):
    """Subtle row fill for the next earnings date on or after today."""
    if df.empty:
        return df
    if highlight_idx is None:
        try:
            return df.style.hide(axis="index")
        except (TypeError, ValueError, AttributeError):
            return df.style.hide_index()

    hi = int(highlight_idx)

    def _row(r):
        if r.name == hi:
            return ["background-color: rgba(245, 158, 11, 0.16)"] * len(r)
        return [""] * len(r)

    sty = df.style.apply(_row, axis=1)
    try:
        return sty.hide(axis="index")
    except (TypeError, ValueError, AttributeError):
        return sty.hide_index()


_PRICE_LEVEL_COLUMN_CONFIG = {
    "Level": st.column_config.TextColumn("Level", width="large"),
    "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
    "vs spot (%)": st.column_config.NumberColumn("vs spot", format="%+.2f%%"),
}


def _options_scan_dataframe(rows: list, *, put_table: bool) -> pd.DataFrame:
    """Normalize CC / CSP rows for display with stable column order."""
    cols = ["strike", "mid", "delta", "otm_pct", "prem_100", "ann_yield", "iv", "volume", "oi"]
    if put_table:
        cols.append("eff_buy")
    cols.append("optimal")
    dfp = pd.DataFrame(rows)[cols].copy()
    dfp["optimal"] = dfp["optimal"].astype(bool)
    rename = {
        "strike": "K",
        "mid": "Mid",
        "delta": "\u0394",
        "otm_pct": "OTM %",
        "prem_100": "$/100 sh",
        "ann_yield": "Ann %",
        "iv": "IV",
        "volume": "Vol",
        "oi": "OI",
        "optimal": "Prop desk",
    }
    if put_table:
        rename["eff_buy"] = "Eff. buy"
    return dfp.rename(columns=rename)


def _options_scan_column_config(*, put_table: bool):
    cfg = {
        "K": st.column_config.NumberColumn("Strike", format="$%.2f"),
        "Mid": st.column_config.NumberColumn("Mid", format="$%.2f"),
        "\u0394": st.column_config.NumberColumn("Delta", format="%.3f"),
        "OTM %": st.column_config.NumberColumn("OTM", format="%.2f%%"),
        "$/100 sh": st.column_config.NumberColumn("$/100 sh", format="$%.2f"),
        "Ann %": st.column_config.NumberColumn("Ann. yield", format="%.1f%%"),
        "IV": st.column_config.NumberColumn("IV", format="%.1f%%"),
        "Vol": st.column_config.NumberColumn("Volume", format="%.0f"),
        "OI": st.column_config.NumberColumn("OI", format="%.0f"),
    }
    if put_table:
        cfg["Eff. buy"] = st.column_config.NumberColumn("Eff. buy", format="$%.2f")
    cfg["Prop desk"] = st.column_config.CheckboxColumn(
        "Prop desk",
        help="Desk-preferred strike for this chain",
        disabled=True,
    )
    return cfg


def _style_propdesk_highlight(df: pd.DataFrame):
    """Emphasize the Prop desk optimal row (summary-style)."""
    col = "Prop desk"

    def _row(r):
        if bool(r[col]):
            return ["background-color: rgba(6, 182, 212, 0.2); font-weight: 700"] * len(r)
        return [""] * len(r)

    sty = df.style.apply(_row, axis=1)
    try:
        return sty.hide(axis="index")
    except (TypeError, ValueError, AttributeError):
        return sty.hide_index()


# ═════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════

def main():
    cfg = load_config()

    if "_sb_scanner_sync" in st.session_state:
        st.session_state["sb_scanner"] = st.session_state.pop("_sb_scanner_sync")
    elif "sb_scanner" not in st.session_state:
        st.session_state["sb_scanner"] = cfg.get("watchlist", DEFAULT_CONFIG["watchlist"])

    # ── Watchlist editor (must run before Mission Control so sb_scanner is committed same run)
    _wl_expanded = bool(st.session_state.pop("_open_watchlist_editor", False))
    st.caption("CashFlow Command Center · v14.1")
    with st.expander("Edit watchlist symbols", expanded=_wl_expanded):
        st.caption(
            "Drop in tickers separated by commas or line breaks. Shuffle the lineup with the controls. "
            "Watchlist and desk preferences are kept in this session (not written to disk)."
        )
        scanner_watchlist_raw = st.text_area(
            "Watchlist symbols",
            height=150,
            help="Paste from a spreadsheet, type commas, or put one ticker per line.",
            key="sb_scanner",
            label_visibility="collapsed",
        )
        watch_items_sb = _parse_watchlist_string(scanner_watchlist_raw)
        scanner_watchlist_sb = ",".join(watch_items_sb)

        if watch_items_sb:
            if "_sb_watch_selected_sync" in st.session_state:
                st.session_state["sb_watch_selected"] = st.session_state.pop("_sb_watch_selected_sync")
            if st.session_state.get("sb_watch_selected") not in watch_items_sb:
                st.session_state["sb_watch_selected"] = watch_items_sb[0]
            sel = st.session_state.get("sb_watch_selected")
            st.markdown(
                "<div style='font-size:.68rem;color:#94a3b8;margin:0 0 6px 0'>"
                + " · ".join(f"<span class='mono' style='color:#cbd5e1'>{_html_mod.escape(x)}</span>" for x in watch_items_sb)
                + "</div>",
                unsafe_allow_html=True,
            )
            up_clicked = st.button("Move up", use_container_width=True, key="sb_move_up")
            down_clicked = st.button("Move down", use_container_width=True, key="sb_move_down")
            remove_clicked = st.button("Remove symbol", use_container_width=True, key="sb_remove_ticker")
            sort_az = st.button("Sort A to Z", use_container_width=True, key="sb_sort_az")

            if up_clicked and sel in watch_items_sb:
                idx = watch_items_sb.index(sel)
                if idx > 0:
                    watch_items_sb[idx - 1], watch_items_sb[idx] = watch_items_sb[idx], watch_items_sb[idx - 1]
                    scanner_watchlist_sb = ",".join(watch_items_sb)
                    st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                    st.session_state["_sb_watch_selected_sync"] = sel
                    cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                    save_config(cfg)
                    st.rerun()
            if down_clicked and sel in watch_items_sb:
                idx = watch_items_sb.index(sel)
                if idx < len(watch_items_sb) - 1:
                    watch_items_sb[idx + 1], watch_items_sb[idx] = watch_items_sb[idx], watch_items_sb[idx + 1]
                    scanner_watchlist_sb = ",".join(watch_items_sb)
                    st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                    st.session_state["_sb_watch_selected_sync"] = sel
                    cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                    save_config(cfg)
                    st.rerun()
            if remove_clicked and sel in watch_items_sb:
                watch_items_sb = [t for t in watch_items_sb if t != sel]
                scanner_watchlist_sb = ",".join(watch_items_sb)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                if watch_items_sb:
                    st.session_state["_sb_watch_selected_sync"] = watch_items_sb[0]
                cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                save_config(cfg)
                st.rerun()
            if sort_az and watch_items_sb:
                watch_items_sb = sorted(watch_items_sb)
                scanner_watchlist_sb = ",".join(watch_items_sb)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                sel2 = st.session_state.get("sb_watch_selected")
                if sel2 not in watch_items_sb:
                    st.session_state["_sb_watch_selected_sync"] = watch_items_sb[0]
                cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                save_config(cfg)
                st.rerun()
        else:
            st.session_state.pop("sb_watch_selected", None)
            st.info("Add at least one symbol (e.g. PLTR, NVDA).")

        st.markdown(
            "<div style='font-size:.72rem;color:#94a3b8;margin:10px 0 2px 0;font-weight:600'>Quick add</div>",
            unsafe_allow_html=True,
        )
        if "_sb_add_ticker_clear" in st.session_state:
            st.session_state["sb_add_ticker"] = ""
            st.session_state.pop("_sb_add_ticker_clear", None)
        add_ticker_raw = st.text_input(
            "Symbol",
            placeholder="Try AMD, then tap Add symbol",
            key="sb_add_ticker",
            label_visibility="collapsed",
        )
        add_clicked = st.button("Add symbol", use_container_width=True, key="sb_add_watch")
        add_ticker = (add_ticker_raw or "").strip().upper()
        if add_clicked:
            if add_ticker:
                if add_ticker not in watch_items_sb:
                    watch_items_sb.append(add_ticker)
                scanner_watchlist_sb = ",".join(watch_items_sb)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                st.session_state["_sb_watch_selected_sync"] = add_ticker
                st.session_state["_sb_add_ticker_clear"] = True
                cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                save_config(cfg)
                st.rerun()
            else:
                st.toast("Enter a ticker in the box above, then tap Add symbol.")

        if st.button("Save and refresh", use_container_width=True, key="sb_save_refresh_main"):
            w = _parse_watchlist_string(st.session_state.get("sb_scanner", ""))
            save_config({**load_config(), "watchlist": ",".join(w)})
            st.rerun()

    # ── GLOBAL COMMAND BAR (HUD — first paint in main column, directly under sticky nav)
    scanner_watchlist_raw = st.session_state.get("sb_scanner", cfg.get("watchlist", ""))
    watch_items = _parse_watchlist_string(scanner_watchlist_raw)
    scanner_watchlist = ",".join(watch_items)

    _scan_idx = (
        0 if cfg.get("scanner_sort_mode", "Custom watchlist order") == "Custom watchlist order" else 1
    )

    # Must resolve sb_watch_selected before st.selectbox(..., key="sb_watch_selected") — Streamlit 1.33+
    # forbids assigning session_state for a widget key after that widget is instantiated (e.g. tape buttons).
    if watch_items:
        if "_sb_watch_selected_sync" in st.session_state:
            st.session_state["sb_watch_selected"] = st.session_state.pop("_sb_watch_selected_sync")
        if st.session_state.get("sb_watch_selected") not in watch_items:
            st.session_state["sb_watch_selected"] = watch_items[0]
        ticker = st.session_state.get("sb_watch_selected", watch_items[0])
    else:
        st.session_state.pop("sb_watch_selected", None)
        ticker = "PLTR"

    with st.container(border=True):
        st.markdown(
            "<div style='font-size:.75rem;color:#cbd5e1;font-weight:800;letter-spacing:.12em;margin-bottom:8px;'>MISSION CONTROL</div>",
            unsafe_allow_html=True,
        )
        r1c1, r1c2, r1c3 = st.columns([1.5, 2, 1])
        with r1c1:
            st.markdown('<p class="cf-hud-label">Target ticker</p>', unsafe_allow_html=True)
            if watch_items:
                st.selectbox(
                    "Target Ticker",
                    watch_items,
                    key="sb_watch_selected",
                    help="Main chart, news, options, and scores use this ticker.",
                    label_visibility="collapsed",
                )
            else:
                st.markdown(
                    '<p class="cf-hud-label">No symbols yet</p><p style="color:#cbd5e1;font-size:0.85rem;margin:0">'
                    "Expand <strong>Edit watchlist symbols</strong> up top or use the shortcut under the tape.</p>",
                    unsafe_allow_html=True,
                )
        with r1c2:
            st.markdown('<p class="cf-hud-label">Strategy</p>', unsafe_allow_html=True)
            if hasattr(st, "segmented_control"):
                st.segmented_control(
                    "Strategy",
                    ["Sell premium", "Hybrid", "Growth"],
                    key="sb_strat_radio",
                    label_visibility="collapsed",
                )
            else:
                st.radio(
                    "Strategy",
                    ["Sell premium", "Hybrid", "Growth"],
                    horizontal=True,
                    key="sb_strat_radio",
                    label_visibility="collapsed",
                )
        with r1c3:
            st.markdown('<p class="cf-hud-label">Performance</p>', unsafe_allow_html=True)
            st.toggle(
                "Turbo mode",
                key="sb_mini_mode",
                help="Skips heavy Plotly charts; glance row, execution strip, quant, and scanner stay live. Toggle off for the full chart stack.",
            )
        r2c1, r2c2 = st.columns([1.2, 1.2])
        with r2c1:
            st.markdown('<p class="cf-hud-label">Option horizon</p>', unsafe_allow_html=True)
            if hasattr(st, "segmented_control"):
                st.segmented_control(
                    "Horizon",
                    ["Weekly", "30 DTE", "45 DTE"],
                    key="sb_horizon_radio",
                    label_visibility="collapsed",
                )
            else:
                st.radio(
                    "Horizon",
                    ["Weekly", "30 DTE", "45 DTE"],
                    horizontal=True,
                    key="sb_horizon_radio",
                    label_visibility="collapsed",
                )
        with r2c2:
            st.markdown('<p class="cf-hud-label">Scanner order</p>', unsafe_allow_html=True)
            _scan_seg = st.radio(
                "Scanner order",
                ["Custom order", "Confluence first"],
                index=_scan_idx,
                horizontal=True,
                key="sb_scan_radio",
                help="Custom follows your lineup. Confluence ranks the strongest tape first.",
            )
            scanner_sort_mode = (
                "Custom watchlist order" if _scan_seg == "Custom order" else "Highest confluence first"
            )

    # Clickable ticker tape (chunk rows on wide lists so columns stay usable on mobile)
    if watch_items:
        st.markdown('<p class="cf-tape-title">Watchlist tape</p>', unsafe_allow_html=True)
        st.caption("Tap a symbol to promote it to the active ticker. Daily move is versus the prior session close (cached).")
        _tape_pct = _tape_pct_changes(tuple(watch_items))
        _TAPE_CHUNK = 8
        tape_i = 0
        for row_start in range(0, len(watch_items), _TAPE_CHUNK):
            row_tickers = watch_items[row_start : row_start + _TAPE_CHUNK]
            tape_cols = st.columns(len(row_tickers))
            for j, tkr in enumerate(row_tickers):
                pct = _tape_pct.get(tkr)
                pct_str = f"{pct:+.2f}%" if pct is not None else "n/a"
                c_pct = "#10b981" if (pct is not None and pct >= 0) else ("#ef4444" if pct is not None else "#64748b")
                is_active = tkr == ticker
                with tape_cols[j]:
                    st.markdown(
                        f"<div class='cf-tape-cell'><span style='color:{c_pct};font-size:.62rem;font-weight:800'>{_html_mod.escape(pct_str)}</span></div>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        tkr,
                        key=f"cf_tape_{tape_i}",
                        use_container_width=True,
                        type="primary" if is_active else "secondary",
                    ):
                        st.session_state["_sb_watch_selected_sync"] = tkr
                        st.rerun()
                tape_i += 1

    b1, b2 = st.columns([1, 2])
    with b1:
        if st.button("Open watchlist editor", use_container_width=True, key="cf_open_watchlist_editor"):
            st.session_state["_open_watchlist_editor"] = True
            st.rerun()
    with b2:
        st.markdown(
            "<div style='color:#94a3b8;font-size:0.7rem;padding-top:10px'>Data: Yahoo Finance · Not advice</div>",
            unsafe_allow_html=True,
        )

    watch_cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
    if watch_cfg != cfg:
        save_config(watch_cfg)
        cfg = watch_cfg

    _hydrate_sidebar_prefs(cfg)

    prefs_cfg = {
        **cfg,
        "strat_focus": st.session_state.get("sb_strat_radio", DEFAULT_CONFIG["strat_focus"]),
        "strat_horizon": st.session_state.get("sb_horizon_radio", DEFAULT_CONFIG["strat_horizon"]),
        "mini_mode": bool(st.session_state.get("sb_mini_mode", cfg.get("mini_mode", False))),
    }
    if prefs_cfg != cfg:
        save_config(prefs_cfg)
        cfg = prefs_cfg

    mini_mode = bool(st.session_state.get("sb_mini_mode", False))
    mobile_chart_layout = _client_suggests_mobile_chart()
    if mini_mode:
        inject_mini_mode_density_css()

    # ── FETCH (parallel I/O: independent Yahoo endpoints + sparkline series) ──
    with st.spinner(f"Loading {ticker}..."):
        with ThreadPoolExecutor(max_workers=7) as _pool:
            _f_df = _submit_with_script_ctx(_pool, fetch_stock, ticker, "1y", "1d")
            _f_wk = _submit_with_script_ctx(_pool, fetch_stock, ticker, "2y", "1wk")
            _f_1mo = _submit_with_script_ctx(_pool, fetch_stock, ticker, "1mo", "1d")
            _f_vix_m = _submit_with_script_ctx(_pool, fetch_stock, "^VIX", "1mo", "1d")
            _f_macro = _submit_with_script_ctx(_pool, fetch_macro)
            _f_news = _submit_with_script_ctx(_pool, fetch_news, ticker)
            _f_earn = _submit_with_script_ctx(_pool, fetch_earnings_date, ticker)
            df = _f_df.result()
            df_wk = _f_wk.result()
            df_1mo_spark = _f_1mo.result()
            vix_1mo_df = _f_vix_m.result()
            macro = _f_macro.result()
            news = _f_news.result()
            earnings_date_raw = _f_earn.result()

    if df is None or df.empty:
        st.error(
            f"Data feed unavailable for {ticker}. Yahoo Finance may be throttling or the tape may be quiet. "
            "We will try again the moment you refresh."
        )
        st.stop()

    # ── HEADER — Live Pulse (timestamp after successful load) ──
    last_update = datetime.now().strftime("%H:%M:%S")
    tk_hdr = _html_mod.escape(ticker)
    st.markdown(
        f"""<div class="cf-page-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
    <h1 style="margin:0;font-size:1.8rem;background:linear-gradient(135deg,#10b981,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">
        {tk_hdr} COMMAND CENTER
    </h1>
    <div style="display:flex;align-items:center;gap:8px;background:rgba(16,185,129,0.1);padding:4px 12px;border-radius:20px;border:1px solid rgba(16,185,129,0.2);">
        <div style="width:8px;height:8px;background:#10b981;border-radius:50%;box-shadow:0 0 8px #10b981;animation:cf_live_dot_pulse 2s ease-in-out infinite;"></div>
        <span style="font-size:.7rem;color:#10b981;font-family:JetBrains Mono,monospace;font-weight:700;">LIVE FEED: {last_update}</span>
    </div>
</div>
<style>
@keyframes cf_live_dot_pulse {{
  0%,100% {{ opacity: 1; }}
  50% {{ opacity: 0.3; }}
}}
</style>""",
        unsafe_allow_html=True,
    )

    # ── EARNINGS AMBUSH CHECK ──
    earnings_near = False
    earnings_dt = None
    days_to_earnings = None
    earnings_parse_failed = False
    if earnings_date_raw is not None:
        try:
            if isinstance(earnings_date_raw, str):
                earnings_dt = datetime.strptime(earnings_date_raw[:10], "%Y-%m-%d")
            else:
                earnings_dt = pd.Timestamp(earnings_date_raw).to_pydatetime()
            if hasattr(earnings_dt, "tzinfo") and earnings_dt.tzinfo:
                earnings_dt = earnings_dt.replace(tzinfo=None)
            days_to_earnings = (earnings_dt - datetime.now()).days
            if 0 <= days_to_earnings <= 14:
                earnings_near = True
        except Exception:
            earnings_parse_failed = True
            earnings_dt = None
            days_to_earnings = None

    if earnings_dt is not None and days_to_earnings is not None:
        if days_to_earnings < 0:
            earn_glance = f"Reported {abs(days_to_earnings)} days ago ({earnings_dt.strftime('%b %d')})"
        elif days_to_earnings == 0:
            earn_glance = "Earnings today"
        else:
            earn_glance = f"{days_to_earnings} days: {earnings_dt.strftime('%b %d, %Y')}"
    else:
        earn_glance = "No date from feed"

    if earnings_near and earnings_dt:
        st.markdown(f"""<div style='background:linear-gradient(135deg,rgba(245,158,11,.15),rgba(217,119,6,.1));
            border:2px solid #f59e0b;border-radius:12px;padding:16px 20px;margin:0 0 16px 0'>
            <span style='font-size:1.1rem;color:#f59e0b;font-weight:700'>⚠️ EARNINGS IN {days_to_earnings} DAYS</span>
            <span style='color:#94a3b8;font-size:.9rem;display:block;margin-top:4px'>
            Implied volatility is rich because the print is close. Picture a retailer marking up tags before a holiday rush.
            Assignment risk on short calls jumps with that backdrop. We pause auto alerts until after {earnings_dt.strftime('%b %d, %Y')}.</span></div>""", unsafe_allow_html=True)

    price = df["Close"].iloc[-1]
    prev = df["Close"].iloc[-2] if len(df) >= 2 else price
    chg = price - prev; chg_pct = chg/prev*100
    hi52, lo52 = df["High"].max(), df["Low"].min()
    vix_v = macro.get("VIX", {}).get("price", 0)
    qs, qb = quant_edge_score(df, vix_v)

    # ── GLANCE ROW (price, VIX, earnings, quant edge) ──
    vix_disp = f"{vix_v:.1f}" if vix_v else "N/A"
    if vix_v and vix_v > 25:
        vix_mood = "Fear is up. Premiums pay better."
    elif vix_v and vix_v > 18:
        vix_mood = "Balanced mood. Normal premiums."
    elif vix_v:
        vix_mood = "Calm tape. Premiums run thin."
    else:
        vix_mood = "VIX not loaded"
    if len(df) >= 7:
        price_spark = df["Close"].tail(7)
    else:
        price_spark = (
            df_1mo_spark["Close"].tail(7)
            if df_1mo_spark is not None and not df_1mo_spark.empty
            else df["Close"].tail(min(7, len(df)))
        )
    vix_spark = (
        vix_1mo_df["Close"].tail(7)
        if vix_1mo_df is not None and not vix_1mo_df.empty
        else pd.Series([vix_v, vix_v, vix_v, vix_v, vix_v, vix_v, vix_v])
    )
    if days_to_earnings is not None:
        earn_anchor = max(1, min(30, days_to_earnings if days_to_earnings >= 0 else 1))
        earnings_spark = pd.Series(np.linspace(earn_anchor + 1, max(0, earn_anchor - 1), 7))
    else:
        earnings_spark = pd.Series(np.linspace(24, 1, 7))
    qe_spark = pd.Series(np.linspace(max(0, qs - 10), min(100, qs + 4), 7))

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.markdown(
            _glance_metric_card(
                f"{_html_mod.escape(ticker)} PRICE",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:#e2e8f0'>${price:.2f}</div>",
                f"<div class='glance-caption'>{chg_pct:+.2f}% vs prior close</div>",
                price_spark,
                "#00E5FF",
            ),
            unsafe_allow_html=True,
        )
    with g2:
        st.markdown(
            _glance_metric_card(
                "MARKET MOOD (VIX)",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:#00E5FF'>{_html_mod.escape(vix_disp)}</div>",
                f"<div class='glance-caption'>{_html_mod.escape(vix_mood)}</div>",
                vix_spark,
                "#FF005C" if vix_v and vix_v > 20 else "#00FFA3",
            ),
            unsafe_allow_html=True,
        )
    with g3:
        st.markdown(
            _glance_metric_card(
                "EARNINGS COUNTDOWN",
                f"<div class='glance-value' style='font-size:1.0rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(earn_glance)}</div>",
                "<div class='glance-caption'>Plan size before the print</div>",
                earnings_spark,
                "#FFD700",
            ),
            unsafe_allow_html=True,
        )
    with g4:
        qe_color = "#00FFA3" if qs > 70 else ("#FFD700" if qs > 50 else "#FF005C")
        st.markdown(
            _glance_metric_card(
                "QUANT EDGE",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:{qe_color}'>{qs:.0f}/100</div>",
                "<div class='glance-caption'>24h directional momentum context</div>",
                qe_spark,
                qe_color,
            ),
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════════════
    #  SHARED COMPUTATIONS
    # ══════════════════════════════════════════════════════════════════
    wk_label, wk_color = weekly_trend_label(df_wk)
    struct, _, _ = TA.market_structure(df)
    fg = Sentiment.fear_greed(df, vix_v)
    fg_label, fg_emoji, fg_advice = Sentiment.interpret(fg)

    ml_v, sl_v, h_v = TA.macd(df["Close"])
    macd_bull = ml_v.iloc[-1] > sl_v.iloc[-1]
    obv_s = TA.obv(df)
    obv_up = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else True
    rsi_v = TA.rsi(df["Close"]).iloc[-1]
    al = Alerts.scan(df, ticker, vix_v)

    # ── DIAMOND / GOLD ZONE / CONFLUENCE ──
    gold_zone_price, gold_zone_components = calc_gold_zone(df, df_wk)
    cp_score, cp_max, cp_breakdown, cp_bearish = calc_confluence_points(
        df, df_wk, vix_v, gold_zone_price=gold_zone_price
    )
    diamonds = detect_diamonds(df, df_wk)
    latest_d = latest_diamond_status(diamonds)
    d_wr, d_avg, d_n = diamond_win_rate(df, diamonds, forward_bars=10)

    cp_color = "#10b981" if cp_score >= 7 else ("#f59e0b" if cp_score >= 4 else "#ef4444")
    cp_label = "STRONG BULLISH" if cp_score >= 7 else ("BULLISH LEAN" if cp_score >= 5 else ("MIXED" if cp_score >= 3 else "BEARISH"))

    # Multi-timeframe bias
    daily_struct = struct
    weekly_struct = "UNKNOWN"
    if df_wk is not None and len(df_wk) >= 20:
        weekly_struct, _, _ = TA.market_structure(df_wk)

    qs_color = "#10b981" if qs > 70 else ("#f59e0b" if qs > 50 else "#ef4444")
    qs_status = "PRIME SELLING ENVIRONMENT" if qs > 70 else ("DECENT SETUP" if qs > 50 else "STAND DOWN. WAIT FOR A CLEANER ENTRY.")

    # ── EARLY OPTIONS FETCH (populates BLUF with specific strikes) ──
    rfr = macro.get("10Y Yield", {}).get("price", 4.5) / 100
    bluf_cc, bluf_csp, bluf_exp, bluf_dte = None, None, None, 0
    opt_exps = []
    try:
        _, opt_exps = fetch_options(ticker)
        if opt_exps:
            bluf_exp = opt_exps[min(2, len(opt_exps) - 1)]
            try:
                bluf_dte = max(1, (datetime.strptime(str(bluf_exp)[:10], "%Y-%m-%d") - datetime.now()).days)
            except Exception:
                bluf_exp, bluf_dte = None, 0
            if bluf_exp:
                bluf_opt, _ = fetch_options(ticker, bluf_exp)
                bluf_calls, bluf_puts = (
                    bluf_opt if isinstance(bluf_opt, (tuple, list)) and len(bluf_opt) == 2 else (pd.DataFrame(), pd.DataFrame())
                )
                bluf_calls = bluf_calls if isinstance(bluf_calls, pd.DataFrame) else pd.DataFrame()
                bluf_puts = bluf_puts if isinstance(bluf_puts, pd.DataFrame) else pd.DataFrame()
                cc_list = Opt.covered_calls(price, bluf_calls, bluf_dte, rfr) if not bluf_calls.empty else []
                csp_list = Opt.cash_secured_puts(price, bluf_puts, bluf_dte, rfr) if not bluf_puts.empty else []
                if cc_list:
                    bluf_cc = next((c for c in cc_list if c.get("optimal")), cc_list[0])
                if csp_list:
                    bluf_csp = next((c for c in csp_list if c.get("optimal")), csp_list[0])
    except Exception as e:
        opt_exps, bluf_cc, bluf_csp, bluf_exp, bluf_dte = [], None, None, None, 0
        st.warning(
            f"Options chain could not be loaded for {tk_hdr}. Strike suggestions and IV context may be limited. ({type(e).__name__})"
        )

    ref_iv_bluf = None
    if bluf_cc and bluf_cc.get("iv"):
        try:
            ref_iv_bluf = float(bluf_cc["iv"])
        except (TypeError, ValueError):
            ref_iv_bluf = None
    elif bluf_csp and bluf_csp.get("iv"):
        try:
            ref_iv_bluf = float(bluf_csp["iv"])
        except (TypeError, ValueError):
            ref_iv_bluf = None

    # ── DETERMINE BEST STRATEGY (example contract counts — no personal position data) ──
    nc = 1
    if struct == "BULLISH" and fg > 50:
        action_strat = "SELL COVERED CALLS"
        action_plain = (
            f"If you hold at least 100 shares, sell {nc} covered call contract(s) above the current price. "
            f"You collect premium today. If {ticker} stays below the strike by expiration, you keep the cash and your shares."
        )
    elif fg < 35:
        action_strat = "SELL CASH SECURED PUTS"
        action_plain = (
            f"The tape is defensive (fear score {fg:.0f}). Protection costs more, which pays you to sell it. "
            f"Sell cash secured puts under spot. Assignment simply means you own {ticker} at the strike you chose."
        )
    elif struct != "BEARISH":
        action_strat = "BULL PUT SPREAD"
        action_plain = "Defined risk credit spread: bank the credit while the broker caps the worst case."
    else:
        action_strat = "BEAR CALL SPREAD"
        action_plain = "Defined risk credit spread when sellers control the tape; you cap upside risk on the structure."

    why_trade_tip = _html_mod.escape(_confluence_why_trade_plain(cp_breakdown))
    trade_hdr_html = (
        "<div style='display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px'>"
        "<div style='font-size:.72rem;font-weight:800;color:#00e5ff;letter-spacing:.18em'>RECOMMENDED TRADE</div>"
        "<span class='cf-tip cf-tip-ico' tabindex='0' aria-label='Why this trade'>"
        "<span class='cf-tip-ico-mark'>ⓘ</span>"
        f"<span class='cf-tiptext'>{why_trade_tip}</span></span>"
        "<span style='font-size:.62rem;color:#94a3b8'>Why this trade?</span></div>"
    )

    # ── RECOMMENDED TRADE (optimal strike from options engine) ──
    master_kind, master_b = None, None
    if opt_exps and bluf_exp:
        br = struct in ("BULLISH", "RANGING")
        if br and bluf_cc:
            master_kind, master_b = "cc", bluf_cc
        elif br and bluf_csp:
            master_kind, master_b = "csp", bluf_csp
        elif bluf_csp:
            master_kind, master_b = "csp", bluf_csp
        elif bluf_cc:
            master_kind, master_b = "cc", bluf_cc

    master_html = ""
    if master_kind and master_b and bluf_exp:
        try:
            exp_dt = datetime.strptime(str(bluf_exp)[:10], "%Y-%m-%d")
            exp_disp = exp_dt.strftime("%B %d").upper()
            dte_m = max(1, (exp_dt - datetime.now()).days)
        except Exception:
            exp_disp = str(bluf_exp).upper()[:18]
            dte_m = max(1, int(bluf_dte or 30))
        _mstrike = float(master_b.get("strike") or 0)
        _mdelta = float(master_b.get("delta") or 0)
        _mprem = float(master_b.get("prem_100") or 0)
        _miv = float(master_b.get("iv") or 0)
        pop_pct = int(min(92, max(55, round((1.0 - abs(_mdelta)) * 100))))
        tk_esc = _html_mod.escape(ticker)
        _ref_rank_iv = _miv if _miv > 0 else ref_iv_bluf
        iv_badge_html = _iv_rank_pill_html(ticker, price, _ref_rank_iv)
        if master_kind == "cc":
            n_c = nc
            prem_tot = _mprem * n_c
            headline = (
                f"SELL {n_c}x {tk_esc} ${_mstrike:.0f} CALLS EXP {exp_disp}. "
                f"COLLECT ${prem_tot:,.0f} CASH TODAY. {pop_pct} PERCENT PROBABILITY OF KEEPING SHARES."
            )
            rh_steps = [
                f"In your broker app, open {ticker} and go to options.",
                f"Choose expiration {bluf_exp} ({dte_m} days out).",
                f"Sell {n_c}x ${_mstrike:.0f} call(s) near mid, then confirm the order.",
            ]
        else:
            prem_tot = _mprem
            headline = (
                f"SELL 1x {tk_esc} ${_mstrike:.0f} PUTS EXP {exp_disp}. "
                f"COLLECT ${prem_tot:,.0f} CASH TODAY. {pop_pct} PERCENT ODDS OPTION EXPIRES WORTHLESS IF PRICE STAYS ABOVE THE STRIKE."
            )
            rh_steps = [
                f"In your broker app, open {ticker} and go to options.",
                f"Choose expiration {bluf_exp} ({dte_m} days out).",
                f"Sell 1x ${_mstrike:.0f} put near mid, then confirm the order.",
            ]
        stepper = "".join(
            f"<div class='rh-step'><div class='num'>{i}.</div><div class='txt'>{_html_mod.escape(s)}</div></div>"
            for i, s in enumerate(rh_steps, start=1)
        )
        strike_s = f"{_mstrike:.0f}"
        iv_line = f"IV {_miv:.1f}% · " if _miv > 0 else ""
        master_html = (
            f"<div class='trade-master'>"
            f"{trade_hdr_html}"
            f"{iv_badge_html}"
            f"<p style='color:#e2e8f0;font-size:1.05rem;line-height:1.55;margin:0 0 14px 0;font-weight:600'>{headline}</p>"
            f"<div class='strike-big' style='margin:8px 0 6px 0'>${_html_mod.escape(strike_s)}</div>"
            f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px'>Desk optimal strike · {iv_line}DTE {dte_m}</div>"
            f"<div style='font-size:.75rem;font-weight:700;color:#a5f3fc;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px'>Broker checklist</div>"
            f"<div class='rh-stepper'>{stepper}</div>"
            f"<p style='color:#64748b;font-size:.78rem;margin:14px 0 0 0'>Quotes can lag. Confirm credit in the app before you send the order.</p>"
            f"</div>"
        )
    elif not opt_exps:
        _iv_off = _iv_rank_pill_html(ticker, price, None, stub="offline")
        master_html = (
            f"<div class='trade-master'>"
            f"{trade_hdr_html}"
            f"{_iv_off}"
            f"<p style='color:#e2e8f0;font-size:1rem;margin:0'>Options chain is offline. Retry when the pit is open or jump to Cash Flow Strategies.</p>"
            f"</div>"
        )
    else:
        _iv_ns = _iv_rank_pill_html(ticker, price, ref_iv_bluf, stub="no_strike" if not ref_iv_bluf else None)
        master_html = (
            f"<div class='trade-master'>"
            f"{trade_hdr_html}"
            f"{_iv_ns}"
            f"<p style='color:#e2e8f0;font-size:1rem;margin:0'>No liquid optimal strike cleared our filters yet. Open Cash Flow Strategies and choose an expiration by hand.</p>"
            f"</div>"
        )

    ema_dist_pct = None
    if len(df) >= 20:
        _e20 = TA.ema(df["Close"], 20).iloc[-1]
        if not pd.isna(_e20) and float(_e20) > 0:
            ema_dist_pct = abs(price / float(_e20) - 1.0) * 100.0

    # Build diamond status badge HTML
    d_badge_html = ""
    if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
        if latest_d["type"] == "blue":
            d_badge_html = f"<span class='diamond-badge badge-blue'>🔷 BLUE DIAMOND ACTIVE</span>"
        else:
            d_badge_html = f"<span class='diamond-badge badge-pink'>💎 PINK DIAMOND: TAKE PROFIT</span>"
    else:
        d_badge_html = "<span class='diamond-badge badge-none'>◇ No Active Diamond</span>"

    iv_rank_info = compute_iv_rank_proxy(ticker, price, ref_iv_bluf) if ref_iv_bluf else None
    ext_warn_html = ""
    if ema_dist_pct is not None and ema_dist_pct > EMA_EXTENSION_WARN_PCT:
        ext_warn_html = (
            f"<div style='margin-top:10px;padding:8px 12px;border-radius:8px;border:1px solid rgba(245,158,11,.45);"
            f"background:rgba(245,158,11,.12);font-size:.76rem;color:#fde68a;line-height:1.45'>"
            f"<strong>Caution: Extended.</strong> Price sits <strong>{ema_dist_pct:.1f}%</strong> away from the 20 day EMA. "
            f"After violent gaps, Gold Zone and Fib anchors can lag even while confluence still reflects the old range.</div>"
        )
    iv_row_html = ""
    if iv_rank_info is not None and ref_iv_bluf:
        rnk = iv_rank_info["rank"]
        lo, hi = iv_rank_info["lo"], iv_rank_info["hi"]
        rk_color = "#f59e0b" if rnk > 70 else ("#34d399" if rnk < 25 else "#94a3b8")
        iv_row_html = (
            f"<div style='margin-top:8px;padding:8px 12px;border-radius:8px;border:1px solid rgba(34,211,238,.35);"
            f"background:rgba(6,182,212,.1);font-size:.74rem;color:#cbd5e1;line-height:1.45'>"
            f"<span style='color:{rk_color};font-weight:800;font-family:JetBrains Mono,monospace'>{rnk:.0f}</span> "
            f"<span style='color:#94a3b8'>IV rank (term-structure proxy)</span> · "
            f"ref <strong>{ref_iv_bluf:.1f}%</strong> vs ATM curve from <span class='mono'>{lo:.1f}%</span> to <span class='mono'>{hi:.1f}%</span> "
            f"across listed expiries. <span style='color:#64748b'>This is a term structure proxy, not a full 52 week IV history.</span></div>"
        )
    elif ref_iv_bluf:
        iv_row_html = (
            "<div style='margin-top:8px;font-size:.72rem;color:#64748b'>IV rank proxy unavailable (need 2+ expiries with IV).</div>"
        )
    bluf_context_strip = ext_warn_html + iv_row_html

    # Confluence bar segments HTML
    cp_bar_html = ""
    for i in range(cp_max):
        filled = i < cp_score
        color = "#10b981" if filled and cp_score >= 7 else ("#f59e0b" if filled and cp_score >= 4 else ("#ef4444" if filled else "#1e293b"))
        cp_bar_html += f"<div style='flex:1;height:10px;background:{color};border-radius:5px;margin:0 1px'></div>"

    gz_gap_pct = ((price / gold_zone_price - 1) * 100) if gold_zone_price else 0.0
    show_gold_glance = bool(st.session_state.get("sb_gold_zone", True))
    bluf_html = f"""<div class='bluf'>
        <div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px'>
            <div>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{qs_color}'>{qs:.0f}</span>
                <span style='color:{qs_color};font-size:.9rem;margin-left:8px'>{qs_status}</span>
            </div>
            <div style='text-align:center'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>CONFLUENCE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{cp_color}'>{cp_score}/{cp_max}</span>
                <span style='color:{cp_color};font-size:.9rem;display:block'>{cp_label}</span>
                <div style='display:flex;gap:2px;margin-top:6px;width:160px'>{cp_bar_html}</div>
            </div>
            <div style='text-align:right'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>WEEKLY TREND</div>
                <span style='font-size:1.2rem;font-weight:700;color:{wk_color}'>{wk_label}</span>
                <div style='margin-top:8px'>{d_badge_html}</div>
            </div>
        </div>
        {bluf_context_strip}
        <div style='display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;border-top:1px solid rgba(255,255,255,.06);padding-top:12px'>
            <div style='flex:1;min-width:250px'>
                <div style='font-size:.7rem;color:{"#eab308" if show_gold_glance else "#64748b"};text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px'>⬥ GOLD ZONE</div>
                <span class='mono' style='font-size:1.3rem;font-weight:700;color:#fbbf24'>${gold_zone_price:.2f}</span>
                <span style='color:#94a3b8;font-size:.8rem;margin-left:8px'>({gz_gap_pct:+.1f}% away)</span>
            </div>
            <div style='flex:1;min-width:250px'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px'>MULTI-TF BIAS</div>
                <span style='font-size:.85rem;color:{"#10b981" if daily_struct=="BULLISH" else ("#ef4444" if daily_struct=="BEARISH" else "#f59e0b")}'>Daily: {daily_struct}</span>
                <span style='margin:0 8px;color:#334155'>|</span>
                <span style='font-size:.85rem;color:{"#10b981" if weekly_struct=="BULLISH" else ("#ef4444" if weekly_struct=="BEARISH" else "#f59e0b")}'>Weekly: {weekly_struct}</span>
                <div style='margin-top:8px;font-size:.78rem;color:#64748b'>52 week: <span class='mono' style='color:#94a3b8'>${hi52:.2f}</span> high · <span class='mono' style='color:#94a3b8'>${lo52:.2f}</span> low</div>
            </div>
        </div>
        <div style='display:flex;gap:24px;flex-wrap:wrap;margin-top:14px;border-top:1px solid rgba(255,255,255,.06);padding-top:12px'>
            <div><span class='tl' style='background:{"#10b981" if macd_bull else "#ef4444"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Momentum: <strong style="color:#e2e8f0">{"Buyers are in control" if macd_bull else "Sellers are gaining ground"}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if obv_up else "#ef4444"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Volume: <strong style="color:#e2e8f0">{"Big money is buying" if obv_up else "Big money is selling"}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if vix_v and vix_v > 20 else "#f59e0b"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Premiums: <strong style="color:#e2e8f0">{"Huge. Fear is high." if vix_v and vix_v > 25 else ("Normal range" if vix_v and vix_v > 18 else "Thin. Market is too calm.")}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if 35 < rsi_v < 65 else "#f59e0b"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>RSI: <strong style="color:#e2e8f0">{rsi_v:.0f}. {"Perfect zone for selling" if 35 < rsi_v < 65 else ("Stock ran too fast" if rsi_v > 65 else "Stock dropped too fast")}</strong></span></div>
        </div>
    </div>"""

    # ══════════════════════════════════════════════════════════════════
    #  EXECUTION STRIP (aligned mission + context)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="execution" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    st.markdown(
        f"<div class='execution-shell'><div class='execution-col'>{master_html}</div><div class='execution-col'>{bluf_html}</div></div>",
        unsafe_allow_html=True
    )

    # ── ALERTS BAR ──
    hi_al = [a for a in al if a["p"] == "HIGH"]
    if hi_al:
        st.markdown(f"<div class='ac'>\U0001f514 <strong>{len(al)} Alert{'s' if len(al) > 1 else ''}</strong>: {hi_al[0]['m']}{'<em> +' + str(len(al) - 1) + ' more</em>' if len(al) > 1 else ''}</div>", unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 1 — TECHNICAL CHART (fragment: overlay toggles without refetching Yahoo)
    # ══════════════════════════════════════════════════════════════════
    _fragment_technical_zone(
        df,
        df_wk,
        ticker,
        gold_zone_price,
        gold_zone_components,
        price,
        diamonds,
        latest_d,
        cp_breakdown,
        d_wr,
        d_n,
        struct,
        mini_mode,
        mobile_chart_layout,
    )
    chart_mood = "bull" if struct == "BULLISH" else ("bear" if struct == "BEARISH" else "neutral")

    dash_tab_setup, dash_tab_cashflow, dash_tab_intel = st.tabs(
        [
            "Setup & quant",
            "Cashflow & strikes",
            "Risk, scanner & intel",
        ]
    )

    with dash_tab_setup:
            # ══════════════════════════════════════════════════════════════════
            #  SECTION 2 \u2014 SETUP ANALYSIS
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="setup" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Setup Analysis", "Trend, range, or fade: here is the read and how to play it without guessing.",
                     tip_plain="This block is your bias clock. Uptrends reward measured premium sales with air above price. Ranges invite two sided discipline. Downtrends demand smaller size and wider buffers.")

            if ticker == "PLTR":
                next_print = datetime(2026, 5, 4)
                d_to_print = (next_print.date() - datetime.now().date()).days
                if d_to_print > 0:
                    countdown_txt = f"{d_to_print} days to earnings ({next_print.strftime('%b %d, %Y')})"
                elif d_to_print == 0:
                    countdown_txt = "Earnings expected today (May 04, 2026)"
                else:
                    countdown_txt = f"Last projected print date passed by {abs(d_to_print)} days (May 04, 2026)"
                with st.expander("STRATEGIC INTELLIGENCE: PLTR · Q4 2025 / 2026 OUTLOOK", expanded=True):
                    gc, bc = st.columns(2)
                    with gc:
                        st.markdown(
                            """
                            <div class='earn-col earn-good'>
                                <h4>THE GOOD (THE CATALYST)</h4>
                                <ul>
                                    <li><strong>Hyper Growth:</strong> Q4 2025 revenue grew 70% Y/Y to $1.41B. U.S. Commercial surged 137%.</li>
                                    <li><strong>Rule of 40:</strong> Palantir is operating at an elite Rule of 40 score of 127%.</li>
                                    <li><strong>2026 Guidance:</strong> Management guided to roughly 61% Y/Y growth with a $7.2B target.</li>
                                    <li><strong>Profitability:</strong> GAAP Net Income reached $609M (43% margin); FCF hit $791M.</li>
                                </ul>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with bc:
                        st.markdown(
                            f"""
                            <div class='earn-col earn-bad'>
                                <h4>THE BAD (THE RISK)</h4>
                                <ul>
                                    <li><strong>Valuation:</strong> Trading near 125x to 248x P/E, priced for near perfection.</li>
                                    <li><strong>International Lag:</strong> U.S. commercial +137% vs international commercial +2%.</li>
                                    <li><strong>SBC &amp; Dilution:</strong> Heavy stock based compensation remains a key bear argument.</li>
                                    <li><strong>Upcoming Print:</strong> {countdown_txt}. Street EPS projection is $0.26 to $0.29.</li>
                                </ul>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    st.markdown(
                        """
                        <div class='earn-meta'>
                            <span class='earn-pill'>Q4 2025 Revenue: $1.41B</span>
                            <span class='earn-pill'>U.S. Commercial: +137% Y/Y</span>
                            <span class='earn-pill'>2026 Guide: $7.2B</span>
                            <span class='earn-pill'>Projected EPS: $0.26-$0.29</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

            sa_left, sa_right = st.columns(2)
            with sa_left:
                cls = "sb" if struct == "BULLISH" else ("sr" if struct == "BEARISH" else "sn")
                st.markdown(f"<div class='{cls}'><strong>Market Structure: {struct}</strong></div>", unsafe_allow_html=True)
                struct_explain = {
                    "BULLISH": "The stock is making higher highs and higher lows. Think of a store where sales grow every single quarter. The trend is your friend. Sell covered calls at the highs to collect rent on your shares.",
                    "BEARISH": "The stock is making lower highs and lower lows. Think of a store where foot traffic drops every month. Be careful. Widen your safety buffers or wait for the bottom before selling options.",
                    "RANGING": "The stock is bouncing between a ceiling and a floor. Think of a business in a steady market. This is actually great for selling options on both sides and collecting cash."}
                _explain("Why this matters for your trade", struct_explain[struct], chart_mood)

                # Hurst Exponent — market regime filter
                hurst_val = TA.hurst(df["Close"])
                if hurst_val > 0.55:
                    h_label, h_color = "TRENDING", "#10b981"
                elif hurst_val < 0.45:
                    h_label, h_color = "MEAN REVERTING", "#8b5cf6"
                else:
                    h_label, h_color = "RANDOM WALK", "#f59e0b"
                st.markdown(f"<div class='tc' style='text-align:center;margin-bottom:12px'>"
                    f"<div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Hurst Exponent (R/S)</div>"
                    f"<div class='mono' style='font-size:1.3rem;color:{h_color}'>{hurst_val:.3f} = {h_label}</div></div>", unsafe_allow_html=True)
                if 0.45 <= hurst_val <= 0.55:
                    _explain("\u26a0\ufe0f Random Walk Warning",
                        f"Hurst is {hurst_val:.3f}. That means the price is moving randomly right now. Like flipping a coin. "
                        "Trend tools like Supertrend, ADX, and MACD are not reliable when this happens. "
                        "Your best move is to wait for a clear direction or use strategies that profit from sideways movement.", "bear")
                elif hurst_val > 0.55:
                    _explain("Hurst says: Trending Market",
                        f"Hurst is {hurst_val:.3f}. The stock has strong trending behavior. Whatever direction it is going, it is likely to keep going. "
                        "Think of a business with sales growing every quarter. You can trust the trend. "
                        "Trend tools like Supertrend and MACD are working correctly right now.", "bull")
                else:
                    _explain("Hurst says: Prices Snap Back",
                        f"Hurst is {hurst_val:.3f}. Prices are snapping back to the average faster than normal. "
                        "Big moves tend to reverse quickly. This is perfect for selling options at extremes. "
                        "You collect the premium and the stock comes back to you. Time decay works in your favor.", "bull")

                st.markdown(f"""<div class='qe'>
                    <div style='font-size:.75rem;color:#8b5cf6;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE SCORE</div>
                    <div style='font-size:3rem;font-weight:800;color:{qs_color};font-family:JetBrains Mono,monospace'>{qs:.0f}</div>
                    <div style='font-size:.85rem;color:#94a3b8'>Your overall score from 5 independent checks</div></div>""", unsafe_allow_html=True)
                for k, v in qb.items():
                    clr = "#10b981" if v > 70 else ("#f59e0b" if v > 50 else "#ef4444")
                    st.markdown(f"<div style='display:flex;align-items:center;margin:3px 0'><span style='width:85px;color:#94a3b8;font-size:.8rem;text-transform:capitalize'>{k}</span><div style='flex:1;background:#1e293b;border-radius:4px;height:7px;margin:0 8px'><div style='width:{v}%;background:{clr};border-radius:4px;height:7px'></div></div><span class='mono' style='color:#e2e8f0;font-size:.8rem'>{v:.0f}</span></div>", unsafe_allow_html=True)

                # ── CONFLUENCE POINTS (0-9 visual meter) ──
                st.markdown(f"""<div class='confluence-meter' style='margin-top:16px'>
                    <div style='font-size:.75rem;color:{cp_color};text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px'>💎 CONFLUENCE POINTS</div>
                    <div style='font-size:2.2rem;font-weight:800;color:{cp_color};font-family:JetBrains Mono,monospace'>{cp_score}/{cp_max} {cp_label}</div>
                    <div style='font-size:.8rem;color:#94a3b8;margin-top:2px'>{"🔷 Blue Diamond territory: strong buy signal active" if cp_score >= 7 else ("Approaching diamond zone: watch closely" if cp_score >= 5 else "Not enough confluence for a diamond signal")}</div>
                </div>""", unsafe_allow_html=True)
                for comp_name, comp_data in cp_breakdown.items():
                    pts = comp_data["pts"]
                    mx = comp_data["max"]
                    detail = comp_data["detail"]
                    bar_pct = (pts / mx * 100) if mx > 0 else 0
                    clr = "#10b981" if pts == mx else ("#f59e0b" if pts > 0 else "#334155")
                    st.markdown(f"<div style='display:flex;align-items:center;margin:3px 0'>"
                        f"<span style='width:95px;color:#94a3b8;font-size:.78rem'>{comp_name}</span>"
                        f"<div style='flex:1;background:#1e293b;border-radius:4px;height:7px;margin:0 8px'>"
                        f"<div style='width:{bar_pct}%;background:{clr};border-radius:4px;height:7px'></div></div>"
                        f"<span class='mono' style='color:#e2e8f0;font-size:.78rem;width:30px;text-align:right'>{pts}/{mx}</span>"
                        f"<span style='color:#64748b;font-size:.72rem;margin-left:8px;width:120px'>{detail}</span></div>",
                        unsafe_allow_html=True)

            with sa_right:
                st.markdown("**Key Price Levels**")
                if len(df) >= 50:
                    rec = df.iloc[-60:]
                    fl = TA.fib_retracement(rec["High"].max(), rec["Low"].min())
                    _fib_df = _df_price_levels(fl, price)
                    st.dataframe(
                        _style_price_levels_table(_fib_df, mode="fib", spot=price),
                        column_config=_PRICE_LEVEL_COLUMN_CONFIG,
                        use_container_width=True,
                        hide_index=True,
                    )
                _explain("What are Fibonacci levels?",
                    "After a big move, stocks tend to pull back to specific levels before continuing. The key levels are 38.2%, 50%, and 61.8%. "
                    "The 61.8% level is called the golden ratio. It is the most watched level by professional traders. "
                    "Why you care: set your put strikes near Fibonacci support. You collect cash AND you buy at a natural price floor.", "neutral")
                if st.checkbox("Gann Square of 9", key="exp_1"):
                    gl = TA.gann_sq9(price)
                    _gann_df = _df_price_levels(gl, price)
                    st.dataframe(
                        _style_price_levels_table(_gann_df, mode="gann", spot=price),
                        column_config=_PRICE_LEVEL_COLUMN_CONFIG,
                        use_container_width=True,
                        hide_index=True,
                    )
                if st.checkbox("Gann Angles", key="exp_2"):
                    ang, sp = TA.gann_angles(df)
                    st.markdown(f"**Swing Low:** ${sp:.2f}")
                    for n_g, p_v in ang.items():
                        st.markdown(f"* **{n_g}** maps to ${p_v:.2f} ({(p_v / price - 1) * 100:+.1f}%)")
                if st.checkbox("Gann Time Cycles", key="exp_3"):
                    for cyc in TA.gann_time_cycles(df):
                        st.markdown(
                            f"* **{cyc['cycle']} bar cycle** lands {cyc['date'].strftime('%Y-%m-%d')} ({cyc['status']})"
                        )

            # ══════════════════════════════════════════════════════════════════
            #  SECTION 3 \u2014 QUANT DASHBOARD (two-column: metric + explanation)
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="quant-dashboard" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Quant Dashboard", "Every dial translated into English. Meaning first. Action second.",
                     tip_plain="Treat this like an aircraft panel. Strong green bars confirm edge. Thin readings mean throttle back. Confluence and Gold Zone still own the headline.")
            rv2 = TA.rsi2(df["Close"]).iloc[-1] if len(df) > 5 else 50
            adx_v, dip, din = TA.adx(df)
            cci_v = TA.cci(df).iloc[-1]
            st_l, st_d = TA.supertrend(df)
            _, kj, sa_ich, sb_ich, _ = TA.ichimoku(df)
            an = adx_v.iloc[-1] if not pd.isna(adx_v.iloc[-1]) else 0

            # RSI
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>RSI (14)</div><div class='mono' style='font-size:1.5rem;color:{'#ef4444' if rsi_v > 70 else ('#10b981' if rsi_v < 30 else '#e2e8f0')}'>{rsi_v:.1f}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>RSI 2 bar: {rv2:.1f}</div></div>", unsafe_allow_html=True)
            with ir:
                if rsi_v > 70:
                    _explain("RSI: Stock is Overheated", f"RSI is {rsi_v:.0f}. The stock ran up too fast. Think of a product flying off shelves after a viral review. Buyers are overpaying right now. This is the ideal time to sell Covered Calls and collect cash at peak excitement.", "bear")
                elif rsi_v < 30:
                    _explain("RSI: Stock is On Sale", f"RSI is {rsi_v:.0f}. Sellers have panicked. Think of a clearance sale that went too deep. This is your signal to sell Cash Secured Puts. You get paid cash today and you might buy shares at a bargain price.", "bull")
                else:
                    _explain("RSI: Stock is Resting", f"RSI is {rsi_v:.0f}. The stock is calm. Buyers are not panicking. Sellers are not panicking. This is the perfect zone to collect cash from selling options.", "neutral")

            # MACD
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>MACD</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if macd_bull else '#ef4444'}'>{'BULLISH' if macd_bull else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Hist: {h_v.iloc[-1]:.3f}</div></div>", unsafe_allow_html=True)
            with ir:
                if macd_bull:
                    _explain("MACD: Buyers Are Winning", "Recent momentum is stronger than the longer term average. Think of a store where this month's sales beat the quarterly average. Buyers are in charge. You can sell Covered Calls at higher strikes with more confidence.", "bull")
                else:
                    _explain("MACD: Sellers Are Winning", "Recent momentum dropped below the longer term average. Think of a store where this month's sales fell below the quarterly trend. Be more careful when picking your strike prices.", "bear")

            # ADX
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>ADX</div><div class='mono' style='font-size:1.5rem;color:{'#10b981' if an > 25 else '#f59e0b'}'>{an:.1f}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Plus DI {dip.iloc[-1]:.1f} · Minus DI {din.iloc[-1]:.1f}</div></div>", unsafe_allow_html=True)
            with ir:
                di_w = "Buyers via plus DI" if dip.iloc[-1] > din.iloc[-1] else "Sellers via minus DI"
                if an > 25:
                    _explain("ADX: Strong Trend Detected", f"ADX is {an:.0f}. That is above 25 which means a strong trend is happening. The winner right now is: {di_w}. Think of a business with a clear growth direction. Sell your options in the direction of the trend for the safest play.", "bull" if dip.iloc[-1] > din.iloc[-1] else "bear")
                else:
                    _explain("ADX: No Clear Trend", f"ADX is {an:.0f}. That is below 25 which means the market has no clear direction right now. Think of a business in a holding pattern. This is a good time for strategies that profit from sideways movement.", "neutral")

            # CCI + Supertrend row
            il, ir = st.columns([1, 2])
            stb = st_d.iloc[-1] == 1
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>CCI (20)</div><div class='mono' style='font-size:1.5rem;color:{'#ef4444' if not pd.isna(cci_v) and cci_v > 100 else ('#10b981' if not pd.isna(cci_v) and cci_v < -100 else '#e2e8f0')}'>{cci_v:.0f}</div></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='tc' style='text-align:center;margin-top:8px'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Supertrend</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if stb else '#ef4444'}'>{'BULLISH' if stb else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>${st_l.iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
            with ir:
                cci_txt = f"CCI is {cci_v:.0f}. " + (
                    "That is above positive 100. The stock is stretched versus its average. Great moment to lean on call sales. "
                    if not pd.isna(cci_v) and cci_v > 100
                    else (
                        "That is below negative 100. The stock washed out under its average. Sellers overdid it. Look at put sales for income. "
                        if not pd.isna(cci_v) and cci_v < -100
                        else "That is in the neutral pocket. No extreme edge to harvest yet. "
                    )
                )
                st_price = st_l.iloc[-1]
                st_txt = f"The Supertrend is your price floor. It is BULLISH at ${st_price:.2f}. As long as the stock stays above this green line, your shares are safe." if stb else f"The Supertrend is BEARISH at ${st_price:.2f}. It is acting as a falling ceiling above the price. The trend is down. Be defensive and protect your shares."
                _explain("CCI and Supertrend", cci_txt + st_txt, "bull" if stb else "bear")

            # Ichimoku + OBV row
            above_cloud = not pd.isna(sa_ich.iloc[-1]) and not pd.isna(sb_ich.iloc[-1]) and price > max(sa_ich.iloc[-1], sb_ich.iloc[-1])
            ou = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else True
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Ichimoku</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if above_cloud else '#ef4444'}'>{'ABOVE CLOUD' if above_cloud else 'IN/BELOW'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Kijun: ${kj.iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='tc' style='text-align:center;margin-top:8px'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>OBV</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if ou else '#ef4444'}'>{'RISING' if ou else 'FALLING'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>{'Accumulation' if ou else 'Distribution'}</div></div>", unsafe_allow_html=True)
            with ir:
                ich_txt = "The price is above the Ichimoku Cloud. The cloud acts as a thick safety net below the stock. When the price floats above it, the trend is strongly in your favor. Your shares are protected. " if above_cloud else "The price is inside or below the cloud. The trend is unclear right now. Think of it like driving through fog. Wait for visibility before you sell options aggressively. "
                obv_txt = "OBV is rising. Big institutional players are quietly buying up shares. Think of your biggest wholesale customers stocking up before a price increase. That is a bullish sign. " if ou else "OBV is falling. Big money is selling into rallies. Think of your best customers reducing their orders. The price may follow them down. Be careful. "
                _explain("Ichimoku Cloud and Volume Flow", ich_txt + obv_txt, "bull" if above_cloud and ou else ("bear" if not above_cloud and not ou else "neutral"))

            # Divergence Scanner
            st.markdown("#### Divergence Scanner")
            rsi_s = TA.rsi(df["Close"])
            divs_rsi = TA.detect_divergences(df["Close"], rsi_s)
            obv_divs = TA.detect_divergences(df["Close"], obv_s)
            all_divs = [(d, "RSI") for d in divs_rsi] + [(d, "OBV") for d in obv_divs]
            if all_divs:
                for d, src in all_divs[-5:]:
                    st.markdown(f"<div class='ac'>{'🟢' if d['type'] == 'bullish' else '🔴'} <strong>{d['type'].title()} {src} divergence</strong> near ${d['price']:.2f} on {d['idx'].strftime('%Y-%m-%d')}</div>", unsafe_allow_html=True)
                _explain("What is a divergence?", "The price makes a new high or low but the indicator does not agree. Think of a company reporting record revenue but declining profits. The numbers do not match. That is an early warning that the trend might reverse soon.", "neutral")
            else:
                st.info("No divergences found. All indicators agree with the current trend.")

            # Volume Profile
            vp = TA.volume_profile(df)
            if not vp.empty:
                poc = vp.loc[vp["volume"].idxmax()]
                if not mini_mode:
                    vmax = vp["volume"].max()
                    fig_vp = go.Figure(
                        go.Bar(
                            x=vp["volume"],
                            y=vp["mid"],
                            orientation="h",
                            marker_color=[_PLOTLY_CASH_UP if v == vmax else _PLOTLY_BLUE for v in vp["volume"]],
                            opacity=0.72,
                            hovertemplate=(
                                "<b>Volume profile</b><br>"
                                "Price <b>$%{y:,.2f}</b><br>"
                                "Volume <b>%{x:,.0f}</b><extra></extra>"
                            ),
                        )
                    )
                    fig_vp.add_hline(
                        y=poc["mid"],
                        line_dash="solid",
                        line_color="rgba(245, 158, 11, 0.85)",
                        line_width=1.5,
                        annotation_text=f"POC ${poc['mid']:,.2f}",
                        annotation_font=dict(size=11, color="#fbbf24"),
                    )
                    fig_vp.update_layout(
                        template="plotly_dark",
                        paper_bgcolor=_PLOTLY_PAPER_BG,
                        plot_bgcolor=_PLOTLY_PLOT_BG,
                        font=_PLOTLY_FONT_MAIN,
                        height=300,
                        margin=dict(l=60, r=20, t=28, b=40),
                        hoverlabel=_chart_hoverlabel(),
                        title=dict(
                            text="Volume by price (horizontal)",
                            x=0,
                            xanchor="left",
                            font=dict(size=13, color="#e2e8f0", family="Inter, system-ui, sans-serif"),
                        ),
                    )
                    fig_vp.update_xaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=False,
                        title_text="Volume (shares)",
                        tickformat=",.0f",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    fig_vp.update_yaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=False,
                        title_text="Price",
                        tickprefix="$",
                        tickformat=",.2f",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    st.plotly_chart(fig_vp, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                else:
                    st.caption(f"Volume POC (mini mode): **${poc['mid']:.2f}**. Full profile chart stays parked while Turbo is on.")
                _explain("\U0001f9e0 Volume Profile", f"The Point of Control (POC) is ${poc['mid']:.2f}. This is the most traded price. Think of it as the price point where your store sees the most customers. The stock is pulled toward this price like a magnet. Use it to pick your option strike prices.", "neutral")

            # ══════════════════════════════════════════════════════════════════

    with dash_tab_cashflow:
            #  SECTION 4 \u2014 CASH-FLOW STRATEGIES
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="strategies" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Cash Flow Strategies", f"Concrete strikes for {ticker} at ${price:.2f}. Lift them straight into your ticket.",
                     tip_plain="Start with the optimal line the desk highlights. Covered calls need stock on hand. Cash secured puts monetize patience. Spreads are for when you want a hard loss ceiling.")
            st.markdown(
                f"<div class='tc'><div style='text-align:center'><span style='color:#64748b;font-size:.8rem'>ANALYZING</span><br>"
                f"<span style='font-size:1.4rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(ticker)} @ ${price:.2f}</span></div></div>",
                unsafe_allow_html=True,
            )

            if opt_exps:
                sel_exp = st.selectbox("Expiration", opt_exps[:10], index=min(2, len(opt_exps) - 1), key="sel_exp")
                dte = max(1, (datetime.strptime(sel_exp, "%Y-%m-%d") - datetime.now()).days)
                try:
                    result_sel, _ = fetch_options(ticker, sel_exp)
                except Exception as e:
                    st.warning(f"Could not load the option chain for expiration {sel_exp}. ({type(e).__name__})")
                    result_sel = (pd.DataFrame(), pd.DataFrame())
                calls, puts = result_sel if isinstance(result_sel, (tuple, list)) and len(result_sel) == 2 else (pd.DataFrame(), pd.DataFrame())
                calls = calls if isinstance(calls, pd.DataFrame) else pd.DataFrame()
                puts = puts if isinstance(puts, pd.DataFrame) else pd.DataFrame()
                if not calls.empty or not puts.empty:
                    s1, s2 = st.columns(2)
                    with s1:
                        st.markdown("#### Covered Calls")
                        cc = Opt.covered_calls(price, calls, dte, rfr)
                        if cc:
                            opt_cc = next((c for c in cc if c.get("optimal")), cc[0])
                            b = opt_cc; nc_s = 1
                            opt_html = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                            in_zone = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                            delta_color = "#10b981" if in_zone else "#f59e0b"
                            st.markdown(f"<div class='sb'>{opt_html}<strong>SELL {nc_s}x ${b['strike']:.0f}C @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color}'>\u0394 {b['delta']:.2f}</strong><br>Premium: <strong style='color:#10b981'>${b['prem_100'] * nc_s:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Ann: {b['ann_yield']:.1f}% | OI: {b['oi']:,}</span></div>", unsafe_allow_html=True)
                            if st.checkbox("All CC strikes", key="exp_5"):
                                _cc_df = _options_scan_dataframe(cc, put_table=False)
                                st.dataframe(
                                    _style_propdesk_highlight(_cc_df),
                                    column_config=_options_scan_column_config(put_table=False),
                                    use_container_width=True,
                                    hide_index=True,
                                )
                        else:
                            st.info("No liquid covered call strikes found. We need at least 100 open interest and 10 volume.")
                    with s2:
                        st.markdown("#### Cash Secured Puts")
                        csp = Opt.cash_secured_puts(price, puts, dte, rfr)
                        if csp:
                            opt_csp = next((c for c in csp if c.get("optimal")), csp[0])
                            b = opt_csp
                            opt_html_p = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                            in_zone_p = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                            delta_color_p = "#10b981" if in_zone_p else "#f59e0b"
                            st.markdown(f"<div class='sb'>{opt_html_p}<strong>SELL 1x ${b['strike']:.0f}P @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color_p}'>\u0394 {b['delta']:.2f}</strong><br>Premium: <strong style='color:#10b981'>${b['prem_100']:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Eff buy: ${b['eff_buy']:.2f} | OI: {b['oi']:,}</span></div>", unsafe_allow_html=True)
                            if st.checkbox("All CSP strikes", key="exp_6"):
                                _csp_df = _options_scan_dataframe(csp, put_table=True)
                                st.dataframe(
                                    _style_propdesk_highlight(_csp_df),
                                    column_config=_options_scan_column_config(put_table=True),
                                    use_container_width=True,
                                    hide_index=True,
                                )
                        else:
                            st.info("No liquid put strikes found. We need at least 100 open interest and 10 volume.")

                    _explain("\U0001f9e0 What are Delta and Theta?",
                        "<strong>Delta is your win probability.</strong> A Delta of 0.16 means you have an 84 percent chance to keep all the cash and keep your shares. Lower Delta means safer. "
                        "<strong>Theta is your daily paycheck.</strong> Every day that passes, the option loses value. That lost value goes straight into your pocket. Time is literally paying you. "
                        "<strong>OI is how busy the market is.</strong> Higher OI means more traders are active. That means you get better prices when you sell. We filter out anything below 100 OI to protect you.", "neutral")

                    st.divider()
                    sp1, sp2 = st.columns(2)
                    with sp1:
                        st.markdown("#### Bull Put Spread")
                        ps = Opt.credit_spreads(price, puts, "put_credit")
                        if ps:
                            b = ps[0]
                            st.markdown(f"<div class='sb'><strong>${b['short']:.0f}P/${b['long']:.0f}P</strong> | Cr: ${b['credit_100']:.0f} | ML: ${b['max_loss']:.0f} | POP: {b['pop']:.0f}%</div>", unsafe_allow_html=True)
                    with sp2:
                        st.markdown("#### Bear Call Spread")
                        cs = Opt.credit_spreads(price, calls, "call_credit")
                        if cs:
                            b = cs[0]
                            st.markdown(f"<div class='sr'><strong>${b['short']:.0f}C/${b['long']:.0f}C</strong> | Cr: ${b['credit_100']:.0f} | ML: ${b['max_loss']:.0f} | POP: {b['pop']:.0f}%</div>", unsafe_allow_html=True)

                    _explain("\U0001f9e0 What is a credit spread?",
                        "A credit spread is like selling insurance with a cap on your worst case. You sell one option and collect cash. Then you buy a cheaper one further away to limit your risk. "
                        "<strong>POP</strong> is your Probability of Profit. <strong>ML</strong> is your Max Loss, the absolute worst case. <strong>Cr</strong> is the cash you receive today. "
                        "A 75% POP means you win roughly 3 out of every 4 times you make this trade.", "neutral")

                    if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
                        st.divider()
                        if latest_d["type"] == "blue":
                            st.markdown(f"""<div class='diamond-blue'>
                                <div style='font-size:1rem;font-weight:700;margin-bottom:8px'>🔷 BLUE DIAMOND AUTO SUGGESTIONS</div>
                                <div style='color:#94a3b8;font-size:.85rem;margin-bottom:10px'>
                                    A Blue Diamond fired {(df.index[-1] - latest_d['date']).days} day(s) ago at ${latest_d['price']:.2f} with confluence {latest_d['score']}/9.
                                    Historical probability of profit: <strong style='color:#10b981'>{d_wr:.0f}%</strong> ({d_n} signals backtested).
                                </div>
                                <div style='color:#e2e8f0;font-size:.9rem;line-height:1.8'>""", unsafe_allow_html=True)
                            suggestions = []
                            if cc:
                                b = cc[0]
                                suggestions.append(f"<strong>Covered Call:</strong> Sell {nc}x ${b['strike']:.0f}C exp {sel_exp} @ ${b['mid']:.2f} (collect ${b['prem_100']*nc:,.0f})")
                            if csp:
                                b = csp[0]
                                suggestions.append(f"<strong>Cash Secured Put:</strong> Sell 1x ${b['strike']:.0f}P exp {sel_exp} @ ${b['mid']:.2f} (collect ${b['prem_100']:,.0f})")
                            if ps:
                                b = ps[0]
                                suggestions.append(f"<strong>Bull Put Spread:</strong> ${b['short']:.0f}/${b['long']:.0f}P exp {sel_exp} credit ${b['credit_100']:,.0f} POP {b['pop']:.0f}%")
                            for sug in suggestions:
                                st.markdown(f"<div style='margin:4px 0'>• {sug}</div>", unsafe_allow_html=True)
                            st.markdown("</div></div>", unsafe_allow_html=True)
                            _explain("Why these trades on a Blue Diamond?",
                                f"The Blue Diamond means {latest_d['score']} out of 9 confluence factors aligned bullish. "
                                "Historically, similar setups have a strong track record. "
                                "Covered Calls collect premium while riding the trend. "
                                "Cash Secured Puts let you buy the dip if it comes. "
                                "Bull Put Spreads give you bullish exposure with capped risk. "
                                "Pick the strategy that matches your capital and conviction.", "bull")
                        else:
                            st.markdown(f"""<div class='diamond-pink'>
                                <div style='font-size:1rem;font-weight:700;margin-bottom:8px'>💎 PINK DIAMOND: DEFENSIVE POSTURE</div>
                                <div style='color:#94a3b8;font-size:.85rem;margin-bottom:10px'>
                                    A Pink Diamond fired {(df.index[-1] - latest_d['date']).days} day(s) ago at ${latest_d['price']:.2f}.
                                    Confluence dropped to {latest_d['score']}/9. Momentum is exhausting.
                                </div>
                                <div style='color:#e2e8f0;font-size:.9rem;line-height:1.8'>""", unsafe_allow_html=True)
                            if cs:
                                b = cs[0]
                                st.markdown(f"<div style='margin:4px 0'>• <strong>Bear Call Spread:</strong> ${b['short']:.0f}/${b['long']:.0f}C credit ${b['credit_100']:,.0f} POP {b['pop']:.0f}%</div>", unsafe_allow_html=True)
                            if cc:
                                b = cc[0]
                                st.markdown(f"<div style='margin:4px 0'>• <strong>Aggressive Covered Call:</strong> Sell ATM or near-ATM ${b['strike']:.0f}C to maximize premium capture</div>", unsafe_allow_html=True)
                            st.markdown(f"<div style='margin:4px 0'>• <strong>Tighten Stops:</strong> If below Gold Zone ${gold_zone_price:.2f}, consider reducing exposure</div>", unsafe_allow_html=True)
                            st.markdown("</div></div>", unsafe_allow_html=True)
                            _explain("Why go defensive on a Pink Diamond?",
                                "The Pink Diamond means bullish momentum has exhausted or confluence collapsed. "
                                "This does not mean crash. It means the easy money in the current leg is done. "
                                "Bear Call Spreads profit from a pullback. Aggressive CCs lock in premium at the top. "
                                "Wait for the next Blue Diamond before entering again aggressively.", "bear")

                    # Greeks, EV & Vol Skew
                    st.divider()
                    st.markdown("#### Greeks, Expected Value & Volatility Skew")
                    gk1, gk2, gk3 = st.columns(3)
                    with gk1:
                        if cc:
                            b0 = cc[0]; iv_d = b0["iv"] / 100 if b0["iv"] > 0 else 0.5; T_y = dte / 365
                            gr = bs_greeks(price, b0["strike"], T_y, rfr, iv_d, "call")
                            fv = bs_price(price, b0["strike"], T_y, rfr, iv_d, "call")
                            edge = b0["mid"] - fv
                            edge_c = "#10b981" if edge > 0 else "#ef4444"
                            st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>TOP CC GREEKS (r={rfr * 100:.2f}%)</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>Delta: <strong style='color:#e2e8f0'>{gr['delta']:.3f}</strong><br>Theta: <strong style='color:#10b981'>${gr['theta']:.3f}/day</strong><br>Vega: <strong style='color:#e2e8f0'>${gr['vega']:.3f}/1%IV</strong><br>Fair: <strong style='color:#e2e8f0'>${fv:.2f}</strong> | Edge: <strong style='color:{edge_c}'>${edge:+.2f}</strong></div></div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div class='tc'><span style='color:#64748b'>No CC data for Greeks</span></div>", unsafe_allow_html=True)
                    with gk2:
                        ev_lines = []
                        if cc:
                            b0 = cc[0]; pop_cc = min(85, max(50, 100 - b0["otm_pct"] * 5))
                            ev_cc = calc_ev(b0["prem_100"], b0["prem_100"] * 3, pop_cc)
                            ec = "#10b981" if ev_cc > 0 else "#ef4444"
                            ev_lines.append(f"CC ${b0['strike']:.0f}: <strong style='color:{ec}'>${ev_cc:+.0f}</strong> (POP ~{pop_cc:.0f}%)")
                        if ps:
                            b0 = ps[0]; ev_ps = calc_ev(b0["credit_100"], b0["max_loss"], b0["pop"])
                            ec = "#10b981" if ev_ps > 0 else "#ef4444"
                            ev_lines.append(f"Put Spread: <strong style='color:{ec}'>${ev_ps:+.0f}</strong> (POP {b0['pop']:.0f}%)")
                        joined = "<br>".join(ev_lines) if ev_lines else "N/A"
                        st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>EXPECTED VALUE</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>{joined}</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>Positive means edge. Negative means walk away.</div></div>", unsafe_allow_html=True)
                    with gk3:
                        skew, p_iv, c_iv = calc_vol_skew(price, calls, puts)
                        if skew is not None:
                            sc = "#ef4444" if skew > 10 else ("#f59e0b" if skew > 5 else "#10b981")
                            sm = "Institutions hedging heavily" if skew > 10 else ("Mild put skew" if skew > 5 else "Balanced")
                            st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>VOL SKEW</div><div class='mono' style='font-size:1.3rem;color:{sc};margin-top:8px'>{skew:+.1f}%</div><div style='color:#94a3b8;font-size:.85rem;margin-top:4px'>Put IV: {p_iv:.1f}% | Call IV: {c_iv:.1f}%</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>{sm}</div></div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div class='tc'><div style='font-size:.7rem;color:#64748b'>VOL SKEW</div><div style='color:#94a3b8;margin-top:8px'>Insufficient IV data</div></div>", unsafe_allow_html=True)

                    _explain("\U0001f9e0 What do these numbers mean for me?",
                        "<strong>Expected Value (EV)</strong> is your long term profit margin. Think of it like calculating net profit per product after returns. Positive EV means you have a real edge. Negative means avoid the trade. "
                        "<strong>Volatility Skew</strong> tells you if big institutions are buying crash insurance. When put prices are much higher than call prices, fear is elevated. You get fatter premiums but the risk is also higher. "
                        "<strong>Edge</strong> is the difference between the market price and the mathematically fair price. Positive Edge means the market is overpaying you. That is exactly what you want.", "neutral")
                else:
                    st.warning(
                        "This expiration returned an empty chain from the feed after walking nearby dates. "
                        "Pick another expiry or retry when the options pit is live."
                    )
            else:
                st.warning("Options data currently unavailable for this ticker.")

            # ══════════════════════════════════════════════════════════════════

    with dash_tab_intel:
            #  SECTION 5 \u2014 PSYCHOLOGY & RISK MANAGEMENT
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="risk" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Psychology and Risk Management", "Sentiment, sizing, guardrails. The stuff that keeps pros solvent.",
                     tip_plain="Fear and Greed shows how the crowd is priced. Kelly and ATR frame responsible size. When stories disagree, shrink the bet and wait for a cleaner tape.")
            p1, p2 = st.columns(2)
            with p1:
                gc = "#10b981" if fg < 30 else ("#f59e0b" if fg < 60 else "#ef4444")
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>FEAR & GREED</div><div style='font-size:3.5rem;font-weight:800;color:{gc};margin:12px 0;font-family:JetBrains Mono,monospace'>{fg:.0f}</div><div style='font-size:1.1rem;color:{gc}'>{fg_emoji} {fg_label}</div><div style='color:#94a3b8;margin-top:8px;font-size:.85rem'>{fg_advice}</div></div>", unsafe_allow_html=True)
                _explain("Why sentiment matters",
                    "Fear and Greed is like reading the room before you set your prices. "
                    "<strong style='color:#10b981'>High fear (low score)</strong>: Customers are panicking. They will pay you extra for protection. Sell options aggressively and collect fat premiums. "
                    "<strong style='color:#ef4444'>High greed (high score)</strong>: Everyone is euphoric. Premiums get thinner and the risk of losing your shares goes up. Be very selective.",
                    "bull" if fg < 40 else ("bear" if fg > 60 else "neutral"))
                st.markdown("#### Macro Environment")
                for k, v in macro.items():
                    dc = "#10b981" if v["chg"] >= 0 else "#ef4444"
                    st.markdown(f"<div style='display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1e293b'><span style='color:#94a3b8'>{k}</span><span class='mono' style='color:#e2e8f0'>{v['price']:.2f} <span style='color:{dc}'>{v['chg']:+.2f}%</span></span></div>", unsafe_allow_html=True)
            with p2:
                mrt = REF_NOTIONAL * RISK_PCT_EXAMPLE / 100
                st.markdown(
                    f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>EXAMPLE MAX RISK/TRADE</div>"
                    f"<div class='mono' style='font-size:1.3rem;color:#e2e8f0'>${mrt:,.0f}</div>"
                    f"<div style='font-size:.65rem;color:#64748b;margin-top:6px'>{RISK_PCT_EXAMPLE:.0f}% of ${REF_NOTIONAL:,.0f} reference (illustrative)</div></div>",
                    unsafe_allow_html=True,
                )
                atr_v = TA.atr(df).iloc[-1]
                if pd.isna(atr_v) or atr_v <= 0:
                    atr_v = price * .03
                sh_atr = int(mrt / (atr_v * 2)) if atr_v > 0 else 0
                st.markdown(f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>ATR SIZING</div><div style='color:#94a3b8;font-size:.85rem;margin-top:8px'>ATR: ${atr_v:.2f} | Max shares: {sh_atr} | Contracts: {sh_atr // 100}</div></div>", unsafe_allow_html=True)
                _explain("Position sizing in plain English",
                    f"ATR is ${atr_v:.2f}. That is how much this stock moves on an average day. Think of it as the normal daily price swing. "
                    f"Using an illustrative {RISK_PCT_EXAMPLE:.0f}% risk budget on a ${REF_NOTIONAL:,.0f} reference account (${mrt:,.0f} max loss per trade), "
                    f"you could size up to about {sh_atr} shares or {max(0, sh_atr // 100)} option contracts. Scale to your own account and rules.", "neutral")

                # Kelly Criterion — mathematically optimal allocation
                k_full, k_half = 0.0, 0.0
                k_source = ""
                if bluf_cc:
                    k_pop = min(85, max(50, 100 - bluf_cc["otm_pct"] * 5))
                    k_win = bluf_cc["prem_100"]
                    k_loss = k_win * 3
                    k_full, k_half = kelly_criterion(k_pop, k_win, k_loss)
                    k_source = f"CC ${bluf_cc['strike']:.0f}"
                elif bluf_csp:
                    k_pop = min(85, max(50, 100 - bluf_csp["otm_pct"] * 5))
                    k_win = bluf_csp["prem_100"]
                    k_loss = bluf_csp["strike"] * 100 - k_win
                    k_full, k_half = kelly_criterion(k_pop, k_win, k_loss)
                    k_source = f"CSP ${bluf_csp['strike']:.0f}"
                if k_half > 0:
                    k_cap = KELLY_DISPLAY_CAP_PCT
                    k_show = min(k_half, k_cap)
                    k_dollars = REF_NOTIONAL * k_show / 100
                    capped_note = (
                        f" Half Kelly math landed at {k_half:.1f}%; <strong>we cap the headline at {k_cap:.0f}%</strong> for portfolio heat. Never treat Kelly as a target allocation."
                        if k_half > k_cap
                        else ""
                    )
                    kc = "#10b981" if k_show <= RISK_PCT_EXAMPLE * 2 else "#f59e0b"
                    st.markdown(
                        f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>KELLY HALF MODE · UI CAP</div>"
                        f"<div class='mono' style='font-size:1.3rem;color:{kc}'>{k_show:.1f}% = ${k_dollars:,.0f}</div>"
                        f"<div style='font-size:.7rem;color:#64748b;margin-top:4px'>Raw half Kelly {k_half:.1f}% · full Kelly {k_full:.1f}% · {k_source}. "
                        f"Display max {k_cap:.0f}% for risk hygiene.{capped_note}</div></div>",
                        unsafe_allow_html=True)
                    _explain("Kelly Criterion in plain English",
                        f"The Kelly formula can suggest large fractions; here we show <strong>Half Kelly</strong> then <strong>cap the headline at {k_cap:.0f}%</strong> "
                        f"so the desk view stays conservative (raw half-Kelly was {k_half:.1f}%). "
                        f"On a <strong>${REF_NOTIONAL:,.0f}</strong> illustrative reference, the capped line is <strong>${k_dollars:,.0f}</strong>. "
                        "Scale to your own capital; Kelly is a theoretical optimum, not an order size.", "neutral")
                else:
                    st.markdown("<div class='tc'><div style='font-size:.75rem;color:#64748b'>KELLY CRITERION</div>"
                        "<div style='color:#94a3b8;font-size:.85rem;margin-top:6px'>Not enough data yet. No liquid option strikes available to calculate your optimal bet size.</div></div>",
                        unsafe_allow_html=True)

                st.markdown("#### Active Alerts")
                if al:
                    for a in al:
                        ic = "\U0001f7e2" if a["t"] == "bullish" else ("\U0001f534" if a["t"] == "bearish" else "\U0001f7e1")
                        st.markdown(f"<div class='ac'>{ic} [{a['p']}] {a['m']}</div>", unsafe_allow_html=True)
                else:
                    st.info("No alerts.")

            # ══════════════════════════════════════════════════════════════════
            #  SECTION 6 \u2014 PREMIUM SIMULATOR
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="simulator" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Premium Simulator", "Replay a year of covered calls with your assumptions before you commit capital.",
                     tip_plain="Dial OTM, hold time, and IV multiplier. Hunt for settings that still look sane in both calm and chaotic tapes.")
            st.warning(
                "Premiums here are modeled from historical volatility. They are illustrative, not a promise. Treat the run as a dress rehearsal; live fills will differ."
            )
            bc1, bc2, bc3, bc4 = st.columns(4)
            bt_otm = bc1.slider("OTM%", 2, 15, 5, key="sim_otm") / 100
            bt_hold = bc2.slider("Hold (d)", 7, 45, 30, key="sim_hold")
            bt_per = bc3.selectbox("Period", ["6mo", "1y"], index=1, key="sim_period")
            bt_iv = bc4.slider("IV Mult", .5, 2.0, 1.0, .1, key="sim_iv")
            br = run_cc_sim_cached(ticker, bt_per, bt_otm, bt_hold, bt_iv)
            if not br.empty:
                tp = br["premium"].sum() * 1
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Trades", len(br))
                m2.metric("Win Rate", f"{(br['profit'] > 0).mean() * 100:.0f}%")
                m3.metric("Avg Ret", f"{br['ret_pct'].mean():.1f}%")
                m4.metric("Est Premium", f"${tp:,.0f}")
                _cum = br["ret_pct"].cumsum().astype(float)
                if not mini_mode:
                    fig_b = go.Figure()
                    _colors = [_PLOTLY_CASH_UP if (i == 0 or _cum.iloc[i] >= _cum.iloc[i - 1]) else _PLOTLY_CASH_DOWN for i in range(len(_cum))]
                    fig_b.add_trace(
                        go.Scatter(
                            x=br["entry_date"],
                            y=_cum,
                            mode="lines+markers",
                            line=dict(color=_PLOTLY_CASH_UP, width=2.2),
                            marker=dict(size=6, color=_colors, line=dict(width=0)),
                            fill="tozeroy",
                            fillcolor="rgba(52, 211, 153, 0.12)",
                            name="Cumulative return",
                            hovertemplate=(
                                "<b>Covered-call sim</b><br>"
                                "Entry %{x|%Y-%m-%d}<br>"
                                "Cumulative <b>%{y:+.2f}%</b><extra></extra>"
                            ),
                        )
                    )
                    fig_b.update_layout(
                        template="plotly_dark",
                        paper_bgcolor=_PLOTLY_PAPER_BG,
                        plot_bgcolor=_PLOTLY_PLOT_BG,
                        font=_PLOTLY_FONT_MAIN,
                        height=300,
                        margin=dict(l=48, r=20, t=36, b=44),
                        hoverlabel=_chart_hoverlabel(),
                        title=dict(
                            text="Modeled cumulative return (% of premium stack)",
                            x=0,
                            xanchor="left",
                            font=dict(size=13, color="#e2e8f0", family="Inter, system-ui, sans-serif"),
                        ),
                        showlegend=False,
                    )
                    fig_b.update_xaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=False,
                        title_text="Trade entry",
                        tickformat="%Y-%m-%d",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    fig_b.update_yaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=True,
                        zerolinecolor="rgba(128,128,128,0.25)",
                        title_text="Cumulative return (%)",
                        ticksuffix="%",
                        tickformat=".1f",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    st.plotly_chart(fig_b, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                else:
                    st.caption(
                        f"Mini mode parks the cumulative return chart. Modeled cumulative return landed at **{_cum.iloc[-1]:.1f}%** across {len(br)} trades."
                    )
                wr = (br["profit"] > 0).mean() * 100
                _explain("\U0001f9e0 What does this backtest tell me?",
                    f"Over {len(br)} simulated trades, selling {bt_otm * 100:.0f}% out of the money covered calls every {bt_hold} days would have made roughly <strong>${tp:,.0f}</strong> in premium cash. "
                    f"The win rate was {wr:.0f}%. That means most of your options expired worthless and you kept all the cash. "
                    "Think of this as reviewing last year's sales numbers before planning this year's budget. It is your proof of concept.",
                    "bull" if wr > 60 else "neutral")
            else:
                st.info(
                    "Not enough daily history for this symbol and settings to run the covered-call sweep. "
                    "Try a longer period, a shorter hold window, or confirm the ticker has a full options tape."
                )

            # ══════════════════════════════════════════════════════════════════
            #  SECTION 7 — MARKET SCANNER (multi-ticker diamond & confluence scan)
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="scanner" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("🔎 Market Scanner", "One pass across the list for Diamonds, confluence stacks, and Gold Zone distance.",
                     tip_plain="Sort mentally by confluence, then hunt for a live Blue Diamond. If nothing clears the bar, flat is a position.")

            watchlist_tickers = [t.strip().upper() for t in scanner_watchlist.split(",") if t.strip()]
            if watchlist_tickers:
                if st.button("Scan Watchlist", key="run_scanner"):
                    scanner_results = []
                    n_scan = len(watchlist_tickers)
                    workers = min(8, max(1, n_scan))
                    scan_progress = st.progress(0)
                    done_ct = 0
                    scan_failed = []
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        future_map = {
                            _submit_with_script_ctx(pool, scan_single_ticker, tkr): tkr for tkr in watchlist_tickers
                        }
                        for fut in as_completed(future_map):
                            done_ct += 1
                            tkr = future_map[fut]
                            scan_progress.progress(done_ct / n_scan, text=f"Scanning {tkr}… ({done_ct}/{n_scan})")
                            try:
                                result = fut.result()
                                if result:
                                    scanner_results.append(result)
                            except Exception as e:
                                scan_failed.append((tkr, type(e).__name__))
                    scan_progress.empty()
                    if scan_failed:
                        failed_line = ", ".join(f"{_html_mod.escape(t)} ({err})" for t, err in scan_failed[:12])
                        more = f" (+{len(scan_failed) - 12} more)" if len(scan_failed) > 12 else ""
                        st.warning(f"Some symbols could not be scanned: {failed_line}{more}")

                    if scanner_results:
                        if scanner_sort_mode == "Highest confluence first":
                            scanner_results.sort(key=lambda x: x["cp_score"], reverse=True)
                        else:
                            order = {t: i for i, t in enumerate(watchlist_tickers)}
                            scanner_results.sort(key=lambda x: order.get(x["ticker"], 10_000))

                        for r in scanner_results:
                            pc = "#10b981" if r["chg_pct"] >= 0 else "#ef4444"
                            cpc = "#10b981" if r["cp_score"] >= 7 else ("#f59e0b" if r["cp_score"] >= 4 else "#ef4444")
                            qec = "#10b981" if r["qs"] > 70 else ("#f59e0b" if r["qs"] > 50 else "#ef4444")
                            gz_c = "#10b981" if r["dist_gz"] > 0 else "#ef4444"

                            cp_mini_bar = ""
                            for bi in range(r["cp_max"]):
                                filled = bi < r["cp_score"]
                                bc = "#10b981" if filled and r["cp_score"] >= 7 else ("#f59e0b" if filled and r["cp_score"] >= 4 else ("#ef4444" if filled else "#1e293b"))
                                cp_mini_bar += f"<div style='flex:1;height:6px;background:{bc};border-radius:3px;margin:0 1px'></div>"

                            st.markdown(f"""<div class='scanner-row'>
                                <div class='scanner-grid'>
                                    <div style='min-width:80px'>
                                        <div style='font-size:1.1rem;font-weight:700;color:#e2e8f0'>{r['ticker']}</div>
                                        <div class='mono' style='font-size:.9rem;color:{pc}'>${r['price']:.2f} ({r['chg_pct']:+.1f}%)</div>
                                    </div>
                                    <div style='text-align:center;min-width:70px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>QE Score</div>
                                        <div class='mono' style='color:{qec};font-weight:700'>{r['qs']:.0f}/100</div>
                                    </div>
                                    <div style='text-align:center;min-width:100px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Confluence</div>
                                        <div class='mono' style='color:{cpc};font-weight:700'>{r['cp_score']}/{r['cp_max']}</div>
                                        <div style='display:flex;gap:1px;margin-top:3px;width:80px'>{cp_mini_bar}</div>
                                    </div>
                                    <div style='text-align:center;min-width:100px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Diamond</div>
                                        <span class='diamond-badge {r["d_class"]}'>{r['d_status']}</span>
                                    </div>
                                    <div style='text-align:center;min-width:90px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Gold Zone</div>
                                        <div class='mono' style='font-size:.8rem;color:#fbbf24'>${r['gold_zone']:.2f}</div>
                                        <div style='font-size:.7rem;color:{gz_c}'>{r['dist_gz']:+.1f}%</div>
                                    </div>
                                    <div style='text-align:center;min-width:60px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Daily</div>
                                        <div style='font-size:.8rem;color:{"#10b981" if r["struct"]=="BULLISH" else ("#ef4444" if r["struct"]=="BEARISH" else "#f59e0b")}'>{r['struct']}</div>
                                    </div>
                                    <div style='flex:1;min-width:180px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Summary</div>
                                        <div class='scan-summary' style='font-size:.82rem;color:#e2e8f0;line-height:1.4'>{r['summary']}</div>
                                    </div>
                                </div>
                            </div>""", unsafe_allow_html=True)

                        _explain("🔎 How to use the Scanner",
                            "Look for tickers with <strong>7+ confluence points</strong> and an active <strong>Blue Diamond</strong>. "
                            "Those are your highest-probability setups across the entire watchlist. "
                            "Tickers near their Gold Zone with rising confluence are about to trigger. "
                            "Pink Diamonds mean take profits or avoid new entries on that ticker. "
                            "Sort mentally by confluence score. The higher the number, the stronger the setup.", "neutral")
                    else:
                        st.info("No scanner results. Check your ticker symbols.")
            else:
                st.info("Add tickers under **Edit watchlist symbols** (top of page) to use the scanner.")

            # ══════════════════════════════════════════════════════════════════
            #  SECTION 8 \u2014 NEWS & MACRO
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="news" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("News and Market Conditions", f"Headlines, macro, and earnings calendar for {ticker} while the tape is open.",
                     tip_plain="Stories explain gaps and IV pops. Always read news through price. When headline risk stacks near earnings, favor safer strikes and lighter size.")
            n_tab, m_tab, e_tab = st.tabs(["🗞️ Market News", "🌍 Macro & Yields", "📅 Upcoming Earnings"])
            with n_tab:
                st.markdown(f"#### {ticker} News")
                if news:
                    for item in news:
                        lnk = f"<a href='{item['link']}' target='_blank' style='color:#06b6d4'>Read</a>" if item["link"] else ""
                        st.markdown(f"<div class='ni'><strong style='color:#e2e8f0'>{item['title']}</strong><br><span style='color:#64748b;font-size:.8rem'>{item['pub']} {item['time']}</span>{' | ' + lnk if lnk else ''}</div>", unsafe_allow_html=True)
                else:
                    st.info("No news found.")
            with m_tab:
                st.markdown('<div id="macro" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                st.markdown("#### Macro Dashboard")
                for k, v in macro.items():
                    dc = "#10b981" if v["chg"] >= 0 else "#ef4444"
                    st.markdown(f"<div class='tc' style='padding:10px 14px;margin-bottom:6px'><div style='display:flex;justify-content:space-between'><span style='color:#94a3b8'>{k}</span><span class='mono' style='color:#e2e8f0'>{v['price']:.2f} <span style='color:{dc}'>{v['chg']:+.2f}%</span></span></div></div>", unsafe_allow_html=True)
            with e_tab:
                st.markdown('<div id="earnings" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                st.markdown(f"#### {_html_mod.escape(ticker)} earnings calendar")
                earn_cal_df, earn_highlight_idx = fetch_earnings_calendar_display(ticker)
                if earn_cal_df.empty:
                    _earn_empty = "No upcoming earnings data available for this ticker."
                    if earnings_parse_failed:
                        _earn_empty += " The feed returned a value we could not parse into a date."
                    st.info(_earn_empty)
                else:
                    st.caption("Rows are newest-first. The next on-calendar print (today or later) is highlighted.")
                    st.dataframe(
                        _style_earnings_next_highlight(earn_cal_df, earn_highlight_idx),
                        column_config=_earnings_calendar_column_config(),
                        use_container_width=True,
                        hide_index=True,
                    )

            with st.expander("Quick Reference Guide", expanded=False):
                st.markdown('<div id="guide" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                _section("Quick Reference Guide", "Plain language glossary for every signal on this desk. Keep it open during live markets.",
                         tip_plain="Reach for this when a label feels fuzzy. Clarity beats impulse every session.")
                edu = [
                    ("Blue Diamond Signal", "A Blue Diamond appears when confluence crosses up to 7+ out of 9, <strong>daily market structure is BULLISH</strong>, the <strong>weekly MACD/EMA bias is not BEARISH</strong>, and <strong>volume is at least 90% of the 20-day volume SMA</strong> (participation). An ATR blow-off guard still filters manic prints. Buy on Blue Diamonds."),
                    ("Pink Diamond Signal", "A Pink Diamond appears when bullish confluence collapses or momentum exhausts (RSI > 75 with weak confluence). Think of it as your dashboard warning lights all turning on. It means the easy money in this move is done. Take profits, sell aggressive covered calls, or tighten your stops. Sell on Pink Diamonds."),
                    ("Gold Zone", "The Gold Zone is a single dynamic price level calculated from Volume Profile POC, the 61.8% Fibonacci golden ratio, the 200-day simple moving average, and the nearest Gann Square of 9 level. When the stock is above the Gold Zone, bulls are in control. Below it, bears have the edge. Use the Gold Zone as your anchor for all strike selection."),
                    ("Confluence Points (0 to 9)", "The Confluence score checks nine independent bullish factors: Supertrend direction (2pts), Ichimoku cloud position (2pts), ADX trend strength (1pt), OBV accumulation (1pt), bullish divergences (1pt), position versus Gold Zone (1pt), and market structure (1pt). Scores of 7 or higher trigger Blue Diamonds. Scores below 4 signal caution."),
                    ("Covered Call", "You own 100 shares. You sell 1 call above the current price. You collect cash today. If the stock stays below that price, you keep the cash AND you keep your shares. Target: 1 to 3 percent per month in pure cash income."),
                    ("Cash Secured Put and The Wheel", "You sell a put and hold cash to buy shares if needed. If you get assigned, you sell Covered Calls on those new shares. When shares get called away, you sell puts again. This is the cash flow loop. Repeat forever."),
                    ("Credit Spreads", "You sell one option and collect cash. Then you buy a cheaper one further away to cap your worst case loss. Bull Put Spread means you are bullish. Bear Call Spread means you are bearish. Uses less money than Cash Secured Puts."),
                    ("RSI (Relative Strength Index)", "RSI is a 0 to 100 energy meter for the stock. Above 70 means buyers are exhausted. Great time to sell calls. Below 30 means sellers panicked. Great time to sell puts. The sweet spot for collecting cash is 40 to 60."),
                    ("MACD", "MACD shows who is winning: buyers or sellers. When the blue line crosses above the orange line, buyers are taking over. When it crosses below, sellers are winning. Think of it as comparing this month's sales to the quarterly average."),
                    ("ADX (Trend Strength)", "ADX is a 0 to 100 gauge for how strong the trend is. Above 25 means a strong trend is happening. Below 20 means the market is going nowhere. ADX does not tell you the direction. It only tells you the strength."),
                    ("Ichimoku Cloud", "The cloud is a safety net for the stock price. When the price floats above the cloud, the trend is bullish. When it falls into or below the cloud, the trend is weak. When all 5 parts agree, that is the strongest signal you can get."),
                    ("Supertrend", "The Supertrend is your price floor or ceiling. Green line below the price means bullish. Your shares are safe. Red line above the price means bearish. When it flips color, that is your signal to act."),
                    ("OBV (On Balance Volume)", "OBV tracks what the big money is doing. Rising OBV means institutions are quietly buying. Think of wholesale customers stocking up. Falling OBV means they are selling. If OBV disagrees with the price, a reversal may be coming."),
                    ("Fibonacci Retracement", "After a big move, stocks pull back to key levels before continuing: 38.2%, 50%, and 61.8%. The 61.8% level is the golden ratio. It is the most watched level on Wall Street. Set your put strikes near these levels for the safest entries."),
                    ("Volatility Skew", "When put options cost much more than call options, big institutions are buying crash insurance. That means premiums are fat for you to sell. But it also means the smart money is nervous. Collect the cash but stay aware."),
                    ("Expected Value", "EV is your long run profit per trade. Multiply win rate by gain, then subtract loss rate times loss. Positive EV means a real edge. Negative EV means pass."),
                    ("Gann Square of 9", "These are natural support and resistance levels calculated from mathematical spirals. Stocks tend to stop or bounce at these prices. Use them to pick smarter strike prices for your options."),
                    ("Quant Edge Score", "Your overall score from 0 to 100. It checks five things: Trend, Momentum, Volume, Volatility, and Structure. Above 70 means prime conditions to sell options. Below 40 means wait for a better setup."),
                    ("Market Scanner", "The Scanner checks your entire watchlist in seconds. It calculates Confluence Points, Diamond Status, Gold Zone distance, and Quant Edge for every ticker. Sort by confluence to find the strongest setups across all your stocks. Tickers with 7+ confluence and a Blue Diamond are your best opportunities."),
                ]
                for i in range(0, len(edu), 2):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i][1]}</div></div>", unsafe_allow_html=True)
                    with ec2:
                        if i + 1 < len(edu):
                            st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i + 1][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i + 1][1]}</div></div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
