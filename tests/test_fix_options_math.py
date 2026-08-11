"""Regression tests for the ``modules/options.py`` defects in AUDIT_2026-08.md.

One test family per audit finding:

* **#1**  ``continuous_kelly`` clipped the Merton fraction *before* applying the correlation
  haircut and the PoP multiplier, so the returned "percentage of bankroll" reached 108.5%
  (130%+ with a 1.20 hedge haircut) and the half-Kelly branch silently collapsed onto the
  full-Kelly branch for every ``f* >= 2``.
* **#4**  ``detect_diamonds`` derived the weekly bias and the Hurst-adaptive RSI/MACD periods
  from the **complete** frame and then applied them as per-bar gates, and passed the unsliced
  weekly frame into the per-bar confluence call: a full-sample lookahead under every
  historical diamond and every displayed win rate.
* **#10** ``find_gamma_flip`` searched for a positive→negative crossing when the signing
  convention produces a negative→positive one.
* **#11** The Pre-Diamond squeeze gate read a ``df["ATR"]`` column nothing creates, so it was
  unconditionally ``True`` inside ``all(conditions)`` and failed **open**.
* **#13** ``compute_explosion_score`` counted one confluence event two or three times and paid
  +5 for *missing* options data.
* **#23** ``diamond_win_rate`` pooled blue long outcomes and pink short outcomes into a single
  "win rate for Diamond signals".

Plus the three medium findings in the same file: the Pink-Diamond weekly tautology, the
``score_10x_potential`` BBW ranking window, and the discarded discrete-Kelly inputs.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules.options import (
    CONTINUOUS_KELLY_MAX_ALLOCATION,
    Opt,
    PortfolioRisk,
    TEN_X_MAX_SCORE,
    _causal_weekly_slice,
    _stock_stop_price,
    _volatility_squeeze_gate,
    compute_explosion_score,
    continuous_kelly,
    detect_diamonds,
    diamond_win_rate,
    diamond_win_rate_by_side,
    explosion_score_detail,
    kelly_criterion,
    score_10x_potential,
    weekly_trend_label,
)

OPTIONS_SRC = (Path(__file__).resolve().parent.parent / "modules" / "options.py").read_text(
    encoding="utf-8"
)

# PoP 100 is the worst case for the multiplier the audit measured: (100/85) ** 0.5.
POP_MULT_AT_100 = (100.0 / 85.0) ** 0.5


# ═══════════════════════════════════════════════════════════════════════════
#  #1: Kelly can exceed 100% of bankroll
# ═══════════════════════════════════════════════════════════════════════════

def test_continuous_kelly_no_longer_returns_108_5_percent_at_pop_100():
    """The exact number in the audit. f* = 25, half-Kelly, PoP 100, no haircut.

    Old: ``max(0, min(1, 12.5)) * 100 * 1.0 * 1.0847`` = **108.5**: more than the whole
    bankroll on a single short put.
    """
    old_broken_value = round(min(1.0, 25.0 / 2.0) * 100 * 1.0 * POP_MULT_AT_100, 1)
    assert old_broken_value == 108.5  # the bug this test exists to prevent

    got = continuous_kelly(
        expected_return=0.30,
        risk_free_rate=0.05,
        variance=0.01,
        half_kelly=True,
        correlation_haircut=1.0,
        pop_mult=POP_MULT_AT_100,
    )
    assert got == pytest.approx(100.0 * CONTINUOUS_KELLY_MAX_ALLOCATION)
    assert got < 100.0


def test_continuous_kelly_cap_survives_the_true_hedge_haircut():
    """``Opt.calc_kelly_haircut`` returns 1.20 for a "true hedge", it must not breach the cap."""
    hedge_haircut = PortfolioRisk.calc_kelly_haircut(-0.4)
    assert hedge_haircut == 1.20  # the boost that used to push the result past 130%

    got = continuous_kelly(
        expected_return=0.50,
        risk_free_rate=0.05,
        variance=0.01,
        half_kelly=False,
        correlation_haircut=hedge_haircut,
        pop_mult=POP_MULT_AT_100,
    )
    assert got <= 100.0 * CONTINUOUS_KELLY_MAX_ALLOCATION + 1e-9


@pytest.mark.parametrize("f_star", [0.05, 0.2, 0.5, 1.0, 2.0, 5.0, 25.0, 1_000.0])
@pytest.mark.parametrize("haircut", [0.50, 0.75, 1.0, 1.20])
@pytest.mark.parametrize("pop_mult", [0.5, 1.0, POP_MULT_AT_100])
def test_continuous_kelly_is_bounded_everywhere(f_star, haircut, pop_mult):
    """No combination of the three multipliers may exceed the cap or go negative."""
    variance = 0.04
    expected_return = 0.05 + f_star * variance
    for half in (True, False):
        got = continuous_kelly(
            expected_return,
            0.05,
            variance,
            half_kelly=half,
            correlation_haircut=haircut,
            pop_mult=pop_mult,
        )
        assert 0.0 <= got <= 100.0 * CONTINUOUS_KELLY_MAX_ALLOCATION + 1e-9


def test_half_kelly_is_exactly_half_of_full_kelly_below_the_cap():
    """The half-Kelly safety margin must be real, not an artefact of where the clip lands."""
    kw = dict(
        expected_return=0.058,
        risk_free_rate=0.05,
        variance=0.04,
        correlation_haircut=1.0,
        pop_mult=1.0,
    )
    full = continuous_kelly(half_kelly=False, **kw)
    half = continuous_kelly(half_kelly=True, **kw)
    assert full < 100.0 * CONTINUOUS_KELLY_MAX_ALLOCATION  # unsaturated region
    assert half == pytest.approx(full / 2.0)
    assert half < full


def test_haircut_and_pop_mult_scale_the_allocation_rather_than_a_saturated_one():
    """Applying them *inside* the clip means a 0.5 haircut genuinely halves the size."""
    kw = dict(expected_return=0.058, risk_free_rate=0.05, variance=0.04, half_kelly=False)
    plain = continuous_kelly(correlation_haircut=1.0, pop_mult=1.0, **kw)
    haircut = continuous_kelly(correlation_haircut=0.5, pop_mult=1.0, **kw)
    boosted = continuous_kelly(correlation_haircut=1.0, pop_mult=POP_MULT_AT_100, **kw)
    assert haircut == pytest.approx(plain * 0.5)
    assert boosted == pytest.approx(plain * POP_MULT_AT_100)


def test_continuous_kelly_rejects_degenerate_inputs():
    assert continuous_kelly(0.2, 0.05, 0.0) == 0.0
    assert continuous_kelly(0.2, 0.05, -1.0) == 0.0
    assert continuous_kelly(0.01, 0.05, 0.04) == 0.0  # drift below the risk-free rate


def test_discrete_kelly_branch_cannot_exceed_the_bankroll():
    """``pop_mult`` multiplied an already-full fraction in the discrete branch too."""
    full, half = kelly_criterion(99.0, 100.0, 1.0, use_quant=False, avg_mc_pop=100.0)
    assert full <= 100.0
    assert half == pytest.approx(full / 2.0)


# ═══════════════════════════════════════════════════════════════════════════
#  #4: lookahead bias in detect_diamonds
# ═══════════════════════════════════════════════════════════════════════════

def _synthetic_ohlcv(n, seed, drift=0.0015):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 60.0 * np.exp(np.cumsum(rng.normal(drift, 0.014, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.integers(2_000_000, 6_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": close * 0.999, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def _weekly(df):
    return df.resample("W").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()


def _rally_then_crash(n=240, cut=150, seed=11):
    """Bullish through ``cut``, then a hard crash, so the *full*-frame weekly bias is
    BEARISH while the point-in-time bias at ``cut`` is still BULLISH."""
    df = _synthetic_ohlcv(n, seed)
    df.iloc[cut + 1:, df.columns.get_loc("Close")] = df["Close"].iloc[cut] * np.exp(
        np.linspace(0.0, -0.6, n - cut - 1)
    )
    df["High"] = df["Close"] * 1.005
    df["Low"] = df["Close"] * 0.995
    df["Open"] = df["Close"] * 0.999
    return df


def _signature(diamonds, upto=None):
    return [
        (d["type"], pd.Timestamp(d["date"]), round(float(d["score"]), 6))
        for d in diamonds
        if upto is None or pd.Timestamp(d["date"]) <= upto
    ]


def test_no_lookahead_todays_weekly_bias_cannot_erase_historical_diamonds():
    """THE audit #4 test.

    A ticker that is bearish *today* used to emit zero historical blue diamonds, because
    ``wk_bias`` was computed once from the complete weekly frame and then applied as a
    per-bar gate. Here the full-frame bias is BEARISH and the point-in-time bias at the cut
    is BULLISH, so under the old code the full-frame run returned nothing for those bars.
    """
    cut = 150
    df = _rally_then_crash(cut=cut)
    ts = df.index[cut]

    assert weekly_trend_label(_weekly(df))[0] == "BEARISH"
    assert weekly_trend_label(_weekly(df.iloc[: cut + 1]))[0] == "BULLISH"

    point_in_time = _signature(detect_diamonds(df.iloc[: cut + 1], _weekly(df.iloc[: cut + 1])))
    full_frame = _signature(detect_diamonds(df, _weekly(df)), upto=ts)

    assert any(t == "blue" for t, _, _ in point_in_time), "fixture must produce blue diamonds"
    assert full_frame == point_in_time


def test_no_lookahead_poisoned_future_bars_do_not_change_the_past():
    """Copy of ``test_asymmetry.py::test_no_lookahead_price_series_functions``' pattern:
    mutate every row after ``i`` into garbage; the signals at or before ``i`` must be
    byte-identical."""
    df = _synthetic_ohlcv(220, seed=2)
    i = 160
    ts = df.index[i]
    before = _signature(detect_diamonds(df, _weekly(df)), upto=ts)
    assert before, "fixture must produce diamonds before the poison point"

    poisoned = df.copy()
    poisoned.iloc[i + 1:, poisoned.columns.get_loc("Close")] = 10_000.0
    poisoned.iloc[i + 1:, poisoned.columns.get_loc("Open")] = 10_000.0
    poisoned.iloc[i + 1:, poisoned.columns.get_loc("High")] = 11_000.0
    poisoned.iloc[i + 1:, poisoned.columns.get_loc("Low")] = 9_000.0
    poisoned.iloc[i + 1:, poisoned.columns.get_loc("Volume")] = 1.0

    after = _signature(detect_diamonds(poisoned, _weekly(poisoned)), upto=ts)
    assert after == before


def test_no_lookahead_hurst_adaptive_periods_are_chosen_causally():
    """The RSI length and all three MACD periods came from ``_hurst_adaptive_signal_periods``
    on the **full** sample. This fixture is one where the full-sample choice differs from the
    point-in-time choice, so a leak would show up as differing signals."""
    from modules.options import _hurst_adaptive_signal_periods

    df = _synthetic_ohlcv(220, seed=2)
    i = 160
    full_periods = _hurst_adaptive_signal_periods(df["Close"])[:4]
    causal_periods = _hurst_adaptive_signal_periods(df["Close"].iloc[: i + 1])[:4]
    assert full_periods != causal_periods, "fixture must exercise the adaptive branch"

    ts = df.index[i]
    assert _signature(detect_diamonds(df, _weekly(df)), upto=ts) == _signature(
        detect_diamonds(df.iloc[: i + 1], _weekly(df.iloc[: i + 1]))
    )


def test_causal_weekly_slice_drops_the_week_still_in_progress():
    df = _synthetic_ohlcv(120, seed=3)
    wk = _weekly(df)
    ts = df.index[60]
    sliced = _causal_weekly_slice(wk, ts)
    assert len(sliced) < len(wk)
    assert (sliced.index <= ts).all()
    # the bar covering ``ts`` itself carries that week's later sessions, it must be gone
    assert (sliced.index <= pd.Timestamp(ts) - pd.Timedelta(days=6)).all()


def test_causal_weekly_slice_tolerates_missing_input():
    assert _causal_weekly_slice(None, pd.Timestamp("2024-01-01")) is None
    empty = pd.DataFrame()
    assert _causal_weekly_slice(empty, pd.Timestamp("2024-01-01")) is empty


# ═══════════════════════════════════════════════════════════════════════════
#  #10: find_gamma_flip searched the wrong crossing direction
# ═══════════════════════════════════════════════════════════════════════════

def _put_skewed_chain(spot=100.0):
    """S=100, 30 DTE, strikes 70→130. Put OI concentrated at and below spot (hedging),
    call OI above: the ordinary shape of a listed equity chain."""
    rows = []
    for k in np.arange(70.0, 131.0, 5.0):
        rows.append({
            "strike": k,
            "openInterest": 4000 if k <= spot else 300,
            "type": "put",
            "impliedVolatility": 0.35 if k < spot else 0.28,
        })
        rows.append({
            "strike": k,
            "openInterest": 300 if k < spot else 4000,
            "type": "call",
            "impliedVolatility": 0.28,
        })
    return pd.DataFrame(rows)


def test_find_gamma_flip_locates_the_negative_to_positive_crossing():
    """Cumulative GEX from the lowest strike upward starts negative (deep-OTM put OI) and
    crosses positive above spot. The finder used to accept only the opposite direction and
    therefore returned ``None`` on this: entirely ordinary, chain."""
    gex = Opt.calc_gamma_exposure(_put_skewed_chain(), 100.0)
    cum = gex.sort_index().cumsum()
    assert cum.iloc[0] < 0 and cum.iloc[-1] > 0, "fixture must contain a neg→pos crossing"
    assert not any(
        float(cum.iloc[j]) > 0 and float(cum.iloc[j + 1]) < 0 for j in range(len(cum) - 1)
    ), "fixture must contain NO pos→neg crossing, the old code returned None here"

    flip = Opt.find_gamma_flip(gex)
    assert flip is not None
    assert 105.0 < float(flip) < 110.0


def test_find_gamma_flip_agrees_with_the_downstream_regime_convention():
    """``gex_regime = STABLE if price > gamma_flip``: dealers long gamma above the flip."""
    flip = float(Opt.find_gamma_flip(Opt.calc_gamma_exposure(_put_skewed_chain(), 100.0)))
    gex = Opt.calc_gamma_exposure(_put_skewed_chain(), 100.0).sort_index()
    cum = gex.cumsum()
    assert float(cum.loc[cum.index > flip].iloc[0]) > 0
    assert float(cum.loc[cum.index < flip].iloc[-1]) < 0


def test_find_gamma_flip_returns_none_without_a_crossing():
    all_negative = pd.Series([-5.0, -20.0, -60.0, -30.0], index=[90.0, 95.0, 100.0, 105.0])
    assert Opt.find_gamma_flip(all_negative) is None
    assert Opt.find_gamma_flip(None) is None
    assert Opt.find_gamma_flip(pd.Series(dtype=float)) is None


# ═══════════════════════════════════════════════════════════════════════════
#  #11: Pre-Diamond squeeze gate is dead and fails open
# ═══════════════════════════════════════════════════════════════════════════

def _raw_ohlcv(n=140, *, expanding, seed=5):
    """Raw OHLCV **exactly as the production path delivers it**: no ATR / BBW column."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100.0 + np.cumsum(rng.normal(0.02, 0.20, n))
    # true range widens toward the end when expanding, collapses when coiling
    width = np.linspace(0.2, 6.0, n) if expanding else np.linspace(6.0, 0.05, n)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + width,
            "Low": close - width,
            "Close": close,
            "Volume": rng.integers(1_000_000, 2_000_000, n).astype(float),
        },
        index=idx,
    )


def test_squeeze_gate_fails_closed_when_volatility_cannot_be_measured():
    """Audit #11: the old gate defaulted to ``True``. Missing data must now reject."""
    ok, pctile = _volatility_squeeze_gate(pd.DataFrame({"Close": [1.0, 2.0, 3.0]}))
    assert ok is False and pctile is None
    assert _volatility_squeeze_gate(None) == (False, None)
    assert _volatility_squeeze_gate(pd.DataFrame()) == (False, None)


def test_squeeze_gate_is_computed_from_raw_ohlcv():
    """No ``ATR`` column anywhere: the gate has to build one itself, and it has to
    discriminate between a coil and a maximum-expansion tape."""
    coiled = _raw_ohlcv(expanding=False)
    expanded = _raw_ohlcv(expanding=True)
    assert "ATR" not in coiled.columns and "BBW" not in coiled.columns

    coiled_ok, coiled_pctile = _volatility_squeeze_gate(coiled)
    expanded_ok, expanded_pctile = _volatility_squeeze_gate(expanded)
    assert coiled_ok is True and coiled_pctile <= 0.25
    assert expanded_ok is False and expanded_pctile > 0.25


def _pre_diamond(df, **over):
    close = float(df["Close"].iloc[-1])
    kw = dict(
        df=df,
        gold_zone_price=close * 0.99,
        shadow_low=close * 0.995,
        weekly_bias="BULLISH",
        confluence_series=pd.Series([4, 5, 6]),
        spy_df=None,
    )
    kw.update(over)
    return Opt.detect_pre_diamond(**kw)


def _with_volume_ramp(df):
    df = df.copy()
    df.iloc[-3:, df.columns.get_loc("Volume")] = float(df["Volume"].tail(10).mean()) * 3.0
    return df


def test_pre_diamond_rejects_a_maximum_expansion_name():
    """The audit's headline symptom: "a name at the 95th BBW percentile passes identically
    to one at the 2nd". It must not any more."""
    expanded = _with_volume_ramp(_raw_ohlcv(expanding=True))
    result = _pre_diamond(expanded)
    assert result["is_pre_diamond"] is False
    assert result["gates"]["squeeze"][0] is False
    # and every *other* gate passed: the squeeze is provably what rejected it
    assert all(ok for name, (ok, _) in result["gates"].items() if name != "squeeze")


def test_pre_diamond_fires_on_a_genuine_coil_from_raw_ohlcv():
    coiled = _with_volume_ramp(_raw_ohlcv(expanding=False))
    result = _pre_diamond(coiled)
    assert result["is_pre_diamond"] is True
    assert result["volatility_state"] == "SQUEEZED"
    # the advertised "bottom 25% of 60-day ATR range" is now an actual measurement
    assert result["atr_pctile_60d"] <= 0.25


def test_pre_diamond_reports_every_gate_with_its_observed_value():
    result = _pre_diamond(_raw_ohlcv(expanding=True), weekly_bias="BEARISH")
    gates = result["gates"]
    assert set(gates) == {
        "confluence_band",
        "confluence_rising",
        "squeeze",
        "volume_ramp",
        "near_support",
        "weekly_not_bearish",
    }
    assert gates["weekly_not_bearish"] == (False, "BEARISH")
    assert all(isinstance(ok, bool) for ok, _ in gates.values())


def test_stock_stop_price_uses_a_real_atr_not_a_flat_five_percent():
    """Same dead column: the ledger advertised a 1.5× ATR stop and always shipped −5%."""
    df = _raw_ohlcv(expanding=True)
    price = float(df["Close"].iloc[-1])
    stop = _stock_stop_price(df, price)
    assert stop is not None
    assert stop != round(price * 0.95, 2)
    assert stop < price


def test_stock_stop_price_falls_back_only_when_atr_is_unavailable():
    bare = pd.DataFrame({"Close": [10.0, 11.0, 12.0]})
    assert _stock_stop_price(bare, 12.0) == round(12.0 * 0.95, 2)


# ═══════════════════════════════════════════════════════════════════════════
#  #13: compute_explosion_score triple-counts and pays for missing data
# ═══════════════════════════════════════════════════════════════════════════

def _row(**over):
    row = {
        "pre_diamond_status": {"is_pre_diamond": False},
        "10x Potential": 0,
        "qs": 0.0,
        "d_status": "None",
        "GEX Regime": "n/a",
    }
    row.update(over)
    return row


def test_missing_options_data_scores_zero_not_five():
    """``gex_regime`` defaults to "n/a" whenever the chain fetch fails. Paying +5 for that
    ranked names with no listed options above names measured as TURBULENT."""
    assert compute_explosion_score(_row(**{"GEX Regime": "n/a"})) == 0.0
    assert compute_explosion_score(_row(**{"GEX Regime": ""})) == 0.0
    assert explosion_score_detail(_row())["gex_available"] is False
    assert explosion_score_detail(_row())["components"]["gex"] == 0.0


def test_measured_regimes_are_flagged_available():
    for regime in ("🛡️ STABLE", "⚠️ TURBULENT"):
        detail = explosion_score_detail(_row(**{"GEX Regime": regime}))
        assert detail["gex_available"] is True


def test_short_gamma_outscores_long_gamma_on_an_explosion_radar():
    """STABLE means spot above the flip, dealers long gamma, hedging that DAMPENS moves.
    The explosion score used to pay +10 for exactly the pinning regime."""
    turbulent = compute_explosion_score(_row(**{"GEX Regime": "⚠️ TURBULENT"}))
    stable = compute_explosion_score(_row(**{"GEX Regime": "🛡️ STABLE"}))
    unknown = compute_explosion_score(_row())
    assert turbulent > stable
    assert turbulent == 10.0
    assert stable == unknown == 0.0


def test_one_confluence_event_is_counted_once():
    """A pre-diamond used to add 20-30 directly **and** a 10x point that re-entered scaled by
    2.5. Holding the 10x score fixed, the pre-diamond must contribute exactly its own term."""
    base = _row(**{"10x Potential": 4})
    with_pre = _row(**{"10x Potential": 4, "pre_diamond_status": {
        "is_pre_diamond": True, "signal_strength": "🔥 IMMINENT BREAKOUT"}})
    assert compute_explosion_score(with_pre) - compute_explosion_score(base) == pytest.approx(30.0)

    with_blue = _row(**{"10x Potential": 4, "d_status": "🔷 BLUE"})
    assert compute_explosion_score(with_blue) - compute_explosion_score(base) == pytest.approx(15.0)


def test_pink_status_earns_nothing():
    """``elif "PINK" not in d_status: score += 0`` was dead code."""
    assert compute_explosion_score(_row(d_status="💎 PINK")) == compute_explosion_score(
        _row(d_status="None")
    )


def test_explosion_components_respect_their_documented_weights():
    maxed = _row(**{
        "pre_diamond_status": {"is_pre_diamond": True, "signal_strength": "🔥 IMMINENT"},
        "10x Potential": TEN_X_MAX_SCORE,
        "qs": 100.0,
        "d_status": "🔷 BLUE",
        "GEX Regime": "⚠️ TURBULENT",
    })
    detail = explosion_score_detail(maxed)
    assert detail["components"] == pytest.approx(
        {"pre_diamond": 30.0, "tenx": 25.0, "qe": 20.0, "diamond": 15.0, "gex": 10.0}
    )
    assert detail["score"] == 100.0


def test_score_10x_no_longer_pays_for_a_diamond_that_scores_elsewhere():
    """Audit #13: the diamond point re-entered ``compute_explosion_score`` through the 30%
    and 15% terms. The flag stays for display; the point is gone."""
    df = _synthetic_ohlcv(300, seed=4)
    info = {"marketCap": 1e9}
    plain, plain_flags = score_10x_potential(df, info)
    with_blue, blue_flags = score_10x_potential(
        df, info, latest_d={"type": "blue", "date": df.index[-1], "price": 1.0}
    )
    with_pre, pre_flags = score_10x_potential(
        df, info, pre_diamond={"is_pre_diamond": True, "signal_strength": "🔥 IMMINENT"}
    )
    assert with_blue == plain == with_pre
    assert blue_flags["blue_diamond"] is True
    assert "pre_diamond" in pre_flags
    assert "blue_diamond" not in plain_flags
    # `flags` holds MATCHED FACTORS only: the Flags column is rendered as
    # ", ".join(sorted(flags.keys())), so bookkeeping keys would display as factors.
    assert "max_score" not in plain_flags
    assert TEN_X_MAX_SCORE == 9


def test_ten_x_score_never_exceeds_its_advertised_maximum():
    df = _synthetic_ohlcv(300, seed=4)
    info = {
        "marketCap": 1e9,
        "revenueGrowth": 0.9,
        "shortPercentOfFloat": 0.4,
        "freeCashflow": 5e8,
    }
    score, _ = score_10x_potential(df, info, spy_df=_synthetic_ohlcv(300, seed=9, drift=0.0))
    assert 0 <= score <= TEN_X_MAX_SCORE


# ═══════════════════════════════════════════════════════════════════════════
#  #23: "PoP" blends long and short win rates
# ═══════════════════════════════════════════════════════════════════════════

def _win_rate_fixture():
    """The audit's exact counter-example: 3 blue entries that all lose, 7 pink fades that all
    win. Pooled, that reads 70% under the label "win rate for Diamond signals"."""
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    diamonds = []
    fwd = 5
    for j, at in enumerate((2, 6, 10)):          # blue: price falls over the next 5 bars
        close[at + fwd] = 90.0 - j
        diamonds.append({"date": idx[at], "price": 100.0, "type": "blue"})
    for j, at in enumerate((16, 20, 24, 28, 32, 36, 40)):  # pink: price falls → fade wins
        close[at + fwd] = 90.0 - j
        diamonds.append({"date": idx[at], "price": 100.0, "type": "pink"})
    df = pd.DataFrame({"Close": close}, index=idx)
    return df, diamonds, fwd


def test_win_rate_does_not_blend_long_entries_with_short_fades():
    df, diamonds, fwd = _win_rate_fixture()

    blended_wr, _, blended_n = diamond_win_rate(
        df, diamonds, forward_bars=fwd, side="all", holdout_frac=None
    )
    assert (blended_wr, blended_n) == (70.0, 10), "fixture must reproduce the audit's 70%"

    entry_wr, _, entry_n = diamond_win_rate(
        df, diamonds, forward_bars=fwd, holdout_frac=None
    )
    assert (entry_wr, entry_n) == (0.0, 3), "the long side actually went 0 for 3"


def test_diamond_win_rate_defaults_to_the_entry_side():
    df, diamonds, fwd = _win_rate_fixture()
    default = diamond_win_rate(df, diamonds, forward_bars=fwd, holdout_frac=None)
    explicit = diamond_win_rate(df, diamonds, forward_bars=fwd, side="blue", holdout_frac=None)
    assert default == explicit


def test_diamond_win_rate_by_side_reports_both_with_their_own_n():
    df, diamonds, fwd = _win_rate_fixture()
    sides = diamond_win_rate_by_side(df, diamonds, forward_bars=fwd, holdout_frac=None)
    assert sides["blue"][0] == 0.0 and sides["blue"][2] == 3
    assert sides["pink"][0] == 100.0 and sides["pink"][2] == 7


def test_win_rate_is_zero_with_no_signals_of_that_side():
    df, diamonds, fwd = _win_rate_fixture()
    only_pink = [d for d in diamonds if d["type"] == "pink"]
    assert diamond_win_rate(df, only_pink, forward_bars=fwd, holdout_frac=None) == (0.0, 0.0, 0)


# ═══════════════════════════════════════════════════════════════════════════
#  Medium findings in the same file
# ═══════════════════════════════════════════════════════════════════════════

def test_pink_diamond_weekly_filter_is_not_a_tautology():
    """The guard read ``if wk_bias in ("BEARISH", "MIXED", "UNKNOWN", "BULLISH")``, all four
    values ``weekly_trend_label`` can return."""
    labels = {"BEARISH", "MIXED", "UNKNOWN", "BULLISH"}
    for line in OPTIONS_SRC.splitlines():
        if "wk_bias in (" in line:
            assert not labels.issubset({tok.strip(" ()\"',:") for tok in line.split()}), line


def test_weekly_trend_label_returns_only_the_four_known_labels():
    """Pins the enumeration the tautology depended on, so the next reader can see why."""
    df = _synthetic_ohlcv(400, seed=6)
    assert weekly_trend_label(_weekly(df))[0] in {"BEARISH", "MIXED", "UNKNOWN", "BULLISH"}
    assert weekly_trend_label(None)[0] == "UNKNOWN"


def test_bbw_percentile_ranks_against_a_fixed_window_not_the_whole_frame():
    """``score_10x_potential`` ranked today's BBW against the entire passed frame while the
    sibling sieve used ``tail(252)``, so "squeeze" meant different things depending on how
    much history the caller happened to fetch."""
    long_frame = _synthetic_ohlcv(1200, seed=8)
    short_frame = long_frame.tail(400)
    info = {"marketCap": 1e9}
    _, long_flags = score_10x_potential(long_frame, info)
    _, short_flags = score_10x_potential(short_frame, info)
    assert long_flags["bbw_pctile"] == short_flags["bbw_pctile"]
    assert long_flags.get("vol_squeeze") == short_flags.get("vol_squeeze")


def test_discrete_kelly_inputs_actually_move_the_number():
    """Changing ``win_p_disc`` from 5.0 to 94.0 used to leave "Adj. Kelly %" bit-identical
    because ``use_quant=True`` with ``variance > 0`` always took the continuous branch."""
    low = kelly_criterion(5.0, 1.0, 1.0, use_quant=False)
    high = kelly_criterion(94.0, 1.0, 1.0, use_quant=False)
    assert low != high

    # the continuous branch is blind to them: which is precisely why the scanner must not
    # rely on it alone for a defined-credit short put
    quant_kw = dict(use_quant=True, expected_return=0.20, variance=0.04)
    assert kelly_criterion(5.0, 1.0, 1.0, **quant_kw) == kelly_criterion(
        94.0, 1.0, 1.0, **quant_kw
    )


def test_scanner_reports_the_more_conservative_of_the_two_kelly_solves():
    """Source-level pin: the scanner must compute *both* solves and surface ``min``, so the
    four discrete inputs it builds are no longer dead."""
    assert "k_disc_full, k_disc_half = kelly_criterion(" in OPTIONS_SRC
    assert "k_half = round(min(k_cont_half, k_disc_half), 1)" in OPTIONS_SRC
    assert '"kelly_discrete_half": k_disc_half,' in OPTIONS_SRC
