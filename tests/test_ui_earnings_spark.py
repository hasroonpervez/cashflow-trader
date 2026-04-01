"""Earnings glance sparkline series — monotonic / length invariants."""
from __future__ import annotations

import numpy as np

from modules.ui_helpers import earnings_runway_spark_series


def test_earnings_spark_none_is_seven_points_descending():
    s = earnings_runway_spark_series(None)
    assert len(s) == 7
    assert float(s.iloc[0]) > float(s.iloc[-1])


def test_earnings_spark_twelve_days_ends_near_twelve():
    s = earnings_runway_spark_series(12)
    assert len(s) == 7
    assert abs(float(s.iloc[-1]) - 12.0) < 1e-6


def test_earnings_spark_negative_post_print():
    s = earnings_runway_spark_series(-3)
    assert len(s) == 7
    assert float(s.iloc[-1]) <= float(s.iloc[0])


def test_earnings_spark_far_dated_gentle():
    s = earnings_runway_spark_series(120)
    assert len(s) == 7
    assert float(s.iloc[0]) >= float(s.iloc[-1])
