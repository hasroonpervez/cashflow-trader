"""Unit tests for risk.promotion_gate."""
from __future__ import annotations

from risk.promotion_gate import PromotionGateResult, check, promotion_gate


def _good_outcomes(n: int = 40) -> list[float]:
    half = [1.0, 0.0, 1.0, 1.0, 0.0] * (n // 10)
    return half + half


def test_check_fails_min_n() -> None:
    result = check([1.0, 0.0, 1.0], min_n=30)
    assert isinstance(result, PromotionGateResult)
    assert result.ok is False
    assert any(r.startswith("min_n:") for r in result.reasons)


def test_check_fails_split_half() -> None:
    left = [1.0] * 20
    right = [0.0] * 20
    result = check(left + right, min_n=30, split_half_corr=0.5)
    assert result.ok is False
    assert any(r.startswith("split_half:") for r in result.reasons)


def test_check_fails_concentration() -> None:
    outcomes = _good_outcomes(40)
    labels = ["A"] * 30 + ["B"] * 10
    result = check(
        outcomes,
        min_n=30,
        split_half_corr=0.0,
        max_concentration=0.35,
        labels=labels,
    )
    assert result.ok is False
    assert any(r.startswith("concentration:") for r in result.reasons)


def test_check_passes_healthy_sample() -> None:
    outcomes = _good_outcomes(40)
    labels = ["A", "B", "C", "D"] * 10
    result = check(
        outcomes,
        min_n=30,
        split_half_corr=0.3,
        max_concentration=0.35,
        labels=labels,
    )
    assert result.ok is True
    assert result.reasons == ()
    assert result.n == 40
    assert result.split_half_corr is not None
    assert result.split_half_corr >= 0.3


def test_promotion_gate_alias() -> None:
    assert promotion_gate([1.0], min_n=5).ok is False
