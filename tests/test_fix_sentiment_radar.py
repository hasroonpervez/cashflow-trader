"""Regression tests for the AUDIT_2026-08 defects in modules/sentiment_radar.py.

Each test names the finding it pins. Every expected number below was computed
by hand (shown in the comment) so the code is checked against the math, not
against itself.

Run:  python -m pytest tests/test_fix_sentiment_radar.py -q
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.sentiment_radar import (
    DISAGREE_CAP,
    EARLY_ROC_LIMIT,
    MACRO_ELEVATED_CAP,
    MACRO_STRESS_CAP,
    STAGE_LABELS,
    STAGE_LATE_ROC,
    STAGE_SELLOFF,
    THIN_CONFIRM_CAP,
    VELOCITY_PRIOR,
    WEIGHTS,
    RadarRow,
    attention_stage,
    build_row,
    earliness_component,
    is_weak_data,
    macro_risk_level,
    macro_score_cap,
    mention_velocity,
    velocity_component,
    verdict_for_row,
)

APPROX = 1e-9


def _ape(mentions=300, prev=100, **kw):
    d = {"mentions": mentions, "mentions_24h_ago": prev}
    d.update(kw)
    return d


def _st(total=50, bullish=40, messages=None):
    return {"total": total, "bullish": bullish,
            "messages": total if messages is None else messages}


def _priced(**kw):
    """Full, clean price inputs so no row is flagged partial-data."""
    base = dict(vol_today=120.0, prior_vols=[100.0, 110.0, 90.0, 105.0, 95.0],
                close_today=100.0, close_5d_ago=100.0)
    base.update(kw)
    return base


# =====================================================================
#  FINDING: "A crash is scored identically to a rally."
#  abs(roc_5d) at earliness_component / attention_stage / verdict_for_row
#  rendered a -25% capitulation as "Already ran — you'd be late" / "Erupted".
# =====================================================================

def test_crash_does_not_consume_earliness():
    """-25% in 5d is not a missed rally: the upside is entirely still there."""
    # 1 - max(0, -0.25)/0.30 = 1 - 0 = 1.0
    assert earliness_component(-0.25) == 1.0
    # ...whereas the SAME magnitude to the upside really is late:
    # 1 - 0.25/0.30 = 0.1666...
    assert abs(earliness_component(0.25) - (1.0 - 0.25 / 0.30)) < APPROX


def test_earliness_is_no_longer_symmetric_about_zero():
    """The bug in one line: earliness(+x) == earliness(-x) for every x."""
    for x in (0.05, 0.10, 0.15, 0.25, 0.40):
        assert earliness_component(x) != earliness_component(-x), x


def test_earliness_still_zero_only_for_a_real_run_up():
    assert earliness_component(0.0) == 1.0
    assert earliness_component(EARLY_ROC_LIMIT) == 0.0
    assert earliness_component(EARLY_ROC_LIMIT + 0.5) == 0.0
    assert earliness_component(-(EARLY_ROC_LIMIT + 0.5)) == 1.0
    assert earliness_component(None) == 0.0   # missing != early (unchanged)


def test_crash_gets_its_own_stage_not_erupted():
    """A -20% break is off the up-cascade, not a later rung of it."""
    assert attention_stage(9.0, 3.0, 5.0, -0.20) == STAGE_SELLOFF
    assert attention_stage(9.0, 3.0, 5.0, 0.20) == 3
    assert STAGE_SELLOFF != 3


def test_selloff_stage_has_a_label_that_does_not_say_late():
    label = STAGE_LABELS[STAGE_SELLOFF]
    assert "late" not in label.lower()
    assert "erupted" not in label.lower()
    # and every stage attention_stage can return must be renderable
    for roc in (None, -0.5, -0.2, -0.05, 0.0, 0.05, 0.2, 0.5):
        assert attention_stage(3.0, 2.0, 2.5, roc) in STAGE_LABELS


def test_stage_selloff_boundary_is_symmetric_in_magnitude_only():
    # just inside the band on the downside -> normal cascade, not selloff
    assert attention_stage(1.0, None, None, -(STAGE_LATE_ROC - 0.001)) == 0
    # exactly at the threshold -> selloff
    assert attention_stage(1.0, None, None, -STAGE_LATE_ROC) == STAGE_SELLOFF


def test_verdict_for_a_crash_is_not_already_ran():
    crashed = build_row("crash", ape=_ape(), st_sent=_st(), reddit_count=250,
                        **_priced(close_today=65.0, close_5d_ago=100.0))
    assert crashed.roc_5d is not None and crashed.roc_5d <= -EARLY_ROC_LIMIT
    v = verdict_for_row(crashed)
    assert "Already ran" not in v
    assert "late" not in v.lower()
    assert "selloff" in v.lower()


def test_verdict_for_a_real_rally_still_says_already_ran():
    """The fix must not disarm the genuine late-chaser warning."""
    ran = build_row("ran", ape=_ape(), st_sent=_st(), reddit_count=250,
                    **_priced(close_today=135.0, close_5d_ago=100.0))
    assert "Already ran" in verdict_for_row(ran)


def test_crash_and_rally_of_equal_magnitude_now_score_differently():
    common = dict(ape=_ape(), st_sent=_st(), reddit_count=250)
    up = build_row("UP", **common, **_priced(close_today=125.0, close_5d_ago=100.0))
    down = build_row("DN", **common, **_priced(close_today=75.0, close_5d_ago=100.0))
    assert up.score != down.score
    # the crash keeps the full 15-point earliness weight; the rally keeps
    # 15 * (1 - 0.25/0.30) = 2.5 of it -> a 12.5-point gap
    assert abs((down.score - up.score) - 12.5) < 0.11   # 0.1 rounding each side


# =====================================================================
#  FINDING: "The VIX macro gate gates nothing" — banner only, no score change.
# =====================================================================

def test_macro_cap_table():
    assert macro_score_cap("stress") == MACRO_STRESS_CAP
    assert macro_score_cap("elevated") == MACRO_ELEVATED_CAP
    assert macro_score_cap("calm") is None
    assert macro_score_cap("unknown") is None      # unknown VIX must not punish


def test_macro_caps_are_placed_below_the_verdict_rungs_they_claim_to_block():
    """The banner copy is only true if the numbers make it true."""
    assert MACRO_ELEVATED_CAP < 70.0    # "no row can reach the 70+ 🔥 tier"
    assert MACRO_STRESS_CAP <= 50.0     # "nothing stronger than 👀 Warming up"


def test_macro_gate_actually_lowers_a_hot_score():
    hot = dict(ape=_ape(mentions=2000, prev=100), st_sent=_st(total=200, bullish=180),
               reddit_count=1800, vol_today=400.0, prior_vols=[100.0] * 30,
               close_today=100.0, close_5d_ago=100.0, trends=3.0)
    calm = build_row("HOT", **hot, macro_risk="calm")
    elevated = build_row("HOT", **hot, macro_risk="elevated")
    stress = build_row("HOT", **hot, macro_risk="stress")

    assert calm.score > MACRO_ELEVATED_CAP, "test needs a genuinely hot row"
    assert elevated.score == MACRO_ELEVATED_CAP
    assert stress.score == MACRO_STRESS_CAP
    assert "macro-capped" in elevated.flags
    assert "macro-capped" in stress.flags
    assert "macro-capped" not in calm.flags


def test_macro_gate_never_raises_a_quiet_score():
    """A cap is a ceiling, not a target."""
    quiet = dict(ape=None, ape_available=True, st_sent=_st(total=4, bullish=1),
                 reddit_count=0, **_priced())
    calm = build_row("Q", **quiet, macro_risk="calm")
    stress = build_row("Q", **quiet, macro_risk="stress")
    assert calm.score < MACRO_STRESS_CAP, "test needs a genuinely quiet row"
    assert stress.score == calm.score
    assert "macro-capped" not in stress.flags


def test_macro_gate_defaults_to_off_for_callers_without_a_vix():
    """find10x calls build_row with no macro_risk — it must be unaffected."""
    hot = dict(ape=_ape(mentions=2000, prev=100), st_sent=_st(total=200, bullish=180),
               reddit_count=1800, vol_today=400.0, prior_vols=[100.0] * 30,
               close_today=100.0, close_5d_ago=100.0, trends=3.0)
    assert build_row("H", **hot).score == build_row("H", **hot, macro_risk="calm").score


def test_macro_gate_wires_to_the_vix_thresholds_the_banner_prints():
    assert macro_score_cap(macro_risk_level(19.99)) is None
    assert macro_score_cap(macro_risk_level(20.0)) == MACRO_ELEVATED_CAP
    assert macro_score_cap(macro_risk_level(24.99)) == MACRO_ELEVATED_CAP
    assert macro_score_cap(macro_risk_level(25.0)) == MACRO_STRESS_CAP
    assert macro_score_cap(macro_risk_level(None)) is None


def test_macro_capped_row_gets_an_honest_verdict():
    hot = build_row("HOT", ape=_ape(mentions=2000, prev=100),
                    st_sent=_st(total=200, bullish=180), reddit_count=1800,
                    vol_today=400.0, prior_vols=[100.0] * 30,
                    close_today=100.0, close_5d_ago=100.0, trends=3.0,
                    macro_risk="stress")
    assert "research-only" in verdict_for_row(hot)


# =====================================================================
#  FINDING: a "⚠️ Weak data — ignore for now" row could occupy a
#  "🏆 Today's top signals" card.
# =====================================================================

def test_is_weak_data_matches_the_weak_verdict_exactly():
    """The card picker and the verdict must not be able to disagree."""
    for flags in ([], ["partial-data"], ["source-disagreement"],
                  ["thin-confirmation"], ["no-price-data", "partial-data"],
                  ["macro-capped"], ["thin-confirmation", "source-disagreement"]):
        r = RadarRow(ticker="X", flags=list(flags), score=80.0,
                     velocity=3.0, wilson=0.7, roc_5d=0.01)
        weak_verdict = verdict_for_row(r).startswith("⚠️")
        assert is_weak_data(r) is weak_verdict, flags


def test_top_signal_selection_drops_weak_rows():
    """Mirrors the picker in _render_results (which is Streamlit-bound)."""
    strong = RadarRow(ticker="GOOD", score=80.0, flags=[])
    partial = RadarRow(ticker="PART", score=95.0, flags=["no-price-data", "partial-data"])
    disagree = RadarRow(ticker="DIS", score=90.0, flags=["source-disagreement"])
    zero = RadarRow(ticker="ZERO", score=0.0, flags=[])
    rows = sorted([strong, partial, disagree, zero], key=lambda r: r.score, reverse=True)

    top = [r for r in rows if r.score > 0 and not is_weak_data(r)][:3]

    assert [r.ticker for r in top] == ["GOOD"]
    # the two loudest scores were both untrustworthy — and were both excluded
    assert rows[0].ticker == "PART"


def test_a_thin_confirmation_row_is_still_card_eligible():
    """Only missing/contradictory SOURCES disqualify — 'thin' is a real reading."""
    thin = RadarRow(ticker="THIN", score=55.0, flags=["thin-confirmation"])
    assert is_weak_data(thin) is False
    assert [r.ticker for r in [thin] if not is_weak_data(r)] == ["THIN"]


def test_end_to_end_weak_row_is_excluded():
    weak = build_row("weak", ape=_ape(mentions=1000, prev=10), st_sent=_st(),
                     reddit_count=2,      # 1000 vs 2 -> source disagreement
                     **_priced())
    assert "source-disagreement" in weak.flags
    assert is_weak_data(weak) is True
    assert verdict_for_row(weak).startswith("⚠️")


# =====================================================================
#  FINDING: the docstring formula and the on-screen weights caption both
#  omit the 15% Trends term and sum to 85%.
# =====================================================================

def test_module_docstring_states_every_weight_and_they_sum_to_one():
    import modules.sentiment_radar as sr

    doc = sr.__doc__ or ""
    for name, w in WEIGHTS.items():
        assert f"{w:.2f}" in doc, f"docstring formula omits {name}={w}"
    assert abs(sum(WEIGHTS.values()) - 1.0) < APPROX
    # the specific omission the audit found: the trends term
    assert "trends" in doc
    # ...and the stale 0.35/0.25/0.25 formula is gone
    assert "0.35*vel" not in doc


def test_onscreen_weights_caption_is_generated_from_the_weights_dict():
    """Source-level guard: the caption may not hardcode weight percentages.

    The old caption listed four literals and summed to 85%. Regenerating it
    from WEIGHTS is what makes drift structurally impossible, so that is what
    is asserted — a value assertion would pass again the moment someone
    re-hardcodes the numbers correctly and then changes WEIGHTS.
    """
    src = Path(__file__).parent.parent / "modules" / "sentiment_radar.py"
    text = src.read_text(encoding="utf-8")
    caption = text.split('"Weights: "')[1].split("thin ≤")[0]
    assert "WEIGHTS.items()" in caption
    assert "sum(WEIGHTS.values())" in caption
    # no literal percentage snuck back in
    for w in WEIGHTS.values():
        assert f"{w:.0%}" not in caption


def test_docstring_documents_the_macro_gate_and_the_direction_rule():
    import modules.sentiment_radar as sr

    doc = sr.__doc__ or ""
    assert "max(0, r)" in doc          # earliness is one-sided now
    assert str(int(MACRO_STRESS_CAP)) in doc and str(int(MACRO_ELEVATED_CAP)) in doc


# =====================================================================
#  FINDING: mention velocity is an unstabilised ratio with the denominator
#  floored at 1 — 1->10 mentions maxes the largest weight while 200->600
#  earns 0.48.
# =====================================================================

def test_the_exact_pair_from_the_audit_is_now_ordered_correctly():
    """1->10 must NOT out-score 200->600."""
    tiny = velocity_component(mention_velocity(10, 1))
    big = velocity_component(mention_velocity(600, 200))
    assert tiny < big, (tiny, big)
    # hand values with K=10: (10+10)/(1+10)   = 1.8181... -> log10 = 0.2596
    #                        (600+10)/(200+10)= 2.9047... -> log10 = 0.4632
    assert abs(mention_velocity(10, 1) - 20.0 / 11.0) < APPROX
    assert abs(mention_velocity(600, 200) - 610.0 / 210.0) < APPROX
    assert abs(tiny - math.log10(20.0 / 11.0)) < APPROX
    assert abs(big - math.log10(610.0 / 210.0)) < APPROX


def test_small_absolute_counts_can_no_longer_max_the_largest_weight():
    """The bug: 1->10 gave a ratio of 10.0, i.e. component 1.0 (saturated)."""
    assert velocity_component(mention_velocity(10, 1)) < 0.5
    assert velocity_component(mention_velocity(5, 0)) < 0.5
    assert velocity_component(mention_velocity(1, 0)) < 0.1


def test_shrinkage_leaves_large_counts_essentially_untouched():
    """K=10 is a prior, not a distortion — it must vanish at scale."""
    raw = 3000.0 / 1000.0
    assert abs(mention_velocity(3000, 1000) - raw) < 0.03


def test_velocity_is_monotone_in_the_current_count():
    prev = 100
    seq = [mention_velocity(n, prev) for n in (0, 50, 100, 200, 400, 800)]
    assert seq == sorted(seq)


def test_velocity_prior_is_applied_to_both_sides():
    """Same K on numerator and denominator -> flat buzz stays exactly 1.0."""
    assert mention_velocity(0, 0) == 0.0          # no data at all -> "none"
    for n in (1, 7, 50, 4000):
        assert mention_velocity(n, n) == 1.0
    assert VELOCITY_PRIOR > 0


def test_a_one_mention_ticker_no_longer_beats_a_crowded_one_end_to_end():
    noise = build_row("NOISE", ape=_ape(mentions=10, prev=1), st_sent=_st(),
                      reddit_count=8, **_priced())
    real = build_row("REAL", ape=_ape(mentions=600, prev=200), st_sent=_st(),
                     reddit_count=500, **_priced())
    assert noise.flags == [] and real.flags == []
    assert real.score > noise.score


# =====================================================================
#  Cross-cutting: the caps still behave, and nothing above broke them.
# =====================================================================

def test_all_caps_compose_lowest_wins():
    row = build_row(
        "MESS", ape=_ape(mentions=5000, prev=10),   # screaming velocity
        st_sent=_st(total=1, bullish=1, messages=1),  # thin confirmation
        reddit_count=3,                               # source disagreement
        **_priced(), macro_risk="stress",
    )
    assert "thin-confirmation" in row.flags
    assert "source-disagreement" in row.flags
    assert row.score <= min(THIN_CONFIRM_CAP, DISAGREE_CAP, MACRO_STRESS_CAP)
