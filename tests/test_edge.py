"""Paper edge annotate from settlement outcomes. Does not change fills."""
from __future__ import annotations

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from risk.calib import apply_settlement, gate_stats_from_ledger
from risk.edge import evaluate_edge, edge_from_stats
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter


def _signal() -> Signal:
    return Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="Sig_K.unit",
        edge=0.05,
    )


def test_evaluate_edge_fail_closed_small_n():
    r = evaluate_edge([1.0, -0.5], min_n=30)
    assert r.ok is False
    assert r.unvalidated is True
    assert r.realized_edge is None
    assert any("insufficient" in x for x in r.reasons)


def test_evaluate_edge_ok_on_positive_mean():
    pnls = [1.0] * 20 + [0.2] * 10
    r = evaluate_edge(pnls, min_n=30, model_edge=0.05)
    assert r.n == 30
    assert r.realized_edge is not None and r.realized_edge > 0
    assert r.hit_rate == 1.0
    assert r.ok is True


def test_pipeline_annotates_edge_and_still_fills():
    ledger = PaperLedger()
    first = run_paper_pipeline(
        _signal(), {"outcomes": []}, KalshiDryRunAdapter(), ledger, 1000.0, fee_rate=0.0
    )
    assert first.edge is not None
    assert first.edge.ok is False
    apply_settlement(ledger, first.fill["order_id"], 1.0)
    stats = gate_stats_from_ledger(ledger, min_n=30)
    second = run_paper_pipeline(
        _signal(), stats, KalshiDryRunAdapter(), ledger, 1000.0, fee_rate=0.0
    )
    assert second.accepted is True
    assert second.fill is not None
    assert second.edge is not None
    assert second.edge.ok is False  # still n=1
    assert "edge: annotate-hold; paper fill still recorded" in second.reasons
    assert edge_from_stats(stats, model_edge=0.05).n == 1
