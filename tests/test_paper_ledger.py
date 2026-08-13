"""Unit tests for execution.paper_ledger."""
from __future__ import annotations

from execution.paper_ledger import PaperLedger


def test_record_and_list_fills() -> None:
    ledger = PaperLedger()
    ledger.record_signal({"id": "s1"})
    ledger.record_order({"market": "M", "size": 10})
    ledger.record_fill({"order_id": "o1", "price": 0.4})
    ledger.record_fill({"order_id": "o2", "price": 0.5})

    fills = ledger.list_fills()
    assert len(fills) == 2
    assert fills[0].kind == "fill"
    assert fills[0].payload["order_id"] == "o1"
    assert fills[1].payload["order_id"] == "o2"


def test_list_events_filter() -> None:
    ledger = PaperLedger()
    ledger.record_signal({"id": "s1"})
    ledger.record_order({"id": "o1"})
    assert len(ledger.list_events()) == 2
    assert len(ledger.list_events("signal")) == 1
    assert len(ledger.list_events("order")) == 1
    assert ledger.list_fills() == []


def test_in_memory_isolation() -> None:
    a = PaperLedger()
    b = PaperLedger()
    a.record_fill({"order_id": "only-a"})
    assert len(a.list_fills()) == 1
    assert len(b.list_fills()) == 0
