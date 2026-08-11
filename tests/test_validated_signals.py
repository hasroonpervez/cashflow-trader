"""Tests for modules/validated_signals.py, pure pandas/numpy, no app deps."""
import numpy as np
import pandas as pd
import pytest

from modules.validated_signals import (
    session_vwap,
    orb30_signal,
    swing_pullback_signal,
    blue_diamond_rank,
    pink_diamond_caution,
    mechanical_exit,
    bootstrap_ci,
    split_half_consistent,
    promotion_gate,
)


def _fake_session(breakout: bool = True) -> pd.DataFrame:
    """One synthetic 5m session, 78 bars, 9:30-15:55 ET."""
    idx = pd.date_range("2026-08-04 13:30", periods=78, freq="5min", tz="UTC")
    base = 100.0
    highs, lows, closes, opens = [], [], [], []
    px = base
    for j in range(78):
        if j < 6:  # opening range ~ [99, 101]
            o, h, l, c = px, px + 1.0, px - 1.0, px + 0.2
        elif breakout and j == 10:  # clean break above OR high
            o, h, l, c = px, px + 2.5, px - 0.1, px + 2.2
        else:
            o, h, l, c = px, px + 0.4, px - 0.4, px + (0.05 if breakout else -0.02)
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)
        px = c
    return pd.DataFrame(
        {"timestamp": idx, "open": opens, "high": highs, "low": lows,
         "close": closes, "volume": np.full(78, 10_000.0)}
    )


def _fake_daily(n=120, trend=0.004, pullback_at=None) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    closes, px = [], 50.0
    for i in range(n):
        drift = trend
        if pullback_at is not None and pullback_at <= i < pullback_at + 4:
            drift = -0.012  # engineered pullback to SMA20
        px *= 1 + drift + rng.normal(0, 0.004)
        closes.append(px)
    c = pd.Series(closes)
    return pd.DataFrame(
        {"open": c.shift(1).fillna(c[0]), "high": c * 1.01, "low": c * 0.99,
         "close": c, "volume": np.full(n, 1e6)}
    )


def test_session_vwap_resets_per_session():
    s1, s2 = _fake_session(), _fake_session()
    s2["timestamp"] = s2["timestamp"] + pd.Timedelta(days=1)
    both = pd.concat([s1, s2], ignore_index=True)
    v = session_vwap(both)
    assert len(v) == 156 and not v.isna().any()
    # first bar of session 2 must equal its own typical price, not carry session 1
    tp = (both.iloc[78]["high"] + both.iloc[78]["low"] + both.iloc[78]["close"]) / 3
    assert abs(v.iloc[78] - tp) < 1e-9


def test_orb30_fires_on_breakout_and_stop_below_entry():
    sig = orb30_signal(_fake_session(breakout=True))
    assert sig and sig["status"] == "signal"
    assert sig["stop"] < sig["signal_close"]


def test_orb30_no_signal_without_breakout():
    assert orb30_signal(_fake_session(breakout=False)) is None


def test_orb30_gap_skip():
    day = _fake_session(breakout=True)
    sig = orb30_signal(day, prior_close=day.iloc[0]["open"] / 1.03)  # +3% gap
    assert sig and sig["status"] == "skipped_gap_day"


def test_swing_pullback_signal_shape():
    d = _fake_daily(n=120, pullback_at=110)
    sig = swing_pullback_signal(d)
    if sig is not None:  # reclaim timing depends on noise; shape must be valid
        assert sig["stop"] < sig["signal_close"] < sig["target_3R"]


def test_blue_diamond_is_ranker_not_trigger():
    out = blue_diamond_rank(_fake_daily())
    assert out and 0 <= out["blue_score"] <= 6
    assert out["setup_state"] in {"in_pullback", "extended", "trend_intact"}
    assert "RANKER" in out["note"]


def test_pink_diamond_never_says_sell():
    out = pink_diamond_caution(_fake_daily())
    assert out is not None and out["pink_caution"] in (0, 1, 2)
    assert "sell all" not in out["action"].lower() or "not" in out["action"].lower()


def test_mechanical_exit_directives():
    d = _fake_daily(n=80)
    out = mechanical_exit(d, entry_price=float(d['close'].iloc[60]), entry_index=60)
    assert out["directive"] in {"hold", "exit_stop", "exit_time"}


def test_promotion_gate_rejects_regime_beta():
    # first half strongly positive, second half negative -> must FAIL
    r = np.concatenate([np.full(60, 0.02), np.full(60, -0.005)])
    out = promotion_gate(r, min_trades=100)
    assert out["pass"] is False and out["split_half"]["consistent"] is False


def test_promotion_gate_accepts_consistent_edge():
    rng = np.random.default_rng(1)
    r = rng.normal(0.004, 0.01, 300)  # steady real edge
    out = promotion_gate(r, min_trades=100)
    assert out["split_half"]["consistent"] is True
    assert out["pass"] is True


def test_bootstrap_ci_orders():
    lo, hi = bootstrap_ci(np.random.default_rng(3).normal(0.002, 0.01, 200))
    assert lo < hi


def test_split_half_small_sample_rejected():
    assert split_half_consistent([0.01] * 5)["consistent"] is False
