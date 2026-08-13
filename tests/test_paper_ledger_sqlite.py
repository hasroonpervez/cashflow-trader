"""SQLite paper ledger persist. Paper only."""
from __future__ import annotations

from pathlib import Path

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from risk.calib import apply_settlement, gate_stats_from_ledger
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter


def _signal() -> Signal:
    return Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="Sig_K.unit",
        edge=0.05,
    )


def test_sqlite_ledger_reloads_fills(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    a = PaperLedger(db_path=path, persist=True)
    a.record_fill({"order_id": "dry-1", "market": "M"})
    a.close()
    b = PaperLedger(db_path=path, persist=True)
    fills = b.list_fills()
    assert len(fills) == 1
    assert fills[0].payload["order_id"] == "dry-1"
    b.close()


def test_sqlite_kill_survives_reload(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    a = PaperLedger(db_path=path, persist=True)
    a.record_fill({"order_id": "dry-2"})
    a.record_kill("dry-2")
    a.close()
    b = PaperLedger(db_path=path, persist=True)
    assert "dry-2" in b.killed_order_ids()
    b.close()


def test_memory_ledger_unchanged_default() -> None:
    led = PaperLedger()
    led.record_fill({"order_id": "m1"})
    assert led._conn is None
    assert len(led.list_fills()) == 1


def test_pipeline_then_new_ledger_sees_settled_pnl(tmp_path: Path) -> None:
    path = tmp_path / "paper.sqlite"
    led = PaperLedger(db_path=path, persist=True)
    result = run_paper_pipeline(
        _signal(), {"outcomes": []}, KalshiDryRunAdapter(), led, 1000.0, fee_rate=0.0
    )
    apply_settlement(led, result.fill["order_id"], 1.25)
    led.close()
    led2 = PaperLedger(db_path=path, persist=True)
    stats = gate_stats_from_ledger(led2)
    assert stats["outcomes"] == [1.25]
    led2.close()
