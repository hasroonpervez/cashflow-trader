"""SQLite WAL snapshot store for OHLCV bars.

Used by ingest workers and the Streamlit read helper. Missing DB files are a
normal Cloud case: callers must treat absence as "no snapshot", never as a
hard failure.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Union

try:
    import pandas as pd
except ImportError:  # pragma: no cover - pandas is a runtime dep of the app
    pd = None  # type: ignore[assignment]

ENV_DB = "CASHFLOW_SNAPSHOTS_DB"
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _REPO_ROOT / "data" / "snapshots.sqlite"

PathLike = Union[str, Path]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    source TEXT,
    PRIMARY KEY (symbol, ts)
)
"""


def resolve_db_path(path: Optional[PathLike] = None) -> Path:
    """Resolve snapshot DB path: explicit arg, then env, then repo default."""
    if path is not None and str(path).strip():
        return Path(path).expanduser()
    env = os.environ.get(ENV_DB, "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_DB_PATH


def _norm_symbol(symbol: str) -> str:
    return str(symbol).upper().strip()


def _norm_ts(ts: Any) -> str:
    """Store timestamps as ISO date (daily) or ISO datetime (intraday)."""
    if isinstance(ts, datetime):
        if ts.hour or ts.minute or ts.second or ts.microsecond:
            return ts.strftime("%Y-%m-%dT%H:%M:%S")
        return ts.strftime("%Y-%m-%d")
    if isinstance(ts, date):
        return ts.isoformat()
    s = str(ts).strip()
    if not s:
        raise ValueError("empty timestamp")
    s = s.replace("Z", "").replace(" ", "T")
    if "T" in s:
        date_part, time_part = s.split("T", 1)
        time_part = time_part.split(".")[0][:8]
        if not time_part or time_part in ("00:00:00", "0:00:00"):
            return date_part
        if len(time_part) == 5:
            time_part = time_part + ":00"
        return f"{date_part}T{time_part}"
    return s[:10]


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def connect(path: Optional[PathLike] = None, *, create: bool = True) -> sqlite3.Connection:
    """Open a SQLite connection in WAL mode and ensure the ``bars`` table exists.

    ``create=False`` does not mkdir or create a missing file (read path / Cloud).
    """
    db_path = resolve_db_path(path)
    if create:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    elif not db_path.is_file():
        raise FileNotFoundError(str(db_path))
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


@contextmanager
def open_db(path: Optional[PathLike] = None, *, create: bool = True) -> Iterator[sqlite3.Connection]:
    conn = connect(path, create=create)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_bars(
    conn: sqlite3.Connection,
    rows: Iterable[Mapping[str, Any]],
    *,
    default_symbol: Optional[str] = None,
    default_source: str = "provided",
) -> int:
    """Insert or replace bars. Returns the number of rows written."""
    payload: list[tuple] = []
    fallback_sym = _norm_symbol(default_symbol) if default_symbol else ""
    for row in rows:
        sym = _norm_symbol(row.get("symbol") or fallback_sym)
        if not sym:
            raise ValueError("bar row missing symbol")
        ts = _norm_ts(row.get("ts") or row.get("timestamp") or row.get("date"))
        source = str(row.get("source") or default_source)
        payload.append(
            (
                sym,
                ts,
                _as_float(row.get("open") if "open" in row else row.get("Open")),
                _as_float(row.get("high") if "high" in row else row.get("High")),
                _as_float(row.get("low") if "low" in row else row.get("Low")),
                _as_float(row.get("close") if "close" in row else row.get("Close")),
                _as_float(row.get("volume") if "volume" in row else row.get("Volume")) or 0.0,
                source,
            )
        )
    if not payload:
        return 0
    conn.executemany(
        """
        INSERT INTO bars (symbol, ts, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, ts) DO UPDATE SET
            open=excluded.open,
            high=excluded.high,
            low=excluded.low,
            close=excluded.close,
            volume=excluded.volume,
            source=excluded.source
        """,
        payload,
    )
    conn.commit()
    return len(payload)


def has_snapshot(conn: sqlite3.Connection, symbol: str) -> bool:
    sym = _norm_symbol(symbol)
    if not sym:
        return False
    row = conn.execute(
        "SELECT 1 FROM bars WHERE symbol = ? LIMIT 1",
        (sym,),
    ).fetchone()
    return row is not None


def latest_bars(conn: sqlite3.Connection, symbol: str, n: int = 252):
    """Return the newest ``n`` bars for ``symbol`` as a chronological DataFrame.

    Columns match ``fetch_stock``: Open, High, Low, Close, Volume with a
    tz-naive DatetimeIndex. Empty snapshot → empty DataFrame (not None).
    """
    if pd is None:
        raise RuntimeError("pandas is required for latest_bars")
    sym = _norm_symbol(symbol)
    limit = max(int(n), 0)
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    empty.attrs["source"] = "snapshot"
    if not sym or limit <= 0:
        return empty
    rows = conn.execute(
        """
        SELECT ts, open, high, low, close, volume, source
        FROM bars
        WHERE symbol = ?
        ORDER BY ts DESC
        LIMIT ?
        """,
        (sym, limit),
    ).fetchall()
    if not rows:
        return empty
    rows = list(reversed(rows))
    idx = pd.to_datetime([r["ts"] for r in rows])
    df = pd.DataFrame(
        {
            "Open": [r["open"] for r in rows],
            "High": [r["high"] for r in rows],
            "Low": [r["low"] for r in rows],
            "Close": [r["close"] for r in rows],
            "Volume": [r["volume"] for r in rows],
        },
        index=idx,
    )
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    sources = {r["source"] for r in rows if r["source"]}
    df.attrs["source"] = "snapshot"
    df.attrs["snapshot_source"] = next(iter(sources)) if len(sources) == 1 else "snapshot"
    return df
