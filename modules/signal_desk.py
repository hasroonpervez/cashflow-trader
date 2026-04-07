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

from .ta import TA

# Rolling VWAP + Z prior window (sessions); keep in sync with ``vwap_distance_stats`` defaults.
_VWAP_ROLL_BARS = 20
_VWAP_Z_PRIOR_BARS = 20


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


def compute_desk_consensus(ctx: Any, df: pd.DataFrame) -> dict:
    """Return score 0–100, traffic-light band, UI hints, and bento strings."""
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
    tape = 58.0 if macd_bull else 44.0
    tape = tape + 6.0 if obv_up else -4.0
    tape = max(0.0, min(100.0, tape))
    vz = last_bar_volume_zscore(df)
    absorb = institutional_absorption(df, volume_z=vz)
    vwap_st = vwap_distance_stats(df)
    vwap_z = vwap_st.get("vwap_z")
    if vz is None:
        vol_s = 50.0
    else:
        vol_s = float(np.clip(50.0 + vz * 9.0, 0.0, 100.0))
    if vwap_z is not None and np.isfinite(float(vwap_z)):
        vz_f = float(vwap_z)
        vwap_s = float(np.clip(50.0 + vz_f * 8.0, 0.0, 100.0))
        vol_s = float(0.5 * vol_s + 0.5 * vwap_s)
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
    bbwp = _bbw_last_pctile(df)
    setup_hint = "Volatility: "
    if bbwp is not None:
        if bbwp <= 0.15:
            setup_hint += "Bollinger bandwidth in the **lower** range (squeeze / coil risk)."
        elif bbwp >= 0.85:
            setup_hint += "Bollinger bandwidth **expanded** (trend or event vol)."
        else:
            setup_hint += "Bollinger bandwidth **mid-range**."
    else:
        setup_hint += "Not enough history for a squeeze read."
    mom_parts = [
        f"RSI ~{getattr(ctx, 'rsi_v', 0):.0f}",
        "MACD bull" if macd_bull else "MACD bearish cross risk",
        "OBV rising" if obv_up else "OBV fading",
    ]
    if vz is not None:
        mom_parts.append(f"Volume Z today **{vz:+.1f}**")
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
    return {
        "score": score,
        "band": band,
        "label": label,
        "color": color,
        "ring_bg": ring_bg,
        "volume_z": vz,
        "bbw_pctile": bbwp,
        "atr_last": atr_last,
        "setup_hint": setup_hint,
        "momentum_hint": momentum_hint,
        "exit_hint": exit_hint,
        "absorption": bool(absorb.get("active")),
        "absorption_detail": absorb,
        "vwap_z": vwap_st.get("vwap_z"),
        "vwap_detail": vwap_st,
        "vwap_urgency": bool(
            vz is not None
            and vwap_z is not None
            and float(vz) >= 2.0
            and float(vwap_z) >= 2.0
        ),
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
    return f"""<div style="margin:0 0 10px 0;padding:8px 12px;border-radius:10px;border:1px solid rgba(148,163,184,0.2);
background:rgba(15,23,42,0.9);font-size:0.82rem;color:#cbd5e1">
<strong style="color:{col};font-family:JetBrains Mono,monospace">{pct}</strong>/100 consensus · {tk} — <span style="color:#e2e8f0">{lab}</span>{_abs}</div>"""


def traders_note_markdown(ticker: str, ctx: Any, df: pd.DataFrame, c: dict) -> str:
    """Plain-language paragraph (markdown); deterministic, no LLM."""
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
    parts = [
        f"**Trader's note — {tk}** is trading near **${px:,.2f}** ({chg:+.2f}% vs prior close). "
        f"Daily structure reads **{st}**; weekly bias **{wk}**. Quant Edge sits near **{qs:.0f}/100**."
    ]
    if squeeze:
        parts.append("Price is in a **tight Bollinger squeeze** (potential energy building).")
    elif bbwp is not None and bbwp >= 0.85:
        parts.append("Bollinger bandwidth is **wide** (realized range expanded).")
    if c.get("absorption"):
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
    elif vz is not None:
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


def bento_box_html(title: str, question: str, body_md: str) -> str:
    """One bento cell; body_md is short HTML-safe text (we escape)."""
    t = html_mod.escape(title)
    q = html_mod.escape(question)
    b = html_mod.escape(body_md)
    b = b.replace("\n", "<br/>")
    return f"""<div style="border-radius:12px;border:1px solid rgba(148,163,184,0.2);
background:rgba(30,41,59,0.55);padding:12px 14px;min-height:120px;box-shadow:0 4px 18px rgba(0,0,0,0.2)">
<div style="font-size:0.65rem;color:#94a3b8;font-weight:800;letter-spacing:0.12em;margin-bottom:4px">{t}</div>
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
