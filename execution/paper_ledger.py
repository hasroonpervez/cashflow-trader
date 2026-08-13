"""In-memory paper ledger for signals, orders, and fills."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LedgerEvent:
    kind: str
    payload: Mapping[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex)
    ts: datetime = field(default_factory=_utc_now)


class PaperLedger:
    """In-memory ledger: record_signal / record_order / record_fill / list_fills."""

    def __init__(self) -> None:
        self._events: list[LedgerEvent] = []

    def record_signal(self, signal: Mapping[str, Any]) -> LedgerEvent:
        ev = LedgerEvent(kind="signal", payload=dict(signal))
        self._events.append(ev)
        return ev

    def record_order(self, order: Mapping[str, Any]) -> LedgerEvent:
        ev = LedgerEvent(kind="order", payload=dict(order))
        self._events.append(ev)
        return ev

    def record_fill(self, fill: Mapping[str, Any]) -> LedgerEvent:
        ev = LedgerEvent(kind="fill", payload=dict(fill))
        self._events.append(ev)
        return ev

    def list_events(self, kind: str | None = None) -> list[LedgerEvent]:
        if kind is None:
            return list(self._events)
        return [e for e in self._events if e.kind == kind]

    def list_fills(self) -> list[LedgerEvent]:
        return self.list_events("fill")
