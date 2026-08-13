"""Unit tests for execution.paper_ledger."""
from __future__ import annotations

from datetime import datetime, timezone

from execution.paper_ledger import PaperLedger


def test_records_signal_order_fill_with_utc():
    led = PaperLedger(":memory:")
    ts = datetime(2026, 8, 12, 20, 0, 0, tzinfo=timezone.utc)
    s = led.record_signal({"strategy": "demo", "market_id": "M1"}, signal_id="s1", ts=ts)
    o = led.record_order({"market_id": "M1", "quantity": 3}, order_id="o1", ts=ts)
    f = led.record_fill({"order_id": "o1", "filled_qty": 3}, fill_id="f1", ts=ts)

    assert s.ts_utc.endswith("Z")
    assert o.ts_utc.endswith("Z")
    assert f.ts_utc.endswith("Z")
    assert led.count() == {"signal": 1, "order": 1, "fill": 1}
    assert led.signals()[0].payload["signal_id"] == "s1"
    assert led.orders()[0].payload["order_id"] == "o1"
    assert led.fills()[0].payload["fill_id"] == "f1"
    led.close()


def test_list_kind_order_is_append_order():
    led = PaperLedger()
    led.record_signal({"n": 1}, signal_id="a")
    led.record_signal({"n": 2}, signal_id="b")
    ids = [r.payload["signal_id"] for r in led.signals()]
    assert ids == ["a", "b"]
