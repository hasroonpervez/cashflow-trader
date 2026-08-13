"""Shared risk helpers (paper path)."""

from __future__ import annotations

from risk.kelly import fee_aware_kelly, fractional_kelly
from risk.promotion_gate import PromotionGateResult, check, promotion_gate

__all__ = [
    "fee_aware_kelly",
    "fractional_kelly",
    "PromotionGateResult",
    "check",
    "promotion_gate",
]
