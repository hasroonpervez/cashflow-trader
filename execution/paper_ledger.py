"""In-memory paper ledger for signals, orders, fills, and outcomes."""
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
    """Append-only paper ledger including outcome/PnL rows for calib feedback."""

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

    def record_outcome(self, outcome: Mapping[str, Any]) -> LedgerEvent:
        """Record settlement / PnL for calib → gate / shrink loops."""
        ev = LedgerEvent(kind="outcome", payload=dict(outcome))
        self._events.append(ev)
        return ev

    def settle_outcome(
        self, *, signal_id: str, pnl: float, extra: Mapping | None = None
    ) -> LedgerEvent:
        payload = {"signal_id": signal_id, "pnl": float(pnl), "settled": True}
        if extra:
            payload.update(dict(extra))
        return self.record_outcome(payload)

    def list_events(self, kind: str | None = None) -> list[LedgerEvent]:
        if kind is None:
            return list(self._events)
        return [e for e in self._events if e.kind == kind]

    def list_fills(self) -> list[LedgerEvent]:
        return self.list_events("fill")

    def list_outcomes(self) -> list[LedgerEvent]:
        return self.list_events("outcome")
