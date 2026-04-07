"""
Desk-level consensus signal, trader's note, and bento-style copy from DashContext + OHLCV.

Single 0–100 score blends quant edge, confluence, sentiment, structure, and volume z-score.
"""
from __future__ import annotations

import html as html_mod
from typing import Any, Optional

import numpy as np
import pandas as pd

from .ta import TA


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
    if vz is None:
        vol_s = 50.0
    else:
        vol_s = float(np.clip(50.0 + vz * 9.0, 0.0, 100.0))
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
    }


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
</div></div>"""


def consensus_compact_html(ticker: str, c: dict) -> str:
    """Single line for Turbo / mini mode."""
    tk = html_mod.escape(str(ticker).upper())
    pct = int(round(float(c["score"])))
    col = c["color"]
    lab = html_mod.escape(str(c["label"]))
    return f"""<div style="margin:0 0 10px 0;padding:8px 12px;border-radius:10px;border:1px solid rgba(148,163,184,0.2);
background:rgba(15,23,42,0.9);font-size:0.82rem;color:#cbd5e1">
<strong style="color:{col};font-family:JetBrains Mono,monospace">{pct}</strong>/100 consensus · {tk} — <span style="color:#e2e8f0">{lab}</span></div>"""


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
    if vz is not None:
        if vz >= 4.0:
            parts.append(
                f"Today's volume is roughly **{vz:.1f}σ** above its recent norm — watch for **institutional footprint**."
            )
        elif vz >= 2.0:
            parts.append(f"Volume is elevated (**{vz:.1f}σ** vs recent sessions).")
        else:
            parts.append(f"Volume Z is **{vz:+.1f}** (quiet to normal).")
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
