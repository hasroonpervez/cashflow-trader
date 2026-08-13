from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter


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
        adapter=KalshiDryRunAdapter(),
        ledger=ledger,
        bankroll=1000.0,
        bypass_gate=True,
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
        adapter=KalshiDryRunAdapter(),
        ledger=PaperLedger(),
        bankroll=1000.0,
        bypass_gate=False,
        gate_outcomes=[],
    )
    assert result.accepted is False
