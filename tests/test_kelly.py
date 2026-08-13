"""Unit tests for risk.kelly fee-aware / fractional Kelly."""
from __future__ import annotations

import pytest

from risk.kelly import fee_aware_kelly, fee_per_contract, kalshi_fee_dollars


def test_fee_per_contract_peaks_near_half():
    mid = fee_per_contract(0.5, rate=0.07)
    wing = fee_per_contract(0.1, rate=0.07)
    assert mid == pytest.approx(0.07 * 0.5 * 0.5)
    assert mid > wing
    assert fee_per_contract(0.0) == 0.0
    assert fee_per_contract(1.0) == 0.0


def test_kalshi_fee_rounds_up_to_cent():
    # 0.07 * 10 * 0.5 * 0.5 = 0.175 -> ceil to 0.18
    assert kalshi_fee_dollars(0.5, 10, rate=0.07) == pytest.approx(0.18)


def test_positive_edge_produces_fractional_kelly():
    sizing = fee_aware_kelly(0.70, 0.40, fraction_of_full=0.25, max_fraction=0.25)
    assert sizing.should_trade
    assert sizing.net_edge > 0
    assert 0 < sizing.recommended_fraction <= sizing.full_kelly
    assert sizing.recommended_fraction == pytest.approx(sizing.full_kelly * 0.25)


def test_fees_can_kill_thin_edge():
    # Gross edge 2c, fee at 0.50 is 1.75c -> still positive; use thinner edge.
    thin = fee_aware_kelly(0.52, 0.50, fee_rate=0.07, min_net_edge=0.0)
    # fee_pc = 0.07*0.5*0.5 = 0.0175; net = 0.02 - 0.0175 = 0.0025 > 0
    assert thin.should_trade
    dead = fee_aware_kelly(0.51, 0.50, fee_rate=0.07)
    # net = 0.01 - 0.0175 < 0
    assert not dead.should_trade
    assert "no-edge-net-of-fees" in dead.flags


def test_max_fraction_cap():
    sizing = fee_aware_kelly(0.95, 0.20, fraction_of_full=1.0, max_fraction=0.05)
    assert sizing.recommended_fraction == pytest.approx(0.05)
    assert "capped-at-max-fraction" in sizing.flags


def test_invalid_p_true_raises():
    with pytest.raises(ValueError):
        fee_aware_kelly(1.5, 0.4)
