"""Stage-2 overfitting hook (paper annotate-only).

Placeholder DSR/PBO reasons. Does not copy kalshi-bot CSCV/norm_ppf.
Never blocks paper fills.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Stage2Result:
    ok: bool
    dsr: float | None
    pbo: float | None
    reasons: tuple[str, ...]
    n: int


def _as_1d(values) -> list[float]:
    if values is None:
        return []
    if hasattr(values, "reshape"):
        try:
            return [float(x) for x in values.reshape(-1).tolist()]
        except Exception:
            pass
    return [float(x) for x in list(values)]


def _matrix_n_cols(returns_matrix) -> int:
    if returns_matrix is None:
        return 0
    if hasattr(returns_matrix, "shape"):
        shape = tuple(returns_matrix.shape)
        if len(shape) == 2:
            return int(shape[1])
        return 0
    rows = list(returns_matrix)
    if not rows:
        return 0
    first = rows[0]
    if isinstance(first, (int, float)):
        return 0
    try:
        ncols = len(first)
    except TypeError:
        return 0
    return int(ncols) if ncols >= 2 else 0


def evaluate_stage2(
    returns,
    *,
    min_n: int = 30,
    dsr_min: float = 0.95,
    pbo_max: float = 0.5,
    n_trials: int = 1,
    returns_matrix=None,
    n_splits: int = 10,
) -> Stage2Result:
    """Annotate placeholder DSR / PBO. Does not block paper fills."""
    del n_trials, n_splits  # signature passthrough; placeholders only
    r = _as_1d(returns)
    n = len(r)
    if n < int(min_n) or n < 3:
        return Stage2Result(
            ok=False,
            dsr=None,
            pbo=None,
            reasons=("stage2: insufficient sample",),
            n=n,
        )

    mean = sum(r) / n
    # Placeholder (not Bailey DSR): 1.0 if mean>0 else 0.0
    dsr = 1.0 if mean > 0.0 else 0.0
    reasons: list[str] = []
    if dsr < dsr_min:
        reasons.append(f"stage2: dsr={dsr:.4f} < {dsr_min}")

    pbo: float | None = None
    if _matrix_n_cols(returns_matrix) >= 2:
        pbo = 0.0  # placeholder; omit CSCV
        if pbo > pbo_max:
            reasons.append(f"stage2: pbo={pbo:.4f} > {pbo_max}")

    return Stage2Result(
        ok=not reasons,
        dsr=dsr,
        pbo=pbo,
        reasons=tuple(reasons),
        n=n,
    )


def stage2_from_stats(gate_stats: Mapping[str, Any] | None) -> Stage2Result:
    """Build a stage-2 result from a pipeline ``gate_stats`` mapping."""
    stats = dict(gate_stats or {})
    series = stats.get("returns")
    if series is None:
        series = stats.get("outcomes") or []
    kwargs: dict[str, Any] = {}
    if "min_n" in stats:
        kwargs["min_n"] = int(stats["min_n"])
    if "dsr_min" in stats:
        kwargs["dsr_min"] = float(stats["dsr_min"])
    if "pbo_max" in stats:
        kwargs["pbo_max"] = float(stats["pbo_max"])
    if "n_trials" in stats:
        kwargs["n_trials"] = int(stats["n_trials"])
    if "n_splits" in stats:
        kwargs["n_splits"] = int(stats["n_splits"])
    if "returns_matrix" in stats:
        kwargs["returns_matrix"] = stats["returns_matrix"]
    return evaluate_stage2(series, **kwargs)
