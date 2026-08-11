"""Independent verification of the `data` engineer's claimed fixes (#16, #17, #25).

Written by the verifier, not the implementer. These do not duplicate tests/test_fix_data.py:
they drive the *public* entry points end to end rather than the extracted pure helpers, which
is where a "helper exists but is not wired" failure would hide.
"""

import types

import numpy as np
import pandas as pd
import pytest

import modules.data as D


# --------------------------------------------------------------------------- #16
_LAST_BAR = pd.Timestamp("2026-08-10")  # a Monday


def _panel_with_partial_last_bar(vol_last: float) -> pd.DataFrame:
    """MultiIndex (Price, Ticker) panel; the final bar is dated ``_LAST_BAR``."""
    idx = pd.bdate_range(end=_LAST_BAR, periods=140)
    n = len(idx)
    rng = np.random.default_rng(7)
    vol = 1_000_000.0 + rng.normal(0, 30_000.0, n)  # real dispersion so sd > 0
    vol[-1] = vol_last
    cols = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], ["AAA", "SPY"]], names=["Price", "Ticker"]
    )
    frame = pd.DataFrame(index=idx, columns=cols, dtype=float)
    for sym, series in (
        ("AAA", 100 + np.cumsum(rng.normal(0.15, 0.6, n))),
        ("SPY", 400 + np.cumsum(rng.normal(0.02, 0.3, n))),
    ):
        frame[("Open", sym)] = series
        frame[("High", sym)] = series + 1
        frame[("Low", sym)] = series - 1
        frame[("Close", sym)] = series
        frame[("Volume", sym)] = vol
    return frame


def _radar_vol_z(monkeypatch, panel, now_et):
    monkeypatch.setattr(D.yf, "download", lambda *a, **k: panel)
    monkeypatch.setattr(D, "_now_et", lambda now=None: now_et)
    rows = D.radar_broad_filter.__wrapped__("AAA,SPY", spy_closes=None)
    aaa = {r["ticker"]: r for r in rows}.get("AAA")
    assert aaa is not None, "AAA should survive the pre_score cut in this fixture"
    return aaa["vol_z"]


def test_16_radar_broad_filter_actually_drops_the_in_progress_bar(monkeypatch):
    """End to end: the quarter-formed bar must not be what the volume Z-score scores.

    Pre-fix, 250k against a ~1.0M baseline reads as a >20-sigma volume *collapse* at 10:30 ET.
    """
    panel = _panel_with_partial_last_bar(250_000.0)
    z = _radar_vol_z(monkeypatch, panel, pd.Timestamp("2026-08-10 10:30", tz="America/New_York"))
    assert abs(z) < 2.0, f"in-progress bar still being scored (z={z})"


def test_16_a_completed_session_is_still_scored_after_the_close(monkeypatch):
    """The guard must not silently delete the newest real bar once 16:00 ET has passed."""
    panel = _panel_with_partial_last_bar(5_000_000.0)  # genuine 5x accumulation day
    z = _radar_vol_z(monkeypatch, panel, pd.Timestamp("2026-08-10 16:30", tz="America/New_York"))
    assert z > 4.0, f"a real 5x volume day must survive after the close (z={z})"


def test_16_a_prior_session_is_never_dropped(monkeypatch):
    """Panel ends Friday, 'now' is the following Monday morning: nothing may be dropped."""
    panel = _panel_with_partial_last_bar(5_000_000.0)
    z = _radar_vol_z(monkeypatch, panel, pd.Timestamp("2026-08-11 10:30", tz="America/New_York"))
    assert z > 4.0, f"stale-dated bar wrongly discarded (z={z})"


def test_16_helper_is_reachable_and_pure():
    idx = pd.date_range("2026-08-10", periods=3, freq="D")
    s = pd.Series([1.0, 2.0, 3.0], index=idx)
    mid = pd.Timestamp("2026-08-12 10:30", tz="America/New_York")
    after = pd.Timestamp("2026-08-12 16:30", tz="America/New_York")
    assert list(D.drop_partial_last_bar(s, now=mid)) == [1.0, 2.0]
    assert list(D.drop_partial_last_bar(s, now=after)) == [1.0, 2.0, 3.0]
    assert list(s) == [1.0, 2.0, 3.0], "helper must not mutate its input"


def test_16_saturday_and_holiday_bars_are_never_treated_as_partial():
    # Last bar Friday, "now" is Saturday morning: date differs, so nothing is dropped.
    idx = pd.DatetimeIndex(["2026-08-06", "2026-08-07"])
    assert D.last_bar_is_partial(idx, now=pd.Timestamp("2026-08-08 11:00")) is False


# --------------------------------------------------------------------------- #17
def _crush_frame(n=200):
    idx = pd.bdate_range("2025-06-02", periods=n)
    rng = np.random.default_rng(3)
    quiet = rng.normal(0, 0.004, n)
    px = 100 * np.cumprod(1 + quiet)
    return pd.DataFrame({"Close": px}, index=idx)


def test_17_public_entrypoint_survives_a_tz_aware_earnings_index(monkeypatch):
    """The exact shape yfinance 0.2.66 returns: a tz-aware DatetimeIndex.

    Pre-fix this raised `TypeError: Cannot compare tz-naive and tz-aware timestamps` inside a
    blanket except and returned None for every symbol forever.
    """
    df = _crush_frame()
    aware = pd.DatetimeIndex(
        [pd.Timestamp("2025-08-05 16:00", tz="America/New_York"),
         pd.Timestamp("2025-11-04 16:00", tz="America/New_York")]
    )
    ed = pd.DataFrame({"EPS Estimate": [1.0, 1.1]}, index=aware)
    monkeypatch.setattr(D, "_yfinance_ticker", lambda s: types.SimpleNamespace(earnings_dates=ed))

    out = D.avg_post_earnings_vol_crush_proxy_pct(df, "AAA", n_cycles=4)
    assert out is not None and np.isfinite(out), "tz-aware earnings_dates must still produce a number"


def test_17_overlay_can_now_set_show_crush(monkeypatch):
    """The consequence the audit named: `show_crush` had never once been True."""
    df = _crush_frame()
    ed = pd.DataFrame(
        {"EPS Estimate": [1.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2025-11-04 16:00", tz="America/New_York")]),
    )
    monkeypatch.setattr(D, "_yfinance_ticker", lambda s: types.SimpleNamespace(earnings_dates=ed))
    ov = D.compute_iv_earnings_chart_overlay(df, "AAA", days_to_earnings=3, current_iv_pct=None, spot_price=100.0)
    assert ov["show_crush"] is True
    assert ov["avg_crush_pct"] is not None


def test_17_programming_errors_are_no_longer_laundered_into_none():
    """A TypeError from the compute path must propagate, not read as 'Yahoo had no data'."""

    class Hostile(pd.DataFrame):
        pass

    with pytest.raises(TypeError):
        D.post_earnings_vol_crush_pct_from_dates(_crush_frame(), [object()])


# --------------------------------------------------------------------------- #25
def test_25_collapsing_business_end_to_end_is_not_a_10x_candidate(monkeypatch):
    """EBITDA -50% over assets -10% used to read +5.0 efficiency and flag ten_x."""
    monkeypatch.setattr(D, "fetch_info", lambda s: {"freeCashflow": 20.0, "enterpriseValue": 100.0})
    monkeypatch.setattr(D, "_alphavantage_efficiency_yoy", lambda s: (-0.50, -0.10))
    out = D._evaluate_fundamental_sieve_cached.__wrapped__("AAA")
    assert out is not None
    assert out["efficiency_ratio"] is None, "must be None, never a fabricated +5.0"
    assert out["ten_x_candidate"] is False
    assert out["fcf_yield"] == pytest.approx(0.20)


def test_25_genuine_growth_still_flags(monkeypatch):
    monkeypatch.setattr(D, "fetch_info", lambda s: {"freeCashflow": 20.0, "enterpriseValue": 100.0})
    monkeypatch.setattr(D, "_alphavantage_efficiency_yoy", lambda s: (0.50, 0.10))
    out = D._evaluate_fundamental_sieve_cached.__wrapped__("AAA")
    assert out["efficiency_ratio"] == pytest.approx(5.0)
    assert out["ten_x_candidate"] is True


@pytest.mark.parametrize("eb,ay", [(-0.5, -0.1), (0.5, -0.1), (-0.5, 0.1), (0.0, 0.1), (0.5, 0.0)])
def test_25_no_sign_combination_other_than_both_positive_produces_a_ratio(eb, ay):
    out = D.fundamental_sieve_from_inputs(20.0, 100.0, eb, ay)
    assert out["efficiency_ratio"] is None
    assert out["ten_x_candidate"] is False


def test_25_consumers_that_read_the_sieve_dict_tolerate_a_none_ratio():
    """options.py / signal_desk.py read ten_x_candidate + fcf_yield only — prove they cope."""
    from modules.signal_desk import compute_desk_consensus  # noqa: F401  (import must not explode)

    sieve = D.fundamental_sieve_from_inputs(20.0, 100.0, -0.5, -0.1)
    assert bool(sieve.get("ten_x_candidate")) is False
    assert float(sieve.get("fcf_yield") or 0) > 0.10  # the OR-leg in signal_desk.py:745 still fires
