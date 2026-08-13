"""Strategy promotion gate: min-n, split-half, concentration -> promote/hold.

Pure functions. Reimplemented for cashflow-trader (concepts only from the
Aug 2026 research program / validation-gate pattern).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class GateDecision:
    """Promote vs hold with explicit reasons."""

    decision: str  # "promote" | "hold"
    passed: bool
    reasons: list[str]
    n: int
    expectancy: float
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict = field(default_factory=dict)


def split_half_consistent(returns: Sequence[float], min_half: int = 10) -> dict:
    """Require positive mean return in both chronological halves."""
    r = np.asarray(list(returns), dtype=float)
    if len(r) < 2 * min_half:
        return {
            "consistent": False,
            "reason": f"insufficient sample for split-half (<{2 * min_half})",
            "h1_mean": float("nan"),
            "h2_mean": float("nan"),
        }
    mid = len(r) // 2
    h1, h2 = r[:mid], r[mid:]
    return {
        "consistent": bool(h1.mean() > 0 and h2.mean() > 0),
        "h1_mean": float(h1.mean()),
        "h2_mean": float(h2.mean()),
    }


def concentration_check(
    returns: Sequence[float],
    buckets: Optional[Sequence] = None,
) -> dict:
    """Lottery-ticket detector: does removing top-3 trades flip expectancy?"""
    r = np.asarray(list(returns), dtype=float)
    if len(r) == 0:
        return {"fragile": True, "reason": "empty returns"}
    total = float(r.sum())
    top3 = float(np.sort(r)[-3:].sum()) if len(r) >= 3 else total
    ex_top3 = total - top3
    out = {
        "total": total,
        "top3_trades_share": (top3 / total) if total > 0 else None,
        "expectancy_ex_top3": float(ex_top3 / max(len(r) - 3, 1)),
        "fragile": bool(total > 0 and ex_top3 <= 0),
    }
    if buckets is not None:
        b = list(buckets)
        if len(b) != len(r):
            out["bucket_error"] = "returns/buckets length mismatch"
        else:
            by: dict = {}
            for ret, key in zip(r, b):
                by[key] = by.get(key, 0.0) + float(ret)
            top_bucket = max(by.values()) if by else 0.0
            out["top_bucket_share"] = (top_bucket / total) if total > 0 else None
    return out


def promotion_gate(
    returns: Iterable[float],
    buckets: Optional[Sequence] = None,
    *,
    min_trades: int = 100,
    require_split_half: bool = True,
    require_concentration: bool = True,
) -> GateDecision:
    """Go/no-go before a strategy earns sizing beyond paper.

    Pass requires:
      - n >= min_trades
      - positive expectancy in both chronological halves (when required)
      - profit not fragile to removing top-3 trades (when required)
    """
    r = np.asarray(list(returns), dtype=float)
    n = int(len(r))
    expectancy = float(r.mean()) if n else 0.0
    halves = split_half_consistent(r)
    conc = concentration_check(r, buckets)

    checks = {
        "min_n": n >= min_trades,
        "split_half": (not require_split_half) or bool(halves.get("consistent")),
        "concentration": (not require_concentration) or (not conc.get("fragile", False)),
    }
    reasons: list[str] = []
    if not checks["min_n"]:
        reasons.append(f"n={n} < min_trades={min_trades}")
    if not checks["split_half"]:
        reasons.append(halves.get("reason") or "split-half not both positive")
    if not checks["concentration"]:
        reasons.append("concentration: expectancy fragile after removing top-3 trades")

    passed = all(checks.values())
    if passed:
        reasons.append("all promotion checks passed")
    return GateDecision(
        decision="promote" if passed else "hold",
        passed=passed,
        reasons=reasons,
        n=n,
        expectancy=expectancy,
        checks=checks,
        details={"split_half": halves, "concentration": conc},
    )
