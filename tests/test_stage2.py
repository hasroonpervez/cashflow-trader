"""Unit tests for risk.stage2 (DSR / PBO annotate-only hook)."""
from __future__ import annotations

import math

import numpy as np

from execution.paper_ledger import PaperLedger
from execution.pipeline import run_paper_pipeline
from risk.stage2 import Stage2Result, evaluate_stage2
from signals.schema import Signal
from venues.kalshi.adapter import KalshiDryRunAdapter


def test_insufficient_n():
    result = evaluate_stage2([0.01] * 10)
    assert isinstance(result, Stage2Result)
    assert result.ok is False
    assert result.dsr is None
    assert result.pbo is None
    assert result.n == 10
    assert any("insufficient" in r for r in result.reasons)

    tiny = evaluate_stage2([0.1, 0.2], min_n=1)
    assert tiny.ok is False
    assert tiny.dsr is None
    assert tiny.pbo is None
    assert "stage2: insufficient sample" in tiny.reasons


def test_positive_returns_n_trials_1():
    returns = [0.01 + 0.001 * ((i % 7) - 3) for i in range(80)]
    result = evaluate_stage2(returns, n_trials=1)
    assert result.n == 80
    assert result.dsr is not None
    assert result.dsr >= 0.95
    assert result.ok is True
    assert result.reasons == ()
    assert result.pbo is None


def test_dsr_fail_mean_zero():
    returns = [0.01, -0.01] * 40
    result = evaluate_stage2(returns, n_trials=1)
    assert result.n == 80
    assert result.ok is False
    assert result.dsr is not None
    assert result.dsr < 0.95
    assert any("dsr=" in r for r in result.reasons)


def test_pipeline_fills_on_stage2_hold():
    outcomes = [0.01, -0.01] * 40
    signal = Signal(
        venue="kalshi",
        market="DEMO-MARKET",
        side="yes",
        p_true=0.65,
        source="Sig_K.unit",
        edge=0.05,
    )
    ledger = PaperLedger()
    result = run_paper_pipeline(
        signal,
        {"outcomes": outcomes, "min_n": 30, "n_trials": 1},
        KalshiDryRunAdapter(),
        ledger,
        1000.0,
        fee_rate=0.0,
    )
    assert result.accepted is True
    assert result.fill is not None
    assert result.stage2 is not None
    assert result.stage2.ok is False
    assert len(ledger.list_fills()) == 1
    assert "stage2: annotate-hold; paper fill still recorded" in result.reasons


def test_pbo_without_matrix_is_none():
    result = evaluate_stage2([0.01 + 0.001 * ((i % 7) - 3) for i in range(80)], n_trials=1)
    assert result.pbo is None
    assert result.ok is True
    assert not any("pbo" in r for r in result.reasons)


def test_pbo_tiny_matrix_no_crash():
    returns = [0.01 + 0.001 * ((i % 7) - 3) for i in range(80)]
    tiny = np.column_stack(
        [
            np.array([0.01, -0.01], dtype=float),
            np.array([0.02, 0.00], dtype=float),
        ]
    )
    result = evaluate_stage2(
        returns,
        n_trials=1,
        returns_matrix=tiny,
        n_splits=10,
    )
    assert isinstance(result, Stage2Result)
    if result.pbo is not None:
        assert math.isfinite(result.pbo)
    else:
        assert "stage2: pbo skipped" in result.reasons


def test_pbo_fail_cscv_matrix():
    """IS-best configs that fail OOS should push CSCV PBO above the bar."""
    t = 40
    overfit = np.array([0.05] * (t // 2) + [-0.05] * (t // 2), dtype=float)
    noise_a = np.array([0.01, -0.01] * (t // 2), dtype=float)
    noise_b = np.array([-0.01, 0.01] * (t // 2), dtype=float)
    noise_c = np.array([0.02, 0.02, -0.02, -0.02] * (t // 4), dtype=float)
    matrix = np.column_stack([overfit, noise_a, noise_b, noise_c])
    result = evaluate_stage2(
        overfit.tolist(),
        min_n=30,
        dsr_min=0.0,
        pbo_max=0.2,
        n_trials=1,
        returns_matrix=matrix,
        n_splits=8,
    )
    assert result.pbo is not None
    assert result.pbo > 0.2
    assert result.ok is False
    assert any("pbo=" in r for r in result.reasons)
