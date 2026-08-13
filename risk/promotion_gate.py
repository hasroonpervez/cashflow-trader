"""Promotion gate - hold signals until sample quality clears."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from modules.validated_signals import bootstrap_ci


@dataclass(frozen=True)
class PromotionGateResult:
    ok: bool
    reasons: tuple[str, ...]
    n: int
    split_half_corr: float | None
    max_label_share: float | None
    ci_low: float | None = None
    ci_high: float | None = None


def _pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    if n != len(b) or n == 0:
        return 0.0
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
    den_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
    if den_a == 0.0 or den_b == 0.0:
        return 0.0
    return num / (den_a * den_b)


def check(
    outcomes: Sequence[float],
    *,
    min_n: int = 30,
    split_half_corr: float = 0.3,
    max_concentration: float = 0.35,
    labels: Sequence[str] | None = None,
    n_boot: int = 4000,
    seed: int = 42,
) -> PromotionGateResult:
    """Evaluate promotion readiness (min_n / split-half corr / concentration / bootstrap CI)."""
    reasons: list[str] = []
    n = len(outcomes)
    corr: float | None = None
    top_share: float | None = None

    if n < min_n:
        reasons.append(f"min_n: {n} < {min_n}")

    if n >= 4:
        mid = n // 2
        left = [float(x) for x in outcomes[:mid]]
        right = [float(x) for x in outcomes[mid : 2 * mid]]
        corr = _pearson(left, right)
        if corr < split_half_corr:
            reasons.append(f"split_half: corr={corr:.3f} < {split_half_corr}")
    else:
        reasons.append("split_half: insufficient sample")

    if labels is not None and n > 0:
        if len(labels) != n:
            reasons.append("concentration: labels length mismatch")
        else:
            counts: dict[str, int] = {}
            for lab in labels:
                counts[str(lab)] = counts.get(str(lab), 0) + 1
            top_share = max(counts.values()) / n
            if top_share > max_concentration:
                reasons.append(
                    f"concentration: top_share={top_share:.3f} > {max_concentration}"
                )

    lo, hi = bootstrap_ci(outcomes, n_boot=n_boot, seed=seed)
    ci_low: float | None = None
    ci_high: float | None = None
    if math.isnan(lo) or math.isnan(hi):
        reasons.append("bootstrap_ci: insufficient sample")
    else:
        ci_low = lo
        ci_high = hi
        if lo <= 0:
            reasons.append(f"bootstrap_ci: lo={lo:.6g} <= 0")

    return PromotionGateResult(
        ok=not reasons,
        reasons=tuple(reasons),
        n=n,
        split_half_corr=corr,
        max_label_share=top_share,
        ci_low=ci_low,
        ci_high=ci_high,
    )


def promotion_gate(
    outcomes: Sequence[float],
    *,
    min_n: int = 30,
    split_half_corr: float = 0.3,
    max_concentration: float = 0.35,
    labels: Sequence[str] | None = None,
    n_boot: int = 4000,
    seed: int = 42,
) -> PromotionGateResult:
    """Alias for :func:`check`."""
    return check(
        outcomes,
        min_n=min_n,
        split_half_corr=split_half_corr,
        max_concentration=max_concentration,
        labels=labels,
        n_boot=n_boot,
        seed=seed,
    )


def gate_from_stats(gate_stats: Mapping[str, object] | None) -> PromotionGateResult:
    """Build a gate result from a pipeline ``gate_stats`` mapping."""
    stats = dict(gate_stats or {})
    outcomes = list(stats.get("outcomes") or [])  # type: ignore[arg-type]
    labels = stats.get("labels")
    kwargs: dict[str, int] = {}
    if "n_boot" in stats:
        kwargs["n_boot"] = int(stats["n_boot"])  # type: ignore[arg-type]
    if "seed" in stats:
        kwargs["seed"] = int(stats["seed"])  # type: ignore[arg-type]
    return check(
        outcomes,
        min_n=int(stats.get("min_n", 30)),  # type: ignore[arg-type]
        split_half_corr=float(stats.get("split_half_corr", 0.3)),  # type: ignore[arg-type]
        max_concentration=float(stats.get("max_concentration", 0.35)),  # type: ignore[arg-type]
        labels=None if labels is None else list(labels),  # type: ignore[arg-type]
        **kwargs,
    )
