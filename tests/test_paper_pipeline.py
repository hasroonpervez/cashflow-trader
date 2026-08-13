from __future__ import annotations

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter


def test_pipeline_records_fill_even_when_gate_holds():
    """Gate annotate-hold must not block paper fills (Graph blocker #2)."""
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="Sig_K.unit",
        edge=0.05,
    )
    assert signal.instrument == "DEMO-MARKET"
    assert signal.p_model == 0.65
    assert signal.source_node == "Sig_K.unit"

    ledger = PaperLedger()
    result = run_paper_pipeline(
        signal,
        {"outcomes": []},
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.promoted is False
    assert result.fill is not None
    assert len(ledger.list_fills()) == 1
    assert len(ledger.list_outcomes()) == 1
    assert result.portfolio_risk is not None


def test_pipeline_records_fill_when_bootstrap_ci_holds():
    """Mean-zero sample fails bootstrap CI; paper fill still records."""
    outcomes = [1.0, -1.0] * 20
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="Sig_K.unit",
        edge=0.05,
    )
    ledger = PaperLedger()
    result = run_paper_pipeline(
        signal,
        {
            "outcomes": outcomes,
            "min_n": 30,
            "split_half_corr": 0.0,
        },
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.promoted is False
    assert result.fill is not None
    assert len(ledger.list_fills()) == 1
    assert any(r.startswith("bootstrap_ci:") for r in result.reasons)
    assert "gate: annotate-hold; paper fill still recorded" in result.reasons


def test_pipeline_promoted_when_gate_ok():
    outcomes = [1.0, 0.0] * 20
    labels = ["A", "B"] * 20
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="unit",
    )
    result = run_paper_pipeline(
        signal,
        {
            "outcomes": outcomes,
            "labels": labels,
            "min_n": 30,
            "split_half_corr": -1.0,
            "max_concentration": 0.6,
        },
        KalshiDryRunAdapter(),
        PaperLedger(),
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.promoted is True
