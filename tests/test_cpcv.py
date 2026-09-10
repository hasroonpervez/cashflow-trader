"""CPCV / deflated-Sharpe stub: annotate-only, never blocks fills."""
from __future__ import annotations

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from risk.cpcv import evaluate_cpcv
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter


def test_insufficient_n():
    result = evaluate_cpcv([0.01] * 10)
    assert result.ok is False
    assert result.cpcv is None
    assert result.deflated_sharpe is None
    assert result.n == 10
    assert result.unvalidated is True
    assert any("insufficient" in r for r in result.reasons)


def test_large_n_still_stub():
    result = evaluate_cpcv([0.01] * 40)
    assert result.ok is False
    assert result.cpcv is None
    assert result.deflated_sharpe is None
    assert any("stub" in r for r in result.reasons)


def test_pipeline_fills_on_cpcv_hold():
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
        {"outcomes": [0.01] * 40, "min_n": 30},
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.fill is not None
    assert result.cpcv is not None
    assert result.cpcv.ok is False
    assert len(ledger.list_fills()) == 1
    assert "cpcv: annotate-hold; paper fill still recorded" in result.reasons
