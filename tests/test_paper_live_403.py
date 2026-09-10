"""mode=live stays 403 after Pulse paper wiring. No Yahoo / Streamlit."""
from __future__ import annotations

from pathlib import Path

import pytest

litestar = pytest.importorskip("litestar")
from litestar.testing import TestClient  # noqa: E402


def _client(tmp_path: Path):
    from api.app import create_app

    app = create_app(
        db_path=tmp_path / "snapshots.sqlite",
        ledger_path=tmp_path / "paper_ledger.sqlite",
    )
    return TestClient(app=app)


def test_paper_endpoints_refuse_live(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        for path in (
            "/paper/preview",
            "/paper/place",
            "/api/paper/place",
            "/paper/kill",
            "/paper/settle",
        ):
            r = client.post(
                path,
                json={
                    "market": "DEMO-MARKET",
                    "side": "yes",
                    "p_true": 0.65,
                    "mode": "live",
                    "pnl": 1.0,
                    "order_id": "x",
                },
            )
            assert r.status_code == 403, (path, r.text)
            assert "live" in str(r.json().get("detail", "")).lower()


def test_paper_place_records_slippage_not_live(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        r = client.post(
            "/paper/place",
            json={
                "market": "DEMO-MARKET",
                "side": "yes",
                "p_true": 0.65,
                "mode": "dry_run",
                "slippage_bps": 7.0,
                "fee_rate": 0.001,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["live"] is False
        assert body["slippage_bps"] == 7.0
        assert body["fee_rate"] == 0.001
        assert body["cpcv"] is not None
        assert body["cpcv"]["ok"] is False
        assert body["fill"]["slippage_bps"] == 7.0
