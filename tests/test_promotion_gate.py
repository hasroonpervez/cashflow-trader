"""Unit tests for risk.promotion_gate."""
from __future__ import annotations

from risk.promotion_gate import PromotionGateResult, check, gate_from_stats, promotion_gate


def _good_outcomes(n: int = 40) -> list[float]:
    half = [1.0, 0.0, 1.0, 1.0, 0.0] * (n // 10)
    return half + half


def _positive_iid(n: int = 40) -> list[float]:
    """Clearly positive iid-like sample (0.01 + tiny alternating noise)."""
    return [0.01 + (0.001 if i % 2 == 0 else -0.001) for i in range(n)]


def test_check_fails_min_n() -> None:
    result = check([1.0, 0.0, 1.0], min_n=30)
    assert isinstance(result, PromotionGateResult)
    assert result.ok is False
    assert any(r.startswith("min_n:") for r in result.reasons)


def test_check_fails_split_half() -> None:
    left = [1.0] * 20
    right = [0.0] * 20
    result = check(left + right, min_n=30, split_half_corr=0.5)
    assert result.ok is False
    assert any(r.startswith("split_half:") for r in result.reasons)


def test_check_fails_concentration() -> None:
    outcomes = _good_outcomes(40)
    labels = ["A"] * 30 + ["B"] * 10
    result = check(
        outcomes,
        min_n=30,
        split_half_corr=0.0,
        max_concentration=0.35,
        labels=labels,
    )
    assert result.ok is False
    assert any(r.startswith("concentration:") for r in result.reasons)


def test_check_passes_healthy_sample() -> None:
    outcomes = _good_outcomes(40)
    labels = ["A", "B", "C", "D"] * 10
    result = check(
        outcomes,
        min_n=30,
        split_half_corr=0.3,
        max_concentration=0.35,
        labels=labels,
    )
    assert result.ok is True
    assert result.reasons == ()
    assert result.n == 40
    assert result.split_half_corr is not None
    assert result.split_half_corr >= 0.3
    assert result.ci_low is not None
    assert result.ci_high is not None
    assert result.ci_low > 0


def test_check_passes_positive_iid_bootstrap() -> None:
    outcomes = _positive_iid(40)
    result = check(outcomes, min_n=30, split_half_corr=0.0)
    assert result.ok is True
    assert result.reasons == ()
    assert result.ci_low is not None and result.ci_low > 0
    assert result.ci_high is not None


def test_check_fails_bootstrap_ci_mean_zero() -> None:
    outcomes = [1.0, -1.0] * 20
    result = check(outcomes, min_n=30, split_half_corr=0.0)
    assert result.ok is False
    assert any(r.startswith("bootstrap_ci: lo=") and r.endswith("<= 0") for r in result.reasons)
    assert result.ci_low is not None
    assert result.ci_low <= 0
    assert not any(r.startswith("min_n:") for r in result.reasons)
    assert not any(r.startswith("split_half:") for r in result.reasons)


def test_check_fails_bootstrap_ci_insufficient_sample() -> None:
    result = check([0.4, 0.5, 0.6, 0.7], min_n=1, split_half_corr=-1.0)
    assert result.ok is False
    assert "bootstrap_ci: insufficient sample" in result.reasons
    assert result.ci_low is None
    assert result.ci_high is None


def test_gate_from_stats_threads_n_boot_seed() -> None:
    outcomes = _positive_iid(40)
    result = gate_from_stats(
        {
            "outcomes": outcomes,
            "min_n": 30,
            "split_half_corr": 0.0,
            "n_boot": 200,
            "seed": 7,
        }
    )
    assert result.ok is True
    assert result.ci_low is not None and result.ci_low > 0


def test_promotion_gate_alias() -> None:
    assert promotion_gate([1.0], min_n=5).ok is False
