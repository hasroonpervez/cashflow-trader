"""Tests for modules/asymmetry.py, pure numpy/pandas, no network, headless.

The two load-bearing tests in this file:
  * ``test_no_lookahead_*``: a function's output at index i must be identical
    when future rows are mutated and appended. If this ever fails, every
    backtest built on the module is fiction.
  * ``test_verdict_partial_data_can_never_be_confident``, the honesty
    invariant. Partial data must not be able to produce a confident verdict
    under any combination of inputs.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules.asymmetry import (
    AsymmetryVerdict,
    BaseRateReport,
    CONFIDENT_THRESHOLD,
    CONVEX_MIN_RATIO,
    MULTIPLE_THRESHOLDS,
    STATUS_REJECTED,
    STATUS_UNVALIDATED,
    STATUS_VALIDATED,
    asymmetry_verdict,
    atr_at,
    atr_upside_target,
    base_rate_report,
    catalyst_component,
    catalyst_window,
    coiled_spring_score,
    convexity_score,
    ev_rank,
    expected_value,
    iv_percentile,
    iv_rank,
    iv_rank_series,
    kelly_fraction_skewed,
    realized_vol_compression,
    support_from_swing_low,
)

MODULE_PATH = Path(__file__).resolve().parent.parent / "modules" / "asymmetry.py"


# ---------------------------------------------------------------------------
# fixtures / builders
# ---------------------------------------------------------------------------

def _fake_daily(n: int = 200, seed: int = 11, flat: bool = False) -> pd.DataFrame:
    """Lowercase-column OHLCV (house style in validated_signals.py)."""
    if flat:
        c = pd.Series(np.full(n, 50.0))
        return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                             "volume": np.full(n, 1e6)})
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0015, 0.018, n)
    c = pd.Series(40.0 * np.exp(np.cumsum(steps)))
    return pd.DataFrame({
        "open": c.shift(1).fillna(c.iloc[0]),
        "high": c * (1 + np.abs(rng.normal(0, 0.006, n))),
        "low": c * (1 - np.abs(rng.normal(0, 0.006, n))),
        "close": c,
        "volume": rng.integers(5e5, 5e6, n).astype(float),
    })


def _good_convexity():
    return convexity_score(100.0, 90.0, upside_target=160.0,
                           gap_risk=False, liquid_stop=True)


def _full_spring():
    return coiled_spring_score(iv_rank_value=0.1, vol_compression_ratio=0.5,
                               float_shares=15e6, short_interest_pct=25.0,
                               days_to_event=4)


def _validated_base_rate(seed: int = 5) -> BaseRateReport:
    rng = np.random.default_rng(seed)
    n = 300
    flags = np.array([i % 2 == 0 for i in range(n)])
    rets = np.where(flags, rng.normal(0.06, 0.07, n), rng.normal(0.0, 0.07, n))
    return base_rate_report("test-screen", flags, rets)


def _positive_ev():
    return expected_value([(0.15, 9.0), (0.25, 1.0), (0.60, -0.30)])


# ---------------------------------------------------------------------------
# 1. expected_value / ev_rank
# ---------------------------------------------------------------------------

def test_expected_value_hand_computed():
    # 10% chance of a 10-bagger (+9), 90% chance of -50%
    res = expected_value([(0.10, 9.0), (0.90, -0.50)])
    assert res is not None
    assert res.ev == pytest.approx(0.10 * 9.0 - 0.90 * 0.50)   # +0.45
    assert res.upside_capture == pytest.approx(0.9)
    assert res.downside_capture == pytest.approx(0.45)
    assert res.asymmetry_ratio == pytest.approx(2.0)
    assert res.p_win == pytest.approx(0.10)
    assert res.p_loss == pytest.approx(0.90)
    assert res.best_payoff == 9.0 and res.worst_payoff == -0.50


def test_expected_value_identity_ev_equals_up_minus_down():
    res = expected_value([{"p": 0.05, "payoff": 19.0}, {"p": 0.20, "payoff": 0.5},
                          {"p": 0.75, "payoff": -0.40}])
    assert res.ev == pytest.approx(res.upside_capture - res.downside_capture)


def test_expected_value_accepts_mapping_form():
    res = expected_value({"moon": (0.1, 9.0), "bust": (0.9, -1.0)})
    assert res.ev == pytest.approx(0.1 * 9.0 - 0.9)


def test_expected_value_empty_returns_none():
    assert expected_value([]) is None
    assert expected_value(None) is None


def test_expected_value_probabilities_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1"):
        expected_value([(0.5, 2.0), (0.2, -1.0)])


def test_expected_value_rejects_negative_probability():
    with pytest.raises(ValueError, match="negative probability"):
        expected_value([(-0.1, 2.0), (1.1, -1.0)])


def test_expected_value_no_downside_flags_instead_of_dividing_by_zero():
    res = expected_value([(0.5, 1.0), (0.5, 2.0)])
    assert res.asymmetry_ratio is None
    assert "no-modeled-downside" in res.flags
    assert res.downside_capture == 0.0


def test_ev_rank_orders_by_payoff_not_by_number_of_positive_outcomes():
    """A candidate with SIX bullish outcomes must lose to one with real EV."""
    many_small_wins = [(0.15, 0.02), (0.15, 0.03), (0.15, 0.04),
                       (0.15, 0.05), (0.15, 0.06), (0.25, -0.60)]
    one_real_edge = [(0.20, 9.0), (0.80, -0.50)]
    out = ev_rank({"POINTS": many_small_wins, "PAYOFF": one_real_edge})
    assert [r["name"] for r in out] == ["PAYOFF", "POINTS"]
    assert out[0]["rank"] == 1 and out[0]["ev"] > 0
    assert out[1]["ev"] < 0


def test_ev_rank_accepts_sequence_and_reports_asymmetry_ratio():
    out = ev_rank([("A", [(0.5, 1.0), (0.5, -0.5)]),
                   ("B", [(0.1, 9.0), (0.9, -0.5)])])
    assert {r["name"] for r in out} == {"A", "B"}
    assert all(r["asymmetry_ratio"] is not None for r in out)


def test_ev_rank_puts_unrankable_last_not_at_zero():
    out = ev_rank({"GOOD": [(0.5, 1.0), (0.5, -0.2)],
                   "BAD": [],
                   "BROKEN": [(0.3, 1.0), (0.3, -1.0)]})
    assert out[0]["name"] == "GOOD"
    tail = {r["name"] for r in out[1:]}
    assert tail == {"BAD", "BROKEN"}
    assert all(r["ev"] is None and "unrankable" in r["flags"] for r in out[1:])


# ---------------------------------------------------------------------------
# 2. convexity_score
# ---------------------------------------------------------------------------

def test_convexity_hand_computed():
    r = convexity_score(100.0, 90.0, upside_target=160.0, gap_risk=False, liquid_stop=True)
    assert r.bounded_loss_frac == pytest.approx(0.10)
    assert r.upside_frac == pytest.approx(0.60)
    assert r.convexity_ratio == pytest.approx(6.0)
    assert r.downside_bounded is True
    assert r.confidence == pytest.approx(1.0)
    assert r.is_convex is True
    assert r.upside_source == "explicit_target"


def test_convexity_from_atr_expansion():
    r = convexity_score(100.0, 90.0, atr=2.0, atr_expansion_mult=3.0,
                        gap_risk=False, liquid_stop=True)
    assert r.upside_frac == pytest.approx(0.06)           # 3 * 2 / 100
    assert r.convexity_ratio == pytest.approx(0.6)
    assert r.is_convex is False                            # below 3:1
    assert r.upside_source == "atr_expansion"


def test_convexity_takes_the_conservative_of_two_estimates():
    r = convexity_score(100.0, 90.0, atr=2.0, prior_range_expansion_frac=0.20,
                        gap_risk=False, liquid_stop=True)
    assert r.upside_frac == pytest.approx(0.06)            # min(0.06, 0.20)
    assert r.upside_source == "conservative_of_atr_and_prior_range"
    assert r.components["upside_frac_prior_range"] == pytest.approx(0.20)


def test_convexity_gap_risk_marks_downside_unbounded():
    r = convexity_score(100.0, 90.0, upside_target=160.0, gap_risk=True, liquid_stop=True)
    assert r.downside_bounded is False
    assert "downside-unbounded" in r.flags and "gap-risk" in r.flags
    assert r.risk_adjusted_ratio == pytest.approx(0.60)    # vs a -100% loss
    assert r.is_convex is False


def test_convexity_illiquid_stop_marks_downside_unbounded():
    r = convexity_score(100.0, 90.0, upside_target=160.0, gap_risk=False, liquid_stop=False)
    assert r.downside_bounded is False
    assert "no-liquid-stop" in r.flags
    assert r.is_convex is False


def test_convexity_unknown_risk_is_not_treated_as_safe():
    r = convexity_score(100.0, 90.0, upside_target=160.0)   # gap/liquidity unknown
    assert r.downside_bounded is None                       # unknown, NOT True
    assert "gap-risk-unknown" in r.flags and "stop-liquidity-unknown" in r.flags
    assert r.confidence == pytest.approx(0.7 * 0.8)
    assert r.is_convex is False


def test_convexity_zero_atr_yields_no_upside_estimate():
    r = convexity_score(100.0, 90.0, atr=0.0, gap_risk=False, liquid_stop=True)
    assert r.convexity_ratio is None
    assert "no-upside-estimate" in r.flags
    assert r.bounded_loss_frac == pytest.approx(0.10)       # the loss is still known


def test_convexity_requires_a_stop():
    assert convexity_score(100.0, None, upside_target=200.0) is None
    assert convexity_score(0.0, 90.0, upside_target=200.0) is None


def test_convexity_rejects_stop_above_entry():
    r = convexity_score(100.0, 110.0, upside_target=160.0)
    assert r.convexity_ratio is None
    assert "invalid-stop-above-entry" in r.flags
    assert r.confidence == 0.0


# ---------------------------------------------------------------------------
# 3. iv_rank / iv_percentile
# ---------------------------------------------------------------------------

def test_iv_rank_hand_computed():
    hist = [10.0] * 10 + [50.0] * 10 + [30.0] * 10      # min 10, max 50, now 30
    assert iv_rank(hist) == pytest.approx((30 - 10) / (50 - 10))


def test_iv_rank_explicit_now_and_bounds():
    hist = list(np.linspace(10, 50, 40))
    assert iv_rank(hist, iv_now=10.0) == pytest.approx(0.0)
    assert iv_rank(hist, iv_now=50.0) == pytest.approx(1.0)
    assert iv_rank(hist, iv_now=999.0) == pytest.approx(1.0)   # clipped, not >1
    assert iv_rank(hist, iv_now=-5.0) == pytest.approx(0.0)


def test_iv_rank_all_equal_returns_none_not_zero():
    assert iv_rank([25.0] * 60) is None


def test_iv_rank_empty_and_short_history_return_none():
    assert iv_rank([]) is None
    assert iv_rank(None) is None
    assert iv_rank([10.0, 20.0, 30.0]) is None                 # < min_observations
    assert iv_rank([10.0, 20.0, 30.0], min_observations=3) == pytest.approx(1.0)


def test_iv_rank_ignores_non_finite_and_respects_lookback():
    hist = [999.0] * 50 + list(np.linspace(10, 30, 30))
    # only the last 30 observations count -> max is 30, not 999
    assert iv_rank(hist, lookback=30) == pytest.approx(1.0)
    assert iv_rank([np.nan] * 30) is None


def test_iv_percentile_hand_computed_with_ties():
    hist = [10.0] * 25 + [20.0] * 25 + [30.0] * 25 + [40.0] * 25
    # now = 30: 50 below, 25 ties -> (50 + 12.5) / 100
    assert iv_percentile(hist, iv_now=30.0) == pytest.approx(0.625)


def test_iv_percentile_all_equal_returns_none():
    assert iv_percentile([12.0] * 40) is None
    assert iv_percentile([]) is None


def test_iv_rank_and_percentile_disagree_on_a_single_spike():
    hist = [15.0] * 99 + [200.0]                # one crisis print in the window
    ivr = iv_rank(hist, iv_now=16.0)
    ivp = iv_percentile(hist, iv_now=16.0)
    assert ivr < 0.02 and ivp > 0.95            # exactly why both are exposed


def test_iv_rank_series_matches_scalar_and_is_bounded():
    rng = np.random.default_rng(4)
    hist = pd.Series(np.abs(rng.normal(30, 8, 400)))
    s = iv_rank_series(hist, lookback=252, min_observations=20)
    assert len(s) == 400
    assert s.iloc[:19].isna().all()
    assert ((s.dropna() >= 0) & (s.dropna() <= 1)).all()
    scalar = iv_rank(hist.tolist(), lookback=252, min_observations=20)
    assert s.iloc[-1] == pytest.approx(scalar)


def test_iv_rank_series_flat_window_is_nan_not_zero():
    s = iv_rank_series(pd.Series([20.0] * 50), lookback=252, min_observations=20)
    assert s.dropna().empty
    assert iv_rank_series(pd.Series(dtype=float)).empty


# ---------------------------------------------------------------------------
# 4/5. catalyst window + coiled spring
# ---------------------------------------------------------------------------

def test_catalyst_window_peaks_a_few_days_before_the_event():
    days = list(range(0, 61))
    vals = [catalyst_window(d) for d in days]
    assert days[int(np.argmax(vals))] == 3
    assert catalyst_window(3) == pytest.approx(1.5)


def test_catalyst_window_decays_after_the_event():
    assert catalyst_window(-1) < catalyst_window(0)        # the IV crush
    assert catalyst_window(-1) < 1.0
    assert catalyst_window(-1) < catalyst_window(-10) < catalyst_window(-100)
    assert catalyst_window(-100) == pytest.approx(1.0, abs=1e-3)


def test_catalyst_window_far_out_is_neutral():
    assert catalyst_window(365) == pytest.approx(1.0, abs=1e-3)


def test_catalyst_window_none_in_none_out():
    assert catalyst_window(None) is None
    assert catalyst_component(None) is None
    assert catalyst_component(3) == pytest.approx(1.0)


def test_coiled_spring_full_inputs_gives_full_confidence():
    r = _full_spring()
    assert r.confidence == pytest.approx(1.0)
    assert r.missing == [] and r.flags == []
    assert r.is_reliable is True
    assert 0.0 <= r.score <= 100.0
    assert set(r.components) == {"cheap_optionality", "compression", "small_float",
                                 "short_interest", "catalyst"}


def test_coiled_spring_missing_inputs_lower_confidence_but_do_not_score_zero():
    r = coiled_spring_score(iv_rank_value=0.10)     # only one of five known
    assert r.score == pytest.approx(90.0)           # NOT 100*0.30*0.9 = 27
    assert r.confidence == pytest.approx(0.30)
    assert r.is_reliable is False
    assert "partial-data" in r.flags and "low-confidence" in r.flags
    assert sorted(r.missing) == ["catalyst", "compression", "short_interest", "small_float"]


def test_coiled_spring_low_iv_rank_beats_high_iv_rank():
    kw = dict(vol_compression_ratio=0.5, float_shares=15e6,
              short_interest_pct=25.0, days_to_event=4)
    cheap = coiled_spring_score(iv_rank_value=0.05, **kw)
    rich = coiled_spring_score(iv_rank_value=0.95, **kw)
    assert cheap.score > rich.score
    assert cheap.confidence == rich.confidence == pytest.approx(1.0)


def test_coiled_spring_no_inputs_returns_none():
    assert coiled_spring_score() is None


def test_coiled_spring_component_edges():
    r = coiled_spring_score(iv_rank_value=0.0, vol_compression_ratio=0.1,
                            float_shares=1e6, short_interest_pct=99.0, days_to_event=3)
    assert r.score == pytest.approx(100.0)
    assert r.components["catalyst"] == pytest.approx(1.0)
    r2 = coiled_spring_score(iv_rank_value=1.0, vol_compression_ratio=3.0,
                             float_shares=5e9, short_interest_pct=0.0, days_to_event=-1)
    # every component pinned at its floor; only the post-event catalyst decay
    # (which starts just above the floor) keeps the score off exactly zero
    assert r2.score < 1.0
    assert all(v == pytest.approx(0.0) for k, v in r2.components.items() if k != "catalyst")
    assert r2.components["catalyst"] < 0.05


# ---------------------------------------------------------------------------
# 6. Kelly
# ---------------------------------------------------------------------------

def test_kelly_classic_symmetric_case():
    # p=0.6, b=1, a=1  ->  f* = 0.6 - 0.4/1 = 0.2
    r = kelly_fraction_skewed(0.6, 1.0, 1.0)
    assert r.full_kelly == pytest.approx(0.2)
    assert r.recommended_fraction == pytest.approx(0.05)     # quarter Kelly
    assert r.capped is False


def test_kelly_hand_computed_for_a_10x_payoff():
    # a 10-bagger is win_mult=9 (net profit multiple); p=0.15, total loss
    # f* = (0.15*9 - 0.85*1) / (1*9) = 0.5/9 = 0.055555...
    r = kelly_fraction_skewed(0.15, 9.0, 1.0)
    assert r.full_kelly == pytest.approx(0.5 / 9.0)
    assert r.edge_per_unit == pytest.approx(0.5)
    assert r.recommended_fraction == pytest.approx(0.25 * 0.5 / 9.0)
    assert "power-law-payoff-p-estimate-dominates-sizing" in r.flags


def test_kelly_10x_at_a_realistic_probability_says_do_not_bet():
    # 5% shot at a 10-bagger with total loss is NEGATIVE EV: 0.05*9 - 0.95 = -0.5
    r = kelly_fraction_skewed(0.05, 9.0, 1.0)
    assert r.full_kelly == 0.0 and r.recommended_fraction == 0.0
    assert r.edge_per_unit == pytest.approx(-0.5)
    assert "no-edge" in r.flags and "do-not-bet" in r.flags


def test_kelly_partial_loss_is_not_the_symmetric_approximation():
    # p=0.3, b=3, a=0.5 -> f* = (0.9 - 0.35) / 1.5 = 0.366666...
    r = kelly_fraction_skewed(0.3, 3.0, 0.5)
    assert r.full_kelly == pytest.approx(0.55 / 1.5)
    symmetric_shortcut = (0.3 * 3.0 - 0.7) / 3.0             # = 0.0667, wrong here
    assert r.full_kelly != pytest.approx(symmetric_shortcut)
    assert r.recommended_fraction == pytest.approx(0.25 * 0.55 / 1.5)


def test_kelly_converges_to_p_for_huge_multiples():
    """A 1,000,000x payoff does NOT justify a bigger bet than a 10x one."""
    huge = kelly_fraction_skewed(0.2, 1e6, 1.0)
    assert huge.full_kelly == pytest.approx(0.2, abs=1e-5)


def test_kelly_p_win_zero_and_one():
    assert kelly_fraction_skewed(0.0, 9.0, 1.0).recommended_fraction == 0.0
    certain = kelly_fraction_skewed(1.0, 9.0, 1.0)
    assert certain.full_kelly == pytest.approx(1.0)
    assert certain.recommended_fraction == pytest.approx(0.20)   # hard cap
    assert certain.capped is True
    assert "p_win=1-is-not-a-real-estimate" in certain.flags


def test_kelly_haircut_parameter_is_honoured():
    full = kelly_fraction_skewed(0.6, 1.0, 1.0, fraction_of_full=1.0, max_fraction=1.0)
    half = kelly_fraction_skewed(0.6, 1.0, 1.0, fraction_of_full=0.5, max_fraction=1.0)
    assert full.recommended_fraction == pytest.approx(0.2)
    assert half.recommended_fraction == pytest.approx(0.1)


def test_kelly_missing_inputs_return_none_and_bad_inputs_raise():
    assert kelly_fraction_skewed(None, 9.0, 1.0) is None
    assert kelly_fraction_skewed(0.2, None, 1.0) is None
    with pytest.raises(ValueError):
        kelly_fraction_skewed(1.5, 9.0, 1.0)
    with pytest.raises(ValueError):
        kelly_fraction_skewed(0.2, -1.0, 1.0)
    with pytest.raises(ValueError):
        kelly_fraction_skewed(0.2, 9.0, 0.0)
    with pytest.raises(ValueError):
        kelly_fraction_skewed(0.2, 9.0, 1.0, fraction_of_full=0.0)


# ---------------------------------------------------------------------------
# 7. base_rate_report, the honesty layer
# ---------------------------------------------------------------------------

def test_base_rate_without_history_is_unvalidated():
    rep = base_rate_report("10x Potential")
    assert rep.validation_status == STATUS_UNVALIDATED
    assert rep.is_validated is False
    assert "never-base-rated" in rep.flags
    assert rep.outcomes == {} and rep.gate is None


def test_base_rate_precision_recall_lift_hand_computed():
    rets = [10.0, 5.0, 1.5, 0.5, -1.0, -0.5, 0.0, 0.0, 12.0, -0.9]
    flags = [True, True, False, True, True, False, False, False, False, True]
    rep = base_rate_report("hand", flags, rets)
    assert rep.n_candidates == 10 and rep.n_flagged == 5

    two = rep.outcomes["2x"]                      # r >= +1.0 -> 4 hits of 10
    assert two["base_rate"] == pytest.approx(0.4)
    assert two["precision"] == pytest.approx(2 / 5)
    assert two["recall"] == pytest.approx(2 / 4)
    assert two["lift"] == pytest.approx(1.0)

    ten = rep.outcomes["10x"]                     # r >= +9.0 -> 2 hits of 10
    assert ten["base_rate"] == pytest.approx(0.2)
    assert ten["precision"] == pytest.approx(1 / 5)
    assert ten["recall"] == pytest.approx(0.5)
    assert set(rep.outcomes) == set(MULTIPLE_THRESHOLDS)


def test_base_rate_small_sample_is_unvalidated_not_validated():
    rng = np.random.default_rng(2)
    flags = np.array([True] * 40 + [False] * 60)
    rets = rng.normal(0.20, 0.05, 100)            # screaming edge, tiny sample
    rep = base_rate_report("small", flags, rets)
    assert rep.validation_status == STATUS_UNVALIDATED
    assert "insufficient-sample" in rep.flags


def test_base_rate_validated_requires_the_promotion_gate():
    rep = _validated_base_rate()
    assert rep.validation_status == STATUS_VALIDATED
    assert rep.is_validated is True
    assert rep.gate["pass"] is True
    assert rep.gate["n"] >= 100
    assert rep.gate["split_half"]["consistent"] is True


def test_base_rate_rejects_regime_beta_screen():
    """Great in the first half, negative in the second, the Blue Diamond v2 trap."""
    flagged_rets = np.concatenate([np.full(80, 0.08), np.full(80, -0.03)])
    rets = np.concatenate([flagged_rets, np.zeros(100)])
    flags = np.array([True] * 160 + [False] * 100)
    rep = base_rate_report("regime-beta", flags, rets)
    assert rep.validation_status == STATUS_REJECTED
    assert "failed-promotion-gate" in rep.flags
    assert rep.gate["split_half"]["consistent"] is False


def test_base_rate_length_mismatch_raises():
    with pytest.raises(ValueError, match="length mismatch"):
        base_rate_report("bad", [True, False], [1.0])


def test_base_rate_drops_non_finite_returns_transparently():
    rets = [10.0, np.nan, 1.5, np.inf, -0.5]
    flags = [True, True, True, False, False]
    rep = base_rate_report("nans", flags, rets)
    assert rep.n_candidates == 3
    assert any(f.startswith("dropped-non-finite") for f in rep.flags)


# ---------------------------------------------------------------------------
# 8. asymmetry_verdict, the partial-data invariant
# ---------------------------------------------------------------------------

def test_verdict_full_data_can_be_confident():
    v = asymmetry_verdict(
        "tst",
        ev_result=_positive_ev(),
        convexity=_good_convexity(),
        spring=_full_spring(),
        base_rate=_validated_base_rate(),
        kelly=kelly_fraction_skewed(0.15, 9.0, 1.0),
    )
    assert isinstance(v, AsymmetryVerdict)
    assert v.ticker == "TST"
    assert v.confidence >= CONFIDENT_THRESHOLD
    assert v.is_confident is True
    assert v.actionable is True
    assert v.validation_status == STATUS_VALIDATED
    assert "ASYMMETRIC" in v.verdict
    assert v.convexity_ratio == pytest.approx(6.0)
    assert v.convexity_ratio >= CONVEX_MIN_RATIO


@pytest.mark.parametrize("drop", ["ev_result", "convexity", "spring", "base_rate"])
def test_verdict_partial_data_can_never_be_confident(drop):
    """THE honesty invariant: any missing pillar forbids a confident verdict."""
    kwargs = dict(
        ev_result=_positive_ev(),
        convexity=_good_convexity(),
        spring=_full_spring(),
        base_rate=_validated_base_rate(),
    )
    kwargs[drop] = None
    v = asymmetry_verdict("tst", **kwargs)
    assert v.is_confident is False, f"partial data ({drop} missing) produced confidence"
    assert v.actionable is False
    assert v.confidence <= 0.40
    assert "partial-data" in v.flags


def test_verdict_no_inputs_at_all_is_not_confident():
    v = asymmetry_verdict("tst")
    assert v.is_confident is False and v.actionable is False
    assert v.confidence == 0.0
    assert v.ev is None
    assert v.validation_status == STATUS_UNVALIDATED
    assert "never-base-rated" in v.flags


def test_verdict_unvalidated_screen_caps_confidence():
    v = asymmetry_verdict(
        "tst",
        ev_result=_positive_ev(),
        convexity=_good_convexity(),
        spring=_full_spring(),
        base_rate=base_rate_report("never-measured"),
    )
    assert v.validation_status == STATUS_UNVALIDATED
    assert v.confidence <= 0.50
    assert v.is_confident is False
    assert "UNVALIDATED" in v.verdict


def test_verdict_unknown_downside_boundedness_caps_confidence():
    v = asymmetry_verdict(
        "tst",
        ev_result=_positive_ev(),
        convexity=convexity_score(100.0, 90.0, upside_target=160.0),   # gap risk unknown
        spring=_full_spring(),
        base_rate=_validated_base_rate(),
    )
    assert v.confidence <= 0.35
    assert v.is_confident is False


def test_verdict_unbounded_downside_says_not_asymmetric():
    v = asymmetry_verdict(
        "tst",
        ev_result=_positive_ev(),
        convexity=convexity_score(100.0, 90.0, upside_target=160.0,
                                  gap_risk=True, liquid_stop=True),
        spring=_full_spring(),
        base_rate=_validated_base_rate(),
    )
    assert "NOT ASYMMETRIC" in v.verdict
    assert v.is_confident is False


def test_verdict_negative_ev_is_never_actionable():
    v = asymmetry_verdict(
        "tst",
        outcomes=[(0.05, 9.0), (0.95, -0.60)],   # EV = 0.45 - 0.57 < 0
        convexity=_good_convexity(),
        spring=_full_spring(),
        base_rate=_validated_base_rate(),
    )
    assert v.ev < 0
    assert v.actionable is False
    assert "SKIP" in v.verdict


def test_verdict_accepts_raw_outcomes_and_reports_bad_distributions():
    v = asymmetry_verdict("tst", outcomes=[(0.5, 1.0), (0.2, -1.0)])
    assert v.ev is None
    assert any(f.startswith("bad-outcome-distribution") for f in v.flags)
    assert v.is_confident is False


# ---------------------------------------------------------------------------
# Price-series helpers + THE no-lookahead proof
# ---------------------------------------------------------------------------

def test_no_lookahead_price_series_functions():
    """THE most important test in this file.

    Output at index i must be byte-identical after future rows are mutated
    into garbage AND extra rows are appended. If a function ever peeks
    forward, this fails.
    """
    df = _fake_daily(200)
    i = 120
    before = {
        "atr": atr_at(df, i),
        "target": atr_upside_target(df, i),
        "support": support_from_swing_low(df, i, lookback=20),
        "compression": realized_vol_compression(df, i, fast=20, slow=100),
    }
    assert all(v is not None for v in before.values())

    poisoned = df.copy()
    poisoned.loc[i + 1:, ["open", "high", "low", "close"]] *= 100.0   # mutate the future
    poisoned.loc[i + 1:, "volume"] = 0.0
    future = _fake_daily(60, seed=99) * 3.0                            # append more future
    poisoned = pd.concat([poisoned, future], ignore_index=True)
    assert len(poisoned) == 260
    # guard the guard: the poisoning must really have changed the future, so
    # this test can never quietly degrade into a no-op
    assert poisoned["high"].max() > df["high"].max() * 10
    assert not poisoned["close"].iloc[i + 1: 200].equals(df["close"].iloc[i + 1: 200])
    # ...while leaving rows [0..i] untouched
    pd.testing.assert_frame_equal(poisoned.iloc[: i + 1], df.iloc[: i + 1])

    after = {
        "atr": atr_at(poisoned, i),
        "target": atr_upside_target(poisoned, i),
        "support": support_from_swing_low(poisoned, i, lookback=20),
        "compression": realized_vol_compression(poisoned, i, fast=20, slow=100),
    }
    for k in before:
        assert after[k] == pytest.approx(before[k]), f"{k} leaked future information"


def test_no_lookahead_iv_rank_series():
    rng = np.random.default_rng(8)
    hist = pd.Series(np.abs(rng.normal(30, 9, 300)))
    first = iv_rank_series(hist, lookback=252, min_observations=20)
    extended = pd.concat([hist, pd.Series(np.abs(rng.normal(300, 50, 120)))],
                         ignore_index=True)
    second = iv_rank_series(extended, lookback=252, min_observations=20)
    pd.testing.assert_series_equal(first, second.iloc[:300], check_names=False)


def test_causal_slice_index_validation():
    df = _fake_daily(50)
    assert support_from_swing_low(df, -1) == pytest.approx(support_from_swing_low(df, 49))
    with pytest.raises(IndexError):
        support_from_swing_low(df, 50)
    with pytest.raises(IndexError):
        atr_at(df, 999)


def test_series_helpers_on_degenerate_input():
    flat = _fake_daily(200, flat=True)
    assert atr_at(flat, 150) == pytest.approx(0.0)        # ATR really is zero
    assert atr_upside_target(flat, 150) is None           # ...so there is no target
    assert realized_vol_compression(flat, 150) is None    # ...and no ratio (0/0)

    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    assert atr_at(empty) is None
    assert support_from_swing_low(empty) is None
    assert realized_vol_compression(empty) is None

    short = _fake_daily(10)
    assert atr_at(short, 5) is None                       # not enough history
    assert realized_vol_compression(short) is None


def test_series_helpers_accept_capitalized_columns():
    df = _fake_daily(200).rename(columns=str.capitalize)
    assert atr_at(df, 150) is not None
    assert support_from_swing_low(df, 150) is not None
    assert realized_vol_compression(df, 150) is not None


def test_support_from_swing_low_is_the_trailing_minimum():
    df = _fake_daily(200)
    i, lb = 150, 20
    assert support_from_swing_low(df, i, lookback=lb) == pytest.approx(
        float(df["low"].iloc[i - lb + 1: i + 1].min()))


def test_end_to_end_pipeline_from_price_series():
    """The intended wiring: prices -> stop/target -> convexity -> verdict."""
    df = _fake_daily(250, seed=3)
    i = 200
    entry = float(df["close"].iloc[i])
    stop = support_from_swing_low(df, i, lookback=20)
    cvx = convexity_score(entry, stop, atr=atr_at(df, i),
                          gap_risk=False, liquid_stop=True)
    spring = coiled_spring_score(
        iv_rank_value=0.12,
        vol_compression_ratio=realized_vol_compression(df, i),
        float_shares=25e6, short_interest_pct=18.0, days_to_event=5,
    )
    v = asymmetry_verdict("pipe", ev_result=_positive_ev(), convexity=cvx,
                          spring=spring, base_rate=_validated_base_rate())
    assert cvx is not None and spring is not None
    assert spring.confidence == pytest.approx(1.0)
    assert v.confidence > 0 and isinstance(v.verdict, str) and v.verdict


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------

def test_module_has_no_streamlit_dependency():
    src = MODULE_PATH.read_text()
    assert "import streamlit" not in src
    assert "from streamlit" not in src


def test_module_reuses_existing_atr_and_promotion_gate():
    """No second ATR, no second promotion gate, reuse is part of the contract."""
    src = MODULE_PATH.read_text()
    assert "from .ta import TA" in src
    assert "from .validated_signals import promotion_gate" in src
    assert "TA.atr(" in src
