"""
Config persistence — watchlist, scanner, strategy, chart overlays.
Atomic JSON writes, st.secrets overlay for Streamlit Cloud.
"""
from __future__ import annotations

import streamlit as st
import json, os
from pathlib import Path
from datetime import datetime

_RADAR_UNIVERSE = "SOUN,BBAI,BIGC,BRZE,DT,GTLB,PATH,ESTC,CFLT,IOT,S,MNDY,DUOL,TOST,RXRX,ABCL,DNA,BEAM,NTLA,EDIT,VERV,ARQT,SANA,DNLI,NUVL,RIVN,LCID,QS,CHPT,ENVX,FREY,ENPH,SEDG,RUN,NOVA,SOFI,UPST,AFRM,HOOD,LMND,ROOT,RELY,DAVE,CIFR,KEEL,MARA,RIOT,CLSK,HUT,CORZ,IREN,COIN,RKLB,ASTS,LUNR,JOBY,ACHR,LILM,STRL,AIT,POWL,AGX,ECG,GVA,CUBI,SSB,RF,FSBC,HIMS,BYND,DLX,PAHC,IONQ,RGTI,QUBT,APLD,GSAT,OUST,LAZR,SMCI,ZETA,OPEN"

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG = {
    "watchlist": (
        "PLTR,HIMS,TSLA,SOFI,RIVN,CIFR,SPY,QQQ"
    ),
    "radar_universe": _RADAR_UNIVERSE,
    # Quantum computing watchlist — user picks + researched pure-plays.
    # IBM = large-cap anchor; the rest are speculative small/mid caps.
    "quantum_watchlist": "INFQ,IONQ,QBTS,RGTI,IBM,QUBT,ARQQ,LAES,BTQ",
    # Universe scanned by the 📡 Sentiment tab (defaults to quantum list +
    # a few high-buzz names so the heat board has contrast).
    "sentiment_universe": "INFQ,IONQ,QBTS,RGTI,IBM,QUBT,ARQQ,LAES,BTQ,PLTR,HIMS,SOFI,HOOD,TSLA",
    "scanner_sort_mode": "Custom watchlist order",
    "scanner_mode": "📈 Options Yield",
    "equity_capital": 10000,
    "intraday_confirmation": True,
    "auto_scan_interval": 300,
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
    "use_quant_models": True,
    # When true, `build_context` skips Yahoo headline + next-earnings fetch; news tab uses `@st.fragment`.
    "defer_headlines_earnings": True,
    # When true, skip options-chain hydration on the first session render to improve Cloud cold boot.
    "defer_options_first_pass": True,
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
    except Exception as _e:
        _ = _e
        return {}


# --- Audit finding #21 -------------------------------------------------------
# `st.secrets` scalars are merged into the in-memory config so Cloud deployments can
# override settings, but every persistence site is a read-modify-write of that same
# dict — so a token in secrets.toml used to land verbatim in the git-tracked
# config.json on the next watchlist edit. Secrets are usable in memory and are
# NEVER written to disk. Two rules, both applied in `save_config`:
#   1. any key whose *name* looks like a credential, and
#   2. any key supplied by `st.secrets` that is not a known DEFAULT_CONFIG setting.
_SECRET_NAME_MARKERS = (
    "token", "secret", "password", "passwd", "apikey", "api_key",
    "webhook", "credential", "private_key", "access_key", "auth",
)


def _looks_like_secret(key) -> bool:
    """True when a config key name reads as a credential rather than a UI preference."""
    k = str(key).lower()
    return k.endswith("_key") or any(m in k for m in _SECRET_NAME_MARKERS)


def secret_only_keys(cfg) -> set:
    """Keys in ``cfg`` that must never be persisted to ``config.json``."""
    keys = {k for k in (cfg or {}) if _looks_like_secret(k)}
    keys |= {k for k in _streamlit_secrets_flat() if k not in DEFAULT_CONFIG}
    return keys


def strip_secrets(cfg) -> dict:
    """Copy of ``cfg`` with every secret-only key removed (pure; used before any write)."""
    drop = secret_only_keys(cfg)
    return {k: v for k, v in (cfg or {}).items() if k not in drop}


def load_config():
    """Defaults + `st.secrets` scalars + `config.json`; then `watchlist` from Secrets wins if set (Cloud-friendly)."""
    secrets_flat = _streamlit_secrets_flat()
    merged = {**DEFAULT_CONFIG, **secrets_flat}
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            merged = {**merged, **saved}
            for k in _LEGACY_CONFIG_KEYS:
                merged.pop(k, None)
    except Exception as _e:
        _ = _e
        pass
    wl_secret = secrets_flat.get("watchlist")
    if wl_secret is not None and str(wl_secret).strip():
        merged["watchlist"] = str(wl_secret).strip()
    merged["use_quant_models"] = bool(merged.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))
    return merged

def save_config(cfg) -> bool:
    """Atomic write — writes to .tmp first, then renames. Returns False if the host cannot write (e.g. read-only Cloud)."""
    try:
        cfg = {**DEFAULT_CONFIG, **(cfg or {})}
        cfg["use_quant_models"] = bool(cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))
        # Finding #21: config.json is git-tracked. Anything that arrived from st.secrets
        # (or that merely *looks* like a credential) is dropped before it can touch disk.
        cfg = strip_secrets(cfg)
        temp_path = CONFIG_PATH.with_suffix('.tmp')
        with open(temp_path, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(temp_path, CONFIG_PATH)
        return True
    except Exception as _e:
        _ = _e
        return False


JOURNAL_PATH = CONFIG_PATH.parent / "trade_journal.json"


# Human-readable notices about files we could not parse. The UI drains this so a silent
# data-loss event becomes a visible warning.
_QUARANTINE_NOTICES: list[str] = []


def drain_quarantine_notices() -> list[str]:
    """Pop any 'your file was corrupt' messages for display, clearing the queue."""
    out = list(_QUARANTINE_NOTICES)
    _QUARANTINE_NOTICES.clear()
    return out


def _quarantine_corrupt(path: Path) -> bool:
    """Rename an unparseable JSON file aside so the next save cannot destroy it.

    Returns True when the original path is now free (safe to write a fresh file).
    Renaming *preserves* the bytes — we never delete a file we failed to read.
    """
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = path.with_name(f"{path.name}.corrupt-{stamp}")
        os.replace(path, dest)
        _QUARANTINE_NOTICES.append(
            f"{path.name} could not be read and was preserved as {dest.name}. "
            f"A new empty {path.name} was started — your old data is still on disk."
        )
        return True
    except Exception:
        _QUARANTINE_NOTICES.append(
            f"{path.name} could not be read and could not be moved aside. "
            f"Writes to it are disabled to avoid destroying it."
        )
        return False


def _load_json_list(path: Path) -> tuple[list, bool]:
    """``(entries, writable)`` — ``writable=False`` means DO NOT overwrite ``path``.

    A corrupt file used to be swallowed into ``[]``, and the next append then atomically
    replaced the whole history with a single entry. Now it is quarantined, and if that
    quarantine fails we refuse the write entirely.
    """
    if not path.exists():
        return [], True
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        return [], _quarantine_corrupt(path)
    if isinstance(data, list):
        return data, True
    # Parsed, but not the shape we persist — still a corruption event.
    return [], _quarantine_corrupt(path)


def load_journal() -> list:
    """Load persistent trade journal from disk (corrupt files are quarantined, not lost)."""
    return _load_json_list(JOURNAL_PATH)[0]


def save_journal(entries: list) -> bool:
    """Atomic write of trade journal. Returns False on read-only filesystem."""
    try:
        temp = JOURNAL_PATH.with_suffix(".tmp")
        with open(temp, "w") as f:
            json.dump(entries, f, indent=2, default=str)
        os.replace(temp, JOURNAL_PATH)
        return True
    except Exception as _e:
        _ = _e
        return False


def journal_add_entry(entry: dict) -> bool:
    """Append one trade and persist. Refuses to write over an unreadable journal."""
    entries, writable = _load_json_list(JOURNAL_PATH)
    if not writable:
        return False
    entries.append(entry)
    return save_journal(entries)


# --- Audit finding #3 --------------------------------------------------------
# Realized P&L used to be computed as *expiry intrinsic* against a widget labelled
# "Close price ($)". A user who buys a strike-30 CSP back for $1.20 and types 1.20
# was recorded at -$2,530 when the truth is +$230. The journal now records WHICH
# convention produced the number, and the buy-back convention is the default because
# that is what a "close price" on an option row realistically is.
CLOSE_BASIS_BUYBACK = "buyback_per_share"       # option price per share paid to close
CLOSE_BASIS_EXPIRY = "underlying_at_expiry"     # underlying spot, settled to intrinsic
CLOSE_BASES = (CLOSE_BASIS_BUYBACK, CLOSE_BASIS_EXPIRY)


def realized_pnl_for_close(entry: dict, close_price: float, basis: str = CLOSE_BASIS_BUYBACK):
    """Realized P&L in dollars for closing one short-premium journal row.

    Pure — no Streamlit, no disk. Returns ``None`` (not a fake ``0.0``) when the row
    carries no usable credit, so the caller can say "unknown" instead of "break-even".

    ``basis``:
      ``CLOSE_BASIS_BUYBACK`` — ``close_price`` is the option's price **per share**
        paid to buy the contract back. P&L = (credit/share - debit/share) x 100 x contracts.
        Correct at any point in the life of the trade, extrinsic included.
      ``CLOSE_BASIS_EXPIRY`` — ``close_price`` is the **underlying** at expiry; the short
        settles to intrinsic. Only correct when the contract is actually held to expiry.
    """
    if basis not in CLOSE_BASES:
        raise ValueError(f"unknown close basis {basis!r}; expected one of {CLOSE_BASES}")
    try:
        prem_100 = float(entry.get("premium_100"))
        px = float(close_price)
    except (TypeError, ValueError):
        return None
    try:
        contracts = int(entry.get("contracts", 1) or 1)
    except (TypeError, ValueError):
        contracts = 1
    if basis == CLOSE_BASIS_BUYBACK:
        return round((prem_100 / 100.0 - px) * 100.0 * contracts, 2)
    try:
        strike = float(entry.get("strike", 0) or 0)
    except (TypeError, ValueError):
        return None
    opt_type = str(entry.get("option_type", "put")).lower()
    intrinsic = (max(0.0, px - strike) if opt_type == "call" else max(0.0, strike - px)) * 100.0 * contracts
    return round(prem_100 * contracts - intrinsic, 2)


def journal_close_trade(
    index: int,
    close_price: float,
    close_date: str = None,
    basis: str = CLOSE_BASIS_BUYBACK,
) -> bool:
    """Close a trade and record realized P&L under an explicit ``basis`` (finding #3).

    ``close_price`` is the **option buy-back price per share** by default. Pass
    ``basis=CLOSE_BASIS_EXPIRY`` to settle against the underlying at expiry instead.
    """
    entries, writable = _load_json_list(JOURNAL_PATH)
    if not writable:
        return False
    if not (0 <= index < len(entries)):
        return False
    if basis not in CLOSE_BASES:
        return False
    e = entries[index]
    e["status"] = "closed"
    e["actual_close_price"] = close_price
    e["close_basis"] = basis
    e["close_date"] = close_date or datetime.now().strftime("%Y-%m-%d")
    pnl = realized_pnl_for_close(e, close_price, basis)
    if pnl is None:
        # No usable credit on the row — do not invent a zero. Leave the key absent so
        # readers fall back to "—" rather than reporting a break-even trade.
        e.pop("realized_pnl", None)
        e["realized_pnl_unavailable"] = "missing or unparseable premium_100"
    else:
        e.pop("realized_pnl_unavailable", None)
        e["realized_pnl"] = pnl
    return save_journal(entries)


def journal_clear() -> bool:
    return save_journal([])


RADAR_HITS_PATH = CONFIG_PATH.parent / "radar_hits.json"


def load_radar_hits() -> list:
    """Load persisted radar hits log (corrupt files are quarantined, not lost)."""
    return _load_json_list(RADAR_HITS_PATH)[0]


def save_radar_hits(entries: list) -> bool:
    """Atomic write of radar hits. Keeps last 200 entries."""
    try:
        entries = entries[-200:]
        temp = RADAR_HITS_PATH.with_suffix(".tmp")
        with open(temp, "w") as f:
            json.dump(entries, f, indent=2, default=str)
        os.replace(temp, RADAR_HITS_PATH)
        return True
    except Exception:
        return False


def radar_add_hit(hit: dict) -> bool:
    """Append one radar hit and persist. Refuses to write over an unreadable log."""
    entries, writable = _load_json_list(RADAR_HITS_PATH)
    if not writable:
        return False
    entries.append(hit)
    return save_radar_hits(entries)


class ConfigTransaction:
    """Batch config mutations; write once at flush instead of many saves per load."""

    def __init__(self):
        self._base = load_config()
        self._mutations: dict = {}

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if self._base.get(k) != v:
                self._mutations[k] = v

    def flush(self) -> bool:
        if not self._mutations:
            return True
        # Finding #20: this used to write `{**self._base, **self._mutations}`, where
        # `_base` is a snapshot taken once at app start. Any key another writer changed
        # on disk since (scanner_mode, the overlay on_change callback) was reverted by a
        # flush that never intended to touch it. Re-read disk and layer only OUR
        # mutations on top, so a flush writes exactly what it means to change.
        merged = {**load_config(), **self._mutations}
        ok = save_config(merged)
        if ok:
            self._base = merged
            self._mutations = {}
        return ok

    @property
    def current(self) -> dict:
        return {**self._base, **self._mutations}

    @property
    def dirty(self) -> bool:
        return bool(self._mutations)

    @property
    def pending_keys(self):
        return frozenset(self._mutations.keys())


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
    """Load Strategy / Chart overlay / quant / scanner UI from config when session has no value yet.

    Must run **before** any widget that uses these ``st.session_state`` keys (Mission Control, chart fragment).
    """
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
    if "sb_use_quant" not in st.session_state:
        st.session_state["sb_use_quant"] = bool(cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))
    if "sb_scan_radio" not in st.session_state:
        sm = cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])
        st.session_state["sb_scan_radio"] = (
            "Custom order" if sm == "Custom watchlist order" else "Confluence first"
        )
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

