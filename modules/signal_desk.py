"""
Desk-level consensus signal, trader's note, and bento-style copy from DashContext + OHLCV.

Blends quant edge, confluence, sentiment, structure, volume Z, and rolling **VWAP distance Z**
(daily multi-bar VWAP from typical price; Z vs prior deviation history — not intraday session VWAP).
"""
from __future__ import annotations

import html as html_mod
from typing import Any, Optional

import numpy as np
import pandas as pd
import streamlit as st

from .ta import TA

# Rolling VWAP + Z prior window (sessions); keep in sync with ``vwap_distance_stats`` defaults.
_VWAP_ROLL_BARS = 20
_VWAP_Z_PRIOR_BARS = 20

# BBW percentile at or below this = tight "coil" for ribbon + conviction (bottom ~5%).
_COIL_BBW_PCTILE_MAX = 0.05

_HURST_WINDOW = 100


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_hurst_rs(symbol: str, closes_tuple: tuple) -> Optional[float]:
    """1h memo of R/S Hurst on the last 100 closes (tuple hash = bar path)."""
    if not closes_tuple or len(closes_tuple) < 60:
        return None
    arr = np.asarray(closes_tuple, dtype=float)
    if arr.size < _HURST_WINDOW:
        return None
    return TA.calculate_hurst_exponent(arr, window=min(_HURST_WINDOW, arr.size))


def desk_conviction_multiplier(
    *,
    coil_active: bool,
    absorption: bool,
    vwap_urgency: bool,
    whale_sweep: bool = False,
) -> tuple[float, str]:
    """
    Position-size conviction tier: 1.0 baseline, 1.25 COIL and/or ICEBERG, 1.5 SWEEP, 2.0 all three.
    ``whale_sweep`` counts like VWAP urgency for the SWEEP tier.
    """
    sweep_gate = bool(vwap_urgency or whale_sweep)
    if coil_active and absorption and sweep_gate:
        return 2.0, "Perfect desk: COIL · ICEBERG · SWEEP"
    if sweep_gate:
        return 1.5, "SWEEP — VWAP urgency and/or whale sweep (volume + ask-side proxy)"
    if coil_active or absorption:
        return 1.25, "COIL and/or ICEBERG (squeeze ≤5% BBW and/or absorption)"
    return 1.0, "Baseline (no elite microstructure gates)"


def institutional_heatmap_ribbon_html(c: dict) -> str:
    """
    Institutional strip: COIL (purple), ICEBERG (cyan), SWEEP (gold), LEADER (emerald).
    Segments light only when their gate is active; inactive slots stay low-contrast slate.
    """
    coil = bool(c.get("coil_active"))
    if "coil_active" not in c:
        bbwp = c.get("bbw_pctile")
        coil = bool(bbwp is not None and float(bbwp) <= _COIL_BBW_PCTILE_MAX)
    ice = bool(c.get("absorption"))
    if "ribbon_sweep_active" in c:
        sweep = bool(c.get("ribbon_sweep_active"))
    else:
        sweep = bool(c.get("vwap_urgency"))
    leader = bool(c.get("market_leader"))

    def seg(label: str, active: bool, active_bg: str, active_border: str, active_text: str) -> str:
        lab = html_mod.escape(label)
        if active:
            return f"""<div style="flex:1;min-width:72px;text-align:center;padding:10px 8px;border-radius:10px;
border:1px solid {active_border};background:{active_bg};box-shadow:0 0 18px {active_border}55;
font-size:0.62rem;font-weight:800;letter-spacing:0.14em;color:{active_text}">{lab}</div>"""
        return f"""<div style="flex:1;min-width:72px;text-align:center;padding:10px 8px;border-radius:10px;
border:1px solid rgba(71,85,105,0.45);background:rgba(30,41,59,0.65);
font-size:0.62rem;font-weight:700;letter-spacing:0.12em;color:#64748b">{lab}</div>"""

    s1 = seg(
        "COIL",
        coil,
        "linear-gradient(145deg,rgba(109,40,217,0.95),rgba(168,85,247,0.88))",
        "rgba(168,85,247,0.85)",
        "#f5f3ff",
    )
    s2 = seg(
        "ICEBERG",
        ice,
        "linear-gradient(145deg,rgba(6,182,212,0.9),rgba(34,211,238,0.82))",
        "rgba(34,211,238,0.75)",
        "#ecfeff",
    )
    s3 = seg(
        "SWEEP",
        sweep,
        "linear-gradient(165deg,rgba(234,179,8,0.95),rgba(202,138,4,0.88),rgba(250,204,21,0.55))",
        "rgba(234,179,8,0.9)",
        "#1c1917",
    )
    s4 = seg(
        "LEADER",
        leader,
        "linear-gradient(145deg,rgba(5,150,105,0.95),rgba(16,185,129,0.88),rgba(52,211,153,0.65))",
        "rgba(52,211,153,0.85)",
        "#ecfdf5",
    )
    mult, why = desk_conviction_multiplier(
        coil_active=coil,
        absorption=ice,
        vwap_urgency=bool(c.get("vwap_urgency")),
        whale_sweep=bool(c.get("whale_sweep")),
    )
    sub = html_mod.escape(f"Conviction ×{mult:.2f} — {why}")
    regime = str(c.get("hurst_regime_label") or "").strip()
    mode = str(c.get("trading_mode_recommendation") or "").strip()
    reg_line = ""
    if regime or mode:
        reg_line = (
            f"<div style=\"margin-top:6px;font-size:0.72rem;color:#a5b4fc;font-weight:700;letter-spacing:0.08em\">"
            f"REGIME · {html_mod.escape(regime or '—')}"
            f"{(' · ' + html_mod.escape(mode)) if mode else ''}</div>"
        )
    dom_line = ""
    if c.get("institutional_dominance"):
        dom_line = (
            "<div style=\"margin-top:6px;font-size:0.72rem;color:#fde047;font-weight:800;letter-spacing:0.1em\">"
            "TOTAL INSTITUTIONAL DOMINANCE · SWEEP + ICEBERG</div>"
        )
    lead_line = ""
    if leader:
        rs_d = c.get("rs_spy_ratio")
        vz_d = c.get("volume_z")
        rs_s = f"{float(rs_d):.2f}" if rs_d is not None and np.isfinite(float(rs_d)) else "—"
        vz_s = f"{float(vz_d):+.1f}σ" if vz_d is not None and np.isfinite(float(vz_d)) else "—"
        lead_line = (
            f"<div style=\"margin-top:6px;font-size:0.72rem;color:#6ee7b7;font-weight:700;letter-spacing:0.06em\">"
            f"MARKET LEADER · RS {html_mod.escape(rs_s)} &gt; 1 vs SPY · Whale volume {html_mod.escape(vz_s)}</div>"
        )
    return f"""<div style="margin:0 0 14px 0;padding:0">
<div style="font-size:0.65rem;color:#94a3b8;font-weight:800;letter-spacing:0.16em;margin:0 0 8px 0">
INSTITUTIONAL HEATMAP</div>
<div style="display:flex;gap:8px;align-items:stretch;flex-wrap:wrap">{s1}{s2}{s3}{s4}</div>
<div style="margin-top:8px;font-size:0.72rem;color:#94a3b8;line-height:1.45">{sub}</div>{reg_line}{dom_line}{lead_line}
</div>"""


def vwap_distance_stats(
    df: pd.DataFrame,
    *,
    vwap_window: int = _VWAP_ROLL_BARS,
    prior_sessions: int = _VWAP_Z_PRIOR_BARS,
    min_prior: int = 10,
) -> dict:
    """
    Rolling multi-session VWAP (typical price × volume), then Z-score of how far the last
    close sits vs that VWAP relative to recent history of the same deviation.

    Uses relative deviation (Close − VWAP) / VWAP so scale is comparable across tickers.
    μ and σ are taken from the prior ``prior_sessions`` bars (last bar excluded), matching
    the volume-Z pattern in ``last_bar_volume_zscore``.

    Not intraday session VWAP — daily OHLCV proxy only.
    """
    out: dict = {"vwap_z": None, "rolling_vwap": None, "deviation_pct": None}
    need = vwap_window + prior_sessions + 2
    if df is None or getattr(df, "empty", True) or len(df) < need:
        return out
    for col in ("High", "Low", "Close", "Volume"):
        if col not in df.columns:
            return out
    h = pd.to_numeric(df["High"], errors="coerce")
    lo = pd.to_numeric(df["Low"], errors="coerce")
    c = pd.to_numeric(df["Close"], errors="coerce")
    v = pd.to_numeric(df["Volume"], errors="coerce")
    if c.isna().all() or v.isna().all():
        return out
    tp = (h + lo + c) / 3.0
    pv = tp * v
    v_sum = v.rolling(vwap_window, min_periods=vwap_window).sum()
    vwap = pv.rolling(vwap_window, min_periods=vwap_window).sum() / v_sum.replace(0, np.nan)
    rel = (c - vwap) / vwap.replace(0, np.nan)
    rel = rel.replace([np.inf, -np.inf], np.nan)
    if rel.isna().all() or len(rel) < prior_sessions + 2:
        return out
    prior = rel.iloc[-(prior_sessions + 1) : -1]
    prior = prior.dropna()
    if len(prior) < min_prior:
        return out
    mu, sig = float(prior.mean()), float(prior.std(ddof=0))
    if not np.isfinite(mu) or not np.isfinite(sig) or sig < 1e-12:
        return out
    last_rel = float(rel.iloc[-1])
    last_vwap = float(vwap.iloc[-1])
    last_c = float(c.iloc[-1])
    if not np.isfinite(last_rel) or not np.isfinite(last_vwap) or last_vwap <= 0 or not np.isfinite(last_c):
        return out
    out["rolling_vwap"] = last_vwap
    out["deviation_pct"] = (last_c / last_vwap - 1.0) * 100.0
    out["vwap_z"] = (last_rel - mu) / sig
    return out


def last_bar_volume_zscore(df: pd.DataFrame) -> Optional[float]:
    """Z-score of last bar volume vs prior 20 sessions (excludes last bar from mean/std)."""
    if df is None or getattr(df, "empty", True) or "Volume" not in df.columns or len(df) < 25:
        return None
    v = pd.to_numeric(df["Volume"], errors="coerce")
    if v.isna().all():
        return None
    prior = v.iloc[-21:-1]
    if len(prior) < 10:
        return None
    mu, sig = float(prior.mean()), float(prior.std())
    if not np.isfinite(mu) or not np.isfinite(sig) or sig < 1e-9:
        return None
    last = float(v.iloc[-1])
    if not np.isfinite(last):
        return None
    return (last - mu) / sig


def whale_session_x_for_chart(df: pd.DataFrame, z_threshold: float = 4.0):
    """Return last bar index for a Plotly vline when volume Z >= threshold; else None."""
    z = last_bar_volume_zscore(df)
    if z is None or z < z_threshold:
        return None
    try:
        return df.index[-1]
    except Exception:
        return None


def daily_aggressor_proxy(df: pd.DataFrame, *, tail_bars: int = 3) -> dict:
    """
    Daily-bar stand-in for order-flow imbalance (not true OFI): where the close prints inside the
    range, weighted by recent volume intensity. Composite in roughly [-1, 1].
    """
    out: dict = {"ofi_proxy": None, "label": "—", "detail": {}}
    if df is None or getattr(df, "empty", True) or len(df) < 5:
        return out
    needed = ("High", "Low", "Close", "Volume")
    if any(c not in df.columns for c in needed):
        return out
    n = max(1, min(int(tail_bars), len(df)))
    pressures: list[float] = []
    for i in range(-n, 0):
        sl = df.iloc[i]
        try:
            h = float(sl["High"])
            lo = float(sl["Low"])
            c = float(sl["Close"])
        except (TypeError, ValueError):
            continue
        if not all(np.isfinite([h, lo, c])) or h <= lo:
            continue
        p = (2.0 * c - h - lo) / (h - lo)
        pressures.append(float(np.clip(p, -1.0, 1.0)))
    if not pressures:
        return out
    last_p = pressures[-1]
    blend = float(np.mean(pressures))
    raw = float(np.clip(0.65 * last_p + 0.35 * blend, -1.0, 1.0))
    vz = last_bar_volume_zscore(df)
    w = 1.0
    if vz is not None and np.isfinite(float(vz)):
        w = float(np.tanh(max(0.0, float(vz)) / 3.0))
    ofi = float(raw * (0.35 + 0.65 * w))
    out["ofi_proxy"] = ofi
    out["detail"] = {"last_pressure": last_p, "tail_mean": blend, "volume_weight": w}
    if ofi > 0.35:
        out["label"] = "net buy pressure (proxy)"
    elif ofi < -0.35:
        out["label"] = "net sell pressure (proxy)"
    else:
        out["label"] = "balanced close-in-range (proxy)"
    return out


def detect_whale_sweep(
    df: pd.DataFrame,
    *,
    vwap_detail: dict,
    volume_z: Optional[float],
    ofi_detail: dict,
    absorption_active: bool,
) -> dict:
    """
    Aggressive urgency proxy: last close **above** rolling VWAP, **volume Z > 4**, and
    **daily aggressor proxy > 0.7** (buy-side pressure in range). If **absorption** is also
    active, flags **TOTAL INSTITUTIONAL DOMINANCE** (sweep + iceberg).
    """
    out: dict = {"active": False, "dominance": False}
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
        return out
    rv = vwap_detail.get("rolling_vwap") if isinstance(vwap_detail, dict) else None
    try:
        last_c = float(pd.to_numeric(df["Close"], errors="coerce").iloc[-1])
    except Exception:
        return out
    rvf = float(rv) if rv is not None and np.isfinite(float(rv)) else None
    price_ok = rvf is not None and rvf > 0 and last_c > rvf
    vz_ok = volume_z is not None and np.isfinite(float(volume_z)) and float(volume_z) > 4.0
    op = ofi_detail.get("ofi_proxy") if isinstance(ofi_detail, dict) else None
    agg_ok = op is not None and np.isfinite(float(op)) and float(op) > 0.7
    out["active"] = bool(price_ok and vz_ok and agg_ok)
    out["dominance"] = bool(out["active"] and absorption_active)
    return out


def ffd_stationarity_proxy(df: pd.DataFrame, *, d: float = 0.4, tail: int = 60) -> bool:
    """True when FFD innovations are materially calmer than raw log returns (memory shaved)."""
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns or len(df) < 80:
        return False
    try:
        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(close) < 80:
            return False
        fd = TA.apply_ffd(close, d=d)
        dfd = fd.diff().dropna().tail(tail)
        lr = np.log(close).replace([np.inf, -np.inf], np.nan).diff().dropna().tail(tail)
        if len(dfd) < 25 or len(lr) < 25:
            return False
        sf = float(dfd.std(ddof=1))
        sr = float(lr.std(ddof=1))
        if not np.isfinite(sf) or not np.isfinite(sr) or sr < 1e-12:
            return False
        return bool(sf < sr * 0.92)
    except Exception:
        return False


def blend_unified_probability(
    qs: float,
    conf_pct: float,
    rs_spy_ratio: Optional[float],
) -> float:
    """Blend Quant Edge, confluence %, and RS vs SPY into a single 0–100 dial."""
    qs = float(max(0.0, min(100.0, qs)))
    conf_pct = float(max(0.0, min(100.0, conf_pct)))
    rs_adj = 50.0
    if rs_spy_ratio is not None and np.isfinite(float(rs_spy_ratio)):
        x = float(rs_spy_ratio)
        if x > 1.0:
            rs_adj = float(np.clip(50.0 + (x - 1.0) * 80.0, 0.0, 100.0))
        else:
            rs_adj = float(np.clip(50.0 - (1.0 - x) * 80.0, 0.0, 100.0))
    u = 0.42 * qs + 0.33 * conf_pct + 0.25 * rs_adj
    return float(max(0.0, min(100.0, u)))


_BENTO_ACCENTS: dict[str, tuple[str, str, str]] = {
    "neutral": ("rgba(148,163,184,0.22)", "rgba(30,41,59,0.55)", "#94a3b8"),
    "bullish": ("rgba(52,211,153,0.42)", "rgba(6,78,59,0.28)", "#6ee7b7"),
    "bearish": ("rgba(248,113,113,0.42)", "rgba(127,29,29,0.22)", "#fca5a5"),
    "warning": ("rgba(251,191,36,0.48)", "rgba(120,53,15,0.22)", "#fcd34d"),
    "elite": ("rgba(168,85,247,0.5)", "rgba(76,29,149,0.28)", "#ddd6fe"),
    "sweep_gold": (
        "rgba(234,179,8,0.72)",
        "rgba(120,53,15,0.42)",
        "#fde047",
    ),
}


def bento_accents_from_consensus(c: dict) -> dict:
    """Traffic-light borders for the three bento cells (setup / momentum / exit)."""
    bbwp = c.get("bbw_pctile")
    coil = bool(c.get("coil_active"))
    setup = "elite" if coil else ("warning" if bbwp is not None and float(bbwp) >= 0.85 else "neutral")
    rsf = c.get("rs_spy_ratio")
    mom = "neutral"
    if c.get("whale_sweep"):
        mom = "sweep_gold"
    elif c.get("market_leader"):
        mom = "elite"
    elif c.get("vwap_urgency"):
        mom = "warning"
    elif rsf is not None and np.isfinite(float(rsf)):
        if float(rsf) > 1.02:
            mom = "bullish"
        elif float(rsf) < 0.98:
            mom = "bearish"
    vz = c.get("volume_z")
    if mom == "neutral" and vz is not None and np.isfinite(float(vz)) and float(vz) > 3.0:
        mom = "warning"
    band = str(c.get("band") or "")
    ex = "bearish" if band == "high_risk" else ("bullish" if band == "conviction" else "neutral")
    return {"setup": setup, "momentum": mom, "exit": ex}


def unified_probability_dial_html(
    ticker: str,
    unified: float,
    *,
    qs: float,
    conf_pct: float,
    rs_line: str,
) -> str:
    """Compact Mission Control dial: blended QS + confluence + RS."""
    tk = html_mod.escape(str(ticker).upper())
    u = float(max(0.0, min(100.0, unified)))
    pct = int(round(u))
    sub1 = html_mod.escape(f"QE {float(qs):.0f}/100 · Confluence {float(conf_pct):.0f}%")
    sub2 = html_mod.escape(rs_line)
    col = "#34d399" if u >= 62 else ("#fbbf24" if u >= 40 else "#f87171")
    return f"""<div style="margin:0 0 12px 0;padding:12px 16px;border-radius:14px;border:1px solid rgba(148,163,184,0.25);
background:linear-gradient(135deg,rgba(15,23,42,0.96),rgba(30,41,59,0.9));box-shadow:0 4px 22px rgba(0,0,0,0.28)">
<div style="font-size:0.65rem;color:#94a3b8;font-weight:800;letter-spacing:0.14em;margin-bottom:6px">UNIFIED PROBABILITY · {tk}</div>
<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
<div style="font-size:2rem;font-weight:800;color:{col};font-family:JetBrains Mono,monospace;line-height:1">{pct}</div>
<div style="flex:1;min-width:180px">
<div style="height:8px;border-radius:5px;background:rgba(51,65,85,0.9);overflow:hidden">
<div style="height:100%;width:{pct}%;background:{col};border-radius:5px;opacity:0.92"></div></div>
<div style="margin-top:8px;font-size:0.76rem;color:#94a3b8;line-height:1.45">{sub1}<br/>{sub2}</div>
</div></div>
<div style="margin-top:8px;font-size:0.7rem;color:#64748b">Weighted blend (42% QE · 33% confluence · 25% RS vs SPY tilt). Illustrative, not a forecast.</div>
</div>"""


def institutional_absorption(
    df: pd.DataFrame,
    volume_z: Optional[float] = None,
    *,
    z_min: float = 4.0,
    atr_mult_flat: float = 0.45,
    min_flat_pct: float = 0.35,
    max_flat_pct: float = 1.0,
    no_atr_fallback_pct: float = 0.55,
) -> dict:
    """
    Whale-trap / absorption: extreme volume Z vs prior sessions, but the last daily close
    barely moved vs an ATR-scaled typical daily range (OHLCV proxy for liquidity taken without marking).

    Returns dict with active flag, diagnostics, and volume_z used.
    """
    out: dict = {
        "active": False,
        "volume_z": None,
        "last_return_pct": None,
        "flat_threshold_pct": None,
    }
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns or len(df) < 25:
        return out
    close = pd.to_numeric(df["Close"], errors="coerce")
    if close.isna().all() or close.iloc[-2] <= 0 or not np.isfinite(float(close.iloc[-1])):
        return out
    vz = volume_z if volume_z is not None else last_bar_volume_zscore(df)
    out["volume_z"] = vz
    if vz is None or vz < z_min:
        return out
    c0, c1 = float(close.iloc[-2]), float(close.iloc[-1])
    r_pct = (c1 / c0 - 1.0) * 100.0
    if not np.isfinite(r_pct):
        return out
    out["last_return_pct"] = r_pct
    thr = no_atr_fallback_pct
    try:
        atr_last = float(TA.atr(df).iloc[-1]) if len(df) >= 15 else 0.0
    except Exception:
        atr_last = 0.0
    if atr_last > 0 and c1 > 0:
        atr_pct = 100.0 * atr_last / c1
        if np.isfinite(atr_pct) and atr_pct > 0:
            thr = float(np.clip(max(min_flat_pct, atr_mult_flat * atr_pct), min_flat_pct, max_flat_pct))
    out["flat_threshold_pct"] = thr
    out["active"] = bool(abs(r_pct) <= thr)
    return out


def _bbw_last_pctile(df: pd.DataFrame, lookback: int = 60) -> Optional[float]:
    """Approximate BBW tightness: percentile rank of last (BB upper-lower)/mid in trailing window."""
    if df is None or len(df) < lookback + 25 or "Close" not in df.columns:
        return None
    try:
        u, mid, lo = TA.bollinger(df["Close"])
        mid = pd.to_numeric(mid, errors="coerce")
        bw = (pd.to_numeric(u, errors="coerce") - pd.to_numeric(lo, errors="coerce")) / mid.replace(0, np.nan)
        bw = bw.dropna()
        if len(bw) < lookback:
            return None
        tail = bw.iloc[-lookback:]
        last = float(bw.iloc[-1])
        if not np.isfinite(last):
            return None
        return float((tail <= last).mean())
    except Exception:
        return None


def _struct_score(label: str) -> float:
    u = (label or "").upper()
    if "BULL" in u:
        return 72.0
    if "BEAR" in u:
        return 28.0
    if "RANG" in u or "MIX" in u:
        return 50.0
    return 48.0


def _wk_score(label: str) -> float:
    u = (label or "").upper()
    if "BULL" in u:
        return 70.0
    if "BEAR" in u:
        return 32.0
    if "MIX" in u:
        return 52.0
    return 50.0


def compute_desk_consensus(
    ctx: Any,
    df: pd.DataFrame,
    *,
    rs_spy_ratio: Optional[float] = None,
    fundamental_sieve: Optional[dict] = None,
) -> dict:
    """Return score 0–100, traffic-light band, UI hints, and bento strings.

    ``rs_spy_ratio``: optional **~90-session** growth-factor ratio vs SPY from the global close matrix
    (> 1 ⇒ outperformance). Combined with **volume Z > 4** → **market leader** ribbon.

    ``fundamental_sieve``: optional output of ``data.evaluate_fundamental_sieve`` for narrative / GOD-tier logic.
    """
    qs = float(getattr(ctx, "qs", 0) or 0)
    qs = max(0.0, min(100.0, qs))
    cp_max = max(1, int(getattr(ctx, "cp_max", 9) or 9))
    cp_score = int(getattr(ctx, "cp_score", 0) or 0)
    conf_pct = max(0.0, min(100.0, 100.0 * cp_score / cp_max))
    fg = float(getattr(ctx, "fg", 50) or 50)
    fg = max(0.0, min(100.0, fg))
    struct_s = _struct_score(str(getattr(ctx, "struct", "") or ""))
    wk_s = _wk_score(str(getattr(ctx, "wk_label", "") or ""))
    macd_bull = bool(getattr(ctx, "macd_bull", False))
    obv_up = bool(getattr(ctx, "obv_up", True))
    rsi_v = float(getattr(ctx, "rsi_v", 50) or 50)
    vz = last_bar_volume_zscore(df)
    rs_f: Optional[float] = None
    if rs_spy_ratio is not None and np.isfinite(float(rs_spy_ratio)):
        rs_f = float(rs_spy_ratio)
    rs_outperf = rs_f is not None and rs_f > 1.0
    vz_whale = vz is not None and float(vz) > 4.0
    market_leader = bool(rs_outperf and vz_whale)
    unified = blend_unified_probability(qs, conf_pct, rs_f)
    absorb = institutional_absorption(df, volume_z=vz)
    ofi_st = daily_aggressor_proxy(df)
    vwap_st = vwap_distance_stats(df)
    vwap_z = vwap_st.get("vwap_z")
    bbwp = _bbw_last_pctile(df)
    coil_active = bool(bbwp is not None and float(bbwp) <= _COIL_BBW_PCTILE_MAX)

    sym_u = str(getattr(ctx, "ticker", "") or "").upper().strip()
    hurst_h: Optional[float] = None
    if sym_u and df is not None and "Close" in df.columns and len(df) >= _HURST_WINDOW:
        tail = pd.to_numeric(df["Close"], errors="coerce").dropna().tail(_HURST_WINDOW)
        if len(tail) >= _HURST_WINDOW:
            tup = tuple(round(float(x), 6) for x in tail.tolist())
            hurst_h = _cached_hurst_rs(sym_u, tup)

    hurst_regime = "neutral"
    hurst_regime_label = "Neutral / random-walk"
    trading_mode = "Balanced"
    tape = 58.0 if macd_bull else 44.0
    tape = tape + 6.0 if obv_up else -4.0
    tape = max(0.0, min(100.0, tape))
    vol_w_rsi = 0.05
    vol_w_flow = 1.0 - vol_w_rsi
    if hurst_h is not None:
        if hurst_h < 0.45:
            hurst_regime = "mean_reverting"
            hurst_regime_label = "Mean reverting"
            trading_mode = "Options Yield"
            tape = float(np.clip(40.0 + min(abs(rsi_v - 50.0), 40.0) * 1.35, 0.0, 100.0))
            if bbwp is not None:
                tape = float(min(100.0, tape + max(0.0, 0.22 - float(bbwp)) * 95.0))
            vol_w_rsi = 0.09
            vol_w_flow = 0.91
        elif hurst_h > 0.55:
            hurst_regime = "trending"
            hurst_regime_label = "Trending"
            trading_mode = "Equity Radar"
            tape = 58.0 if macd_bull else 44.0
            tape = tape + 6.0 if obv_up else -4.0
            if rs_outperf:
                tape = float(min(100.0, tape + 12.0))
            tape = max(0.0, min(100.0, tape))
            vol_w_rsi = 0.03
            vol_w_flow = 0.97

    rsi_bb_blend = float(np.clip(50.0 + (rsi_v - 50.0) * 1.1, 0.0, 100.0))
    if bbwp is not None:
        rsi_bb_blend = float(0.55 * rsi_bb_blend + 0.45 * float(np.clip(100.0 * (1.0 - bbwp), 0.0, 100.0)))

    if vz is None:
        vol_s = 50.0
    else:
        vol_s = float(np.clip(50.0 + float(vz) * 9.0, 0.0, 100.0))
    if vwap_z is not None and np.isfinite(float(vwap_z)):
        vz_f = float(vwap_z)
        vwap_s = float(np.clip(50.0 + vz_f * 8.0, 0.0, 100.0))
        vol_s = float(vol_w_flow * (0.5 * vol_s + 0.5 * vwap_s) + vol_w_rsi * rsi_bb_blend)
    else:
        vol_s = float(vol_w_flow * vol_s + vol_w_rsi * rsi_bb_blend)

    # Weights sum to 1.0
    score = (
        0.28 * qs
        + 0.20 * conf_pct
        + 0.16 * fg
        + 0.14 * struct_s
        + 0.10 * wk_s
        + 0.07 * tape
        + 0.05 * vol_s
    )
    if absorb.get("active"):
        score = float(min(100.0, score + 2.5))
    score = float(max(0.0, min(100.0, score)))
    if score < 40.0:
        band = "high_risk"
        label = "Elevated risk / weak alignment"
        color = "#f87171"
        ring_bg = "rgba(248,113,113,0.15)"
    elif score < 62.0:
        band = "neutral"
        label = "Neutral — wait for catalyst"
        color = "#fbbf24"
        ring_bg = "rgba(251,191,36,0.12)"
    else:
        band = "conviction"
        label = "Stronger alignment"
        color = "#34d399"
        ring_bg = "rgba(52,211,153,0.14)"
    setup_hint = "Volatility: "
    if bbwp is not None:
        if bbwp <= _COIL_BBW_PCTILE_MAX:
            setup_hint += f"Bollinger bandwidth in the **extreme lower** range (≤**{_COIL_BBW_PCTILE_MAX:.0%}** tile — **COIL** / spring risk)."
        elif bbwp <= 0.15:
            setup_hint += "Bollinger bandwidth in the **lower** range (squeeze / coil risk)."
        elif bbwp >= 0.85:
            setup_hint += "Bollinger bandwidth **expanded** (trend or event vol)."
        else:
            setup_hint += "Bollinger bandwidth **mid-range**."
    else:
        setup_hint += "Not enough history for a squeeze read."
    if hurst_h is not None and np.isfinite(float(hurst_h)):
        setup_hint += (
            f" **Hurst** (100-bar R/S, 1h cache) **{float(hurst_h):.2f}** → **{hurst_regime_label}**; "
            f"desk suggests **{trading_mode}**."
        )

    sweep_d = detect_whale_sweep(
        df,
        vwap_detail=vwap_st,
        volume_z=vz,
        ofi_detail=ofi_st,
        absorption_active=bool(absorb.get("active")),
    )
    whale_sweep = bool(sweep_d.get("active"))
    institutional_dominance = bool(sweep_d.get("dominance"))
    ffd_ok = ffd_stationarity_proxy(df)
    fund = fundamental_sieve if isinstance(fundamental_sieve, dict) else None
    fundamental_fcf_strong = False
    if fund:
        fundamental_fcf_strong = bool(
            bool(fund.get("ten_x_candidate"))
            or float(fund.get("fcf_yield") or 0) > 0.10
        )
    god_tier_unicorn = bool(
        ffd_ok
        and hurst_h is not None
        and float(hurst_h) > 0.55
        and fundamental_fcf_strong
        and whale_sweep
    )

    mom_parts = [
        f"RSI ~{getattr(ctx, 'rsi_v', 0):.0f}",
        "MACD bull" if macd_bull else "MACD bearish cross risk",
        "OBV rising" if obv_up else "OBV fading",
    ]
    _opx = ofi_st.get("ofi_proxy")
    if _opx is not None and np.isfinite(float(_opx)) and abs(float(_opx)) >= 0.2:
        mom_parts.append(
            f"**Aggressor proxy** (daily OFI stand-in): **{float(_opx):+.2f}** — {ofi_st.get('label', '')}"
        )
    if vz is not None:
        mom_parts.append(f"Volume Z today **{vz:+.1f}**")
    if rs_f is not None:
        _rs_tag = "outperforming SPY" if rs_f > 1.0 else "lagging SPY"
        mom_parts.append(f"RS vs SPY (~90d ratio) **{rs_f:.2f}** ({_rs_tag})")
    if vwap_z is not None and np.isfinite(float(vwap_z)):
        dp = vwap_st.get("deviation_pct")
        if dp is not None and np.isfinite(float(dp)):
            mom_parts.append(
                f"VWAP distance Z **{float(vwap_z):+.1f}** (close **{dp:+.2f}%** vs **{_VWAP_ROLL_BARS}-bar** VWAP)"
            )
        else:
            mom_parts.append(f"VWAP distance Z **{float(vwap_z):+.1f}**")
    if absorb.get("active"):
        rp = absorb.get("last_return_pct")
        thr = absorb.get("flat_threshold_pct")
        if rp is not None and thr is not None:
            mom_parts.append(
                f"**Institutional absorption** (whale trap): huge print, flat close (**{rp:+.2f}%** vs ≤**{thr:.2f}%** “quiet” band)"
            )
        else:
            mom_parts.append("**Institutional absorption** (whale trap): extreme volume vs muted close")
    if hurst_h is not None and np.isfinite(float(hurst_h)):
        mom_parts.append(
            f"Hurst **{float(hurst_h):.2f}** ({hurst_regime_label}) — flow blend tilts **RSI/Bollinger** vs **MACD/RS** by regime."
        )
    if whale_sweep:
        mom_parts.append(
            "**Whale sweep:** spot above rolling VWAP, volume Z >4, aggressor proxy >0.7 — urgency / ask-side pressure (proxy)."
        )
    if institutional_dominance:
        mom_parts.append("**TOTAL INSTITUTIONAL DOMINANCE:** sweep plus **Iceberg absorption** simultaneously.")
    momentum_hint = " · ".join(mom_parts)
    gz = float(getattr(ctx, "gold_zone_price", 0) or 0)
    px = float(getattr(ctx, "price", 0) or 0)
    exit_hint = ""
    if gz > 0 and px > 0:
        dist = (px / gz - 1.0) * 100.0
        exit_hint = f"Gold Zone ~${gz:,.2f} (**{dist:+.1f}%** vs spot). Use your plan for stops (e.g. ATR multiple below entry)."
    else:
        exit_hint = "Gold Zone not fused — use structure and your own stop rule."
    try:
        atr_last = float(TA.atr(df).iloc[-1]) if df is not None and len(df) >= 15 else 0.0
    except Exception:
        atr_last = 0.0
    vwap_urgency = bool(
        vz is not None
        and vwap_z is not None
        and float(vz) >= 2.0
        and float(vwap_z) >= 2.0
    )
    ribbon_sweep_active = bool(whale_sweep or vwap_urgency)
    conv_mult, conv_lbl = desk_conviction_multiplier(
        coil_active=coil_active,
        absorption=bool(absorb.get("active")),
        vwap_urgency=vwap_urgency,
        whale_sweep=whale_sweep,
    )
    return {
        "score": score,
        "band": band,
        "label": label,
        "color": color,
        "ring_bg": ring_bg,
        "volume_z": vz,
        "bbw_pctile": bbwp,
        "coil_active": coil_active,
        "atr_last": atr_last,
        "setup_hint": setup_hint,
        "momentum_hint": momentum_hint,
        "exit_hint": exit_hint,
        "absorption": bool(absorb.get("active")),
        "absorption_detail": absorb,
        "vwap_z": vwap_st.get("vwap_z"),
        "vwap_detail": vwap_st,
        "vwap_urgency": vwap_urgency,
        "conviction_multiplier": float(conv_mult),
        "conviction_label": conv_lbl,
        "rs_spy_ratio": rs_f,
        "market_leader": market_leader,
        "unified_probability": unified,
        "ofi_detail": ofi_st,
        "hurst_exponent": hurst_h,
        "hurst_regime": hurst_regime,
        "hurst_regime_label": hurst_regime_label,
        "trading_mode_recommendation": trading_mode,
        "whale_sweep": whale_sweep,
        "institutional_dominance": institutional_dominance,
        "ribbon_sweep_active": ribbon_sweep_active,
        "ffd_stationary_ok": ffd_ok,
        "fundamental_sieve": fund,
        "fundamental_fcf_strong": fundamental_fcf_strong,
        "god_tier_unicorn": god_tier_unicorn,
    }


def _absorption_banner_html(c: dict) -> str:
    if not c.get("absorption"):
        return ""
    d = c.get("absorption_detail") or {}
    vz = d.get("volume_z")
    rp = d.get("last_return_pct")
    thr = d.get("flat_threshold_pct")
    vz_s = f"{vz:.1f}σ" if vz is not None and np.isfinite(float(vz)) else "high"
    if rp is not None and thr is not None and np.isfinite(rp) and np.isfinite(thr):
        sub = html_mod.escape(f"Last session {rp:+.2f}% vs ≤{thr:.2f}% quiet band (volume {vz_s} vs 20d norm).")
    else:
        sub = html_mod.escape("Extreme volume vs muted daily close — often absorption / liquidity reload.")
    return f"""<div style="margin-top:10px;padding:10px 12px;border-radius:10px;border:1px solid rgba(34,211,238,0.35);
background:rgba(6,182,212,0.12);font-size:0.78rem;color:#a5f3fc;line-height:1.5">
<strong style="color:#22d3ee;letter-spacing:0.06em">INSTITUTIONAL ABSORPTION</strong> · {sub}
<span style="display:block;margin-top:4px;color:#64748b;font-size:0.72rem">Microstructure proxy on daily bars — not order-book imbalance.</span></div>"""


def consensus_banner_html(ticker: str, c: dict) -> str:
    """Full-width card: ring progress + score + label."""
    tk = html_mod.escape(str(ticker).upper())
    sc = float(c["score"])
    pct = int(round(sc))
    lab = html_mod.escape(str(c["label"]))
    col = c["color"]
    bg = c["ring_bg"]
    # Conic ring: filled portion = score%
    ring = (
        f"conic-gradient({col} 0deg {sc * 3.6}deg, rgba(51,65,85,0.9) {sc * 3.6}deg 360deg)"
    )
    return f"""<div class="cf-consensus-strip" style="display:flex;align-items:center;gap:18px;flex-wrap:wrap;
padding:14px 18px;margin:0 0 14px 0;border-radius:14px;border:1px solid rgba(148,163,184,0.22);
background:linear-gradient(135deg,rgba(15,23,42,0.95),rgba(30,41,59,0.88));box-shadow:0 6px 28px rgba(0,0,0,0.35)">
<div style="width:72px;height:72px;border-radius:50%;background:{ring};padding:5px;flex-shrink:0">
<div style="width:100%;height:100%;border-radius:50%;background:rgba(15,23,42,0.96);display:flex;align-items:center;justify-content:center;flex-direction:column">
<span style="font-size:1.35rem;font-weight:800;color:{col};font-family:JetBrains Mono,monospace">{pct}</span>
<span style="font-size:0.58rem;color:#94a3b8;letter-spacing:0.08em">SCORE</span>
</div></div>
<div style="flex:1;min-width:200px">
<div style="font-size:0.68rem;color:#94a3b8;font-weight:700;letter-spacing:0.14em;margin-bottom:4px">CONSENSUS · {tk}</div>
<div style="font-size:1.02rem;color:#e2e8f0;font-weight:600;margin-bottom:6px">{lab}</div>
<div style="height:6px;border-radius:4px;background:rgba(51,65,85,0.85);overflow:hidden">
<div style="height:100%;width:{pct}%;background:{col};border-radius:4px;opacity:0.92"></div></div>
<div style="margin-top:8px;font-size:0.75rem;color:#64748b;line-height:1.45">
Blend: Quant Edge, confluence, tape sentiment, structure, weekly bias, volume anomaly.</div>
{_absorption_banner_html(c)}
</div></div>"""


def consensus_compact_html(ticker: str, c: dict) -> str:
    """Single line for Turbo / mini mode."""
    tk = html_mod.escape(str(ticker).upper())
    pct = int(round(float(c["score"])))
    col = c["color"]
    lab = html_mod.escape(str(c["label"]))
    _abs = ""
    if c.get("absorption"):
        _abs = " · <span style=\"color:#22d3ee;font-weight:700\">ABSORPTION</span>"
    _sw = ""
    if c.get("whale_sweep"):
        _sw = " · <span style=\"color:#facc15;font-weight:800\">SWEEP</span>"
    if c.get("institutional_dominance"):
        _sw += " · <span style=\"color:#fde047;font-weight:800\">DOMINANCE</span>"
    _rg = ""
    hr = str(c.get("hurst_regime_label") or "").strip()
    if hr:
        _rg = f" · <span style=\"color:#a5b4fc;font-weight:700\">{html_mod.escape(hr[:24])}</span>"
    return f"""<div style="margin:0 0 10px 0;padding:8px 12px;border-radius:10px;border:1px solid rgba(148,163,184,0.2);
background:rgba(15,23,42,0.9);font-size:0.82rem;color:#cbd5e1">
<strong style="color:{col};font-family:JetBrains Mono,monospace">{pct}</strong>/100 consensus · {tk} — <span style="color:#e2e8f0">{lab}</span>{_abs}{_sw}{_rg}</div>"""


def _recent_resistance_high(df: pd.DataFrame, bars: int = 20) -> Optional[float]:
    """Tactical resistance proxy: max High over last ``bars`` sessions (OHLCV desk)."""
    if df is None or getattr(df, "empty", True) or "High" not in df.columns:
        return None
    if len(df) < 2:
        return None
    tail = df["High"].tail(min(bars, len(df)))
    tail = pd.to_numeric(tail, errors="coerce").dropna()
    if tail.empty:
        return None
    v = float(tail.max())
    return v if np.isfinite(v) else None


def traders_note_markdown(
    ticker: str,
    ctx: Any,
    df: pd.DataFrame,
    c: dict,
    *,
    alpha_realization_pct: Optional[float] = None,
    turbo_desk: bool = False,
) -> str:
    """Plain-language paragraph (markdown); deterministic, no LLM.

    ``turbo_desk``: when True, return a **single** tight paragraph (Mission Control Turbo / mini).
    """
    tk = str(ticker).upper()
    px = float(getattr(ctx, "price", 0) or 0)
    chg = float(getattr(ctx, "chg_pct", 0) or 0)
    qs = float(getattr(ctx, "qs", 0) or 0)
    st = str(getattr(ctx, "struct", "") or "UNKNOWN")
    wk = str(getattr(ctx, "wk_label", "") or "UNKNOWN")
    vz = c.get("volume_z")
    bbwp = c.get("bbw_pctile")
    atr = float(c.get("atr_last") or 0)
    stop_px = px - 1.5 * atr if px > 0 and atr > 0 else None
    squeeze = bbwp is not None and bbwp <= 0.15
    perfect_storm = bool(c.get("coil_active") and c.get("absorption") and c.get("market_leader"))
    parts = [
        f"**Trader's note — {tk}** is trading near **${px:,.2f}** ({chg:+.2f}% vs prior close). "
        f"Daily structure reads **{st}**; weekly bias **{wk}**. Quant Edge sits near **{qs:.0f}/100**."
    ]
    if turbo_desk:
        return " ".join(parts)
    if alpha_realization_pct is not None and np.isfinite(float(alpha_realization_pct)):
        ar = float(alpha_realization_pct)
        if ar >= 105.0:
            parts.append(
                f"**Alpha realization** (~**{ar:.0f}%** of **qs_at_entry** on tracked Sentinel legs): Quant Edge is **strengthening** vs when you booked the trade."
            )
        elif ar <= 92.0:
            parts.append(
                f"**Alpha realization** (~**{ar:.0f}%**): the live edge looks **soft vs entry** — signal may be **rotting**; revisit size and thesis."
            )
        else:
            parts.append(
                f"**Alpha realization** ~**{ar:.0f}%** vs **qs_at_entry** — roughly **in line** with the score at track time."
            )
    if c.get("god_tier_unicorn"):
        hh = c.get("hurst_exponent")
        hs = f"{float(hh):.2f}" if hh is not None and np.isfinite(float(hh)) else "—"
        parts.append(
            "**GOD TIER UNICORN — 10x sieve:** FFD shows **stationary memory** vs raw returns, Hurst is **trending**, **FCF / fundamental** gate is **on**, and a **whale sweep** is live — "
            f"all four institutional filters aligned (Hurst **{hs}**). **Rare tape**; still not a forecast — manage **gap** and **headline** risk."
        )
    elif c.get("fundamental_fcf_strong") and isinstance(c.get("fundamental_sieve"), dict):
        fs = c.get("fundamental_sieve") or {}
        fy = fs.get("fcf_yield_pct")
        fy_s = f"{float(fy):.2f}%" if fy is not None and np.isfinite(float(fy)) else "strong"
        parts.append(
            f"**Fundamental sieve (cash / EV):** FCF yield proxy **{fy_s}** with **efficiency** tilt — you are not only trading prints; see scanner **fundamental_sieve** for detail."
        )
    if perfect_storm:
        rsv = c.get("rs_spy_ratio")
        vzv = c.get("volume_z")
        ad = c.get("absorption_detail") or {}
        rp = ad.get("last_return_pct")
        thr = ad.get("flat_threshold_pct")
        rs_s = f"{float(rsv):.2f}" if rsv is not None and np.isfinite(float(rsv)) else "—"
        vz_s = f"{float(vzv):+.1f}" if vzv is not None and np.isfinite(float(vzv)) else "—"
        coil_s = f"≤{_COIL_BBW_PCTILE_MAX:.0%} BBW tile (COIL)"
        abs_s = (
            f"quiet close **{float(rp):+.2f}%** vs ≤**{float(thr):.2f}%** band"
            if rp is not None and thr is not None and np.isfinite(rp) and np.isfinite(thr)
            else "muted close vs volume (Iceberg)"
        )
        rh = _recent_resistance_high(df, 20)
        res_s = f"**${rh:,.2f}** (20d high)" if rh is not None and np.isfinite(rh) else "**the nearest structural high**"
        parts.append(
            f"**Unicorn alert — high-conviction stack:** **{tk}** is a **market leader** "
            f"(**RS ≈ {rs_s}** vs SPY on the ~90d batch; **volume Z {vz_s}** whale) **and** shows **institutional absorption** "
            f"(Iceberg: {abs_s}). **COIL** is live (**{coil_s}**) — often **compressed energy** while size trades "
            "without marking price. **If price clears** "
            f"{res_s}, the tape is set up for a **sharp resolution**; it is **not** a promise of direction — "
            "confirm with your levels and **size** using the desk **conviction** tier."
        )
    elif squeeze:
        parts.append("Price is in a **tight Bollinger squeeze** (potential energy building).")
    elif bbwp is not None and bbwp >= 0.85:
        parts.append("Bollinger bandwidth is **wide** (realized range expanded).")
    if not perfect_storm and c.get("market_leader"):
        rsv = c.get("rs_spy_ratio")
        vzv = c.get("volume_z")
        if rsv is not None and vzv is not None and np.isfinite(float(rsv)) and np.isfinite(float(vzv)):
            parts.append(
                f"**Market leader:** **RS vs SPY (~90d batch ratio) {float(rsv):.2f}** (>1 = outperformance) **and** "
                f"**volume Z {float(vzv):+.1f}** (whale, >4σ vs 20d) — leadership on the global snapshot benchmark."
            )
        else:
            parts.append(
                "**Market leader:** RS outperformance vs SPY on the batch benchmark plus whale volume — see momentum row."
            )
    if not perfect_storm and c.get("absorption"):
        ad = c.get("absorption_detail") or {}
        rp = ad.get("last_return_pct")
        thr = ad.get("flat_threshold_pct")
        vz_a = ad.get("volume_z")
        if rp is not None and thr is not None and vz_a is not None:
            parts.append(
                f"**Whale trap / absorption:** volume ~**{vz_a:.1f}σ** vs the prior 20 sessions, but the session closed only "
                f"**{rp:+.2f}%** vs a **≤{thr:.2f}%** “quiet-close” band (ATR-scaled). "
                "Large size may be changing hands without yet marking price — watch the next sessions for resolution."
            )
        else:
            parts.append(
                "**Whale trap / absorption:** extreme volume with a muted daily close — watch for a volatility release."
            )
    elif not perfect_storm and vz is not None:
        if vz >= 4.0:
            parts.append(
                f"Today's volume is roughly **{vz:.1f}σ** above its recent norm — watch for **institutional footprint**."
            )
        elif vz >= 2.0:
            parts.append(f"Volume is elevated (**{vz:.1f}σ** vs recent sessions).")
        else:
            parts.append(f"Volume Z is **{vz:+.1f}** (quiet to normal).")
    wz_note = c.get("vwap_z")
    wd = c.get("vwap_detail") or {}
    if wz_note is not None and np.isfinite(float(wz_note)) and abs(float(wz_note)) >= 2.0:
        dp_n = wd.get("deviation_pct")
        if dp_n is not None and np.isfinite(float(dp_n)):
            parts.append(
                f"Versus a **{_VWAP_ROLL_BARS}-bar** rolling VWAP (daily OHLCV proxy), spot is **{float(dp_n):+.2f}%** "
                f"from VWAP with deviation **Z ≈ {float(wz_note):+.1f}** vs its own recent history — "
                "pair with volume for an **urgency** read (not intraday session VWAP)."
            )
        else:
            parts.append(
                f"**VWAP stretch:** deviation Z ≈ **{float(wz_note):+.1f}** vs recent **{_VWAP_ROLL_BARS}-bar** VWAP — "
                "context for institutional footprint."
            )
    if stop_px and stop_px > 0:
        parts.append(
            f"An **ATR-style risk anchor** (~1.5× 14d ATR below spot) sits near **${stop_px:,.2f}** — "
            "not a broker order; size your own risk."
        )
    else:
        parts.append("ATR is thin or missing — define risk with your own stop rule.")
    return " ".join(parts)


def bento_box_html(title: str, question: str, body_md: str, *, accent: str = "neutral") -> str:
    """One bento cell; body_md is short HTML-safe text (we escape). ``accent`` tints border/title from desk state."""
    border, bg, title_c = _BENTO_ACCENTS.get(accent, _BENTO_ACCENTS["neutral"])
    sh = "box-shadow:0 4px 18px rgba(0,0,0,0.2);"
    if accent == "sweep_gold":
        sh = "box-shadow:0 0 28px rgba(250,204,21,0.48),0 6px 24px rgba(0,0,0,0.35);"
    t = html_mod.escape(title)
    q = html_mod.escape(question)
    b = html_mod.escape(body_md)
    b = b.replace("\n", "<br/>")
    return f"""<div style="border-radius:12px;border:1px solid {border};
background:{bg};padding:12px 14px;min-height:120px;{sh}">
<div style="font-size:0.65rem;color:{title_c};font-weight:800;letter-spacing:0.12em;margin-bottom:4px">{t}</div>
<div style="font-size:0.95rem;color:#f1f5f9;font-weight:600;margin-bottom:8px;line-height:1.35">{q}</div>
<div style="font-size:0.8rem;color:#cbd5e1;line-height:1.5">{b}</div>
</div>"""


def suggested_shares_atr_risk(account: float, risk_pct: float, price: float, atr: float, atr_mult: float = 1.5) -> Optional[int]:
    """Shares so cash risk ≈ risk_pct% of account if stop = atr_mult × ATR below entry (illustrative)."""
    if account <= 0 or risk_pct <= 0 or price <= 0 or atr <= 0 or atr_mult <= 0:
        return None
    risk_dollars = account * (risk_pct / 100.0)
    stop_dist = atr * atr_mult
    if stop_dist <= 0:
        return None
    sh = int(risk_dollars // stop_dist)
    return max(0, sh)
