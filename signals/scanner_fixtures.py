"""Synthetic OHLCV for scanner / Sig_orb_rvol_vwap tests and CLI --demo."""
from __future__ import annotations

from typing import Any

import pandas as pd


def _prior_daily(
    *,
    n: int = 20,
    close: float = 100.0,
    volume: float = 1_000_000.0,
    start: str = "2026-08-03",
    tz: str = "America/New_York",
) -> pd.DataFrame:
    days = pd.bdate_range(start, periods=n, tz=tz)
    idx = pd.DatetimeIndex([d.tz_convert(tz).replace(hour=16, minute=0) for d in days])
    px = float(close)
    rows = []
    for _ in idx:
        rows.append((px * 0.998, px * 1.01, px * 0.99, px, float(volume)))
    return pd.DataFrame(
        rows, index=idx, columns=["open", "high", "low", "close", "volume"]
    )


def session_5m(
    date: str,
    *,
    open0: float,
    or_high: float,
    or_low: float,
    breakout: bool,
    fade_below_vwap: bool = False,
    volume_per_bar: float = 80_000.0,
    n: int = 78,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """One regular session of 5m bars. Optional ORB break, optional VWAP fade."""
    start = pd.Timestamp(f"{date} 09:30", tz=tz)
    idx = pd.date_range(start, periods=n, freq="5min")
    opens, highs, lows, closes, vols = [], [], [], [], []
    px = float(open0)
    for j in range(n):
        if j < 6:
            o = px
            h = max(o, float(or_high) * 0.999, o + 0.15)
            # Keep OR high as the max of the first six highs.
            if j == 0:
                h = float(or_high)
            l = min(o, float(or_low), o - 0.15)
            c = o + 0.05
        elif breakout and j == 10:
            o = px
            h = float(or_high) + 1.2
            l = o - 0.1
            c = float(or_high) + 0.8
        elif fade_below_vwap and j >= 40:
            o = px
            c = float(open0) * 0.97
            h = max(o, c) + 0.1
            l = min(o, c) - 0.1
        else:
            o = px
            drift = 0.04 if breakout else -0.02
            c = o + drift
            h = max(o, c) + 0.25
            l = min(o, c) - 0.25
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        vols.append(float(volume_per_bar))
        px = c
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        },
        index=idx,
    )


def build_in_play_orb(
    *,
    symbol: str = "PLAY",
    prior_close: float = 100.0,
    gap_pct: float = 6.0,
    breakout: bool = True,
    fade_below_vwap: bool = False,
    volume_per_bar: float = 80_000.0,
    prior_volume: float = 1_000_000.0,
    session_date: str = "2026-09-01",
) -> pd.DataFrame:
    """Prior daily sessions + one 5m session that can fire ORB on a gapper."""
    prior = _prior_daily(close=prior_close, volume=prior_volume)
    open0 = prior_close * (1.0 + gap_pct / 100.0)
    or_high = open0 + 1.0
    or_low = open0 - 1.0
    today = session_5m(
        session_date,
        open0=open0,
        or_high=or_high,
        or_low=or_low,
        breakout=breakout,
        fade_below_vwap=fade_below_vwap,
        volume_per_bar=volume_per_bar,
    )
    return pd.concat([prior, today])


def build_demo_frames() -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]]:
    """PLAY in-play+ORB; DEAD flat; CHEAP below price floor. No network."""
    play = build_in_play_orb(symbol="PLAY")
    dead = build_in_play_orb(
        symbol="DEAD",
        gap_pct=0.2,
        breakout=False,
        volume_per_bar=8_000.0,
        prior_volume=1_000_000.0,
    )
    cheap = build_in_play_orb(
        symbol="CHEAP",
        prior_close=1.20,
        gap_pct=8.0,
        volume_per_bar=200_000.0,
        prior_volume=80_000.0,
    )
    # Shift CHEAP/DEAD dates? Same calendar is fine — independent frames.
    frames = {"PLAY": play, "DEAD": dead, "CHEAP": cheap}
    return frames, {}


def demo_payload() -> dict[str, Any]:
    """JSON-serializable demo universe (timestamps as ISO)."""
    frames, _hints = build_demo_frames()
    out: dict[str, Any] = {}
    for sym, df in frames.items():
        rows = []
        for ts, row in df.iterrows():
            rows.append(
                {
                    "ts": pd.Timestamp(ts).isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        out[sym] = {"bars": rows}
    return out
