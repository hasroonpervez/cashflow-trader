"""Read helper: prefer SQLite WAL snapshots, else existing Yahoo fetch.

``load_bars(symbol)`` is the Streamlit-facing wrapper. Missing / empty DBs
are not errors (Streamlit Cloud must not hard-fail).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from workers.store import (
    connect,
    has_snapshot as store_has_snapshot,
    latest_bars,
    resolve_db_path,
)

PathLike = Union[str, Path]

# Keep this module importable without pulling ``modules.data`` (streamlit /
# yfinance). Tag matches ``modules.data.PRICE_BASIS_ADJUSTED``.
_PRICE_BASIS_ADJUSTED = "adjusted"

# Same tails ``modules.data._fetch_stock_alphavantage`` uses so a snapshot
# substitutes for a Yahoo ``period=`` request without changing callers.
_PERIOD_TAIL = {
    "1d": 5,
    "5d": 8,
    "1mo": 24,
    "3mo": 66,
    "6mo": 128,
    "1y": 270,
    "2y": 540,
    "5y": 1300,
    "10y": 2600,
}


def _tail_n(period: str, n: Optional[int]) -> int:
    if n is not None:
        return max(int(n), 0)
    return int(_PERIOD_TAIL.get(str(period), 270))


def has_snapshot(symbol: str, db_path: Optional[PathLike] = None) -> bool:
    """True when the snapshot DB exists and has at least one bar for ``symbol``."""
    try:
        path = resolve_db_path(db_path)
        if not path.is_file():
            return False
        conn = connect(path, create=False)
        try:
            return store_has_snapshot(conn, symbol)
        finally:
            conn.close()
    except Exception:
        return False


def try_snapshot_bars(
    symbol: str,
    *,
    n: Optional[int] = None,
    period: str = "1y",
    db_path: Optional[PathLike] = None,
):
    """Return snapshot bars or ``None``. Never fetches Yahoo. Never raises."""
    try:
        path = resolve_db_path(db_path)
        if not path.is_file():
            return None
        limit = _tail_n(period, n)
        conn = connect(path, create=False)
        try:
            if not store_has_snapshot(conn, symbol):
                return None
            df = latest_bars(conn, symbol, limit)
        finally:
            conn.close()
        if df is None or getattr(df, "empty", True):
            return None
        df.attrs["price_basis"] = _PRICE_BASIS_ADJUSTED
        df.attrs["source"] = "snapshot"
        return df
    except Exception:
        return None


def load_bars(
    symbol: str,
    *,
    n: Optional[int] = None,
    period: str = "1y",
    db_path: Optional[PathLike] = None,
    fallback: bool = True,
):
    """Snapshot if present, else existing ``fetch_stock`` (Yahoo / AV).

    ``fallback=True`` is the Cloud-safe default: empty DB → live fetch.
    """
    snap = try_snapshot_bars(symbol, n=n, period=period, db_path=db_path)
    if snap is not None:
        return snap
    if not fallback:
        return None
    from modules.data import fetch_stock

    return fetch_stock(symbol, period=period, interval="1d")
