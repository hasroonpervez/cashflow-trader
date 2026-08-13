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


def _write_symbol(db: Path, symbol: str = "AAPL", n: int = 3, start_close: float = 10.0) -> None:
    dates = pd.bdate_range("2025-01-02", periods=n)
    rows = [
        _bar(d.strftime("%Y-%m-%d"), close=float(start_close + i))
        for i, d in enumerate(dates)
    ]
    ingest_provided(str(db), symbol, rows, source="test")


def _write_aapl(db: Path, n: int = 3) -> None:
    # Closes start at 12 so n=5 still ends at 16 (existing assertions).
    dates = pd.bdate_range("2025-01-02", periods=n)
    rows = [_bar(d.strftime("%Y-%m-%d"), close=float(10 + i)) for i, d in enumerate(dates, start=2)]
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

def test_pages_boot_daily_ohlcv_prefers_snapshot_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modules.pages import boot_daily_ohlcv

    db = tmp_path / "snapshots.sqlite"
    _write_aapl(db, n=8)

    def _boom(*a, **k):
        raise AssertionError("pages boot helper must not network")

    monkeypatch.setattr("modules.data.fetch_stock", _boom)
    monkeypatch.setattr("modules.data.yf.download", _boom)
    monkeypatch.setattr("yfinance.download", _boom)

    out = boot_daily_ohlcv("AAPL", db_path=db)
    assert out is not None
    assert not out.empty
    assert out.attrs.get("source") == "snapshot"
    assert "Close" in out.columns
    assert len(out) == 8


def test_pages_boot_daily_ohlcv_none_when_snapshot_missing(tmp_path: Path) -> None:
    from modules.pages import boot_daily_ohlcv

    assert boot_daily_ohlcv("AAPL", db_path=tmp_path / "missing.sqlite") is None
    assert boot_daily_ohlcv("", db_path=tmp_path / "missing.sqlite") is None


def test_build_context_prefers_snapshot_over_yahoo_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pages.py boot uses SQLite daily bars even when the Yahoo panel is populated."""
    from unittest.mock import MagicMock, patch

    from modules.data import DeskMarketSnapshot, GlobalMarketSnapshot
    from modules.pages import DashContext, build_context

    db = tmp_path / "snapshots.sqlite"
    _write_symbol(db, "SNAP", n=80, start_close=50.0)
    monkeypatch.setenv("CASHFLOW_SNAPSHOTS_DB", str(db))

    dates = pd.bdate_range("2025-01-02", periods=80)
    yahoo_df = pd.DataFrame(
        {
            "Open": [1.0] * 80,
            "High": [1.0] * 80,
            "Low": [1.0] * 80,
            "Close": [1.0] * 80,
            "Volume": [1.0] * 80,
        },
        index=dates,
    )
    yahoo_df.attrs["source"] = "yahoo"
    wk_dates = pd.bdate_range("2024-01-05", periods=30, freq="W-FRI")
    weekly_df = pd.DataFrame(
        {
            "Open": [1.0] * 30,
            "High": [1.0] * 30,
            "Low": [1.0] * 30,
            "Close": [1.0] * 30,
            "Volume": [1.0] * 30,
        },
        index=wk_dates,
    )

    mock_gs = MagicMock(spec=GlobalMarketSnapshot)
    mock_gs.active_daily_df = yahoo_df
    mock_gs.active_weekly_df = weekly_df
    mock_gs.active_1mo_df = yahoo_df.iloc[-28:].copy()
    mock_gs.desk = MagicMock(spec=DeskMarketSnapshot)
    mock_gs.desk.macro = {
        "10Y Yield": {"price": 4.5, "chg": 0.0},
        "VIX": {"price": 20.0, "chg": 0.0},
    }
    mock_gs.desk.vix_1mo_df = None

    def _boom(*a, **k):
        raise AssertionError("daily Yahoo/AV must not run when a snapshot exists")

    cfg = {"watchlist": "SNAP", "use_quant_models": False}
    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.spinner = MagicMock(
        return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
    )
    mock_st.warning = MagicMock()

    with (
        patch("modules.pages.fetch_stock", _boom),
        patch("modules.pages.fetch_news_headlines", return_value=[]),
        patch("modules.pages.fetch_earnings_date", return_value=None),
        patch("modules.pages.fetch_options", return_value=([], [])),
        patch("modules.pages.st", mock_st),
        patch("modules.data.yf.download", _boom),
    ):
        ctx = build_context(
            "SNAP",
            cfg,
            global_snapshot=mock_gs,
            defer_headlines_earnings=True,
            defer_options_fetch=True,
        )

    assert isinstance(ctx, DashContext)
    assert ctx.df is not None
    assert ctx.df.attrs.get("source") == "snapshot"
    assert ctx.df["Close"].iloc[-1] == pytest.approx(50.0 + 79)
    assert ctx.df["Close"].iloc[-1] != pytest.approx(1.0)
