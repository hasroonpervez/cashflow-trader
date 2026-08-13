"""Thin paper sizing adapter. Wraps existing Kelly helpers; does not reimplement math_engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from risk.kelly import fractional_kelly

_SKEWED_VENUES = frozenset({"robinhood", "coinbase"})


@dataclass(frozen=True)
class PaperSize:
    stake_frac: float
    method: str  # "binary_fractional_kelly" | "skewed_kelly"
    reasons: tuple[str, ...]


def size_paper(
    signal: Any,
    bankroll: float,
    *,
    odds_b: float = 1.0,
    fee_rate: float = 0.0,
    kelly_fraction: float = 0.25,
    win_mult: float | None = None,
    loss_frac: float = 1.0,
) -> PaperSize:
    """Wrap existing Kelly helpers. Does not port kalshi-bot math_engine."""
    del bankroll  # fraction-only; pipeline multiplies by bankroll
    venue = (getattr(signal, "venue", "") or "").strip().lower()
    p = getattr(signal, "p_true", 0.0)

    if venue in _SKEWED_VENUES:
        try:
            from modules.asymmetry import kelly_fraction_skewed
        except ImportError:
            stake_frac = fractional_kelly(
                float(p), odds_b, fraction=kelly_fraction, fee_rate=fee_rate
            )
            return PaperSize(
                stake_frac=stake_frac,
                method="binary_fractional_kelly",
                reasons=("skewed_kelly: unavailable, fallback binary",),
            )
        b = odds_b if win_mult is None else win_mult
        result = kelly_fraction_skewed(
            p, b, loss_frac, fraction_of_full=kelly_fraction
        )
        if result is not None:
            return PaperSize(
                stake_frac=float(result.recommended_fraction),
                method="skewed_kelly",
                reasons=tuple(result.flags or ()),
            )
        stake_frac = fractional_kelly(
            float(p), odds_b, fraction=kelly_fraction, fee_rate=fee_rate
        )
        return PaperSize(
            stake_frac=stake_frac,
            method="binary_fractional_kelly",
            reasons=("skewed_kelly: unavailable, fallback binary",),
        )

    stake_frac = fractional_kelly(
        float(p), odds_b, fraction=kelly_fraction, fee_rate=fee_rate
    )
    return PaperSize(
        stake_frac=stake_frac,
        method="binary_fractional_kelly",
        reasons=(),
    )
