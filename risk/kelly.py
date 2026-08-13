"""Kelly helpers — pure functions for paper sizing."""

from __future__ import annotations


def fractional_kelly(
    p: float,
    b: float,
    fraction: float = 0.25,
    fee_rate: float = 0.0,
) -> float:
    """Return stake as a fraction of bankroll in ``[0, 1]``.

    Classic Kelly for binary bets with net odds ``b`` (net profit per unit
    risked if win). ``fee_rate`` haircuts effective odds before sizing.
    """
    if not 0.0 <= float(p) <= 1.0:
        raise ValueError("p must be in [0, 1]")
    if not 0.0 <= float(fraction) <= 1.0:
        raise ValueError("fraction must be in [0, 1]")
    if float(fee_rate) < 0:
        raise ValueError("fee_rate must be >= 0")
    if float(b) <= 0:
        return 0.0

    p = float(p)
    b = float(b)
    fraction = float(fraction)
    fee_rate = float(fee_rate)

    q = 1.0 - p
    b_eff = max(b * (1.0 - fee_rate), 0.0)
    if b_eff <= 0:
        return 0.0
    f_star = (p * b_eff - q) / b_eff
    if f_star <= 0:
        return 0.0
    return float(min(1.0, f_star * fraction))


def fee_aware_kelly(
    p: float,
    b: float,
    *,
    fraction: float = 0.25,
    fee_rate: float = 0.07,
) -> float:
    """Convenience wrapper with a Kalshi-like default fee haircut."""
    return fractional_kelly(p, b, fraction=fraction, fee_rate=fee_rate)
