"""TA.get_correlation_matrix — inner join, Pearson, shape."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.ta import TA


def test_correlation_matrix_empty_dict():
    assert TA.get_correlation_matrix({}).empty


def test_correlation_matrix_single_ticker():
    idx = pd.date_range("2024-01-01", periods=20, freq="D")
    s = pd.Series(np.linspace(100, 105, 20), index=idx)
    out = TA.get_correlation_matrix({"AAA": s})
    assert out.empty


def test_correlation_matrix_two_tickers_aligned():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    rng = np.random.default_rng(0)
    a = pd.Series(100 + np.cumsum(rng.normal(0, 1, 100)), index=idx)
    b = pd.Series(50 + np.cumsum(rng.normal(0, 1, 100)), index=idx)
    mat = TA.get_correlation_matrix({"AAA": a, "BBB": b}, lookback_days=90)
    assert not mat.empty
    assert mat.shape == (2, 2)
    assert "AAA" in mat.index and "BBB" in mat.index
    assert abs(float(mat.loc["AAA", "AAA"]) - 1.0) < 1e-9
    assert abs(float(mat.loc["BBB", "BBB"]) - 1.0) < 1e-9
    assert -1.0 <= float(mat.loc["AAA", "BBB"]) <= 1.0


def test_correlation_matrix_inner_join_mismatched_dates():
    """Misaligned calendars should align on intersection only."""
    i1 = pd.date_range("2024-01-01", periods=30, freq="D")
    i2 = pd.date_range("2024-01-15", periods=30, freq="D")
    a = pd.Series(np.linspace(100, 110, 30), index=i1)
    b = pd.Series(np.linspace(200, 190, 30), index=i2)
    mat = TA.get_correlation_matrix({"X": a, "Y": b}, lookback_days=90)
    assert not mat.empty
    assert mat.shape == (2, 2)
