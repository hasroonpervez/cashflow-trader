"""Tests for Opt.detect_pre_diamond — the killer Equity Radar feature."""
import numpy as np
import pandas as pd

from modules.options import Opt


def _make_df(n=120, trend="up", squeeze=True, vol_ramp=True):
    """Build synthetic OHLCV with controllable squeeze / volume ramp."""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    base = np.linspace(95, 110, n) if trend == "up" else np.linspace(110, 95, n)
    noise = np.random.normal(0, 0.5, n)
    close = np.maximum(base + noise, 1.0)
    high = close + np.random.uniform(0.3, 2.0, n)
    low = np.maximum(close - np.random.uniform(0.3, 2.0, n), 0.5)

    tr = np.maximum(high - low, np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1)))
    atr = pd.Series(tr).rolling(14).mean().values
    if squeeze:
        # detect_pre_diamond checks rank percentile of the *last* ATR within tail(60),
        # so force the latest ATR to be the local minimum.
        atr[-60:] = np.linspace(0.20, 0.05, 60)

    vol = np.random.randint(500_000, 2_000_000, n).astype(float)
    if vol_ramp:
        vol[-3:] = vol[-10:-7].mean() * 1.8
    else:
        # Force last-3 mean below tail-10 mean so ramp condition is false.
        vol[-10:] = np.linspace(1_400_000, 600_000, 10)

    return pd.DataFrame(
        {
            "Open": close - np.random.uniform(0, 1, n),
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": vol,
            "ATR": atr,
        },
        index=dates,
    )


def _make_spy(n=120):
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = np.linspace(450, 460, n) + np.random.normal(0, 1, n)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": np.random.randint(50_000_000, 100_000_000, n),
        },
        index=dates,
    )


def _confluence_rising_5_to_6():
    return pd.Series([4, 5, 6])


def _confluence_flat_low():
    return pd.Series([2, 2, 3])


def test_pre_diamond_fires_on_ideal_setup():
    df = _make_df(trend="up", squeeze=True, vol_ramp=True)
    close = float(df["Close"].iloc[-1])
    result = Opt.detect_pre_diamond(
        df=df,
        gold_zone_price=close * 0.98,
        shadow_low=close * 0.985,
        weekly_bias="BULLISH",
        confluence_series=_confluence_rising_5_to_6(),
        spy_df=_make_spy(),
    )
    assert result["is_pre_diamond"] is True
    assert "signal_strength" in result
    assert result["signal_strength"] != "—"


def test_pre_diamond_blocked_by_bearish_weekly():
    df = _make_df(trend="up", squeeze=True, vol_ramp=True)
    close = float(df["Close"].iloc[-1])
    result = Opt.detect_pre_diamond(
        df=df,
        gold_zone_price=close * 0.98,
        shadow_low=close * 0.985,
        weekly_bias="BEARISH",
        confluence_series=_confluence_rising_5_to_6(),
        spy_df=_make_spy(),
    )
    assert result["is_pre_diamond"] is False


def test_pre_diamond_blocked_by_low_confluence():
    df = _make_df(trend="up", squeeze=True, vol_ramp=True)
    close = float(df["Close"].iloc[-1])
    result = Opt.detect_pre_diamond(
        df=df,
        gold_zone_price=close * 0.98,
        shadow_low=close * 0.985,
        weekly_bias="BULLISH",
        confluence_series=_confluence_flat_low(),
        spy_df=_make_spy(),
    )
    assert result["is_pre_diamond"] is False


def test_pre_diamond_blocked_by_no_volume_ramp():
    df = _make_df(trend="up", squeeze=True, vol_ramp=False)
    close = float(df["Close"].iloc[-1])
    result = Opt.detect_pre_diamond(
        df=df,
        gold_zone_price=close * 0.98,
        shadow_low=close * 0.985,
        weekly_bias="BULLISH",
        confluence_series=_confluence_rising_5_to_6(),
        spy_df=_make_spy(),
    )
    assert result["is_pre_diamond"] is False


def test_pre_diamond_blocked_far_from_support():
    df = _make_df(trend="up", squeeze=True, vol_ramp=True)
    close = float(df["Close"].iloc[-1])
    result = Opt.detect_pre_diamond(
        df=df,
        gold_zone_price=close * 0.90,
        shadow_low=close * 0.92,
        weekly_bias="BULLISH",
        confluence_series=_confluence_rising_5_to_6(),
        spy_df=_make_spy(),
    )
    assert result["is_pre_diamond"] is False


def test_pre_diamond_returns_dict_on_none_inputs():
    result = Opt.detect_pre_diamond(
        df=None,
        gold_zone_price=None,
        shadow_low=None,
        weekly_bias="BULLISH",
        confluence_series=None,
    )
    assert isinstance(result, dict)
    assert result["is_pre_diamond"] is False


def test_pre_diamond_volatility_state_label():
    df = _make_df(trend="up", squeeze=True, vol_ramp=True)
    close = float(df["Close"].iloc[-1])
    result = Opt.detect_pre_diamond(
        df=df,
        gold_zone_price=close * 0.98,
        shadow_low=close * 0.985,
        weekly_bias="BULLISH",
        confluence_series=_confluence_rising_5_to_6(),
        spy_df=_make_spy(),
    )
    if result["is_pre_diamond"]:
        assert "volatility_state" in result
        assert result["volatility_state"] == "SQUEEZED"
