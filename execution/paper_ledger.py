"""In-memory / SQLite paper ledger for signals, orders, and fills (UTC).

Persistence note
----------------
The existing ``db/`` Alembic chain targets Postgres partitioned market-data
tables. Paper trade accounting is intentionally kept in this lightweight
SQLite / in-memory store so P0 does not couple to that schema. See
``docs/P0_MULTI_VENUE.md``.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class LedgerRow:
    kind: str
    row_id: str
    ts_utc: str
    payload: dict[str, Any]


class PaperLedger:
    """Append-only paper ledger backed by SQLite (``:memory:`` by default)."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS paper_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                row_id TEXT NOT NULL UNIQUE,
                ts_utc TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_paper_events_kind ON paper_events(kind);
            CREATE INDEX IF NOT EXISTS ix_paper_events_ts ON paper_events(ts_utc);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _insert(self, kind: str, payload: dict[str, Any], row_id: Optional[str] = None,
                ts: Optional[datetime] = None) -> LedgerRow:
        rid = row_id or str(uuid4())
        ts_utc = _iso(ts or utcnow())
        self._conn.execute(
            "INSERT INTO paper_events (kind, row_id, ts_utc, payload_json) VALUES (?, ?, ?, ?)",
            (kind, rid, ts_utc, json.dumps(payload, default=str)),
        )
        self._conn.commit()
        return LedgerRow(kind=kind, row_id=rid, ts_utc=ts_utc, payload=payload)

    def record_signal(self, signal_payload: dict[str, Any], *,
                      signal_id: Optional[str] = None,
                      ts: Optional[datetime] = None) -> LedgerRow:
        payload = dict(signal_payload)
        sid = signal_id or payload.get("signal_id") or str(uuid4())
        payload["signal_id"] = sid
        return self._insert("signal", payload, row_id=f"sig-{sid}", ts=ts)

    def record_order(self, order_payload: dict[str, Any], *,
                     order_id: Optional[str] = None,
                     ts: Optional[datetime] = None) -> LedgerRow:
        payload = dict(order_payload)
        oid = order_id or payload.get("order_id") or str(uuid4())
        payload["order_id"] = oid
        return self._insert("order", payload, row_id=f"ord-{oid}", ts=ts)

    def record_fill(self, fill_payload: dict[str, Any], *,
                    fill_id: Optional[str] = None,
                    ts: Optional[datetime] = None) -> LedgerRow:
        payload = dict(fill_payload)
        fid = fill_id or payload.get("fill_id") or str(uuid4())
        payload["fill_id"] = fid
        return self._insert("fill", payload, row_id=f"fill-{fid}", ts=ts)

    def list_kind(self, kind: str) -> list[LedgerRow]:
        cur = self._conn.execute(
            "SELECT kind, row_id, ts_utc, payload_json FROM paper_events "
            "WHERE kind = ? ORDER BY id ASC",
            (kind,),
        )
        out: list[LedgerRow] = []
        for row in cur.fetchall():
            out.append(
                LedgerRow(
                    kind=row["kind"],
                    row_id=row["row_id"],
                    ts_utc=row["ts_utc"],
                    payload=json.loads(row["payload_json"]),
                )
            )
        return out

    def signals(self) -> list[LedgerRow]:
        return self.list_kind("signal")

    def orders(self) -> list[LedgerRow]:
        return self.list_kind("order")

    def fills(self) -> list[LedgerRow]:
        return self.list_kind("fill")

    def count(self) -> dict[str, int]:
        cur = self._conn.execute(
            "SELECT kind, COUNT(*) AS n FROM paper_events GROUP BY kind"
        )
        return {row["kind"]: int(row["n"]) for row in cur.fetchall()}
