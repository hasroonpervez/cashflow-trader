"""Pure risk helpers for the multi-venue paper scaffold."""
from .kelly import fee_per_contract, fee_aware_kelly, KellySizing
from .promotion_gate import promotion_gate, GateDecision

__all__ = [
    "fee_per_contract",
    "fee_aware_kelly",
    "KellySizing",
    "promotion_gate",
    "GateDecision",
]
