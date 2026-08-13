"""Betting/edge annotate from settlement→calib outcomes. Paper only.

Does not rewrite math_engine. Does not change stake. Never live.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class EdgeModelResult:
    ok: bool
    realized_edge: float | None
    n: int
    hit_rate: float | None
    model_edge: float | None
    reasons: tuple[str, ...]
    unvalidated: bool = True


def _pnls(stats: Mapping[str, Any] | None) -> list[float]:
    if not stats:
        return []
    raw = stats.get("outcomes")
    if not raw:
        return []
    out: list[float] = []
    for x in raw:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            continue
    return out


def evaluate_edge(
    outcomes: list[float] | None,
    *,
    min_n: int = 30,
    model_edge: float | None = None,
) -> EdgeModelResult:
    """Mean settled PnL + hit rate. Fail closed when n < min_n. Annotate only."""
    pnls = [float(x) for x in (outcomes or [])]
    n = len(pnls)
    reasons: list[str] = []
    me = None if model_edge is None else float(model_edge)
    if n < int(min_n):
        reasons.append(f"edge: insufficient sample ({n} < {min_n})")
        return EdgeModelResult(
            ok=False,
            realized_edge=None,
            n=n,
            hit_rate=None,
            model_edge=me,
            reasons=tuple(reasons),
        )
    realized = sum(pnls) / n
    hits = sum(1 for x in pnls if x > 0) / n
    if realized <= 0:
        reasons.append("edge: realized mean PnL <= 0")
        ok = False
    else:
        ok = True
    if me is not None and abs(me) > 1e-12 and realized < 0.5 * me:
        reasons.append("edge: realized << model edge (unvalidated)")
        ok = False
    reasons.append("edge: annotate-only; not for live sizing")
    return EdgeModelResult(
        ok=ok,
        realized_edge=realized,
        n=n,
        hit_rate=hits,
        model_edge=me,
        reasons=tuple(reasons),
    )


def edge_from_stats(
    gate_stats: Mapping[str, Any] | None,
    *,
    model_edge: float | None = None,
) -> EdgeModelResult:
    stats = dict(gate_stats or {})
    min_n = int(stats.get("min_n") or 30)
    return evaluate_edge(
        _pnls(stats),
        min_n=min_n,
        model_edge=model_edge,
    )
