"""Consensus signal helpers (no Yahoo)."""
from types import SimpleNamespace
import numpy as np
import pandas as pd

from modules.signal_desk import (
    compute_desk_consensus,
    desk_conviction_multiplier,
    institutional_absorption,
    institutional_heatmap_ribbon_html,
    last_bar_volume_zscore,
    suggested_shares_atr_risk,
    vwap_distance_stats,
    whale_session_x_for_chart,
)


def _dummy_df(n=120):
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 0.6,
            "Low": close - 0.6,
            "Close": close,
            "Volume": rng.integers(1_000_000, 3_000_000, n),
        },
        index=idx,
    )


def test_last_bar_volume_zscore_reasonable():
    df = _dummy_df()
    z = last_bar_volume_zscore(df)
    assert z is not None
    assert -5 < z < 5


def test_whale_marker_only_when_spike():
    df = _dummy_df()
    df.loc[df.index[-1], "Volume"] = df["Volume"].iloc[:-1].max() * 50
    x = whale_session_x_for_chart(df, z_threshold=4.0)
    assert x == df.index[-1]


def test_consensus_score_in_range():
    df = _dummy_df()
    ctx = SimpleNamespace(
        qs=55.0,
        cp_score=5,
        cp_max=9,
        fg=50.0,
        struct="BULLISH",
        wk_label="BULLISH",
        macd_bull=True,
        obv_up=True,
        price=float(df["Close"].iloc[-1]),
        gold_zone_price=float(df["Close"].iloc[-1]) * 0.98,
        rsi_v=55.0,
        chg_pct=1.0,
    )
    c = compute_desk_consensus(ctx, df)
    assert 0 <= c["score"] <= 100
    assert c["band"] in ("high_risk", "neutral", "conviction")
    assert "absorption" in c and isinstance(c["absorption"], bool)
    assert "absorption_detail" in c
    assert "vwap_z" in c
    assert "vwap_detail" in c
    assert "vwap_urgency" in c and isinstance(c["vwap_urgency"], bool)
    assert "coil_active" in c and isinstance(c["coil_active"], bool)
    assert "conviction_multiplier" in c and 1.0 <= c["conviction_multiplier"] <= 2.0
    assert "conviction_label" in c and isinstance(c["conviction_label"], str)
    assert "rs_spy_ratio" in c
    assert "market_leader" in c and isinstance(c["market_leader"], bool)


def test_institutional_absorption_triggers_on_flat_close():
    df = _dummy_df(80)
    tail = df.index[-21:-1]
    df.loc[tail, "Volume"] = np.linspace(900_000, 1_100_000, len(tail)).astype(np.int64)
    df.loc[df.index[-1], "Volume"] = 50_000_000
    c_prev = float(df["Close"].iloc[-2])
    df.loc[df.index[-1], "Close"] = c_prev * 1.0005
    a = institutional_absorption(df)
    assert a["active"] is True
    assert a["volume_z"] is not None and a["volume_z"] >= 4.0


def test_institutional_absorption_off_when_price_runs():
    df = _dummy_df(80)
    tail = df.index[-21:-1]
    df.loc[tail, "Volume"] = np.linspace(900_000, 1_100_000, len(tail)).astype(np.int64)
    df.loc[df.index[-1], "Volume"] = 50_000_000
    c_prev = float(df["Close"].iloc[-2])
    df.loc[df.index[-1], "Close"] = c_prev * 1.05
    a = institutional_absorption(df)
    assert a["active"] is False


def test_vwap_distance_stats_finite():
    s = vwap_distance_stats(_dummy_df(120))
    assert set(s.keys()) == {"vwap_z", "rolling_vwap", "deviation_pct"}
    assert s["vwap_z"] is not None
    assert s["rolling_vwap"] is not None and s["rolling_vwap"] > 0
    assert s["deviation_pct"] is not None


def test_vwap_z_extreme_positive_on_gap_close():
    df = _dummy_df(100)
    base = float(df["Close"].iloc[-2])
    df.loc[df.index[-1], "High"] = base * 1.08
    df.loc[df.index[-1], "Low"] = base * 1.02
    df.loc[df.index[-1], "Close"] = base * 1.07
    df.loc[df.index[-1], "Open"] = base * 1.01
    z = vwap_distance_stats(df).get("vwap_z")
    assert z is not None and float(z) > 2.0


def test_desk_conviction_multiplier_tiers():
    assert desk_conviction_multiplier(coil_active=False, absorption=False, vwap_urgency=False) == (
        1.0,
        "Baseline (no elite microstructure gates)",
    )
    assert desk_conviction_multiplier(coil_active=True, absorption=False, vwap_urgency=False)[0] == 1.25
    assert desk_conviction_multiplier(coil_active=False, absorption=True, vwap_urgency=False)[0] == 1.25
    assert desk_conviction_multiplier(coil_active=False, absorption=False, vwap_urgency=True)[0] == 1.5
    assert desk_conviction_multiplier(coil_active=True, absorption=True, vwap_urgency=True)[0] == 2.0


def test_institutional_heatmap_ribbon_html_smoke():
    html = institutional_heatmap_ribbon_html(
        {
            "coil_active": True,
            "absorption": True,
            "vwap_urgency": True,
            "conviction_multiplier": 2.0,
            "conviction_label": "test",
        }
    )
    assert "INSTITUTIONAL HEATMAP" in html
    assert "COIL" in html and "ICEBERG" in html and "SWEEP" in html
    assert "LEADER" in html


def test_market_leader_when_rs_and_whale_volume():
    df = _dummy_df(80)
    tail = df.index[-21:-1]
    df.loc[tail, "Volume"] = np.linspace(900_000, 1_100_000, len(tail)).astype(np.int64)
    df.loc[df.index[-1], "Volume"] = 50_000_000
    c_prev = float(df["Close"].iloc[-2])
    df.loc[df.index[-1], "Close"] = c_prev * 1.02
    ctx = SimpleNamespace(
        qs=55.0,
        cp_score=5,
        cp_max=9,
        fg=50.0,
        struct="BULLISH",
        wk_label="BULLISH",
        macd_bull=True,
        obv_up=True,
        price=float(df["Close"].iloc[-1]),
        gold_zone_price=float(df["Close"].iloc[-1]) * 0.98,
        rsi_v=55.0,
        chg_pct=1.0,
    )
    c = compute_desk_consensus(ctx, df, rs_spy_ratio=1.08)
    assert c["volume_z"] is not None and c["volume_z"] > 4.0
    assert c["market_leader"] is True
    assert c["rs_spy_ratio"] == 1.08
    html = institutional_heatmap_ribbon_html(c)
    assert "MARKET LEADER" in html


def test_suggested_shares():
    sh = suggested_shares_atr_risk(100_000.0, 1.0, 100.0, 2.0, 1.5)
    assert sh is not None and sh > 0
