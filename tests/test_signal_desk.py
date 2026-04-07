"""Consensus signal helpers (no Yahoo)."""
from types import SimpleNamespace
import numpy as np
import pandas as pd

from modules.signal_desk import (
    blend_unified_probability,
    bento_accents_from_consensus,
    compute_desk_consensus,
    daily_aggressor_proxy,
    desk_conviction_multiplier,
    institutional_absorption,
    institutional_heatmap_ribbon_html,
    last_bar_volume_zscore,
    suggested_shares_atr_risk,
    traders_note_markdown,
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
        ticker="TEST",
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
    assert "unified_probability" in c and 0 <= float(c["unified_probability"]) <= 100
    assert "ofi_detail" in c and isinstance(c["ofi_detail"], dict)


def test_blend_unified_probability_bounds():
    u = blend_unified_probability(80.0, 70.0, 1.1)
    assert 0 < u <= 100
    u2 = blend_unified_probability(50.0, 50.0, None)
    assert u2 == 50.0


def test_daily_aggressor_proxy_finite():
    df = _dummy_df()
    d = daily_aggressor_proxy(df)
    assert d["ofi_proxy"] is not None
    assert -1.1 < float(d["ofi_proxy"]) < 1.1


def test_bento_accents_keys():
    df = _dummy_df()
    ctx = SimpleNamespace(
        ticker="TEST",
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
    c = compute_desk_consensus(ctx, df, rs_spy_ratio=1.05)
    acc = bento_accents_from_consensus(c)
    assert set(acc.keys()) == {"setup", "momentum", "exit"}


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
    assert desk_conviction_multiplier(
        coil_active=False, absorption=False, vwap_urgency=False, whale_sweep=True
    )[0] == 1.5


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
        ticker="TEST",
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


def test_traders_note_unicorn_perfect_storm():
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    df = pd.DataFrame(
        {
            "High": np.linspace(100, 118, 100),
            "Low": np.linspace(99, 117, 100),
            "Open": np.linspace(99.5, 117.5, 100),
            "Close": np.linspace(100, 118, 100),
            "Volume": np.full(100, 1_000_000),
        },
        index=idx,
    )
    ctx = SimpleNamespace(price=118.0, chg_pct=0.4, qs=62.0, struct="BULLISH", wk_label="BULLISH")
    c = {
        "coil_active": True,
        "absorption": True,
        "market_leader": True,
        "rs_spy_ratio": 1.2,
        "volume_z": 4.6,
        "absorption_detail": {"last_return_pct": 0.08, "flat_threshold_pct": 0.45, "volume_z": 4.6},
        "bbw_pctile": 0.03,
        "atr_last": 2.0,
    }
    md = traders_note_markdown("PLTR", ctx, df, c)
    assert "Unicorn alert" in md
    assert "market leader" in md
    assert "Iceberg" in md
    assert "COIL" in md
    assert "20d high" in md


def test_suggested_shares():
    sh = suggested_shares_atr_risk(100_000.0, 1.0, 100.0, 2.0, 1.5)
    assert sh is not None and sh > 0
