"""CPCV / deflated-Sharpe annotate stub (paper only).

Does not implement combinatorial purged CV or Bailey DSR. Does not rewrite
math_engine. Never blocks paper fills — Graph-friendly for small n.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CpcvGateResult:
    ok: bool
    cpcv: float | None
    deflated_sharpe: float | None
    n: int
    reasons: tuple[str, ...]
    unvalidated: bool = True


def _as_1d(values) -> list[float]:
    if values is None:
        return []
    if hasattr(values, "reshape"):
        try:
            return [float(x) for x in values.reshape(-1).tolist()]
        except Exception:
            pass
    out: list[float] = []
    for x in list(values):
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            continue
    return out


def evaluate_cpcv(
    returns,
    *,
    min_n: int = 30,
) -> CpcvGateResult:
    """Stub CPCV + deflated Sharpe. Annotate only; fail closed on small n."""
    r = _as_1d(returns)
    n = len(r)
    reasons = ["cpcv: stub annotate-only; not Bailey DSR / not math_engine"]
    if n < int(min_n):
        reasons.append(f"cpcv: insufficient sample ({n} < {min_n})")
        return CpcvGateResult(
            ok=False,
            cpcv=None,
            deflated_sharpe=None,
            n=n,
            reasons=tuple(reasons),
        )
    reasons.append("cpcv: metrics not computed (placeholder hold)")
    return CpcvGateResult(
        ok=False,
        cpcv=None,
        deflated_sharpe=None,
        n=n,
        reasons=tuple(reasons),
    )


def cpcv_from_stats(gate_stats: Mapping[str, Any] | None) -> CpcvGateResult:
    stats = dict(gate_stats or {})
    series = stats.get("returns")
    if series is None:
        series = stats.get("outcomes") or []
    min_n = int(stats.get("min_n") or 30)
    return evaluate_cpcv(series, min_n=min_n)
