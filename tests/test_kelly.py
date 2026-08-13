"""Unit tests for risk.kelly."""
from __future__ import annotations

import pytest

from risk.kelly import fee_aware_kelly, fractional_kelly


def test_fractional_kelly_fair_coin_is_zero() -> None:
    assert fractional_kelly(0.5, 1.0) == 0.0


def test_fractional_kelly_positive_edge() -> None:
    assert fractional_kelly(0.6, 1.0, fraction=0.25) == pytest.approx(0.05)


def test_fractional_kelly_clamps_to_unit_interval() -> None:
    assert 0.0 <= fractional_kelly(0.99, 10.0, fraction=1.0) <= 1.0


def test_fractional_kelly_fee_reduces_stake() -> None:
    no_fee = fractional_kelly(0.6, 1.0, fraction=0.25, fee_rate=0.0)
    with_fee = fractional_kelly(0.6, 1.0, fraction=0.25, fee_rate=0.07)
    assert with_fee < no_fee


def test_fractional_kelly_rejects_bad_p() -> None:
    with pytest.raises(ValueError):
        fractional_kelly(1.5, 1.0)


def test_fractional_kelly_nonpositive_b() -> None:
    assert fractional_kelly(0.9, 0.0) == 0.0
    assert fractional_kelly(0.9, -1.0) == 0.0


def test_fee_aware_kelly_defaults() -> None:
    assert fee_aware_kelly(0.6, 1.0) == fractional_kelly(
        0.6, 1.0, fraction=0.25, fee_rate=0.07
    )
