"""Fallback OTM strike picker logic (mirrors Cashflow tab heuristic)."""
import numpy as np
import pandas as pd

def _fallback_pick(df_opt, side, price: float):
    if not isinstance(df_opt, pd.DataFrame) or df_opt.empty:
        return None
    w = df_opt.copy()
    w["strike"] = pd.to_numeric(w.get("strike"), errors="coerce")
    w["bid"] = pd.to_numeric(w.get("bid"), errors="coerce").fillna(0.0)
    w["ask"] = pd.to_numeric(w.get("ask"), errors="coerce").fillna(0.0)
    w["lastPrice"] = pd.to_numeric(w.get("lastPrice"), errors="coerce").fillna(0.0)
    w["mid"] = (w["bid"] + w["ask"]) / 2.0
    w["est_px"] = np.where(w["mid"] > 0.0, w["mid"], w["lastPrice"])
    if side == "call":
        w = w[w["strike"] > price].copy()
        w["otm"] = (w["strike"] / price - 1.0) * 100.0
        strike_sort = ["target_gap", "strike"]
        asc = [True, True]
    else:
        w = w[w["strike"] < price].copy()
        w["otm"] = (1.0 - w["strike"] / price) * 100.0
        strike_sort = ["target_gap", "strike"]
        asc = [True, False]
    w = w[w["otm"].notna()].copy()
    if w.empty:
        return None
    preferred = w[(w["otm"] >= 3.0) & (w["otm"] <= 7.0)].copy()
    if preferred.empty:
        preferred = w
    preferred["target_gap"] = (preferred["otm"] - 5.0).abs()
    return preferred.sort_values(strike_sort, ascending=asc).iloc[0]


def test_fallback_pick_call_prefers_band():
    price = 100.0
    df = pd.DataFrame(
        {
            "strike": [102.0, 108.0, 115.0],
            "bid": [1.0, 2.0, 3.0],
            "ask": [1.2, 2.2, 3.2],
            "lastPrice": [0.0, 0.0, 0.0],
        }
    )
    row = _fallback_pick(df, "call", price)
    assert row is not None
    assert float(row["strike"]) == 102.0


def test_fallback_pick_put_side():
    price = 100.0
    df = pd.DataFrame(
        {
            "strike": [88.0, 92.0, 97.0],
            "bid": [1.0, 1.5, 2.0],
            "ask": [1.1, 1.6, 2.1],
            "lastPrice": [0.0, 0.0, 0.0],
        }
    )
    row = _fallback_pick(df, "put", price)
    assert row is not None
    assert float(row["strike"]) < price


def test_fallback_pick_empty():
    assert _fallback_pick(pd.DataFrame(), "call", 100) is None
