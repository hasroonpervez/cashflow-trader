from execution.paper_ledger import PaperLedger


def test_ledger_records_kinds():
    led = PaperLedger()
    led.record_signal({"id": "s1"})
    led.record_order({"id": "o1"})
    led.record_fill({"order_id": "f1"})
    led.record_outcome({"order_id": "f1", "pnl": 1.25, "settled": True})
    assert len(led.list_events()) == 4
    assert len(led.list_fills()) == 1
    assert len(led.list_outcomes()) == 1
    assert led.list_outcomes()[0].payload["pnl"] == 1.25
