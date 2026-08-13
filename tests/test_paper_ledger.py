from execution.paper_ledger import PaperLedger


def test_ledger_records_kinds():
    led = PaperLedger()
    led.record_signal({"id": "s1"})
    led.record_order({"id": "o1"})
    led.record_fill({"order_id": "f1"})
    assert len(led.list_events()) == 3
    assert len(led.list_fills()) == 1
    assert led.list_fills()[0].payload["order_id"] == "f1"
