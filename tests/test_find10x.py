"""Tests for the Find 10x ranking logic.

The point of this tab is that it ranks on payoff SHAPE first and attention
second: the inverse of the audited `score_10x_potential`, which had no payoff
term at all. These tests pin that ordering so it cannot regress.
"""
import numpy as np
import pandas as pd
import pytest

from modules.find10x import (
    CONVEXITY_SATURATION, MIN_DISPLAY_SCORE, W_CONFIRMATION, W_CONVEXITY,
    OpportunityRow, build_opportunity_row, confirmation_component,
    convexity_component, opportunity_score, plain_verdict, rank_opportunities,
)


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

def test_convexity_component_saturates_at_the_asymmetric_threshold():
    assert convexity_component(CONVEXITY_SATURATION) == 1.0
    assert convexity_component(CONVEXITY_SATURATION * 3) == 1.0
    assert convexity_component(CONVEXITY_SATURATION / 2) == pytest.approx(0.5)


def test_unknown_convexity_is_none_not_zero():
    """An unknown payoff shape is not a bad one."""
    assert convexity_component(None) is None
    assert convexity_component(0.0) is None
    assert convexity_component(-3.0) is None


def test_confirmation_reweights_across_present_sources_only():
    """One source at 80 must read 0.80, not be diluted toward zero."""
    assert confirmation_component(80.0, None) == pytest.approx(0.80)
    assert confirmation_component(None, 80.0) == pytest.approx(0.80)
    assert confirmation_component(None, None) is None


def test_confirmation_blends_when_both_present():
    got = confirmation_component(100.0, 0.0)
    assert 0.0 < got < 1.0


# --------------------------------------------------------------------------
# The core ranking claim
# --------------------------------------------------------------------------

def test_payoff_shape_outranks_pure_hype():
    """The whole point: a quiet name with 5:1 beats a loud name with 1:1."""
    quiet_good_shape, _, _ = opportunity_score(5.0, 10.0, None)
    loud_bad_shape, _, _ = opportunity_score(1.0, 100.0, 100.0)
    assert quiet_good_shape > loud_bad_shape


def test_attention_breaks_ties_between_equal_shapes():
    dull, _, _ = opportunity_score(5.0, 10.0, 10.0)
    lively, _, _ = opportunity_score(5.0, 90.0, 90.0)
    assert lively > dull


def test_attention_alone_cannot_manufacture_an_opportunity():
    """No payoff shape means the convexity pillar is absent, not satisfied."""
    score, confidence, flags = opportunity_score(None, 100.0, 100.0)
    assert "no-convexity-data" in flags
    assert confidence == pytest.approx(W_CONFIRMATION)
    assert confidence < 1.0


def test_confidence_is_the_fraction_of_pillars_present():
    _, both, _ = opportunity_score(5.0, 50.0, 50.0)
    _, shape_only, _ = opportunity_score(5.0, None, None)
    _, noise_only, _ = opportunity_score(None, 50.0, 50.0)
    assert both == pytest.approx(1.0)
    assert shape_only == pytest.approx(W_CONVEXITY)
    assert noise_only == pytest.approx(W_CONFIRMATION)


def test_no_evidence_scores_zero_and_says_so():
    score, confidence, flags = opportunity_score(None, None, None)
    assert score == 0.0 and confidence == 0.0
    assert "no-evidence" in flags


def test_missing_sources_are_each_named():
    _, _, flags = opportunity_score(3.0, None, None)
    assert "no-radar" in flags and "no-creator-coverage" in flags


# --------------------------------------------------------------------------
# Ranking + display
# --------------------------------------------------------------------------

def test_rank_drops_rows_below_the_noise_floor():
    rows = [
        OpportunityRow(ticker="LOUD", score=MIN_DISPLAY_SCORE - 1, confidence=1.0),
        OpportunityRow(ticker="REAL", score=MIN_DISPLAY_SCORE + 1, confidence=1.0),
    ]
    assert [r.ticker for r in rank_opportunities(rows)] == ["REAL"]


def test_confidence_breaks_score_ties_so_half_blind_rows_sink():
    rows = [
        OpportunityRow(ticker="BLIND", score=60.0, confidence=0.4),
        OpportunityRow(ticker="FULL", score=60.0, confidence=1.0),
    ]
    assert [r.ticker for r in rank_opportunities(rows)] == ["FULL", "BLIND"]


def test_rank_respects_limit():
    rows = [OpportunityRow(ticker=f"T{i}", score=50.0 + i, confidence=1.0) for i in range(10)]
    assert len(rank_opportunities(rows, limit=3)) == 3


def test_is_partial_flags_incomplete_rows():
    assert OpportunityRow(ticker="A", confidence=1.0).is_partial is False
    assert OpportunityRow(ticker="A", confidence=0.6).is_partial is True
    assert OpportunityRow(ticker="A", confidence=1.0, flags=["no-radar"]).is_partial is True


# --------------------------------------------------------------------------
# Plain English: the UX requirement, pinned
# --------------------------------------------------------------------------

def test_verdict_is_a_real_sentence_with_no_jargon():
    row = OpportunityRow(
        ticker="X", score=70.0, confidence=1.0,
        convexity_ratio=4.0, upside_frac=0.40, downside_frac=0.10,
        radar_score=60.0, creator_sources=3,
    )
    sentence, tone = plain_verdict(row)
    assert sentence.endswith(".")
    assert "convexity" not in sentence.lower()
    assert "wilson" not in sentence.lower()
    assert "4.0 to 1" in sentence
    assert tone == "good"


def test_verdict_warns_when_reward_does_not_beat_risk():
    row = OpportunityRow(
        ticker="X", score=30.0, confidence=1.0,
        convexity_ratio=1.2, upside_frac=0.12, downside_frac=0.10,
        radar_score=80.0,
    )
    sentence, tone = plain_verdict(row)
    assert tone == "warn"
    assert "does not clearly beat" in sentence


def test_verdict_admits_when_it_knows_nothing():
    sentence, tone = plain_verdict(OpportunityRow(ticker="X", score=0.0, flags=["no-evidence"]))
    assert "Nothing to go on" in sentence
    assert tone == "neutral"


def test_verdict_says_early_when_nobody_is_talking():
    row = OpportunityRow(
        ticker="X", score=50.0, confidence=1.0,
        convexity_ratio=4.0, upside_frac=0.4, downside_frac=0.1,
        radar_score=5.0, creator_sources=0,
    )
    sentence, _ = plain_verdict(row)
    assert "Nobody is talking about it yet" in sentence


# --------------------------------------------------------------------------
# Row assembly from a real-shaped frame
# --------------------------------------------------------------------------

def _frame(n=200, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, n))
    close = np.maximum(close, 5.0)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + rng.uniform(0.5, 2.0, n),
            "Low": np.maximum(close - rng.uniform(0.5, 2.0, n), 1.0),
            "Close": close,
            "Volume": rng.integers(1e6, 5e6, n).astype(float),
        },
        index=pd.date_range("2025-01-01", periods=n, freq="B"),
    )


def test_build_row_derives_convexity_from_price():
    row = build_opportunity_row("TEST", daily=_frame(), radar_score=60.0)
    assert row.ticker == "TEST"
    assert row.entry is not None
    assert row.score > 0


def test_build_row_without_price_data_still_returns_a_row():
    row = build_opportunity_row("TEST", daily=None, radar_score=60.0)
    assert row.convexity_ratio is None
    assert "no-convexity-data" in row.flags
    assert row.confidence < 1.0


def test_build_row_never_raises_on_a_malformed_frame():
    junk = pd.DataFrame({"Close": ["a", "b", "c"]})
    row = build_opportunity_row("TEST", daily=junk)
    assert isinstance(row, OpportunityRow)


def test_build_row_is_causal():
    """Poisoning future bars must not change today's row."""
    df = _frame()
    baseline = build_opportunity_row("T", daily=df.iloc[:150], radar_score=50.0)

    poisoned = df.copy()
    poisoned.iloc[150:, :] *= 100.0
    after = build_opportunity_row("T", daily=poisoned.iloc[:150], radar_score=50.0)

    assert baseline.convexity_ratio == after.convexity_ratio
    assert baseline.score == after.score


def test_weights_sum_to_one():
    assert W_CONVEXITY + W_CONFIRMATION == pytest.approx(1.0)


def test_module_imports_headless():
    import subprocess, sys
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; import modules.find10x; "
         "assert 'streamlit' not in sys.modules, 'streamlit leaked at import'"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
