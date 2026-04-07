"""Tests for modules/utils.py"""
import math

import numpy as np
import pandas as pd

from modules.utils import log_warn, safe_float, safe_html, safe_last


def test_safe_last_series():
    assert safe_last(pd.Series([1, 2, 3])) == 3


def test_safe_last_empty_series():
    assert safe_last(pd.Series([], dtype=float)) is None
    assert safe_last(pd.Series([], dtype=float), 0.0) == 0.0


def test_safe_last_nan():
    assert safe_last(pd.Series([1.0, float("nan")])) is None


def test_safe_last_none():
    assert safe_last(None) is None
    assert safe_last(None, 42) == 42


def test_safe_last_list():
    assert safe_last([10, 20]) == 20
    assert safe_last([]) is None


def test_safe_last_ndarray():
    assert safe_last(np.array([1.0, 2.0])) == 2.0
    assert safe_last(np.array([])) is None


def test_safe_float_normal():
    assert safe_float(3.14) == 3.14
    assert safe_float("2.5") == 2.5


def test_safe_float_none():
    assert safe_float(None) == 0.0
    assert safe_float(None, -1.0) == -1.0


def test_safe_float_nan():
    assert safe_float(float("nan")) == 0.0


def test_safe_float_inf():
    assert safe_float(float("inf")) == 0.0


def test_safe_float_string():
    assert safe_float("not_a_number") == 0.0


def test_safe_html_escapes():
    assert safe_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert safe_html("PLTR") == "PLTR"
    assert safe_html(None) == "None"


def test_log_warn_does_not_raise(capsys):
    log_warn("test context", ValueError("boom"), ticker="PLTR")
    captured = capsys.readouterr()
    assert "ValueError" in captured.err
    assert "PLTR" in captured.err
