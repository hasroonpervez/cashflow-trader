"""
Config persistence — watchlist, scanner, strategy, chart overlays.
Atomic JSON writes, st.secrets overlay for Streamlit Cloud.
"""
import streamlit as st
import json, os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

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
KELLY_DISPLAY_CAP_PCT = 5.0
EMA_EXTENSION_WARN_PCT = 10.0

def _streamlit_secrets_flat():
    """Scalar top-level keys from st.secrets (Streamlit Cloud). Skips nested tables."""
    try:
        if not hasattr(st, "secrets"):
            return {}
        # Avoid local warning banner when no secrets file exists.
        local_secret_paths = (
            Path.home() / ".streamlit" / "secrets.toml",
            CONFIG_PATH.parent / ".streamlit" / "secrets.toml",
        )
        if not any(p.exists() for p in local_secret_paths):
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


def load_config():
    """Local `config.json` merged over defaults; optional `st.secrets` overlay for Cloud."""
    merged = {**DEFAULT_CONFIG, **_streamlit_secrets_flat()}
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            merged = {**merged, **saved}
            for k in _LEGACY_CONFIG_KEYS:
                merged.pop(k, None)
    except Exception:
        pass
    return merged

def save_config(cfg):
    """Atomic write — writes to .tmp first, then renames. Zero corruption risk."""
    try:
        temp_path = CONFIG_PATH.with_suffix('.tmp')
        with open(temp_path, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(temp_path, CONFIG_PATH)
    except Exception:
        pass


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
    """Persist overlay toggles from session state (used inside chart fragment). Merges onto latest config on disk."""
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

