"""INDEPENDENT VERIFIER probes for the sentiment-radar fixes.

These are NOT fixes. Each test documents a behaviour I found while verifying
engineer "sentiment-radar"'s claims. Tests named `test_confirm_*` assert the fix works.

The `test_EXPOSES_*` probes below were originally xfail markers documenting an
undisclosed regression: `mention_velocity` was changed to a shrunk ratio but every
threshold calibrated against the old RAW ratio was left at 2.0, which silently
disabled the attention node, the fire gate, and the thin-confirmation integrity
cap. Those thresholds now derive from `VELOCITY_DOUBLING`, so these are live
assertions pinning the recalibration.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.sentiment_radar import (  # noqa: E402
    FIRE_MIN_VELOCITY,
    MIN_CONFIRM_MSGS,
    STAGE_ATTENTION_VEL,
    THIN_CONFIRM_CAP,
    VELOCITY_DOUBLING,
    attention_stage,
    build_row,
    mention_velocity,
)


# ---------------------------------------------------------------------------
# Confirmations
# ---------------------------------------------------------------------------

def test_confirm_crash_and_rally_diverge_end_to_end():
    common = dict(ape={"mentions": 300, "mentions_24h_ago": 100},
                  st_sent={"total": 50, "bullish": 40, "messages": 50},
                  reddit_count=250, vol_today=120.0,
                  prior_vols=[100.0, 110.0, 90.0, 105.0, 95.0])
    up = build_row("UP", **common, close_today=125.0, close_5d_ago=100.0)
    dn = build_row("DN", **common, close_today=75.0, close_5d_ago=100.0)
    # earliness weight is 0.15; the rally keeps 1-0.25/0.30 of it
    assert abs((dn.score - up.score) - 12.5) < 0.11


def test_confirm_macro_cap_is_a_real_ceiling_not_a_banner():
    hot = dict(ape={"mentions": 2000, "mentions_24h_ago": 100},
               st_sent={"total": 200, "bullish": 180, "messages": 200},
               reddit_count=1800, vol_today=400.0, prior_vols=[100.0] * 30,
               close_today=100.0, close_5d_ago=100.0, trends=3.0)
    assert build_row("H", **hot).score > 65.0
    assert build_row("H", **hot, macro_risk="elevated").score == 65.0
    assert build_row("H", **hot, macro_risk="stress").score == 50.0


# ---------------------------------------------------------------------------
# Velocity shrinkage — thresholds must track the metric (was: 6 xfail probes)
# ---------------------------------------------------------------------------

def test_a_genuine_doubling_of_mentions_lights_attention():
    """The whole point of the attention node: a real 2x in chatter must fire it."""
    v = mention_velocity(200, 100)          # a real 2x in Reddit chatter
    assert v >= STAGE_ATTENTION_VEL
    assert attention_stage(v, None, None, 0.0) == 1


def test_thin_confirmation_guard_still_catches_a_2x_spike():
    """INTEGRITY CAP — the regression that mattered most.

    A 2.25x mention spike (20 -> 45) backed by a single StockTwits message must be
    flagged thin-confirmation and capped. With the trigger left at a literal 2.0 the
    shrunk velocity (1.83) slipped under it and the row kept an uncapped score.
    """
    row = build_row(
        "THIN", ape={"mentions": 45, "mentions_24h_ago": 20},
        st_sent={"total": 1, "bullish": 1, "messages": MIN_CONFIRM_MSGS - 2},
        reddit_count=40, vol_today=120.0,
        prior_vols=[100.0, 110.0, 90.0, 105.0, 95.0],
        close_today=100.0, close_5d_ago=100.0,
    )
    assert "thin-confirmation" in row.flags
    assert row.score <= THIN_CONFIRM_CAP


def test_fire_gate_means_what_its_comment_says():
    assert mention_velocity(1000, 500) >= FIRE_MIN_VELOCITY


def test_small_count_doublings_deliberately_do_not_clear_the_gate():
    """The shrinkage exists so tiny absolute counts cannot dominate the board.

    2 -> 4 mentions is a 'doubling' that means nothing; it must NOT fire, while a
    doubling off a real base must. This is the trade the K=10 prior buys.
    """
    assert mention_velocity(4, 2) < STAGE_ATTENTION_VEL
    assert mention_velocity(200, 100) >= STAGE_ATTENTION_VEL


def test_velocity_is_not_the_raw_mention_ratio_and_the_tooltip_says_so():
    """3x more mentions renders as ~2.8x by design — so the Buzz help text must not
    promise "'3.0x' = three times more mentions", which is what it used to claim."""
    assert mention_velocity(300, 100) < 3.0
    src = (Path(__file__).parent.parent / "modules" / "sentiment_radar.py").read_text("utf-8")
    assert "three times more" not in src
    assert "NOT the raw" in src, "Buzz tooltip must disclose that this is a shrunk ratio"


def test_zero_current_mentions_reads_as_no_buzz():
    """100 -> 0 must render 'none', not a misleading '0.1x' from the prior."""
    assert mention_velocity(0, 100) == 0.0
    assert mention_velocity(0, 0) == 0.0


def test_a_real_crowd_arriving_outranks_a_tiny_spike():
    """The original defect: 1 -> 10 mentions used to max the largest weight while
    200 -> 600 earned half of it."""
    assert mention_velocity(600, 200) > mention_velocity(10, 1)


# ---------------------------------------------------------------------------
# Documentation drift inside the owned file
# ---------------------------------------------------------------------------

def test_no_stale_plus_minus_comment_on_early_roc_limit():
    src = (Path(__file__).parent.parent / "modules" / "sentiment_radar.py").read_text("utf-8")
    line = next(ln for ln in src.splitlines() if ln.startswith("EARLY_ROC_LIMIT"))
    assert "+/-" not in line, line


def test_velocity_thresholds_all_derive_from_one_constant():
    """Prevents the exact regression: a literal 2.0 re-appearing beside the metric."""
    assert STAGE_ATTENTION_VEL == VELOCITY_DOUBLING
    assert FIRE_MIN_VELOCITY == VELOCITY_DOUBLING
    src = (Path(__file__).parent.parent / "modules" / "sentiment_radar.py").read_text("utf-8")
    assert "row.velocity >= VELOCITY_DOUBLING" in src
