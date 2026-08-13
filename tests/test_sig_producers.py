"""Unit tests for Sig_* producers → paper Signal / pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from signals.producers import (
    produce_kalshi_event,
    produce_orb30,
    produce_swing_pullback,
)
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter
from venues.robinhood.adapter import RobinhoodReadAdapter


def _fake_session(breakout: bool = True) -> pd.DataFrame:
    idx = pd.date_range("2026-08-04 13:30", periods=78, freq="5min", tz="UTC")
    base = 100.0
    highs, lows, closes, opens = [], [], [], []
    px = base
    for j in range(78):
        if j < 6:
            o, h, l, c = px, px + 1.0, px - 1.0, px + 0.2
        elif breakout and j == 10:
            o, h, l, c = px, px + 2.5, px - 0.1, px + 2.2
        else:
            o, h, l, c = px, px + 0.4, px - 0.4, px + (0.05 if breakout else -0.02)
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        px = c
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.full(78, 10_000.0),
        }
    )


def _engineered_swing_daily() -> pd.DataFrame:
    """Build a daily frame that should trigger swing_pullback_signal."""
    n = 80
    closes = []
    px = 100.0
    for _ in range(n - 6):
        px *= 1.008
        closes.append(px)
    for _ in range(4):
        px *= 0.985
        closes.append(px)
    px *= 1.03
    closes.append(px)
    c = pd.Series(closes, dtype=float)
    lows = c * 0.99
    lows.iloc[-5:] = c.iloc[-5:] * 0.97
    return pd.DataFrame(
        {
            "open": c.shift(1).fillna(c.iloc[0]),
            "high": c * 1.01,
            "low": lows,
            "close": c,
            "volume": np.full(len(c), 1e6),
        }
    )


def test_produce_orb30_emits_valid_signal_aliases():
    sig = produce_orb30(
        _fake_session(breakout=True), symbol="TSLA", p_true=0.60, edge=0.05
    )
    assert isinstance(sig, Signal)
    assert sig.venue == "robinhood"
    assert sig.market == "TSLA"
    assert sig.side == "buy"
    assert sig.source == "Sig_orb30"
    assert sig.instrument == "TSLA"
    assert sig.market_id == "TSLA"
    assert sig.p_model == 0.60
    assert sig.source_node == "Sig_orb30"
    assert sig.edge == 0.05
    assert sig.metadata.get("paper_only") is True
    assert sig.metadata.get("validated_raw", {}).get("status") == "signal"


def test_produce_orb30_none_without_breakout():
    assert produce_orb30(_fake_session(breakout=False), symbol="TSLA") is None


def test_produce_orb30_none_on_gap_skip():
    day = _fake_session(breakout=True)
    out = produce_orb30(
        day, symbol="TSLA", prior_close=float(day.iloc[0]["open"]) / 1.03
    )
    assert out is None


def test_produce_swing_pullback_emits_valid_signal():
    sig = produce_swing_pullback(_engineered_swing_daily(), symbol="AAPL", p_true=0.57)
    assert sig is not None, "expected swing_pullback producer to fire"
    assert sig.venue == "robinhood"
    assert sig.market == "AAPL"
    assert sig.source_node == "Sig_swing_pullback"
    assert sig.p_model == 0.57
    assert 0.0 <= sig.p_true <= 1.0


def test_produce_kalshi_event_aliases_and_edge():
    sig = produce_kalshi_event(
        p_true=0.65,
        market_price=0.45,
        market_id="DEMO-MARKET",
        strategy="unit",
    )
    assert sig.venue == "kalshi"
    assert sig.market_id == "DEMO-MARKET"
    assert sig.instrument == "DEMO-MARKET"
    assert sig.p_model == 0.65
    assert sig.source_node == "Sig_K.unit"
    assert sig.side == "yes"
    assert abs(float(sig.edge) - 0.20) < 1e-9
    assert sig.metadata.get("no_network") is True
    assert sig.metadata.get("paper_only") is True


def test_produce_kalshi_event_source_node_and_no_side():
    sig = produce_kalshi_event(
        p_true=0.40,
        market_price=0.55,
        market_id="MKT-2",
        source_node="Sig_K.custom",
        side="no",
    )
    assert sig.source_node == "Sig_K.custom"
    assert sig.side == "no"
    assert abs(float(sig.edge) - 0.05) < 1e-9


def test_kalshi_producer_through_paper_pipeline_records_fill_outcome():
    """Gate may hold; fill + outcome stub must still record."""
    signal = produce_kalshi_event(
        p_true=0.65,
        market_price=0.45,
        market_id="DEMO-MARKET",
        source_node="Sig_K.unit",
    )
    ledger = PaperLedger()
    result = run_paper_pipeline(
        signal,
        {"outcomes": []},
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.promoted is False
    assert result.fill is not None
    assert len(ledger.list_fills()) == 1
    assert len(ledger.list_outcomes()) == 1
    assert ledger.list_outcomes()[0].payload.get("settled") is False


def test_orb30_producer_through_robinhood_paper_pipeline():
    signal = produce_orb30(_fake_session(breakout=True), symbol="TSLA", p_true=0.62)
    assert signal is not None
    ledger = PaperLedger()
    result = run_paper_pipeline(
        signal,
        {"outcomes": []},
        RobinhoodReadAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.promoted is False
    assert result.fill is not None
    assert len(ledger.list_fills()) == 1
    assert len(ledger.list_outcomes()) == 1
    assert result.fill["mode"] == "paper"
