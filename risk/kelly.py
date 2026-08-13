"""Fee-aware / fractional Kelly for binary contracts (pure, no I/O).

Reimplemented cleanly for cashflow-trader. Concepts (fee schedule shape,
net-edge Kelly) inspired by public Kalshi fee math; no external bot code
is copied.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

DEFAULT_FEE_RATE = 0.07
DEFAULT_FRACTION = 0.25
DEFAULT_MAX_FRACTION = 0.05


def fee_per_contract(price: float, rate: float = DEFAULT_FEE_RATE) -> float:
    """Marginal fee per contract ~= rate * P * (1-P) for P in (0, 1)."""
    if price <= 0.0 or price >= 1.0:
        return 0.0
    return float(rate) * float(price) * (1.0 - float(price))


def kalshi_fee_dollars(
    price: float,
    contracts: int,
    rate: float = DEFAULT_FEE_RATE,
) -> float:
    """Total fee in dollars, rounded UP to the next cent."""
    if contracts <= 0 or price <= 0.0 or price >= 1.0:
        return 0.0
    raw_cents = rate * contracts * price * (1.0 - price) * 100.0
    return math.ceil(raw_cents - 1e-9) / 100.0


@dataclass(frozen=True)
class KellySizing:
    """Result of fee-aware fractional Kelly."""

    full_kelly: float
    recommended_fraction: float
    fraction_of_full: float
    net_edge: float
    fee_per_contract: float
    should_trade: bool
    flags: list[str] = field(default_factory=list)


def fee_aware_kelly(
    p_true: float,
    price: float,
    *,
    fee_rate: float = DEFAULT_FEE_RATE,
    fraction_of_full: float = DEFAULT_FRACTION,
    max_fraction: float = DEFAULT_MAX_FRACTION,
    min_net_edge: float = 0.0,
) -> KellySizing:
    """Binary-contract Kelly on edge net of fees.

    For a YES contract priced at ``price`` with true probability ``p_true``:

        fee_pc = rate * price * (1 - price)
        net_edge = p_true - price - fee_pc
        f* = net_edge / (1 - price)     # when price < 1
        f_rec = min(max_fraction, fraction_of_full * f*)

    Returns zero size when net edge is non-positive or below ``min_net_edge``.
    """
    flags: list[str] = []
    p = float(p_true)
    px = float(price)
    if not (0.0 <= p <= 1.0):
        raise ValueError(f"p_true must be in [0, 1], got {p}")
    if not (0.0 < px < 1.0):
        flags.append("invalid-price")
        return KellySizing(
            full_kelly=0.0,
            recommended_fraction=0.0,
            fraction_of_full=float(fraction_of_full),
            net_edge=0.0,
            fee_per_contract=0.0,
            should_trade=False,
            flags=flags + ["do-not-bet"],
        )
    if not (0.0 < fraction_of_full <= 1.0):
        raise ValueError(f"fraction_of_full must be in (0, 1], got {fraction_of_full}")
    if max_fraction < 0.0:
        raise ValueError(f"max_fraction must be >= 0, got {max_fraction}")

    fee_pc = fee_per_contract(px, fee_rate)
    net_edge = p - px - fee_pc
    if net_edge <= 0.0:
        return KellySizing(
            full_kelly=0.0,
            recommended_fraction=0.0,
            fraction_of_full=float(fraction_of_full),
            net_edge=float(net_edge),
            fee_per_contract=float(fee_pc),
            should_trade=False,
            flags=["no-edge-net-of-fees", "do-not-bet"],
        )
    if net_edge < min_net_edge:
        return KellySizing(
            full_kelly=0.0,
            recommended_fraction=0.0,
            fraction_of_full=float(fraction_of_full),
            net_edge=float(net_edge),
            fee_per_contract=float(fee_pc),
            should_trade=False,
            flags=["below-min-net-edge", "do-not-bet"],
        )

    full = net_edge / (1.0 - px)
    rec = full * float(fraction_of_full)
    if rec > max_fraction:
        rec = float(max_fraction)
        flags.append("capped-at-max-fraction")

    return KellySizing(
        full_kelly=float(full),
        recommended_fraction=float(rec),
        fraction_of_full=float(fraction_of_full),
        net_edge=float(net_edge),
        fee_per_contract=float(fee_pc),
        should_trade=rec > 0.0,
        flags=flags,
    )
