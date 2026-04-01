"""Opt helpers that do not hit the network."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.options import Opt, bs_price, calc_ev


def test_simple_corr_haircut_identity():
    df = pd.DataFrame({"A": [0.01, -0.02, 0.005], "B": [0.02, -0.01, 0.0]})
    h = Opt._simple_corr_haircut(["A", "B"], "A", df)
    assert 0.35 <= h <= 1.0


def test_simple_corr_haircut_single_ticker():
    df = pd.DataFrame({"A": [0.01, -0.02]})
    assert Opt._simple_corr_haircut(["A"], "A", df) == 1.0


def test_portfolio_allocation_weights_and_contracts():
    diamonds = [
        {"ticker": "AAA", "quant_edge": 80.0, "mc_pop_pct": 50.0, "premium_per_contract": 100.0},
        {"ticker": "BBB", "quant_edge": 20.0, "mc_pop_pct": 50.0, "premium_per_contract": 100.0},
    ]
    lr = pd.DataFrame(
        {
            "AAA": np.random.default_rng(1).normal(0, 0.01, 20),
            "BBB": np.random.default_rng(2).normal(0, 0.01, 20),
        }
    )
    out = Opt.portfolio_allocation(
        diamonds,
        total_capital=10_000.0,
        watchlist_tickers=["AAA", "BBB"],
        log_returns_df=lr,
    )
    assert len(out) == 2
    assert sum(r["capital_allocation"] for r in out) <= 10_000.0 + 1.0
    for r in out:
        assert r["contracts"] >= 0
        assert r["ticker"] in ("AAA", "BBB")


def test_calc_ev_sign():
    ev = calc_ev(premium=100, max_loss=300, pop_pct=60)
    assert ev == round(0.6 * 100 - 0.4 * 300, 2)


def test_bs_price_call_positive():
    px = bs_price(100, 100, 30 / 365.0, 0.05, 0.25, "call")
    assert px > 0
