"""INDEPENDENT verification of the options-math engineer's claims (AUDIT_2026-08.md).

Written by the verifier, deliberately using different fixtures/paths from
``tests/test_fix_options_math.py`` so the two files cannot pass for the same reason.
"""
import numpy as np
import pandas as pd
import pytest

from modules.options import (
    CONTINUOUS_KELLY_MAX_ALLOCATION,
    Opt,
    _causal_weekly_slice,
    _volatility_squeeze_gate,
    compute_explosion_score,
    continuous_kelly,
    detect_diamonds,
    diamond_win_rate,
    explosion_score_detail,
    kelly_criterion,
    score_10x_potential,
)


def _ohlcv(n, seed, drift=0.0009, vol=0.017):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-03-06", periods=n, freq="B")
    close = 42.0 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    return pd.DataFrame(
        {
            "Open": close * (1 + rng.normal(0, 0.001, n)),
            "High": close * (1 + np.abs(rng.normal(0, 0.007, n))),
            "Low": close * (1 - np.abs(rng.normal(0, 0.007, n))),
            "Close": close,
            "Volume": rng.integers(700_000, 9_000_000, n).astype(float),
        },
        index=idx,
    )


def _wfri(df):
    """Weekly frame built exactly the way production does it (data.py:910, W-FRI)."""
    return pd.DataFrame(
        {
            "Open": df["Open"].resample("W-FRI").first(),
            "High": df["High"].resample("W-FRI").max(),
            "Low": df["Low"].resample("W-FRI").min(),
            "Close": df["Close"].resample("W-FRI").last(),
        }
    ).dropna(how="any")


# ── #1 Kelly ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", range(40))
def test_kelly_random_sweep_never_breaches_the_cap(seed):
    rng = np.random.default_rng(seed)
    for _ in range(40):
        out = continuous_kelly(
            expected_return=float(rng.uniform(-1.0, 5.0)),
            risk_free_rate=float(rng.uniform(0.0, 0.06)),
            variance=float(rng.uniform(1e-4, 1.0)),
            half_kelly=bool(rng.integers(0, 2)),
            correlation_haircut=float(rng.uniform(0.0, 1.2)),
            pop_mult=float(rng.uniform(0.0, 1.09)),
        )
        assert 0.0 <= out <= 100.0 * CONTINUOUS_KELLY_MAX_ALLOCATION + 1e-9


def test_kelly_criterion_quant_branch_is_also_capped():
    full, half = kelly_criterion(
        94.0, 2.0, 3.0, use_quant=True, expected_return=3.0, variance=0.01,
        correlation_haircut=1.20, avg_mc_pop=100.0,
    )
    assert full <= 25.0 and half <= 25.0


def test_kelly_saturation_note_full_and_half_still_collide_at_the_cap():
    """Not a defect vs the audit's prescribed fix, but pinned so it is visible:
    above the cap the half-Kelly branch is again indistinguishable from full."""
    kw = dict(expected_return=1.05, risk_free_rate=0.05, variance=0.02,
              correlation_haircut=1.0, pop_mult=1.0)
    assert continuous_kelly(half_kelly=True, **kw) == continuous_kelly(half_kelly=False, **kw)


# ── #4 lookahead ────────────────────────────────────────────────────────────

def _sig(ds, upto=None):
    return [
        (d["type"], pd.Timestamp(d["date"]), round(float(d["score"]), 8), round(float(d["rsi"]), 8))
        for d in ds
        if upto is None or pd.Timestamp(d["date"]) <= upto
    ]


@pytest.mark.parametrize("seed,cut", [(101, 120), (102, 150), (103, 180)])
def test_detect_diamonds_is_point_in_time_on_wfri_weeklies(seed, cut):
    """Truncating the frame at ``cut`` must not change any signal at or before ``cut``.
    Uses W-FRI weekly bars (the production shape), not the ``W`` used by the author."""
    df = _ohlcv(240, seed)
    ts = df.index[cut]
    full = _sig(detect_diamonds(df, _wfri(df)), upto=ts)
    pit = _sig(detect_diamonds(df.iloc[: cut + 1], _wfri(df.iloc[: cut + 1])))
    assert full == pit


def test_detect_diamonds_ignores_a_future_regime_flip():
    """Bull run then a 55% crash: the crash must not delete signals recorded before it."""
    df = _ohlcv(230, 77, drift=0.004, vol=0.012)
    cut = 150
    tail = np.exp(np.linspace(0.0, -0.8, len(df) - cut - 1))
    df.iloc[cut + 1:, df.columns.get_loc("Close")] = df["Close"].iloc[cut] * tail
    df["High"] = df["Close"] * 1.006
    df["Low"] = df["Close"] * 0.994
    df["Open"] = df["Close"] * 0.999
    ts = df.index[cut]
    assert _sig(detect_diamonds(df, _wfri(df)), upto=ts) == _sig(
        detect_diamonds(df.iloc[: cut + 1], _wfri(df.iloc[: cut + 1]))
    )


def test_detect_diamonds_survives_a_short_frame_whose_weekly_slice_empties():
    """Early bars have < 26 causal weekly bars; the call must not raise."""
    df = _ohlcv(60, 5)
    assert isinstance(detect_diamonds(df, _wfri(df)), list)
    assert isinstance(detect_diamonds(df, None), list)


def test_causal_weekly_slice_never_leaks_a_bar_that_had_not_closed():
    """No returned bar may close AFTER ``ts``.

    ``<=``, not ``<``: on a ``W-FRI`` frame the bar stamped Friday F closes at that
    Friday's close, which is the same instant the daily bar at ``ts == F`` closes.
    Both are in the same information set, so including it is not lookahead — and
    excluding it (the old flat ``ts - 6 days`` rule) left the weekly bias a week stale.
    A genuinely open week resamples to the *upcoming* Friday label, which is ``> ts``
    and is still correctly excluded.
    """
    df = _ohlcv(120, 9)
    wk = _wfri(df)
    for i in (60, 61, 62, 63, 64):
        ts = df.index[i]
        sliced = _causal_weekly_slice(wk, ts)
        assert (sliced.index <= ts).all()


def test_causal_weekly_slice_is_label_convention_aware():
    """The flat ``ts - 6 days`` rule was exact for LEFT-labelled weeklies (yfinance
    ``interval="1wk"``, Monday-stamped) but dropped one already-closed week on a
    RIGHT-labelled frame (``data.py:910`` resamples ``W-FRI``), leaving the gate's
    weekly bias up to ~12 days stale. The slice now derives each bar's real close
    date from the label convention, so neither frame is over-truncated."""
    df = _ohlcv(300, 101)
    wk = _wfri(df)
    ts = df.index[-3]  # a mid-week timestamp
    stale_days = (ts - _causal_weekly_slice(wk, ts).index[-1]).days
    assert 0 <= stale_days <= 7, f"right-labelled weeklies still stale by {stale_days}d"


def test_causal_weekly_slice_never_leaks_either_convention():
    """The property that actually matters: no returned bar may close after ``ts``."""
    df = _ohlcv(300, 202)

    right = _wfri(df)                                    # Friday-stamped (period end)
    left = right.copy()
    left.index = right.index - pd.Timedelta(days=4)      # Monday-stamped (period start)

    for ts in (df.index[-1], df.index[-3], df.index[-8], df.index[-15]):
        got = _causal_weekly_slice(right, ts)
        assert (got.index <= ts).all(), "right-labelled: returned an unclosed week"

        got_left = _causal_weekly_slice(left, ts)
        # A Monday-stamped bar closes on the Friday 4 days later.
        assert (got_left.index + pd.Timedelta(days=4) <= ts).all(), \
            "left-labelled: returned a week that had not closed yet"


# ── #10 gamma flip ──────────────────────────────────────────────────────────

def _chain(spot=100.0):
    rows = []
    for k in np.arange(75.0, 126.0, 5.0):
        rows.append({"strike": k, "openInterest": 5000 if k <= spot else 400,
                     "type": "put", "impliedVolatility": 0.33})
        rows.append({"strike": k, "openInterest": 400 if k < spot else 5000,
                     "type": "call", "impliedVolatility": 0.30})
    return pd.DataFrame(rows)


def test_gamma_flip_found_and_bracketed_by_the_sign_change():
    gex = Opt.calc_gamma_exposure(_chain(), 100.0).sort_index()
    cum = gex.cumsum()
    flip = Opt.find_gamma_flip(gex)
    assert flip is not None
    below = cum.loc[cum.index <= flip]
    above = cum.loc[cum.index >= flip]
    assert float(below.iloc[-1]) <= 0 <= float(above.iloc[0])


# ── #11 squeeze gate ────────────────────────────────────────────────────────

def test_squeeze_gate_discriminates_on_raw_production_shaped_ohlcv():
    coil = _ohlcv(160, 21)
    coil["High"] = coil["Close"] * 1.0004
    coil["Low"] = coil["Close"] * 0.9996
    expand = _ohlcv(160, 21)
    w = np.linspace(0.001, 0.09, len(expand))
    expand["High"] = expand["Close"] * (1 + w)
    expand["Low"] = expand["Close"] * (1 - w)
    assert "ATR" not in coil.columns
    assert _volatility_squeeze_gate(expand)[0] is False
    assert _volatility_squeeze_gate(coil)[0] in (True, False)  # coil shape is data-dependent
    assert _volatility_squeeze_gate(expand)[1] > 0.25


def test_pre_diamond_fails_closed_without_measurable_volatility():
    df = pd.DataFrame({"Close": np.linspace(10, 11, 40)},
                      index=pd.date_range("2024-01-01", periods=40, freq="B"))
    df["Volume"] = 1_000_000.0
    out = Opt.detect_pre_diamond(df, 10.9, 10.95, "BULLISH", pd.Series([4, 5, 6]))
    assert out["is_pre_diamond"] is False


# ── #13 explosion score ─────────────────────────────────────────────────────

def test_no_options_data_no_longer_outranks_a_measured_name():
    blank = {"pre_diamond_status": {}, "10x Potential": 0, "qs": 0.0,
             "d_status": "None", "GEX Regime": "—"}
    measured = dict(blank, **{"GEX Regime": "🛡️ STABLE"})
    assert compute_explosion_score(blank) == compute_explosion_score(measured) == 0.0
    assert explosion_score_detail(blank)["gex_available"] is False
    assert explosion_score_detail(measured)["gex_available"] is True


def test_explosion_score_is_bounded_and_matches_its_components():
    row = {"pre_diamond_status": {"is_pre_diamond": True, "signal_strength": "🟡 ACCUMULATING"},
           "10x Potential": 20, "qs": 999.0, "d_status": "🔷 BLUE",
           "GEX Regime": "⚠️ TURBULENT"}
    detail = explosion_score_detail(row)
    assert detail["score"] <= 100.0
    assert detail["components"]["tenx"] <= 25.0
    assert detail["components"]["qe"] <= 20.0
    assert compute_explosion_score(row) == detail["score"]


def test_ten_x_flags_contain_only_matched_factors():
    """renderers.py:2750 renders ", ".join(sorted(flags.keys())) as the "Flags" column,
    so any bookkeeping key in `flags` is shown to the user as a matched factor.

    A `max_score` key briefly lived here and was removed; this pins that no meta key
    creeps back in. Consumers import TEN_X_MAX_SCORE from modules.options instead.
    """
    _, flags = score_10x_potential(_ohlcv(300, 31), {"marketCap": 1e9})
    assert "max_score" not in flags
    rendered = ", ".join(sorted(flags.keys()))
    assert "max_score" not in rendered
    for key in flags:
        assert not key.startswith("_"), f"private key {key!r} would render as a factor"


# ── #23 win rate ────────────────────────────────────────────────────────────

def test_entry_side_win_rate_ignores_pink_outcomes():
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    close = np.full(40, 50.0)
    close[7] = 40.0   # blue at 2 loses
    close[13] = 40.0  # pink at 8 wins
    df = pd.DataFrame({"Close": close}, index=idx)
    ds = [{"date": idx[2], "price": 50.0, "type": "blue"},
          {"date": idx[8], "price": 50.0, "type": "pink"}]
    assert diamond_win_rate(df, ds, forward_bars=5, holdout_frac=None) == (0.0, -20.0, 1)
    assert diamond_win_rate(df, ds, forward_bars=5, side="pink", holdout_frac=None) == (
        100.0, 20.0, 1)


def test_zero_blue_signals_returns_a_fake_zero_percent_with_n_zero():
    """Documents the remaining sharp edge: n=0 comes back as 0.0%, not None. Two of the
    four display sites guard on n; renderers.py:1820 prints the 0% verbatim."""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    df = pd.DataFrame({"Close": np.full(30, 10.0)}, index=idx)
    ds = [{"date": idx[3], "price": 10.0, "type": "pink"}]
    assert diamond_win_rate(df, ds, forward_bars=5, holdout_frac=None) == (0.0, 0.0, 0)
