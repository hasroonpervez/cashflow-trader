"""Shared risk helpers (paper path)."""
from __future__ import annotations

from risk.calib import apply_settlement, gate_stats_from_ledger, outcomes_from_ledger
from risk.edge import EdgeModelResult, edge_from_stats, evaluate_edge
from risk.kelly import fee_aware_kelly, fractional_kelly
from risk.portfolio_risk import PortfolioRiskAdvice, advise_portfolio_risk
from risk.promotion_gate import PromotionGateResult, check, gate_from_stats, promotion_gate
from risk.sizing import PaperSize, size_paper
from risk.stage2 import Stage2Result, evaluate_stage2, stage2_from_stats

__all__ = [
    "apply_settlement",
    "outcomes_from_ledger",
    "gate_stats_from_ledger",
    "fee_aware_kelly",
    "fractional_kelly",
    "PaperSize",
    "size_paper",
    "PromotionGateResult",
    "check",
    "promotion_gate",
    "gate_from_stats",
    "PortfolioRiskAdvice",
    "advise_portfolio_risk",
    "Stage2Result",
    "evaluate_stage2",
    "stage2_from_stats",
    "EdgeModelResult",
    "evaluate_edge",
    "edge_from_stats",
]
