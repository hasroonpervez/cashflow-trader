"""Phase B Litestar snapshot API. Temp SQLite only — no network."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

litestar = pytest.importorskip("litestar")
from litestar.testing import TestClient  # noqa: E402

from workers.ingest_bars import ingest_provided

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
    dates = pd.bdate_range("2025-01-02", periods=n)
    rows = [_bar(d.strftime("%Y-%m-%d"), close=float(10 + i)) for i, d in enumerate(dates, start=2)]
    ingest_provided(str(db), "AAPL", rows, source="test")


def _client(tmp_path: Path, *, seed: bool = True, ledger_path=None):
    from api.app import create_app

    db = tmp_path / "snapshots.sqlite"
    if seed:
        _write_aapl(db, n=5)
    led = ledger_path or (tmp_path / "paper_ledger.sqlite")
    app = create_app(db_path=db, ledger_path=led)
    return TestClient(app=app), db


def _boom(*a, **k):
    raise AssertionError("external fetch must not run in Phase B API handlers")


@pytest.fixture
def no_yahoo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yfinance.download", _boom, raising=False)
    monkeypatch.setattr("yfinance.Ticker", _boom, raising=False)
    monkeypatch.setattr("modules.data.fetch_stock", _boom, raising=False)
    monkeypatch.setattr("modules.snapshot_bars.load_bars", _boom, raising=False)
    if "yfinance" in sys.modules:
        monkeypatch.setattr(sys.modules["yfinance"], "download", _boom, raising=False)


def test_health(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path, seed=False)
    with client:
        for path in ("/health", "/api/health"):
            r = client.get(path)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "ok"
            assert body["mode"] == "paper"
            assert body["live"] is False
            assert "127.0.0.1" in body["bind"]


def test_bars_from_snapshot(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path)
    with client:
        r = client.get("/bars/AAPL")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["symbol"] == "AAPL"
        assert body["source"] == "snapshot"
        assert body["count"] == 5
        assert body["bars"][-1]["close"] == pytest.approx(16.0)
        assert "ts" in body["bars"][0]
        r2 = client.get("/api/bars/AAPL?n=2")
        assert r2.status_code == 200
        assert r2.json()["count"] == 2
        assert r2.json()["bars"][-1]["close"] == pytest.approx(16.0)


def test_bars_missing_snapshot_404_no_yahoo(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path, seed=True)
    with client:
        r = client.get("/bars/MSFT")
        assert r.status_code == 404
        body = r.json()
        assert "detail" in body
        assert "MSFT" in str(body["detail"])


def test_bars_missing_db_file_404(tmp_path: Path, no_yahoo: None) -> None:
    from api.app import create_app

    missing = tmp_path / "nope.sqlite"
    app = create_app(db_path=missing)
    with TestClient(app=app) as client:
        r = client.get("/api/bars/AAPL")
        assert r.status_code == 404


def test_snapshot_exists(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path)
    with client:
        yes = client.get("/snapshot/aapl")
        assert yes.status_code == 200
        assert yes.json() == {"symbol": "AAPL", "exists": True}
        no = client.get("/api/snapshot/MSFT")
        assert no.status_code == 200
        assert no.json() == {"symbol": "MSFT", "exists": False}


def test_paper_preview_dry_run(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path, seed=False)
    with client:
        r = client.post(
            "/paper/preview",
            json={
                "market": "DEMO-MARKET",
                "side": "yes",
                "p_true": 0.65,
                "source": "api.test",
                "edge": 0.05,
                "bankroll": 1000.0,
                "gate_stats": {"outcomes": []},
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["live"] is False
        assert body["mode"] == "dry_run"
        assert body["preview"] is True
        assert body["accepted"] is True
        assert body["fill"] is not None
        assert body["stake"] > 0


def test_paper_place_dry_run(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path, seed=False)
    with client:
        r = client.post(
            "/api/paper/place",
            json={
                "market": "DEMO-MARKET",
                "side": "yes",
                "p_true": 0.65,
                "source": "api.test",
                "bankroll": 1000.0,
                "id": "abc123",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["preview"] is False
        assert body["live"] is False
        assert body["mode"] == "dry_run"
        assert body["fill"]["order_id"].startswith("dry-")
        assert body["signal_id"] == "abc123"


def test_paper_live_mode_refused(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path, seed=False)
    with client:
        for path in ("/paper/preview", "/paper/place", "/api/paper/place", "/paper/kill", "/api/paper/kill", "/paper/settle", "/api/paper/settle"):
            r = client.post(
                path,
                json={
                    "market": "DEMO-MARKET",
                    "side": "yes",
                    "p_true": 0.65,
                    "mode": "live",
                },
            )
            assert r.status_code == 403, (path, r.text)
            assert "live" in str(r.json().get("detail", "")).lower()


def test_paper_place_rejects_live_adapter_construction(tmp_path: Path, no_yahoo: None) -> None:
    """place_order live remains refused at the venue adapter."""
    from venues.base import Mode, OrderRequest
    from venues.kalshi.adapter import KalshiDryRunAdapter

    with pytest.raises(ValueError):
        KalshiDryRunAdapter(mode=Mode.LIVE)
    adapter = KalshiDryRunAdapter(mode=Mode.PAPER)
    adapter.mode = Mode.LIVE
    with pytest.raises(PermissionError):
        adapter.place_order(OrderRequest(market="M", side="yes", size=1.0, signal_id="sig"))


def test_api_module_does_not_import_yfinance() -> None:
    src = (_REPO / "api" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "yfinance" not in imported
    assert "modules.data" not in src
    assert "fetch_stock" not in src


def test_paper_positions_and_kill(tmp_path: Path, no_yahoo: None) -> None:
    client, _ = _client(tmp_path, seed=False)
    with client:
        empty = client.get("/paper/positions")
        assert empty.status_code == 200, empty.text
        assert empty.json()["live"] is False
        assert empty.json()["positions"] == []
        placed = client.post(
            "/paper/place",
            json={
                "market": "DEMO-MARKET",
                "side": "yes",
                "p_true": 0.65,
                "mode": "dry_run",
                "id": "pos-1",
            },
        )
        assert placed.status_code == 201, placed.text
        oid = placed.json()["fill"]["order_id"]
        book = client.get("/api/paper/positions")
        assert book.status_code == 200
        assert book.json()["count"] == 1
        assert book.json()["positions"][0]["order_id"] == oid
        killed = client.post("/paper/kill", json={"order_id": oid})
        assert killed.status_code == 201, killed.text
        assert killed.json()["live"] is False
        assert oid in killed.json()["cancelled"]
        after = client.get("/paper/positions")
        assert after.json()["positions"] == []


def test_paper_ledger_survives_app_restart(tmp_path: Path, no_yahoo: None) -> None:
    """SQLite ledger: positions and kills survive a new create_app."""
    from api.app import create_app

    db = tmp_path / "snapshots.sqlite"
    led = tmp_path / "paper_ledger.sqlite"
    with TestClient(app=create_app(db_path=db, ledger_path=led)) as client:
        placed = client.post(
            "/paper/place",
            json={"market": "DEMO-MARKET", "side": "yes", "p_true": 0.65, "mode": "dry_run"},
        )
        assert placed.status_code == 201, placed.text
        oid = placed.json()["fill"]["order_id"]
    with TestClient(app=create_app(db_path=db, ledger_path=led)) as client:
        book = client.get("/paper/positions")
        assert book.status_code == 200
        assert book.json()["count"] == 1
        assert book.json()["positions"][0]["order_id"] == oid
        killed = client.post("/paper/kill", json={"order_id": oid})
        assert killed.status_code == 201, killed.text
    with TestClient(app=create_app(db_path=db, ledger_path=led)) as client:
        after = client.get("/paper/positions")
        assert after.json()["positions"] == []


def test_place_seeds_gate_stats_from_ledger(tmp_path: Path, no_yahoo: None) -> None:
    """Settled SQLite outcomes seed the next preview/place. Body cannot clobber."""
    from api.app import create_app
    from execution.paper_ledger import PaperLedger
    from risk.calib import apply_settlement

    db = tmp_path / "snapshots.sqlite"
    led = tmp_path / "paper_ledger.sqlite"
    with TestClient(app=create_app(db_path=db, ledger_path=led)) as client:
        first = client.post(
            "/paper/place",
            json={"market": "DEMO-MARKET", "side": "yes", "p_true": 0.65, "mode": "dry_run"},
        )
        assert first.status_code == 201, first.text
        oid = first.json()["fill"]["order_id"]
        assert first.json()["edge"]["n"] == 0
    persist = PaperLedger(db_path=led, persist=True)
    apply_settlement(persist, oid, 1.25)
    persist.close()
    with TestClient(app=create_app(db_path=db, ledger_path=led)) as client:
        preview = client.post(
            "/paper/preview",
            json={
                "market": "DEMO-MARKET",
                "side": "yes",
                "p_true": 0.65,
                "gate_stats": {"outcomes": [99.0], "min_n": 30},
            },
        )
        assert preview.status_code == 201, preview.text
        assert preview.json()["preview"] is True
        assert preview.json()["edge"]["n"] == 1
        assert client.get("/paper/positions").json()["count"] == 1
        second = client.post(
            "/paper/place",
            json={
                "market": "DEMO-MARKET",
                "side": "yes",
                "p_true": 0.65,
                "mode": "dry_run",
                "gate_stats": {"outcomes": [99.0]},
            },
        )
        assert second.status_code == 201, second.text
        assert second.json()["edge"]["n"] == 1
        assert client.get("/paper/positions").json()["count"] == 2


def test_paper_settle_seeds_edge_across_restart(tmp_path: Path, no_yahoo: None) -> None:
    """POST /paper/settle writes PnL; next app preview/place see edge.n."""
    from api.app import create_app

    db = tmp_path / "snapshots.sqlite"
    led = tmp_path / "paper_ledger.sqlite"
    with TestClient(app=create_app(db_path=db, ledger_path=led)) as client:
        placed = client.post(
            "/paper/place",
            json={"market": "DEMO-MARKET", "side": "yes", "p_true": 0.65, "mode": "dry_run"},
        )
        assert placed.status_code == 201, placed.text
        oid = placed.json()["fill"]["order_id"]
        missing = client.post("/paper/settle", json={"order_id": "no-such", "pnl": 1.0})
        assert missing.status_code == 404
        bad = client.post("/paper/settle", json={"order_id": oid})
        assert bad.status_code == 400
        settled = client.post("/paper/settle", json={"order_id": oid, "pnl": 1.25})
        assert settled.status_code == 201, settled.text
        assert settled.json()["live"] is False
        assert settled.json()["settled"] is True
        assert settled.json()["pnl"] == 1.25
    with TestClient(app=create_app(db_path=db, ledger_path=led)) as client:
        preview = client.post(
            "/paper/preview",
            json={"market": "DEMO-MARKET", "side": "yes", "p_true": 0.65},
        )
        assert preview.status_code == 201, preview.text
        assert preview.json()["edge"]["n"] == 1
        assert client.get("/paper/positions").json()["count"] == 1
