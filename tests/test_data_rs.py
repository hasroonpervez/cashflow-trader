"""RS vs SPY from aligned close matrix (no Yahoo)."""
import numpy as np
import pandas as pd

from modules.data import rs_spy_ratio_map_from_close_matrix


def test_rs_spy_ratio_outperformance():
    idx = pd.date_range("2020-01-01", periods=120, freq="B")
    spy = pd.Series(np.linspace(100, 102, 120), index=idx)
    stk = pd.Series(np.linspace(100, 115, 120), index=idx)
    close = pd.DataFrame({"SPY": spy, "ABC": stk})
    m = rs_spy_ratio_map_from_close_matrix(close, ("ABC",), sessions=90)
    assert m.get("ABC") is not None
    assert m["ABC"] > 1.0


def test_rs_spy_ratio_underperformance():
    idx = pd.date_range("2020-01-01", periods=120, freq="B")
    spy = pd.Series(np.linspace(100, 110, 120), index=idx)
    stk = pd.Series(np.linspace(100, 105, 120), index=idx)
    close = pd.DataFrame({"SPY": spy, "ABC": stk})
    m = rs_spy_ratio_map_from_close_matrix(close, ("ABC",), sessions=90)
    assert m.get("ABC") is not None
    assert m["ABC"] < 1.0


def test_rs_spy_none_for_spy_ticker():
    idx = pd.date_range("2020-01-01", periods=120, freq="B")
    close = pd.DataFrame({"SPY": np.linspace(100, 105, 120)}, index=idx)
    m = rs_spy_ratio_map_from_close_matrix(close, ("SPY",), sessions=90)
    assert m.get("SPY") is None


def test_rs_spy_missing_column():
    idx = pd.date_range("2020-01-01", periods=120, freq="B")
    close = pd.DataFrame({"SPY": np.linspace(100, 105, 120)}, index=idx)
    m = rs_spy_ratio_map_from_close_matrix(close, ("ZZZ",), sessions=90)
    assert m.get("ZZZ") is None
