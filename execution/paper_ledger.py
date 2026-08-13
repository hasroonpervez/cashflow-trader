"""Paper ledger: in-memory by default, optional SQLite persist.

SQLite is paper-only. No live orders, no secrets.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Union
from uuid import uuid4

ENV_LEDGER_DB = "CASHFLOW_PAPER_LEDGER_DB"
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER_PATH = _REPO_ROOT / "data" / "paper_ledger.sqlite"

PathLike = Union[str, Path]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_ledger_path(path: Optional[PathLike] = None) -> Path:
    if path is not None and str(path).strip():
        return Path(path).expanduser()
    env = os.environ.get(ENV_LEDGER_DB, "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_LEDGER_PATH


def _parse_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        ts = raw
    else:
        s = str(raw).replace("Z", "+00:00")
        try:
            ts = datetime.fromisoformat(s)
        except ValueError:
            ts = _utc_now()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


@dataclass
class LedgerEvent:
    kind: str
    payload: Mapping[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex)
    ts: datetime = field(default_factory=_utc_now)


class PaperLedger:
    """Append-only paper ledger. Optional SQLite so calib/edge survive restart."""

    def __init__(self, db_path: Optional[PathLike] = None, *, persist: bool = False) -> None:
        self._events: list[LedgerEvent] = []
        self._db_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        if persist or db_path is not None:
            self._db_path = resolve_ledger_path(db_path)
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id TEXT PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            self._conn.commit()
            self._load()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _load(self) -> None:
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT id, ts, kind, payload FROM events ORDER BY ts, id"
        ).fetchall()
        events: list[LedgerEvent] = []
        for eid, ts, kind, payload in rows:
            try:
                body = json.loads(payload)
            except json.JSONDecodeError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            events.append(
                LedgerEvent(kind=str(kind), payload=body, id=str(eid), ts=_parse_ts(ts))
            )
        self._events = events

    def _append(self, ev: LedgerEvent) -> LedgerEvent:
        self._events.append(ev)
        if self._conn is not None:
            self._conn.execute(
                "INSERT OR REPLACE INTO events (id, ts, kind, payload) VALUES (?, ?, ?, ?)",
                (
                    ev.id,
                    ev.ts.isoformat(),
                    ev.kind,
                    json.dumps(dict(ev.payload), default=str),
                ),
            )
            self._conn.commit()
        return ev

    def record_signal(self, signal: Mapping[str, Any]) -> LedgerEvent:
        return self._append(LedgerEvent(kind="signal", payload=dict(signal)))

    def record_order(self, order: Mapping[str, Any]) -> LedgerEvent:
        return self._append(LedgerEvent(kind="order", payload=dict(order)))

    def record_fill(self, fill: Mapping[str, Any]) -> LedgerEvent:
        return self._append(LedgerEvent(kind="fill", payload=dict(fill)))

    def record_outcome(self, outcome: Mapping[str, Any]) -> LedgerEvent:
        return self._append(LedgerEvent(kind="outcome", payload=dict(outcome)))

    def record_kill(self, order_id: str) -> LedgerEvent:
        return self._append(
            LedgerEvent(kind="kill", payload={"order_id": str(order_id), "paper_only": True})
        )

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

    def killed_order_ids(self) -> list[str]:
        out: list[str] = []
        for ev in self.list_events("kill"):
            oid = str(ev.payload.get("order_id") or "").strip()
            if oid:
                out.append(oid)
        return out
