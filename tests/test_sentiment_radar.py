"""Hand-verified unit tests for every formula in modules/sentiment_radar.py.

Each expected value below was computed by hand (shown in comments), then the
test asserts the code matches — the code is checked against the math, not
against itself.
Run:  python -m pytest tests/test_sentiment_radar.py -q
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.sentiment_radar import (
    DISAGREE_CAP, THIN_CONFIRM_CAP, WEIGHTS,
    build_row, clip01, composite_score, earliness_component,
    mention_velocity, sources_disagree, velocity_component,
    volume_component, volume_zscore, wilson_lower_bound,
)

APPROX = 1e-9


# ---------------- mention velocity ----------------

def test_velocity_basic():
    # 30 mentions now vs 10 yesterday -> 3.0
    assert mention_velocity(30, 10) == 3.0

def test_velocity_zero_prior_floored():
    # prior floored at 1: 8 / max(1,0) = 8, NOT infinity
    assert mention_velocity(8, 0) == 8.0

def test_velocity_none_inputs():
    assert mention_velocity(None, None) == 0.0

def test_velocity_component_log_scale():
    # v=1 -> log10(1)=0 ; v=10 -> log10(10)=1 ; v=100 capped at 1
    assert velocity_component(1.0) == 0.0
    assert abs(velocity_component(10.0) - 1.0) < APPROX
    assert velocity_component(100.0) == 1.0
    # v = 3.1622776601 = 10^0.5 -> 0.5 exactly
    assert abs(velocity_component(10 ** 0.5) - 0.5) < APPROX
    assert velocity_component(0.5) == 0.0   # decaying buzz never negative


# ---------------- Wilson lower bound ----------------

def test_wilson_no_data_is_zero():
    assert wilson_lower_bound(0, 0) == 0.0

def test_wilson_two_of_two():
    # Hand calc, p=1, n=2, z=1.96, z^2=3.8416:
    #   denom  = 1 + 3.8416/2            = 2.9208
    #   centre = 1 + 3.8416/4            = 1.9604
    #   margin = 1.96*sqrt(0 + 3.8416/16)= 1.96*0.49 = 0.9604
    #   LB     = (1.9604-0.9604)/2.9208  = 1/2.9208  = 0.342372...
    expected = 1.0 / 2.9208
    assert abs(wilson_lower_bound(2, 2) - expected) < 1e-6

def test_wilson_forty_of_fifty():
    # p=0.8, n=50: centre=0.838416, margin=1.96*sqrt(0.0032+0.00038416)
    #   = 1.96*sqrt(0.00358416) = 1.96*0.05986785... = 0.117341...
    #   denom = 1.076832 ; LB = (0.838416-0.117341)/1.076832 = 0.669581...
    got = wilson_lower_bound(40, 50)
    margin = 1.96 * math.sqrt(0.8 * 0.2 / 50 + 3.8416 / (4 * 2500))
    expected = (0.8 + 3.8416 / 100 - margin) / (1 + 3.8416 / 50)
    assert abs(got - expected) < APPROX
    assert 0.66 < got < 0.68

def test_wilson_small_sample_scores_below_large_sample_same_ratio():
    # anti-hallucination property: 2/2 must score BELOW 40/50
    assert wilson_lower_bound(2, 2) < wilson_lower_bound(40, 50)

def test_wilson_never_negative_and_bounded():
    assert wilson_lower_bound(0, 10) >= 0.0
    assert wilson_lower_bound(10, 10) < 1.0


# ---------------- volume z-score ----------------

def test_volume_z_hand_computed():
    # prior = [100,110,90,105,95]: mean=100, ddof=1 var=(0+100+100+25+25)/4=62.5
    # std = 7.905694..., today=120 -> z = 20/7.905694 = 2.529822...
    z = volume_zscore(120, [100, 110, 90, 105, 95])
    assert abs(z - (20.0 / math.sqrt(62.5))) < APPROX

def test_volume_z_insufficient_data_is_none():
    assert volume_zscore(120, [100, 110]) is None

def test_volume_z_zero_variance_is_none():
    assert volume_zscore(120, [100] * 10) is None

def test_volume_component_mapping():
    assert volume_component(None) == 0.0
    assert volume_component(-1.0) == 0.0   # below-average volume is not a spike
    assert abs(volume_component(2.0) - 0.5) < APPROX  # z=2 -> 2/4
    assert volume_component(6.0) == 1.0    # saturates at z=4


# ---------------- earliness ----------------

def test_earliness_flat_price_is_fully_early():
    assert earliness_component(0.0) == 1.0

def test_earliness_hand_values():
    # +15% of the 30% limit -> 1 - 0.15/0.30 = 0.5 ; direction-agnostic
    assert abs(earliness_component(0.15) - 0.5) < APPROX
    assert abs(earliness_component(-0.15) - 0.5) < APPROX
    assert earliness_component(0.45) == 0.0   # already ran, fully late

def test_earliness_none_is_zero_not_one():
    # missing price data must NOT pretend the setup is early
    assert earliness_component(None) == 0.0


# ---------------- composite + integrity caps ----------------

def test_composite_hand_computed():
    # 100*(0.35*0.5 + 0.25*0.6 + 0.25*0.4 + 0.15*1.0) = 100*(0.175+0.15+0.10+0.15) = 57.5
    assert composite_score(0.5, 0.6, 0.4, 1.0) == 57.5

def test_composite_perfect_is_100_and_floor_0():
    assert composite_score(1, 1, 1, 1) == 100.0
    assert composite_score(0, 0, 0, 0) == 0.0

def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < APPROX

def test_caps_applied():
    assert composite_score(1, 1, 1, 1, thin_confirmation=True) == THIN_CONFIRM_CAP
    assert composite_score(1, 1, 1, 1, source_disagreement=True) == DISAGREE_CAP
    # both flags -> the stricter (lower) cap wins
    assert composite_score(1, 1, 1, 1, True, True) == min(THIN_CONFIRM_CAP, DISAGREE_CAP)
    # cap never RAISES a low score
    assert composite_score(0.1, 0, 0, 0, thin_confirmation=True) == 3.5


# ---------------- cross-source disagreement ----------------

def test_disagreement_requires_both_sources():
    assert sources_disagree(None, 50) is False
    assert sources_disagree(50, None) is False

def test_disagreement_ratio():
    assert sources_disagree(100, 10) is True    # 10x apart
    assert sources_disagree(10, 100) is True    # symmetric
    assert sources_disagree(50, 20) is False    # 2.5x is fine
    assert sources_disagree(0, 3) is False      # floors: 1 vs 3 = 3x < 5x


# ---------------- end-to-end row ----------------

def test_build_row_full_data():
    row = build_row(
        "ionq",
        ape={"mentions": 30, "mentions_24h_ago": 10, "upvotes": 500, "rank": 4},
        st_sent={"total": 50, "bullish": 40, "messages": 60},
        reddit_count=25,
        vol_today=120, prior_vols=[100, 110, 90, 105, 95],
        close_today=115.0, close_5d_ago=100.0,
    )
    assert row.ticker == "IONQ"
    assert row.flags == []          # clean row
    # components: vel=log10(3)=0.477121; wilson(40/50)=0.669581;
    # volz=2.529822/4=0.632456; roc=0.15 -> early=0.5
    expected = 100 * (0.35 * math.log10(3.0)
                      + 0.25 * wilson_lower_bound(40, 50)
                      + 0.25 * ((20.0 / math.sqrt(62.5)) / 4.0)
                      + 0.15 * 0.5)
    assert abs(row.score - round(expected, 1)) < 0.05

def test_build_row_thin_confirmation_capped():
    row = build_row(
        "xyz",
        ape={"mentions": 40, "mentions_24h_ago": 5},   # velocity 8 = hot
        st_sent={"total": 0, "bullish": 0, "messages": 1},  # but nobody on ST
        reddit_count=None, vol_today=None, prior_vols=None,
        close_today=None, close_5d_ago=None,
    )
    assert "thin-confirmation" in row.flags
    assert row.score <= THIN_CONFIRM_CAP

def test_build_row_missing_sources_flagged_partial():
    row = build_row("abc", ape=None, st_sent=None, reddit_count=None,
                    vol_today=None, prior_vols=None,
                    close_today=None, close_5d_ago=None)
    assert "partial-data" in row.flags
    assert row.score == 0.0

def test_clip01():
    assert clip01(-5) == 0.0 and clip01(5) == 1.0 and clip01(0.3) == 0.3
