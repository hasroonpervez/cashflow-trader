from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter


def _promote_stats():
    outcomes = [1.0, 0.0] * 20
    labels = ["A", "B"] * 20
    return {
        "outcomes": outcomes,
        "labels": labels,
        "min_n": 30,
        "split_half_corr": -1.0,
        "max_concentration": 0.6,
    }


def test_pipeline_paper_fill():
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="unit-test",
    )
    ledger = PaperLedger()
    result = run_paper_pipeline(
        signal,
        _promote_stats(),
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.stake > 0
    assert result.fill is not None
    assert len(ledger.list_fills()) == 1


def test_pipeline_holds_without_history():
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="unit-test",
    )
    result = run_paper_pipeline(
        signal,
        {"outcomes": []},
        KalshiDryRunAdapter(),
        PaperLedger(),
        1000.0,
    )
    assert result.accepted is False
