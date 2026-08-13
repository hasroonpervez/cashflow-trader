"""Unit tests for execution.pipeline paper path."""
from __future__ import annotations

from datetime import datetime, timezone

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from signals.schema import Signal
from venues.kalshi import KalshiDryRunAdapter


def _signal(**kwargs):
    base = dict(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="unit-test",
        id="sig-pipeline-1",
        ts=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
        metadata={},
    )
    base.update(kwargs)
    return Signal(**base)


def _passing_gate_stats(n: int = 40) -> dict:
    half = [1.0, 0.0, 1.0, 1.0, 0.0] * (n // 10)
    outcomes = half + half
    labels = ["A", "B", "C", "D"] * (n // 4)
    return {
        "outcomes": outcomes,
        "labels": labels,
        "min_n": 30,
        "split_half_corr": 0.3,
        "max_concentration": 0.35,
    }


def test_pipeline_holds_without_history() -> None:
    ledger = PaperLedger()
    result = run_paper_pipeline(
        _signal(),
        {},
        KalshiDryRunAdapter(),
        ledger,
        bankroll=1000.0,
    )
    assert result.accepted is False
    assert result.fill is None
    assert ledger.list_fills() == []
    assert len(ledger.list_events("signal")) == 1


def test_pipeline_accepts_and_records_fill() -> None:
    ledger = PaperLedger()
    result = run_paper_pipeline(
        _signal(p_true=0.7),
        _passing_gate_stats(),
        KalshiDryRunAdapter(mode="paper"),
        ledger,
        bankroll=1000.0,
        odds_b=1.0,
        fee_rate=0.0,
        kelly_fraction=0.25,
    )
    assert result.accepted is True
    assert result.stake > 0
    assert result.fill is not None
    assert result.fill["mode"] == "paper"
    assert len(ledger.list_fills()) == 1
    assert len(ledger.list_events("order")) == 1


def test_pipeline_rejects_nonpositive_kelly() -> None:
    ledger = PaperLedger()
    result = run_paper_pipeline(
        _signal(p_true=0.4),
        _passing_gate_stats(),
        KalshiDryRunAdapter(),
        ledger,
        bankroll=1000.0,
        odds_b=1.0,
        fee_rate=0.0,
    )
    assert result.accepted is False
    assert "kelly: non-positive stake" in result.reasons


def test_signal_requires_utc() -> None:
    sig = _signal(ts=datetime(2026, 1, 1, 0, 0))
    assert sig.ts.tzinfo is not None
