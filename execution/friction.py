"""Fee + slippage fields for paper fills / replay. Never live."""
from __future__ import annotations

from typing import Any, Mapping


def apply_friction(
    gross_pnl: float,
    *,
    notional: float,
    fee_rate: float = 0.0,
    slippage_bps: float = 0.0,
) -> float:
    """Haircut gross PnL by fee_rate * |notional| + slippage_bps on notional."""
    if float(fee_rate) < 0 or float(slippage_bps) < 0:
        raise ValueError("fee_rate and slippage_bps must be >= 0")
    cost = abs(float(notional)) * (float(fee_rate) + float(slippage_bps) / 10_000.0)
    return float(gross_pnl) - cost


def friction_fields(
    *,
    fee_rate: float = 0.0,
    slippage_bps: float = 0.0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out = {
        "fee_rate": float(fee_rate),
        "slippage_bps": float(slippage_bps),
        "paper_only": True,
    }
    if extra:
        out.update(dict(extra))
    return out
