"""Sig_orb_rvol_vwap on synthetic movers bars."""
from __future__ import annotations

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from signals.producers import produce_orb_rvol_vwap
from signals.scanner_fixtures import build_in_play_orb
from venues.base import Mode, OrderRequest
from venues.robinhood.adapter import RobinhoodReadAdapter


def test_emits_sig_on_in_play_orb_above_vwap():
    sig = produce_orb_rvol_vwap(build_in_play_orb(), symbol="PLAY", p_true=0.56, edge=0.04)
    assert sig is not None
    assert sig.source == "Sig_orb_rvol_vwap"
    assert sig.source_node == "Sig_orb_rvol_vwap"
    assert sig.venue == "robinhood"
    assert sig.market == "PLAY"
    assert sig.side == "buy"
    assert sig.p_model == 0.56
    assert sig.metadata.get("paper_only") is True
    assert sig.metadata.get("unvalidated") is True
    assert sig.metadata.get("vwap_side") == "above"
    assert sig.metadata.get("universe", {}).get("in_play") is True
    assert sig.metadata.get("validated_raw", {}).get("status") == "signal"


def test_none_without_orb_break():
    bars = build_in_play_orb(breakout=False)
    assert produce_orb_rvol_vwap(bars, symbol="PLAY") is None


def test_none_when_faded_below_vwap():
    bars = build_in_play_orb(breakout=True, fade_below_vwap=True)
    assert produce_orb_rvol_vwap(bars, symbol="PLAY") is None


def test_none_when_not_in_universe():
    bars = build_in_play_orb(gap_pct=0.2, volume_per_bar=5_000.0)
    assert produce_orb_rvol_vwap(bars, symbol="DEAD") is None


def test_through_robinhood_paper_pipeline():
    sig = produce_orb_rvol_vwap(build_in_play_orb(), symbol="PLAY", p_true=0.56)
    assert sig is not None
    ledger = PaperLedger()
    result = run_paper_pipeline(
        sig,
        {"outcomes": []},
        RobinhoodReadAdapter(),
        ledger,
        10_000.0,
        fee_rate=0.001,
        slippage_bps=5.0,
    )
    assert result.accepted is True
    assert result.promoted is False
    assert result.fill is not None
    assert result.fill["fee_rate"] == 0.001
    assert result.fill["slippage_bps"] == 5.0
    assert result.cpcv is not None
    assert result.cpcv.ok is False
    assert "cpcv: annotate-hold; paper fill still recorded" in result.reasons
    assert len(ledger.list_fills()) == 1
    assert ledger.list_outcomes()[0].payload.get("settled") is False


def test_robinhood_live_still_refused():
    with __import__("pytest").raises(ValueError):
        RobinhoodReadAdapter(mode=Mode.LIVE)
    adapter = RobinhoodReadAdapter()
    adapter.mode = Mode.LIVE
    with __import__("pytest").raises(PermissionError):
        adapter.place_order(OrderRequest(market="PLAY", side="buy", size=1.0))
