"""Stage-2 overfitting stats lifted from kalshi-bot/backtest.py (Bailey / Lopez de Prado).

Paper annotate-only: DSR and PBO never block paper fills. Pure numpy (no scipy).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping

import numpy as np

_GAMMA = 0.5772156649015329  # Euler-Mascheroni
_E = math.e

#  -- Normal CDF / inverse CDF (pure python) ---------------


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation, ~1e-9)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


#  -- Basic performance metrics ----------------------------

_VAR_EPS = 1e-12  # treat std below this as "no variance" (avoids fp-dust blowups)


def sharpe(returns, periods_per_year: int = 252, rf: float = 0.0) -> float:
    r = np.asarray(returns, dtype=float) - rf / periods_per_year
    if r.size < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd <= _VAR_EPS:
        return 0.0
    return float(r.mean() / sd * math.sqrt(periods_per_year))


#  -- Sharpe-ratio significance under multiple testing -----

def _sr_moments(returns):
    r = np.asarray(returns, dtype=float)
    T = r.size
    sd = r.std(ddof=1)
    sr = r.mean() / sd if sd > _VAR_EPS else 0.0   # per-period (non-annualized)
    m = r - r.mean()
    s2 = np.mean(m ** 2)
    skew = float(np.mean(m ** 3) / s2 ** 1.5) if s2 > 0 else 0.0
    kurt = float(np.mean(m ** 4) / s2 ** 2) if s2 > 0 else 3.0   # normal = 3
    return sr, skew, kurt, T


def probabilistic_sharpe_ratio(returns, sr_benchmark: float = 0.0) -> float:
    """
    PSR = P(true per-period SR > sr_benchmark), correcting for skew, kurtosis
    and sample length (Bailey & Lopez de Prado).
    """
    sr, skew, kurt, T = _sr_moments(returns)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2))
    z = (sr - sr_benchmark) * math.sqrt(max(T - 1, 1)) / denom
    return _norm_cdf(z)


def expected_max_sharpe(n_trials: int, var_sr: float) -> float:
    """
    False Strategy Theorem: expected MAX per-period Sharpe among `n_trials`
    unskilled strategies whose SR estimates have cross-sectional variance var_sr.
    This is the bar a real strategy must clear.
    """
    N = max(int(n_trials), 1)
    sd = math.sqrt(max(var_sr, 0.0))
    if N == 1:
        return 0.0
    a = (1.0 - _GAMMA) * _norm_ppf(1.0 - 1.0 / N)
    b = _GAMMA * _norm_ppf(1.0 - 1.0 / (N * _E))
    return sd * (a + b)


def deflated_sharpe_ratio(returns, n_trials: int, sr_trials_var: float | None = None) -> float:
    """
    DSR = PSR evaluated against the expected-max-Sharpe benchmark for n_trials.
    DSR > 0.95 => the Sharpe is significant *after* accounting for how many
    strategies you tried. If you don't pass the cross-sectional variance of your
    trials' Sharpes, we use the SR estimator's asymptotic variance as a proxy.
    """
    sr, skew, kurt, T = _sr_moments(returns)
    if sr_trials_var is None:
        sr_trials_var = (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2) / max(T - 1, 1)
    sr_star = expected_max_sharpe(n_trials, sr_trials_var)
    return probabilistic_sharpe_ratio(returns, sr_benchmark=sr_star)


#  -- Probability of Backtest Overfitting (CSCV) -----------

def pbo_cscv(returns_matrix, n_splits: int = 10, periods_per_year: int = 252) -> dict:
    """
    Probability of Backtest Overfitting via Combinatorially Symmetric
    Cross-Validation (Bailey, Borwein, Lopez de Prado, Zhu).

    returns_matrix: T x N array -- N candidate strategy/parameter configs, T periods.
    Partition time into S=n_splits blocks; over every way to choose S/2 blocks as
    in-sample, pick the best config IS and measure its OOS rank. PBO is the
    fraction of splits where the IS-best config lands below the OOS median --
    i.e. selection didn't generalize. PBO near 0 = robust; near 0.5 = pure
    overfitting.
    """
    M = np.asarray(returns_matrix, dtype=float)
    T, N = M.shape
    S = n_splits if n_splits % 2 == 0 else n_splits + 1
    S = min(S, T)
    if S < 2 or N < 2:
        return {"pbo": float("nan"), "n_combos": 0, "note": "need >=2 configs and >=2 splits"}

    bounds = np.linspace(0, T, S + 1).astype(int)
    blocks = [np.arange(bounds[i], bounds[i + 1]) for i in range(S)]
    half = S // 2
    logits = []
    for is_idx in combinations(range(S), half):
        is_rows = np.concatenate([blocks[i] for i in is_idx])
        oos_rows = np.concatenate([blocks[i] for i in range(S) if i not in is_idx])
        if is_rows.size < 2 or oos_rows.size < 2:
            continue
        is_sr = np.array([sharpe(M[is_rows, j], periods_per_year) for j in range(N)])
        oos_sr = np.array([sharpe(M[oos_rows, j], periods_per_year) for j in range(N)])
        best = int(np.argmax(is_sr))
        # relative OOS rank of the IS-best config, in (0,1)
        rank = (np.sum(oos_sr <= oos_sr[best])) / (N + 1.0)
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1.0 - rank)))
    if not logits:
        return {"pbo": float("nan"), "n_combos": 0}
    logits = np.array(logits)
    pbo = float(np.mean(logits <= 0.0))
    return {
        "pbo": pbo,
        "n_combos": int(logits.size),
        "median_logit": float(np.median(logits)),
        "interpretation": ("robust" if pbo < 0.2 else "suspect" if pbo < 0.5 else "overfit"),
    }


@dataclass(frozen=True)
class Stage2Result:
    ok: bool
    dsr: float | None
    pbo: float | None
    reasons: tuple[str, ...]
    n: int


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
    """Annotate DSR / PBO on a return series. Does not block paper fills."""
    r = np.asarray(returns, dtype=float).reshape(-1)
    n = int(r.size)
    if n < int(min_n) or n < 3:
        return Stage2Result(
            ok=False,
            dsr=None,
            pbo=None,
            reasons=("stage2: insufficient sample",),
            n=n,
        )

    dsr = float(deflated_sharpe_ratio(r, int(n_trials)))
    reasons: list[str] = []
    if dsr < dsr_min:
        reasons.append(f"stage2: dsr={dsr:.4f} < {dsr_min}")

    pbo: float | None = None
    if returns_matrix is not None:
        M = np.asarray(returns_matrix, dtype=float)
        if M.ndim == 2 and M.shape[1] >= 2:
            pbo_val = pbo_cscv(M, n_splits=int(n_splits)).get("pbo")
            pbo_f = float(pbo_val) if pbo_val is not None else float("nan")
            if math.isnan(pbo_f):
                reasons.append("stage2: pbo skipped")
                pbo = None
            else:
                pbo = pbo_f
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
