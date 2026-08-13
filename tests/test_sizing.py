"""Unit tests for the thin paper sizing adapter."""
from __future__ import annotations

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from risk.kelly import fractional_kelly
from risk.sizing import size_paper
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter
from venues.robinhood.adapter import RobinhoodReadAdapter


def test_kalshi_signal_uses_binary_fractional_kelly() -> None:
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="Sig_K.unit",
        edge=0.05,
    )
    sized = size_paper(
        signal,
        1000.0,
        odds_b=1.0,
        fee_rate=0.0,
        kelly_fraction=0.25,
    )
    assert sized.method == "binary_fractional_kelly"
    assert sized.stake_frac == fractional_kelly(
        signal.p_true, 1.0, fraction=0.25, fee_rate=0.0
    )


def test_pipeline_still_fills() -> None:
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="Sig_K.unit",
        edge=0.05,
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
    assert result.fill is not None
    assert len(ledger.list_fills()) == 1
    assert result.portfolio_risk is not None


def test_robinhood_signal_skewed_or_fallback() -> None:
    signal = Signal(
        venue="robinhood",
        market="AAPL",
        side="buy",
        p_true=0.60,
        source="Sig_orb30",
    )
    try:
        from modules.asymmetry import kelly_fraction_skewed
    except ImportError:
        sized = size_paper(signal, 1000.0, odds_b=1.0, kelly_fraction=0.25)
        assert sized.method == "binary_fractional_kelly"
        assert "skewed_kelly: unavailable, fallback binary" in sized.reasons
        assert sized.stake_frac == fractional_kelly(
            signal.p_true, 1.0, fraction=0.25, fee_rate=0.0
        )
        return

    sized = size_paper(
        signal,
        1000.0,
        odds_b=1.0,
        kelly_fraction=0.25,
        win_mult=1.0,
        loss_frac=1.0,
    )
    assert sized.method == "skewed_kelly"
    expected = kelly_fraction_skewed(
        signal.p_true, 1.0, 1.0, fraction_of_full=0.25
    )
    assert expected is not None
    assert sized.stake_frac == expected.recommended_fraction

    result = run_paper_pipeline(
        signal,
        {"outcomes": []},
        RobinhoodReadAdapter(),
        PaperLedger(),
        1000.0,
    )
    assert result.accepted is True
    assert result.fill is not None
