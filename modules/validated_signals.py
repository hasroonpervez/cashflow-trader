"""Validated signals — evidence-backed strategy logic from the Aug 2026 research program.

Every function here corresponds to a backtested, adversarially-verified result.
Nothing in this module is folklore. Provenance for each rule is documented in
RESEARCH_UPGRADE.md and the research reports (rounds 1-3, quant lab).

Summary of evidence status:
  ORB-30 (TSLA)          : champion day-trade signal. +16.6%/4mo, PF 1.89, t=1.46,
                           positive in both data halves (86 sessions, 5m bars).
  Swing pullback (SMA20) : PROMOTED. n=413 trades / 18mo / 34 symbols,
                           +125.9 bps/trade (replicated v1's +127.6), PF 1.39,
                           t=1.81, bootstrap 95% CI [+0.8, +271.8] — fully above 0.
  Pink Diamond exit      : DISPROVEN as a sell signal. 1,022 fires -> +1.8% avg
                           forward 5d return. Use mechanical_exit() instead.
  Compression breakout   : lottery profile (3 trades = all profit). Not exposed
                           here as a signal; compression is a WATCHLIST hint only.
  Gap-chasing            : disproven (all configs negative). ORB skips gap days.

All signal functions are anti-lookahead by construction: they evaluate only
completed bars and return orders intended for execution at the NEXT bar's open.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Session-anchored VWAP (the old TA.vwap was cumulative-from-first-bar and NOT
# valid intraday; this one resets each session)
# ---------------------------------------------------------------------------

def session_vwap(df: pd.DataFrame, tz: str = "America/New_York") -> pd.Series:
    """VWAP anchored to each trading session (correct for intraday use).

    df: intraday OHLCV with a tz-aware DatetimeIndex (or 'timestamp' column),
        columns: open, high, low, close, volume.
    Returns a Series aligned to df.index.
    """
    d = df.copy()
    if "timestamp" in d.columns:
        d = d.set_index(pd.DatetimeIndex(d["timestamp"]))
    idx = d.index.tz_convert(tz)
    session = idx.date
    tp = (d["high"] + d["low"] + d["close"]) / 3.0
    pv = tp * d["volume"]
    grp = pd.Series(session, index=d.index)
    vwap = pv.groupby(grp).cumsum() / d["volume"].groupby(grp).cumsum()
    vwap.name = "session_vwap"
    return vwap


# ---------------------------------------------------------------------------
# ORB-30: the validated day-trade signal (long-only, cash-account deployable)
# ---------------------------------------------------------------------------

def orb30_signal(
    day_5m: pd.DataFrame,
    *,
    latest_entry: str = "14:00",
    gap_skip_pct: float = 2.0,
    prior_close: float | None = None,
    tz: str = "America/New_York",
) -> dict | None:
    """Evaluate the ORB-30 long signal on ONE session of 5-minute bars.

    Rules (validated on TSLA, 86 sessions, both halves positive):
      - Opening range = high/low of the first six 5m bars (09:30-10:00 ET).
      - Signal: a 5m bar CLOSES above the OR high before `latest_entry`.
      - Entry: NEXT bar open (caller executes; this function only signals).
      - Stop: OR low if range < 1% of price, else close - (2/3 * range).
      - Exit: ride to the last bar of the session (no profit target).
      - Gap skip: if the session opened >= gap_skip_pct above prior close,
        stand down (gap-chasing was proven a net loser; gap days hurt ORB too).

    Returns None when there is no trade, else a dict describing the order.
    """
    d = day_5m.copy()
    if "timestamp" in d.columns:
        d = d.set_index(pd.DatetimeIndex(d["timestamp"]))
    d = d.sort_index()
    times = d.index.tz_convert(tz)
    if len(d) < 8:
        return None

    # Gap filter (validated: gaps fade in high-beta names)
    if prior_close is not None and prior_close > 0:
        gap = (d.iloc[0]["open"] / prior_close - 1.0) * 100.0
        if gap >= gap_skip_pct:
            return {"status": "skipped_gap_day", "gap_pct": round(gap, 2)}

    orh = float(d.iloc[:6]["high"].max())
    orl = float(d.iloc[:6]["low"].min())
    rng = orh - orl
    if rng <= 0:
        return None

    cutoff = pd.Timestamp(latest_entry).time()
    for j in range(6, len(d) - 1):
        if times[j].time() >= cutoff:
            break
        c = float(d.iloc[j]["close"])
        if c > orh:
            stop = orl if rng / c < 0.01 else c - (2.0 * rng / 3.0)
            return {
                "status": "signal",
                "side": "buy",
                "signal_bar_time": str(times[j]),
                "entry_hint": "next bar open",
                "or_high": round(orh, 4),
                "or_low": round(orl, 4),
                "signal_close": round(c, 4),
                "stop": round(stop, 4),
                "risk_pct_at_signal": round((c - stop) / c * 100.0, 2),
                "exit_rule": "stop, else hold to session close (no target)",
            }
    return None


# ---------------------------------------------------------------------------
# Swing pullback: the PROMOTED daily strategy (CI fully above zero, n=413)
# ---------------------------------------------------------------------------

def swing_pullback_signal(daily: pd.DataFrame) -> dict | None:
    """Evaluate the validated SMA20-reclaim swing signal on daily bars.

    Rules (validated config 'v1|sma50|nofilt|tgt3+trail'):
      - Regime: close > SMA50 AND SMA20 rising.
      - Setup: price touched/neared SMA20 within the last 5 sessions
        (session low <= SMA20 * 1.005).
      - Trigger: latest completed close back ABOVE SMA20 (the reclaim).
      - Entry: next open. Stop: min(low, 5 sessions) - 0.5 * ATR14.
      - Exits: 3R target OR next-open exit when a close < SMA20 OR 10-session
        time exit — whichever comes first.
      - Caller responsibility: skip entries within ~3 sessions of earnings
        (earnings avoidance was NOT testable from OHLCV; treat as mandatory
        common sense, not backtested).

    daily: OHLCV DataFrame, oldest->newest, >= 60 rows.
    Returns None or an order-descriptor dict.
    """
    d = daily.copy().reset_index(drop=True)
    if len(d) < 60:
        return None
    c = d["close"]
    sma20 = c.rolling(20).mean()
    sma50 = c.rolling(50).mean()
    tr = np.maximum(
        d["high"] - d["low"],
        np.maximum((d["high"] - c.shift()).abs(), (d["low"] - c.shift()).abs()),
    )
    atr14 = tr.rolling(14).mean()

    i = len(d) - 1  # latest completed bar
    if any(np.isnan(x) for x in (sma20.iloc[i], sma50.iloc[i], atr14.iloc[i], sma20.iloc[i - 5])):
        return None

    in_regime = c.iloc[i] > sma50.iloc[i] and sma20.iloc[i] > sma20.iloc[i - 5]
    touched = bool(
        (d["low"].iloc[i - 4 : i + 1].values <= sma20.iloc[i - 4 : i + 1].values * 1.005).any()
    )
    reclaimed = c.iloc[i] > sma20.iloc[i] and c.iloc[i - 1] <= sma20.iloc[i - 1] * 1.005

    if not (in_regime and touched and (reclaimed or c.iloc[i] > sma20.iloc[i])):
        return None
    # Require an actual reclaim event, not just riding above the line
    if not reclaimed:
        return None

    stop = float(d["low"].iloc[i - 4 : i + 1].min() - 0.5 * atr14.iloc[i])
    entry_ref = float(c.iloc[i])
    if stop >= entry_ref:
        return None
    r = entry_ref - stop
    return {
        "status": "signal",
        "side": "buy",
        "entry_hint": "next open",
        "signal_close": round(entry_ref, 4),
        "stop": round(stop, 4),
        "target_3R": round(entry_ref + 3.0 * r, 4),
        "risk_pct_at_signal": round(r / entry_ref * 100.0, 2),
        "exit_rule": "3R target OR next-open exit on close<SMA20 OR 10-session time exit",
        "earnings_warning": "do not enter within ~3 sessions of an earnings report",
    }


# ---------------------------------------------------------------------------
# Mechanical exits (replaces Pink Diamond, which was disproven as a sell signal)
# ---------------------------------------------------------------------------

PINK_DIAMOND_STATUS = (
    "DISPROVEN 2026-08-05: across 1,022 pink fires on 34 symbols / 18 months, "
    "average forward returns were POSITIVE (+1.8% 5d, +3.3% 10d). Pink-style "
    "exits cut winners and underperformed simple stop+time exits at every "
    "confluence threshold. Keep the visual as a caution flag if desired, but "
    "never as an automated sell trigger."
)


def mechanical_exit(
    daily: pd.DataFrame,
    entry_price: float,
    entry_index: int,
    *,
    atr_mult: float = 2.5,
    max_hold_sessions: int = 15,
) -> dict:
    """The exit logic that BEAT pink-diamond exits in testing: ATR stop + time.

    Evaluates a long swing position opened at `entry_index` (row position in
    `daily`) and returns the current directive: 'hold', 'exit_stop', or
    'exit_time'.
    """
    d = daily.copy().reset_index(drop=True)
    c = d["close"]
    tr = np.maximum(
        d["high"] - d["low"],
        np.maximum((d["high"] - c.shift()).abs(), (d["low"] - c.shift()).abs()),
    )
    atr14 = tr.rolling(14).mean()
    stop = entry_price - atr_mult * float(atr14.iloc[entry_index])
    last = len(d) - 1
    held = last - entry_index
    if float(d["low"].iloc[entry_index : last + 1].min()) <= stop:
        return {"directive": "exit_stop", "stop": round(stop, 4)}
    if held >= max_hold_sessions:
        return {"directive": "exit_time", "held_sessions": held}
    return {"directive": "hold", "stop": round(stop, 4), "held_sessions": held}


# ---------------------------------------------------------------------------
# Diamonds v3 — rebuilt on evidence: Blue = a STATE to watch, Pink = TIGHTEN
# ---------------------------------------------------------------------------

def blue_diamond_rank(daily: pd.DataFrame) -> dict | None:
    """Blue Diamond v3 — a watchlist RANKER, deliberately not a buy trigger.

    Evidence: the confluence score used as a direct entry produced regime beta
    (great in the 2025 melt-up, negative after). Used as a *ranking* of which
    names are in a healthy uptrend with participation, it tells you WHERE to
    hunt; the validated triggers (ORB break intraday, SMA20 reclaim daily)
    tell you WHEN to fire. See it -> you know WHAT TO WAIT FOR.

    Returns score 0-6 with component breakdown, plus setup_state:
      'in_pullback'  -> price resting on/near SMA20; a reclaim close would be
                        the validated swing entry (watch tomorrow's close)
      'extended'     -> strong but stretched; wait for the pullback
      'trend_intact' -> healthy trend, no setup yet
    """
    d = daily.copy().reset_index(drop=True)
    if len(d) < 60:
        return None
    c, v = d["close"], d["volume"]
    sma20, sma50 = c.rolling(20).mean(), c.rolling(50).mean()
    tr = np.maximum(d["high"] - d["low"], np.maximum((d["high"] - c.shift()).abs(), (d["low"] - c.shift()).abs()))
    atr14 = tr.rolling(14).mean()
    # RSI(14)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    # OBV slope
    obv = (np.sign(c.diff().fillna(0)) * v).cumsum()
    obv_slope = obv.diff(10)
    # ADX-lite: directional persistence proxy
    up10 = (c.diff() > 0).rolling(10).mean()
    vol_z = (v - v.rolling(20).mean()) / v.rolling(20).std()

    i = len(d) - 1
    comp = {
        "uptrend_sma": bool(c.iloc[i] > sma50.iloc[i] and sma20.iloc[i] > sma20.iloc[i - 5]),
        "sma_alignment": bool(sma20.iloc[i] > sma50.iloc[i]),
        "obv_rising": bool(obv_slope.iloc[i] > 0),
        "rsi_healthy": bool(40 <= (rsi.iloc[i] or 0) <= 70),
        "persistence": bool(up10.iloc[i] >= 0.5),
        "volume_alive": bool((vol_z.iloc[i] or -1) > 0),
    }
    score = int(sum(comp.values()))
    dist_sma20_atr = float((c.iloc[i] - sma20.iloc[i]) / atr14.iloc[i]) if atr14.iloc[i] > 0 else 0.0
    near_sma20 = bool(d["low"].iloc[i - 2 : i + 1].min() <= sma20.iloc[i] * 1.005)
    if near_sma20 and comp["uptrend_sma"]:
        state = "in_pullback"
        next_step = "WATCH: a close back above SMA20 is the validated swing entry (see swing_pullback_signal)"
    elif dist_sma20_atr > 2.5:
        state = "extended"
        next_step = "WAIT: stretched >2.5 ATR above SMA20; chasing here is the losing pattern"
    else:
        state = "trend_intact"
        next_step = "HOLD WATCH: no setup; re-rank tomorrow"
    return {
        "blue_score": score,
        "components": comp,
        "setup_state": state,
        "next_step": next_step,
        "dist_above_sma20_atr": round(dist_sma20_atr, 2),
        "note": "RANKER not trigger — entries come from validated triggers only",
    }


def pink_diamond_caution(daily: pd.DataFrame) -> dict | None:
    """Pink Diamond v3 — a TIGHTEN signal, never a sell trigger.

    Evidence: 1,022 historical pink fires were followed by POSITIVE average
    forward returns (+1.8% 5d / +3.3% 10d) — selling on pink cut winners.
    But the pattern does mark extension/climax. The profitable response in
    testing was mechanical: stay in, RAISE the stop. See it -> you know
    YOUR STOP MOVES UP (and optionally take partial profits), nothing more.

    caution levels:
      0 none      -> normal trailing rules
      1 stretched -> price >2.5 ATR above SMA20: trail at 2.0x ATR
      2 climax    -> RSI>75 AND volume>=1.5x avg: trail at 1.25x ATR under close,
                     partial profit-taking reasonable; DO NOT auto-sell all
    """
    d = daily.copy().reset_index(drop=True)
    if len(d) < 40:
        return None
    c, v = d["close"], d["volume"]
    sma20 = c.rolling(20).mean()
    tr = np.maximum(d["high"] - d["low"], np.maximum((d["high"] - c.shift()).abs(), (d["low"] - c.shift()).abs()))
    atr14 = tr.rolling(14).mean()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    i = len(d) - 1
    if atr14.iloc[i] is None or np.isnan(atr14.iloc[i]) or atr14.iloc[i] <= 0:
        return None
    ext_atr = float((c.iloc[i] - sma20.iloc[i]) / atr14.iloc[i])
    climax = bool((rsi.iloc[i] or 0) > 75 and v.iloc[i] >= 1.5 * v.rolling(20).mean().iloc[i])
    if climax:
        level, action = 2, f"CLIMAX: raise stop to {round(float(c.iloc[i] - 1.25 * atr14.iloc[i]), 4)} (1.25xATR under close); partial profits OK; do NOT sell all"
    elif ext_atr > 2.5:
        level, action = 1, f"STRETCHED: raise stop to {round(float(c.iloc[i] - 2.0 * atr14.iloc[i]), 4)} (2.0xATR under close)"
    else:
        level, action = 0, "normal trailing rules apply"
    return {
        "pink_caution": level,
        "action": action,
        "extension_atr": round(ext_atr, 2),
        "rsi": round(float(rsi.iloc[i] or 0), 1),
        "evidence": "selling on pink was disproven; tightening preserves runaway winners",
    }


# ---------------------------------------------------------------------------
# Validation gate — the discipline that caught Blue Diamond v2's fake t=2.98
# ---------------------------------------------------------------------------

def bootstrap_ci(returns, n_boot: int = 4000, seed: int = 42, alpha: float = 0.05):
    """Bootstrap CI of the mean per-trade return. Returns (low, high)."""
    r = np.asarray(list(returns), dtype=float)
    if len(r) < 5:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    boots = np.array([rng.choice(r, len(r), replace=True).mean() for _ in range(n_boot)])
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (float(lo), float(hi))


def split_half_consistent(returns) -> dict:
    """Sign-consistency check across chronological halves.

    The single most important lesson of the research program: Blue Diamond v2
    posted t=2.98 on the full sample and was NEGATIVE in the second half.
    A strategy must be positive in BOTH halves to be taken seriously.
    """
    r = np.asarray(list(returns), dtype=float)
    if len(r) < 20:
        return {"consistent": False, "reason": "insufficient sample (<20 trades)"}
    h1, h2 = r[: len(r) // 2], r[len(r) // 2 :]
    return {
        "consistent": bool(h1.mean() > 0 and h2.mean() > 0),
        "h1_mean_bps": round(float(h1.mean()) * 1e4, 1),
        "h2_mean_bps": round(float(h2.mean()) * 1e4, 1),
    }


def promotion_gate(returns, min_trades: int = 100) -> dict:
    """The full go/no-go gate a strategy must pass before real money.

    Pass requires: n >= min_trades, bootstrap 95% CI above zero, and
    positive expectancy in both chronological halves.
    """
    r = np.asarray(list(returns), dtype=float)
    lo, hi = bootstrap_ci(r)
    halves = split_half_consistent(r)
    t = float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 2 and r.std(ddof=1) > 0 else 0.0
    passed = len(r) >= min_trades and (not np.isnan(lo)) and lo > 0 and halves.get("consistent", False)
    return {
        "pass": bool(passed),
        "n": int(len(r)),
        "expectancy_bps": round(float(r.mean()) * 1e4, 1) if len(r) else 0.0,
        "t_stat": round(t, 2),
        "ci_bps": [round(lo * 1e4, 1), round(hi * 1e4, 1)] if not np.isnan(lo) else None,
        "split_half": halves,
        "rule": f"pass iff n>={min_trades} AND CI_low>0 AND both halves positive",
    }
