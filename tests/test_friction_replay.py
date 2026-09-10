"""Fee/slippage fields and replay hooks (injected bars)."""
from __future__ import annotations

import pytest

from execution.friction import apply_friction
from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from execution.replay import mark_to_close_pnl, replay_fill_to_last_close, replay_ledger
from signals.producers import produce_orb_rvol_vwap
from signals.scanner_fixtures import build_in_play_orb
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter
from venues.robinhood.adapter import RobinhoodReadAdapter


def test_apply_friction_haircuts_notional():
    net = apply_friction(10.0, notional=1000.0, fee_rate=0.001, slippage_bps=10)
    # 1000 * 0.001 + 1000 * 0.001 = 2
    assert net == pytest.approx(8.0)


def test_mark_to_close_buy_and_friction():
    gross, net = mark_to_close_pnl(
        side="buy",
        size=1000.0,
        entry_price=100.0,
        exit_price=110.0,
        fee_rate=0.0,
        slippage_bps=0.0,
    )
    assert gross == pytest.approx(100.0)
    assert net == pytest.approx(100.0)
    _g, net_f = mark_to_close_pnl(
        side="buy",
        size=1000.0,
        entry_price=100.0,
        exit_price=110.0,
        fee_rate=0.01,
        slippage_bps=0.0,
    )
    assert net_f == pytest.approx(90.0)


def test_replay_uses_first_close_when_fill_price_zero():
    bars = build_in_play_orb()
    mark = replay_fill_to_last_close(
        {"market": "PLAY", "side": "buy", "size": 1000.0, "price": 0.0},
        bars,
        fee_rate=0.0,
        slippage_bps=0.0,
    )
    assert mark.entry_price > 0
    assert mark.exit_price > 0
    assert mark.paper_only is True


def test_replay_ledger_skips_missing_symbol():
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="unit",
    )
    ledger = PaperLedger()
    run_paper_pipeline(
        signal, {"outcomes": []}, KalshiDryRunAdapter(), ledger, 1000.0
    )
    marks = replay_ledger(ledger, {})
    assert marks == []


def test_replay_after_pulse_fill():
    bars = build_in_play_orb()
    sig = produce_orb_rvol_vwap(bars, symbol="PLAY")
    assert sig is not None
    ledger = PaperLedger()
    run_paper_pipeline(
        sig,
        {"outcomes": []},
        RobinhoodReadAdapter(),
        ledger,
        5000.0,
        fee_rate=0.001,
        slippage_bps=5.0,
    )
    marks = replay_ledger(ledger, {"PLAY": bars})
    assert len(marks) == 1
    assert marks[0].fee_rate == 0.001
    assert marks[0].slippage_bps == 5.0
