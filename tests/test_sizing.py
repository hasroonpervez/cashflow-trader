"""Unit tests for risk.sizing (thin math_engine Kelly adapter). Paper only."""
from __future__ import annotations

import pytest

from risk.kelly import fractional_kelly
from risk.sizing import (
    adjusted_kelly,
    binary_matches_fractional_kelly,
    fee_per_contract,
    kelly_criterion,
    size_paper,
)
from signals.schema import Signal


def _kalshi_signal(
    *,
    p_true: float = 0.65,
    market_price: float = 0.45,
    side: str = "yes",
) -> Signal:
    return Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side=side,
        p_true=p_true,
        source="Sig_K.unit",
        edge=(p_true - market_price) if side == "yes" else ((1.0 - p_true) - market_price),
        metadata={"market_price": market_price, "paper_only": True},
    )


def _equity_signal(*, p_true: float = 0.60, win_mult: float | None = None) -> Signal:
    meta: dict = {"paper_only": True, "family": "equity_day"}
    if win_mult is not None:
        meta["win_mult"] = win_mult
    return Signal(
        venue="robinhood",
        market="TSLA",
        side="buy",
        p_true=p_true,
        source="Sig_orb30",
        edge=0.05,
        metadata=meta,
    )


def test_kelly_criterion_lifted_positive_edge() -> None:
    assert kelly_criterion(0.65, 0.45) == pytest.approx(0.20 / 0.55)
    assert kelly_criterion(0.40, 0.45) == 0.0
    assert kelly_criterion(0.9, 0.0) == 0.0
    assert kelly_criterion(0.9, 1.0) == 0.0


def test_adjusted_kelly_scales_criterion() -> None:
    raw = kelly_criterion(0.65, 0.45)
    assert adjusted_kelly(0.65, 0.45, 0.25) == pytest.approx(0.25 * raw)


def test_binary_adapter_positive_stake_when_p_true_gt_implied() -> None:
    sizing = size_paper(_kalshi_signal(p_true=0.65, market_price=0.45), 1000.0, fee_rate=0.0)
    assert sizing.mode == "binary"
    assert sizing.fallback is False
    assert sizing.stake > 0
    assert sizing.fraction > 0
    assert sizing.stake_frac == sizing.fraction
    assert sizing.p_true == pytest.approx(0.65)
    assert sizing.p_implied == pytest.approx(0.45)
    assert sizing.fraction == pytest.approx(adjusted_kelly(0.65, 0.45, 0.25))


def test_binary_adapter_zero_when_no_edge() -> None:
    sizing = size_paper(_kalshi_signal(p_true=0.40, market_price=0.45), 1000.0)
    assert sizing.stake == 0.0
    assert sizing.fraction == 0.0
    assert sizing.mode == "binary"


def test_binary_adapter_fee_aware_reduces_stake() -> None:
    no_fee = size_paper(_kalshi_signal(), 1000.0, fee_rate=0.0)
    with_fee = size_paper(_kalshi_signal(), 1000.0, fee_rate=0.07)
    assert with_fee.stake > 0
    assert with_fee.stake < no_fee.stake
    fee_pc = fee_per_contract(0.45, 0.07)
    net_edge = (0.65 - 0.45) - fee_pc
    expected_raw = net_edge / (1.0 - 0.45)
    assert with_fee.kelly_raw == pytest.approx(expected_raw)
    assert with_fee.kelly_adj == pytest.approx(0.25 * expected_raw)


def test_binary_zero_fee_matches_fractional_kelly() -> None:
    p, implied, frac = 0.65, 0.45, 0.25
    sizing = size_paper(
        _kalshi_signal(p_true=p, market_price=implied),
        1000.0,
        fee_rate=0.0,
        kelly_fraction=frac,
    )
    b = (1.0 - implied) / implied
    assert sizing.fraction == pytest.approx(fractional_kelly(p, b, fraction=frac, fee_rate=0.0))
    assert sizing.fraction == pytest.approx(
        binary_matches_fractional_kelly(p, implied, fraction=frac)
    )


def test_size_paper_kalshi_uses_binary_mode() -> None:
    sizing = size_paper(_kalshi_signal(), 500.0, mode="kalshi")
    assert sizing.mode == "binary"
    assert "math_engine" in sizing.reason or "binary" in sizing.reason


def test_size_paper_never_places_orders() -> None:
    """Adapter returns stake only; no venue / order attributes."""
    sizing = size_paper(_kalshi_signal(), 1000.0)
    assert hasattr(sizing, "stake")
    assert not hasattr(sizing, "order_id")
    assert not hasattr(sizing, "place_order")


def test_skewed_path_or_skip() -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("modules.asymmetry")
    from modules.asymmetry import kelly_fraction_skewed

    sig = _equity_signal(p_true=0.15, win_mult=9.0)
    sizing = size_paper(sig, 1000.0, odds_b=9.0, kelly_fraction=0.25)
    expected = kelly_fraction_skewed(0.15, 9.0, 1.0, fraction_of_full=0.25)
    assert expected is not None
    assert sizing.mode == "skewed"
    assert sizing.fallback is False
    assert sizing.method == "skewed_kelly"
    assert sizing.fraction == pytest.approx(expected.recommended_fraction)
    assert sizing.stake == pytest.approx(1000.0 * expected.recommended_fraction)
    assert sizing.stake > 0


def test_skewed_fallback_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    import risk.sizing as sizing_mod

    monkeypatch.setattr(
        sizing_mod,
        "_load_skewed",
        lambda: (
            None,
            "skewed unavailable (ImportError: pandas); falling back to binary Kelly",
        ),
    )
    result = size_paper(_equity_signal(p_true=0.62), 1000.0)
    assert result.fallback is True
    assert result.mode == "binary"
    assert "falling back to binary Kelly" in result.reason
    assert result.stake > 0


def test_pipeline_uses_adapter_and_still_fills() -> None:
    from execution.paper_ledger import PaperLedger
    from execution.pipeline import run_paper_pipeline
    from venues.kalshi.adapter import KalshiDryRunAdapter

    signal = _kalshi_signal(p_true=0.65, market_price=0.45)
    ledger = PaperLedger()
    result = run_paper_pipeline(
        signal,
        {"outcomes": []},
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.07,
    )
    assert result.accepted is True
    assert result.promoted is False
    assert result.fill is not None
    assert result.sizing is not None
    assert result.sizing.mode == "binary"
    assert result.sizing.stake > 0
    assert result.stake > 0
    assert len(ledger.list_fills()) == 1
    assert any("fee-aware Kelly" in r or r.startswith("binary:") for r in result.reasons)
    assert "gate: annotate-hold; paper fill still recorded" in result.reasons
