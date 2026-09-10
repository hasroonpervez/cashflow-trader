"""Movers scanner: synthetic OHLCV only — no network."""
from __future__ import annotations

import pandas as pd
import pytest

from signals.scanner import (
    ScannerConfig,
    frames_from_payload,
    relative_volume,
    scan_universe,
    score_symbol,
)
from signals.scanner_fixtures import build_in_play_orb, session_5m


def test_in_play_gapper_passes_floors():
    bars = build_in_play_orb()
    cand = score_symbol("PLAY", bars)
    assert cand.in_play is True
    assert cand.gap_pct is not None and cand.gap_pct >= 3.0
    assert cand.rvol is not None and cand.rvol >= 2.0
    assert cand.price is not None and cand.price >= 5.0
    assert cand.dollar_volume is not None and cand.dollar_volume >= 2_000_000
    assert cand.paper_only is True
    assert cand.score > 0


def test_rejects_flat_low_rvol():
    bars = build_in_play_orb(gap_pct=0.2, breakout=False, volume_per_bar=8_000.0)
    cand = score_symbol("DEAD", bars)
    assert cand.in_play is False
    assert any("gap" in r or "rvol" in r for r in cand.reasons)


def test_rejects_price_floor():
    bars = build_in_play_orb(prior_close=1.2, gap_pct=8.0, breakout=False)
    cand = score_symbol("CHEAP", bars)
    assert cand.in_play is False
    assert any("price floor" in r for r in cand.reasons)


def test_hints_without_prior_sessions():
    today = session_5m(
        "2026-09-01",
        open0=110.0,
        or_high=111.0,
        or_low=109.0,
        breakout=True,
        volume_per_bar=50_000.0,
    )
    missing = score_symbol("HINT", today)
    assert missing.in_play is False
    hinted = score_symbol(
        "HINT", today, prior_close=100.0, avg_volume=500_000.0
    )
    assert hinted.in_play is True
    assert hinted.gap_pct == pytest.approx(10.0, abs=0.05)


def test_rvol_time_adjusts():
    raw = relative_volume(100_000, 1_000_000, elapsed_minutes=39.0)
    assert raw == pytest.approx(1.0)
    full = relative_volume(2_000_000, 1_000_000, elapsed_minutes=390.0)
    assert full == pytest.approx(2.0)


def test_scan_universe_ranks_in_play_first():
    frames = {
        "DEAD": build_in_play_orb(gap_pct=0.1, volume_per_bar=5_000.0),
        "PLAY": build_in_play_orb(),
    }
    ranked = scan_universe(frames)
    assert ranked[0].symbol == "PLAY"
    assert ranked[0].in_play is True
    assert ranked[-1].in_play is False


def test_frames_from_payload_object_and_hints():
    payload = {
        "abc": {
            "prior_close": 20.0,
            "avg_volume": 1e6,
            "bars": [
                {
                    "ts": "2026-09-01T09:30:00-04:00",
                    "open": 22.0,
                    "high": 22.5,
                    "low": 21.8,
                    "close": 22.2,
                    "volume": 200_000,
                }
            ],
        }
    }
    frames, hints = frames_from_payload(payload)
    assert "ABC" in frames
    assert hints["ABC"]["prior_close"] == 20.0
    cand = score_symbol("ABC", frames["ABC"], **hints["ABC"])
    assert cand.gap_pct == pytest.approx(10.0)


def test_empty_bars_not_in_play():
    cand = score_symbol("NONE", pd.DataFrame())
    assert cand.in_play is False
    assert cand.score == 0.0


def test_custom_floors():
    bars = build_in_play_orb(gap_pct=4.0)
    tight = ScannerConfig(min_gap_pct=10.0)
    assert score_symbol("PLAY", bars, config=tight).in_play is False
