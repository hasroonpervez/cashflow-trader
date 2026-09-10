"""Pulse movers path: scan → Sig_orb_rvol_vwap → paper ledger."""
from __future__ import annotations

import pytest

from execution.paper_ledger import PaperLedger
from execution.pulse import run_movers_paper
from signals.scanner_fixtures import build_demo_frames, build_in_play_orb
from venues.base import Mode
from venues.robinhood.adapter import RobinhoodReadAdapter


def test_run_movers_paper_records_play_only():
    frames, hints = build_demo_frames()
    ledger = PaperLedger()
    run = run_movers_paper(
        frames,
        ledger,
        10_000.0,
        hints=hints,
        fee_rate=0.0,
        slippage_bps=2.0,
        p_true=0.55,
    )
    assert run.paper_only is True
    symbols = {c.symbol: c.in_play for c in run.candidates}
    assert symbols["PLAY"] is True
    assert symbols["DEAD"] is False
    assert symbols["CHEAP"] is False
    assert len(run.signals) == 1
    assert run.signals[0].source_node == "Sig_orb_rvol_vwap"
    assert len(run.results) == 1
    assert run.results[0].accepted is True
    assert run.results[0].fill is not None
    assert run.results[0].fill["slippage_bps"] == 2.0
    assert len(ledger.list_fills()) == 1
    assert ledger.list_fills()[0].payload["mode"] == "paper"


def test_no_signal_still_lists_candidates():
    frames = {"DEAD": build_in_play_orb(gap_pct=0.1, volume_per_bar=1_000.0)}
    run = run_movers_paper(frames, PaperLedger(), 1000.0)
    assert run.candidates[0].in_play is False
    assert run.signals == ()
    assert run.results == ()


def test_pulse_does_not_construct_live_adapter():
    with pytest.raises(ValueError):
        RobinhoodReadAdapter(mode=Mode.LIVE)
    with pytest.raises(ValueError):
        run_movers_paper(
            {"PLAY": build_in_play_orb()},
            PaperLedger(),
            1000.0,
            adapter=RobinhoodReadAdapter(mode=Mode.LIVE),
        )
