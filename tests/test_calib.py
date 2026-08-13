from __future__ import annotations

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from risk.calib import apply_settlement, gate_stats_from_ledger, outcomes_from_ledger
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


def test_unsettled_after_fill_then_settle_feeds_calib():
    ledger = PaperLedger()
    signal = _signal()
    result = run_paper_pipeline(
        signal,
        {"outcomes": []},
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.fill is not None
    stub = ledger.list_outcomes()[0].payload
    assert stub.get("settled") is False
    assert stub.get("pnl") is None
    assert outcomes_from_ledger(ledger) == []

    apply_settlement(ledger, signal.id, 1.25)
    assert outcomes_from_ledger(ledger) == [1.25]
    stats = gate_stats_from_ledger(ledger, min_n=30)
    assert stats["outcomes"] == [1.25]
    assert stats["min_n"] == 30
    assert "labels" not in stats


def test_second_pipeline_run_still_paper_fills_on_hold():
    """Settled PnL feeds gate_stats; gate/stage2 hold still records a paper fill."""
    ledger = PaperLedger()
    adapter = KalshiDryRunAdapter()
    first = run_paper_pipeline(
        _signal(),
        {"outcomes": []},
        adapter,
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert first.accepted is True
    assert first.fill is not None
    apply_settlement(ledger, first.fill["order_id"], -0.5)

    stats = gate_stats_from_ledger(ledger, min_n=30)
    assert stats["outcomes"] == [-0.5]

    second = run_paper_pipeline(
        _signal(),
        stats,
        adapter,
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert second.accepted is True
    assert second.fill is not None
    assert second.promoted is False
    assert second.stage2 is not None
    assert second.stage2.ok is False
    assert len(ledger.list_fills()) == 2
    assert "gate: annotate-hold; paper fill still recorded" in second.reasons
    assert "stage2: annotate-hold; paper fill still recorded" in second.reasons
