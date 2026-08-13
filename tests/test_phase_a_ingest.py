"""Phase A: SQLite WAL ingest snapshots. No network."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from workers.ingest_bars import ingest_provided, main as ingest_main
from workers.store import (
    connect,
    has_snapshot,
    latest_bars,
    open_db,
    upsert_bars,
)

_REPO = Path(__file__).resolve().parent.parent


def _bar(ts: str, close: float = 10.0, **extra):
    row = {
        "ts": ts,
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "volume": 1000.0,
        "source": "test",
    }
    row.update(extra)
    return row


def _write_aapl(db: Path, n: int = 3) -> None:
    rows = [_bar(f"2026-01-{i:02d}", close=float(10 + i)) for i in range(2, 2 + n)]
    ingest_provided(str(db), "AAPL", rows, source="test")


def test_connect_uses_wal(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.sqlite"
    conn = connect(db)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        cols = {r[1] for r in conn.execute("PRAGMA table_info(bars)").fetchall()}
        assert cols == {"symbol", "ts", "open", "high", "low", "close", "volume", "source"}
    finally:
        conn.close()


def test_upsert_latest_and_has_snapshot(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.sqlite"
    _write_aapl(db, n=5)
    with open_db(db, create=False) as conn:
        assert has_snapshot(conn, "aapl") is True
        assert has_snapshot(conn, "MSFT") is False
        df = latest_bars(conn, "AAPL", n=3)
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert len(df) == 3
        assert df["Close"].iloc[-1] == pytest.approx(16.0)
        assert df.index.is_monotonic_increasing


def test_upsert_replaces_on_primary_key(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.sqlite"
    ingest_provided(str(db), "AAPL", [_bar("2026-01-02", close=10.0)])
    ingest_provided(str(db), "AAPL", [_bar("2026-01-02", close=11.5, volume=50)])
    with open_db(db, create=False) as conn:
        df = latest_bars(conn, "AAPL", n=10)
        assert len(df) == 1
        assert df["Close"].iloc[0] == pytest.approx(11.5)
        assert df["Volume"].iloc[0] == pytest.approx(50.0)


def test_has_snapshot_false_when_file_missing(tmp_path: Path) -> None:
    from modules.snapshot_bars import has_snapshot as helper_has
    from modules.snapshot_bars import try_snapshot_bars

    missing = tmp_path / "nope.sqlite"
    assert helper_has("AAPL", db_path=missing) is False
    assert try_snapshot_bars("AAPL", db_path=missing) is None


def test_load_bars_returns_snapshot_when_present(tmp_path: Path) -> None:
    from modules.snapshot_bars import load_bars

    db = tmp_path / "snapshots.sqlite"
    _write_aapl(db, n=4)
    df = load_bars("AAPL", n=10, db_path=db, fallback=False)
    assert df is not None
    assert len(df) == 4
    assert df.attrs.get("source") == "snapshot"
    assert df.attrs.get("price_basis") == "adjusted"


def test_load_bars_fallback_when_db_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from modules import snapshot_bars as SB

    sentinel = pd.DataFrame(
        {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1.0]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    sentinel.attrs["source"] = "yahoo"

    def _fake_fetch(symbol, period="1y", interval="1d"):
        assert symbol == "AAPL"
        return sentinel

    monkeypatch.setattr("modules.data.fetch_stock", _fake_fetch)
    empty = tmp_path / "empty.sqlite"
    connect(empty).close()
    out = SB.load_bars("AAPL", db_path=empty, fallback=True)
    assert out is sentinel


def test_load_bars_missing_db_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.snapshot_bars import load_bars

    monkeypatch.setattr(
        "modules.data.fetch_stock",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not fetch when fallback=False")),
    )
    out = load_bars("AAPL", db_path=tmp_path / "missing.sqlite", fallback=False)
    assert out is None


def test_cli_writes_provided_bars_without_fetch(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.sqlite"
    bars_path = tmp_path / "bars.json"
    bars_path.write_text(json.dumps([_bar("2026-01-02", close=42.0)]), encoding="utf-8")
    rc = ingest_main(
        ["--db", str(db), "--symbols", "AAPL", "--bars-json", str(bars_path)]
    )
    assert rc == 0
    with open_db(db, create=False) as conn:
        df = latest_bars(conn, "AAPL", n=5)
        assert len(df) == 1
        assert df["Close"].iloc[0] == pytest.approx(42.0)


def test_cli_module_subprocess_no_network(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.sqlite"
    bars_path = tmp_path / "bars.json"
    bars_path.write_text(json.dumps([_bar("2026-01-03", close=7.0)]), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "workers.ingest_bars",
            "--db",
            str(db),
            "--symbols",
            "AAPL",
            "--bars-json",
            str(bars_path),
        ],
        cwd=str(_REPO),
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    with open_db(db, create=False) as conn:
        assert has_snapshot(conn, "AAPL")
        assert latest_bars(conn, "AAPL", n=1)["Close"].iloc[0] == pytest.approx(7.0)


def test_cli_default_does_not_call_yahoo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(symbol: str):
        raise AssertionError(f"yahoo fetch must not run for {symbol}")

    monkeypatch.setattr("workers.ingest_bars._bars_from_yahoo", _boom)
    rc = ingest_main(["--db", str(tmp_path / "x.sqlite"), "--symbols", "AAPL"])
    assert rc == 0
    assert not (tmp_path / "x.sqlite").exists()


def test_cli_fetch_flag_is_off_by_default() -> None:
    from workers.ingest_bars import parse_args

    args = parse_args(["--db", "x.sqlite", "--symbols", "AAPL"])
    assert args.fetch is False


def test_fetch_stock_uses_snapshot_not_yahoo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modules import data as D

    db = tmp_path / "snapshots.sqlite"
    _write_aapl(db, n=6)
    monkeypatch.setenv("CASHFLOW_SNAPSHOTS_DB", str(db))

    def _boom(*a, **k):
        raise AssertionError("Yahoo must not be called when a snapshot exists")

    monkeypatch.setattr(D, "_yfinance_ticker", _boom)
    monkeypatch.setattr(D, "_fetch_stock_alphavantage", _boom)
    if hasattr(D.fetch_stock, "clear"):
        D.fetch_stock.clear()
    out = D.fetch_stock("AAPL", "1y", "1d")
    assert out is not None
    assert not out.empty
    assert out.attrs.get("source") == "snapshot"
    assert "Close" in out.columns


def test_fetch_stock_falls_back_when_db_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modules import data as D

    monkeypatch.setenv("CASHFLOW_SNAPSHOTS_DB", str(tmp_path / "missing.sqlite"))
    sentinel = pd.DataFrame(
        {"Open": [2.0], "High": [2.0], "Low": [2.0], "Close": [2.0], "Volume": [9.0]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    sentinel.attrs["source"] = "yahoo"
    sentinel.attrs["price_basis"] = D.PRICE_BASIS_ADJUSTED
    monkeypatch.setattr(D, "retry_fetch", lambda fn: sentinel)
    if hasattr(D.fetch_stock, "clear"):
        D.fetch_stock.clear()
    out = D.fetch_stock("MSFT", "1y", "1d")
    assert out is sentinel


def test_gitignore_covers_snapshot_wal() -> None:
    text = (_REPO / ".gitignore").read_text(encoding="utf-8")
    assert "data/snapshots.sqlite*" in text
