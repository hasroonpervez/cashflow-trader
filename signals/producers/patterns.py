"""Pure pattern features for Sig_* producers. Paper annotate only. No sizing."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

_OHLC = ("open", "high", "low", "close")


def _cols(df: pd.DataFrame) -> dict[str, str]:
    lower = {str(c).lower(): c for c in df.columns}
    out = {}
    for name in _OHLC:
        if name in lower:
            out[name] = lower[name]
        elif name.title() in df.columns:
            out[name] = name.title()
    return out


def bar_patterns(df: pd.DataFrame, *, lookback: int = 5) -> dict[str, Any]:
    """OHLC pattern tags. Empty dict if the frame is too short. Never raises."""
    if df is None or getattr(df, "empty", True):
        return {}
    cols = _cols(df)
    if not {"high", "low", "close"}.issubset(cols):
        return {}
    high = df[cols["high"]].astype(float)
    low = df[cols["low"]].astype(float)
    close = df[cols["close"]].astype(float)
    n = int(lookback)
    if n < 2 or len(df) < 2:
        return {}
    last_h, last_l = float(high.iloc[-1]), float(low.iloc[-1])
    prev_h, prev_l = float(high.iloc[-2]), float(low.iloc[-2])
    rng = last_h - last_l
    prev_rng = prev_h - prev_l
    tail = min(n, len(df) - 1)
    hh = int((high.diff() > 0).iloc[-tail:].sum())
    hl = int((low.diff() > 0).iloc[-tail:].sum())
    med = float(high.subtract(low).iloc[-min(20, len(df)):].median() or 0.0)
    close_loc = None
    if rng > 0:
        close_loc = (float(close.iloc[-1]) - last_l) / rng
    return {
        "inside_bar": bool(last_h <= prev_h and last_l >= prev_l),
        "range_compression": bool(med > 0 and rng < 0.6 * med),
        "hh_count": hh,
        "hl_count": hl,
        "close_location": close_loc,
        "lookback": tail,
        "paper_only": True,
        "unvalidated": True,
    }


def event_patterns(*, p_true: float, market_price: float) -> dict[str, Any]:
    """Kalshi yes/no book shape. Annotate only. Not a live edge claim."""
    p = float(p_true)
    px = float(market_price)
    edge = p - px
    return {
        "price_extreme": bool(px <= 0.15 or px >= 0.85),
        "edge_sign": 1 if edge > 0 else (-1 if edge < 0 else 0),
        "abs_edge": abs(edge),
        "crowded_yes": bool(px >= 0.85),
        "crowded_no": bool(px <= 0.15),
        "paper_only": True,
        "unvalidated": True,
    }


def merge_patterns(meta: Mapping[str, Any] | None, patterns: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(meta or {})
    out["patterns"] = dict(patterns)
    return out
