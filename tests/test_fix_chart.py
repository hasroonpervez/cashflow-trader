"""Regression tests for the "the chart lies" defects in modules/chart.py.

Covers audit #18 (IV-crush caption) plus the Charts/labels findings: phantom diamond
markers, transposed Fibonacci labels, side-blind S/R rails, price-space diamond offsets,
the unlabelled gamma tint, and the undisclosed institutional-flow proxy.
"""
import numpy as np
import pandas as pd
import pytest

from modules import chart as chart_mod
from modules.chart import (
    _fib_levels_directional,
    _fib_swing_is_down,
    _levels_nearest,
    _realized_vol_delta_label,
    build_chart,
)
from modules.ta import TA


def _ohlcv(closes, volumes=None):
    """Minimal daily OHLCV frame with a business-day index."""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    if volumes is None:
        volumes = np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.01,
            "Low": closes * 0.99,
            "Close": closes,
            "Volume": np.asarray(volumes, dtype=float),
        },
        index=idx,
    )


def _up_then_down(n=120):
    """Rally into a peak, then sell off below the start — swing low postdates the high."""
    up = np.linspace(130.0, 160.0, n // 2)
    down = np.linspace(160.0, 100.0, n - n // 2)
    return np.concatenate([up, down])


def _down_then_up(n=120):
    """Sell off into a trough, then rally past the old high — swing high postdates the low."""
    down = np.linspace(130.0, 100.0, n // 2)
    up = np.linspace(100.0, 160.0, n - n // 2)
    return np.concatenate([down, up])


def _annotations(fig):
    return [(a.text or "", a.y) for a in fig.layout.annotations]


def _trace_by_name(fig, name):
    for tr in fig.data:
        if getattr(tr, "name", None) == name:
            return tr
    return None


# --- _levels_nearest side filter (green "S" above spot / red "R" below) --------------

def test_levels_nearest_below_never_returns_a_level_above_spot():
    sups = [90.0, 95.0, 101.0, 108.0]
    got = _levels_nearest(sups, 100.0, 2, side="below")
    assert got == [95.0, 90.0]
    assert all(v <= 100.0 for v in got)


def test_levels_nearest_above_never_returns_a_level_below_spot():
    ress = [92.0, 99.0, 103.0, 120.0]
    got = _levels_nearest(ress, 100.0, 2, side="above")
    assert got == [103.0, 120.0]
    assert all(v >= 100.0 for v in got)


def test_levels_nearest_returns_fewer_rather_than_wrong_side():
    # Only one candidate sits below spot: draw one rail, do not borrow one from above.
    assert _levels_nearest([99.5, 105.0, 110.0], 100.0, 2, side="below") == [99.5]
    assert _levels_nearest([101.0, 105.0], 100.0, 2, side="below") == []


def test_levels_nearest_unfiltered_still_ranks_by_distance():
    assert _levels_nearest([90.0, 101.0, 130.0], 100.0, 2) == [101.0, 90.0]


def test_levels_nearest_drops_non_finite_and_unparseable():
    assert _levels_nearest([float("nan"), None, 98.0], 100.0, 3, side="below") == [98.0]


def _zigzag(n=200, drift=-0.45):
    """Oscillating tape with a drift: leaves pivot lows above (or highs below) the last price."""
    i = np.arange(n)
    return 120.0 + drift * i + 9.0 * np.sin(i / 6.0)


def _sr_rails(fig):
    return [(t, float(y)) for t, y in _annotations(fig) if t.startswith(("S $", "R $"))]


@pytest.mark.parametrize("drift", [-0.45, 0.45])
def test_chart_sr_rails_are_on_the_correct_side_of_spot(drift):
    # Downtrend leaves every pivot low above spot; uptrend leaves every pivot high below it.
    # Pre-fix, _levels_nearest ranked on |x - price| alone and happily drew green "S" rails
    # overhead and red "R" rails underneath.
    df = _ohlcv(_zigzag(200, drift))
    fig_p = build_chart(df, "TEST", show_fib=False, show_gann=False, show_sr=True)[0]
    last_px = float(df["Close"].iloc[-1])
    rails = _sr_rails(fig_p)
    assert rails, "expected at least one S/R rail on this fixture"
    for text, y in rails:
        if text.startswith("S $"):
            assert y <= last_px, f"green support rail drawn above spot: {text}"
        else:
            assert y >= last_px, f"red resistance rail drawn below spot: {text}"


def test_chart_draws_no_support_rail_when_every_pivot_low_is_overhead():
    df = _ohlcv(_zigzag(200, -0.45))
    fig_p = build_chart(df, "TEST", show_fib=False, show_gann=False, show_sr=True)[0]
    rails = _sr_rails(fig_p)
    assert not [t for t, _ in rails if t.startswith("S $")]
    assert [t for t, _ in rails if t.startswith("R $")], "resistance rails should still draw"


# --- Fibonacci anchoring ------------------------------------------------------------

def test_fib_swing_direction_detection():
    assert _fib_swing_is_down(_ohlcv(_up_then_down(80))) is True
    assert _fib_swing_is_down(_ohlcv(_down_then_up(80))) is False


def test_fib_up_swing_matches_ta_helper():
    # Swing high is the most recent extreme: ta.py's high-anchored levels are already right.
    assert _fib_levels_directional(160.0, 100.0, False) == TA.fib_retracement(160.0, 100.0)


def test_fib_down_swing_anchors_zero_percent_at_the_low():
    lv = _fib_levels_directional(160.0, 100.0, True)
    assert lv["0.0%"] == pytest.approx(100.0)
    assert lv["100.0%"] == pytest.approx(160.0)
    assert lv["38.2%"] == pytest.approx(122.92)
    assert lv["61.8%"] == pytest.approx(137.08)
    # The transposition bug: 38.2% and 61.8% carried each other's prices.
    assert lv["38.2%"] < lv["61.8%"]
    naive = TA.fib_retracement(160.0, 100.0)
    assert lv["38.2%"] == pytest.approx(naive["61.8%"])
    assert lv["61.8%"] == pytest.approx(naive["38.2%"])


def test_fib_levels_stay_inside_the_swing_both_directions():
    for down in (True, False):
        lv = _fib_levels_directional(160.0, 100.0, down)
        assert all(100.0 - 1e-9 <= v <= 160.0 + 1e-9 for v in lv.values())
        assert lv["50.0%"] == pytest.approx(130.0)


def test_chart_fib_labels_not_transposed_on_a_down_swing():
    df = _ohlcv(_up_then_down(160))
    fig_p = build_chart(df, "TEST", show_fib=True, show_gann=False, show_sr=False)[0]
    prices = {}
    for text, y in _annotations(fig_p):
        for tag in ("38%", "61%"):
            if text.startswith(tag + " $"):
                prices[tag] = float(y)
    assert set(prices) == {"38%", "61%"}
    rec = df.iloc[-60:]
    lo, hi = float(rec["Low"].min()), float(rec["High"].max())
    # Down-swing: the 38.2% retracement is the shallower bounce, i.e. nearer the swing low.
    assert abs(prices["38%"] - lo) < abs(prices["61%"] - lo)
    assert abs(prices["61%"] - hi) < abs(prices["38%"] - hi)


# --- Diamond markers ----------------------------------------------------------------

def _diamond_fig(diamonds):
    df = _ohlcv(_down_then_up(120))
    return build_chart(
        df, "TEST", show_fib=False, show_gann=False, show_sr=False, diamonds=diamonds
    )[0], df


def test_no_phantom_diamond_markers_when_none_fired():
    fig_p, _ = _diamond_fig([])
    for name in ("Blue diamond", "Pink diamond"):
        tr = _trace_by_name(fig_p, name)
        assert tr is not None, f"{name} legend entry should still exist"
        assert len(tr.x) == 0 and len(tr.y) == 0, f"{name} drew a marker with no signal"


def test_diamond_markers_plot_at_the_true_signal_price():
    df = _ohlcv(_down_then_up(120))
    b_date, p_date = df.index[40], df.index[80]
    diamonds = [
        {"type": "blue", "date": b_date, "price": 123.45},
        {"type": "pink", "date": p_date, "price": 154.32},
    ]
    fig_p = build_chart(
        df, "TEST", show_fib=False, show_gann=False, show_sr=False, diamonds=diamonds
    )[0]
    blue = _trace_by_name(fig_p, "Blue diamond")
    pink = _trace_by_name(fig_p, "Pink diamond")
    # No 1.5%/0.985 price-space fudge: y must be the price the hover claims.
    assert blue.y == (123.45,)
    assert pink.y == (154.32,)
    assert blue.customdata is not None and float(blue.customdata[0]) == 123.45
    # Separation from the candle is screen-space (pixels), so it cannot misstate a level.
    assert float(blue.marker.standoff) > 0
    assert float(pink.marker.standoff) > 0
    assert blue.marker.angleref == "up" and pink.marker.angleref == "up"


# --- Gamma tint overlay key ---------------------------------------------------------

def test_full_canvas_gamma_tint_is_named_in_the_overlay_key():
    df = _ohlcv(_down_then_up(120))
    last_px = float(df["Close"].iloc[-1])
    out = build_chart(
        df, "TEST", show_fib=False, show_gann=False, show_sr=False,
        gamma_flip_price=last_px * 1.10,
    )
    fig_p, key_html = out[0], out[4]
    assert any(
        getattr(s, "fillcolor", "") == "rgba(255, 0, 0, 0.05)" for s in fig_p.layout.shapes
    ), "fixture should trigger the negative-gamma wash"
    assert "Negative-gamma tint" in key_html


def test_no_gamma_tint_row_when_spot_is_above_the_flip():
    df = _ohlcv(_down_then_up(120))
    last_px = float(df["Close"].iloc[-1])
    key_html = build_chart(
        df, "TEST", show_fib=False, show_gann=False, show_sr=False,
        gamma_flip_price=last_px * 0.90,
    )[4]
    assert "Gamma flip" in key_html
    assert "Negative-gamma tint" not in key_html


# --- Audit #18: realized-vol delta mislabelled as "IV Crush" -------------------------

def test_realized_vol_delta_label_never_calls_a_positive_delta_a_crush():
    pos = _realized_vol_delta_label(42.1)
    assert "IV Crush" not in pos and "IV crush" not in pos
    assert "+42.1%" in pos
    assert "ROSE" in pos and "no crush" in pos


def test_realized_vol_delta_label_marks_the_measure_as_realized_and_a_proxy():
    for v in (-18.0, 0.0, 12.5):
        lab = _realized_vol_delta_label(v)
        assert "realized-vol" in lab
        assert "proxy" in lab
        assert "IV Crush" not in lab
    assert "crush-like" in _realized_vol_delta_label(-18.0)


def test_chart_overlay_annotation_uses_the_realized_vol_wording(monkeypatch):
    monkeypatch.setattr(
        chart_mod,
        "compute_iv_earnings_chart_overlay",
        lambda *a, **k: {"show_crush": True, "avg_crush_pct": 42.1, "vega_risk": False},
    )
    df = _ohlcv(_down_then_up(120))
    fig_p = build_chart(
        df, "TEST", show_fib=False, show_gann=False, show_sr=False, earnings_days_to=3
    )[0]
    texts = [t for t, _ in _annotations(fig_p)]
    assert any("realized-vol" in t and "proxy" in t for t in texts)
    assert not any("IV Crush: +" in t for t in texts)


# --- Institutional flow proxy disclosure --------------------------------------------

def test_volume_marker_hover_discloses_it_is_a_volume_proxy():
    closes = _down_then_up(120)
    rng = np.random.default_rng(7)
    # Needs a non-degenerate baseline: a flat volume series has sd == 0 and yields z == 0.
    vols = 1_000_000.0 + rng.normal(0.0, 40_000.0, len(closes))
    vols[-3] = 40_000_000.0  # force a z-score spike so the marker trace exists
    df = _ohlcv(closes, vols)
    fig_v = build_chart(df, "TEST", show_fib=False, show_gann=False, show_sr=False)[1]
    marker = None
    for tr in fig_v.data:
        if tr.type == "scatter" and "proxy" in str(getattr(tr, "hovertemplate", "")):
            marker = tr
            break
    assert marker is not None, "unusual-volume marker trace missing or hover lacks 'proxy'"
    hov = marker.hovertemplate
    assert "proxy" in hov
    assert "volume z-score" in hov.lower()
    assert "no venue or block-print data" in hov.lower()
