"""Advisory PortfolioRisk stub (P0 — no live flatten)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PortfolioRiskAdvice:
    """Advisory-only risk view. Never blocks paper fills at P0."""

    ok: bool
    haircut: float
    reasons: tuple[str, ...]
    details: Mapping[str, Any]


def advise_portfolio_risk(
    *,
    stake: float,
    bankroll: float,
    open_exposure: float = 0.0,
    max_heat: float = 0.25,
) -> PortfolioRiskAdvice:
    """Return advisory haircut / flags. Does not refuse paper execution."""
    reasons: list[str] = []
    heat = 0.0 if bankroll <= 0 else (open_exposure + max(stake, 0.0)) / bankroll
    haircut = 0.0
    if heat > max_heat:
        haircut = min(1.0, (heat - max_heat) / max_heat)
        reasons.append(f"advisory_heat: {heat:.3f} > max_heat {max_heat}")
    return PortfolioRiskAdvice(
        ok=not reasons,
        haircut=haircut,
        reasons=tuple(reasons),
        details={"heat": heat, "stake": stake, "bankroll": bankroll},
    )
