"""Pattern features on Sig_* producers. Paper annotate only."""
from __future__ import annotations

import pandas as pd

from signals.producers import (
    bar_patterns,
    event_patterns,
    produce_kalshi_event,
    produce_orb30,
    produce_swing_pullback,
)
from tests.test_sig_producers import _engineered_swing_daily, _fake_session


def test_bar_patterns_inside_bar_and_hh():
    df = pd.DataFrame(
        {
            "open": [10.0, 10.2, 10.3],
            "high": [11.0, 10.8, 10.7],
            "low": [9.0, 10.0, 10.1],
            "close": [10.5, 10.4, 10.5],
        }
    )
    p = bar_patterns(df)
    assert p["inside_bar"] is True
    assert p["paper_only"] is True
    assert p["unvalidated"] is True
    assert "hh_count" in p
    assert "close_location" in p


def test_bar_patterns_empty():
    assert bar_patterns(pd.DataFrame()) == {}


def test_orb30_attaches_patterns():
    sig = produce_orb30(_fake_session(breakout=True), symbol="TSLA", p_true=0.60)
    assert sig is not None
    pats = sig.metadata.get("patterns") or {}
    assert pats.get("paper_only") is True
    assert pats.get("unvalidated") is True
    assert "inside_bar" in pats


def test_swing_attaches_patterns():
    sig = produce_swing_pullback(_engineered_swing_daily(), symbol="AAPL", p_true=0.57)
    assert sig is not None
    assert "patterns" in sig.metadata
    assert sig.metadata["patterns"]["unvalidated"] is True


def test_kalshi_event_patterns_not_a_live_claim():
    sig = produce_kalshi_event(
        p_true=0.65, market_price=0.90, market_id="MKT", strategy="unit"
    )
    pats = sig.metadata["patterns"]
    assert pats["price_extreme"] is True
    assert pats["crowded_yes"] is True
    assert pats["unvalidated"] is True
    assert pats["edge_sign"] == -1
    assert event_patterns(p_true=0.65, market_price=0.45)["abs_edge"] == 0.20


def test_event_patterns_side_no():
    yes = event_patterns(p_true=0.40, market_price=0.55, side="yes")
    no = event_patterns(p_true=0.40, market_price=0.55, side="no")
    assert no["side"] == "no"
    assert abs(no["abs_edge"] - 0.05) < 1e-9
    assert no["edge_sign"] == 1
    assert yes["edge_sign"] == -1


def test_caller_metadata_cannot_clobber_patterns():
    sig = produce_kalshi_event(
        p_true=0.65,
        market_price=0.90,
        market_id="MKT",
        metadata={"patterns": {"hijack": True}, "note": "keep"},
    )
    assert sig.metadata["note"] == "keep"
    assert sig.metadata["patterns"].get("hijack") is True
    assert sig.metadata["patterns"]["unvalidated"] is True
    assert sig.metadata["patterns"]["price_extreme"] is True
