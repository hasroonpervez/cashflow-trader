"""Regression tests for the AUDIT_2026-08 defects fixed in modules/ta.py.

Covers:
  #26  rolling volume Z-score was capped at sqrt(w-1) -> whale tier unreachable
  #27  both Hurst estimators were indistinguishable from noise at their thresholds
  med. TA.atr used an SMA of True Range instead of Wilder's RMA (TA.adx inherited it)
  med. the "90-day" correlation matrix was built from 39 observations
  med. ffd_returns_from_closes silently dropped short-history tickers
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from modules.ta import TA


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------
def _ohlcv(n=300, seed=0, base=100.0):
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 1.0, n))
    close = np.maximum(close, 1.0)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + np.abs(rng.normal(0, 0.6, n)),
            "Low": close - np.abs(rng.normal(0, 0.6, n)),
            "Close": close,
            "Volume": rng.integers(500_000, 1_500_000, n).astype(float),
        },
        index=idx,
    )


def _fgn(n, H, rng):
    """Fractional Gaussian noise (Davies-Harte circulant embedding) — a series with a
    *known* true Hurst exponent, which a drift-plus-iid-noise series is not: R/S removes
    the mean, so constant drift carries no persistence."""
    k = np.arange(0, n)
    g = 0.5 * (np.abs(k - 1) ** (2 * H) - 2 * np.abs(k) ** (2 * H) + np.abs(k + 1) ** (2 * H))
    c = np.concatenate([g, g[-2:0:-1]])
    lam = np.fft.fft(c).real
    lam[lam < 0] = 0.0
    m = c.size
    w = rng.normal(size=m) + 1j * rng.normal(size=m)
    return np.fft.fft(np.sqrt(lam / (2 * m)) * w).real[:n]


def _fbm_closes(n, H, rng, base=100.0):
    return base * np.exp(np.cumsum(_fgn(n, H, rng) * 0.02))


def _wilder_rma(values, p):
    """Reference Wilder RMA computed by hand, recursively."""
    out = []
    prev = None
    for v in values:
        prev = v if prev is None else prev + (v - prev) / p
        out.append(prev)
    return out


# --------------------------------------------------------------------------------------
# AUDIT #26 — volume Z-score ceiling
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("w", [10, 30, 40])
def test_volume_zscore_is_not_capped_at_sqrt_w_minus_one(w, monkeypatch):
    """A single enormous print must not be clipped to sqrt(w-1) = 3.00 / 5.39 / 6.24."""
    monkeypatch.setattr(TA, "_whale_zscore_window", staticmethod(lambda df: w))
    n = 120
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(3)
    vol = rng.normal(1_000_000, 50_000, n)
    vol[-1] = 20_000_000.0  # 20x print on the final bar
    df = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0 + np.cumsum(rng.normal(0, 0.4, n)),
            "Volume": vol,
        },
        index=idx,
    )
    z = float(TA.get_dark_pool_proxy(df)["volume_z_score"].iloc[-1])
    assert z > math.sqrt(w - 1), f"z={z} still capped at sqrt(w-1)={math.sqrt(w - 1)}"
    # detect_diamonds (options.py:909) grades `zlv > 3.0` for its 2-point whale tier.
    assert z > 3.0


def test_volume_zscore_baseline_excludes_the_scored_bar():
    """mu/sd must describe the *prior* w bars, not a window containing the spike itself."""
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    vol = np.full(n, 1_000_000.0)
    vol[30:] += np.arange(n - 30) * 1.0  # break degenerate sd == 0
    vol[-1] = 50_000_000.0
    df = pd.DataFrame(
        {"Open": 10.0, "High": 10.5, "Low": 9.5, "Close": 10.0, "Volume": vol}, index=idx
    )
    out = TA.get_dark_pool_proxy(df)
    assert float(out["vol_mean_roll"].iloc[-1]) < 2_000_000.0  # spike not in its own baseline
    assert bool(out["is_whale_alert"].iloc[-1])


def test_volume_zscore_quiet_tape_stays_small():
    """The fix must not manufacture whales out of ordinary variation."""
    df = _ohlcv(200, seed=9)
    z = TA.get_dark_pool_proxy(df)["volume_z_score"]
    assert float(z.abs().max()) < 6.0
    assert int(z.tail(100).gt(2.0).sum()) < 15


# --------------------------------------------------------------------------------------
# AUDIT #27 — Hurst
# --------------------------------------------------------------------------------------
def test_hurst_null_is_centred_on_half_after_bias_correction():
    """Anis-Lloyd correction: raw log(R/S)/log(n) measured 0.524 on pure noise."""
    rng = np.random.default_rng(101)
    vals = []
    for _ in range(200):
        lr = rng.normal(0, 0.02, 252)
        closes = 100.0 * np.exp(np.cumsum(lr))
        est = TA.hurst_rs_estimate(closes)
        assert est is not None
        vals.append(est["h"])
    assert abs(float(np.mean(vals)) - 0.5) < 0.02


def test_hurst_false_classification_rate_under_ten_percent():
    """200 seeded random walks: fewer than 10% may earn a trending/mean-reverting verdict."""
    rng = np.random.default_rng(202)
    verdicts = 0
    trials = 200
    for _ in range(trials):
        closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, 252)))
        if TA.hurst_regime(closes) is not None:
            verdicts += 1
    assert verdicts / trials < 0.10, f"{verdicts}/{trials} pure random walks classified"


def test_hurst_returns_none_when_uncertainty_spans_the_threshold():
    """calculate_hurst_exponent must not hand callers a number they will threshold on noise."""
    rng = np.random.default_rng(303)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, 252)))
    est = TA.hurst_rs_estimate(closes)
    assert est is not None and est["significant"] is False
    assert TA.calculate_hurst_exponent(closes) is None
    assert TA.hurst_regime(closes) is None
    # ...but the raw estimate is still available for display, with its uncertainty.
    raw = TA.calculate_hurst_exponent(closes, require_significance=False)
    assert raw is not None and 0.0 <= raw <= 1.0
    assert TA.hurst_rs_stderr(est["n"]) > 0.0


def test_hurst_any_returned_value_clears_the_callers_published_cutoffs():
    """Callers branch on 0.55 / 0.45 — a returned value must never sit inside that band."""
    rng = np.random.default_rng(404)
    seen = 0
    for _ in range(300):
        drift = rng.choice([0.0, 0.004, -0.004])
        closes = 100.0 * np.exp(np.cumsum(rng.normal(drift, 0.02, 252)))
        h = TA.calculate_hurst_exponent(closes)
        if h is None:
            continue
        seen += 1
        assert h > 0.55 or h < 0.45
    assert seen > 0


def test_hurst_detects_a_genuinely_trending_series():
    """Gating on significance must not cost all the power: true H=0.8 is still found."""
    rng = np.random.default_rng(505)
    trending = sum(
        TA.hurst_regime(_fbm_closes(252, 0.8, rng)) == "TRENDING" for _ in range(60)
    )
    assert trending >= 30
    rng = np.random.default_rng(505)
    closes = _fbm_closes(252, 0.85, rng)
    est = TA.hurst_rs_estimate(closes)
    assert est is not None and est["regime"] == "TRENDING" and est["significant"]
    assert TA.calculate_hurst_exponent(closes) > 0.55


def test_hurst_detects_a_genuinely_mean_reverting_series():
    rng = np.random.default_rng(606)
    reverting = sum(
        TA.hurst_regime(_fbm_closes(252, 0.25, rng)) == "MEAN_REVERTING" for _ in range(60)
    )
    assert reverting >= 30
    n = 252
    closes = 100.0 * np.exp(0.02 * np.array([(-1) ** i for i in range(n)], dtype=float))
    assert TA.hurst_regime(closes) == "MEAN_REVERTING"
    assert TA.calculate_hurst_exponent(closes) < 0.45


def test_hurst_single_estimator_no_disagreement():
    """TA.hurst used to be a second, contradictory estimator (variance-ratio slope/2)."""
    rng = np.random.default_rng(505)
    closes = pd.Series(_fbm_closes(252, 0.85, rng))
    rs = TA.calculate_hurst_exponent(closes)
    assert rs is not None
    assert TA.hurst(closes) == pytest.approx(round(float(rs), 3))


def test_hurst_returns_random_walk_prior_rather_than_a_verdict():
    rng = np.random.default_rng(707)
    closes = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, 252))))
    assert TA.hurst(closes) == 0.5  # float-returning contract kept for options/renderers
    assert TA.hurst(pd.Series([100.0, 101.0, 102.0])) == 0.5  # too little history
    assert TA.calculate_hurst_exponent(np.array([100.0, 101.0])) is None


# --------------------------------------------------------------------------------------
# ATR / ADX — Wilder RMA
# --------------------------------------------------------------------------------------
def test_atr_is_wilder_rma_not_sma():
    df = _ohlcv(120, seed=11)
    p = 14
    tr = TA.true_range(df)
    got = TA.atr(df, p)
    expect = pd.Series(_wilder_rma(tr.to_numpy(dtype=float), p), index=df.index)
    expect.iloc[: p - 1] = np.nan
    pd.testing.assert_series_equal(got, expect, check_names=False)
    # ...and it is genuinely different from the old simple mean.
    sma = tr.rolling(p).mean()
    assert not np.allclose(got.dropna().to_numpy(), sma.dropna().to_numpy(), rtol=1e-6)


def test_atr_true_range_definition_hand_checked():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    df = pd.DataFrame(
        {"High": [11.0, 20.0, 12.0], "Low": [9.0, 18.0, 11.0], "Close": [10.0, 19.0, 11.5]},
        index=idx,
    )
    tr = TA.true_range(df)
    assert float(tr.iloc[0]) == pytest.approx(2.0)   # first bar: H-L
    assert float(tr.iloc[1]) == pytest.approx(10.0)  # gap up: H - prev C
    assert float(tr.iloc[2]) == pytest.approx(8.0)   # gap down: prev C - L


def test_atr_retains_a_shock_longer_than_an_sma_does():
    """The behavioural point of RMA: an old spike decays, it does not fall off a cliff."""
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    close = np.full(n, 100.0)
    high[20] = 140.0  # one violent bar
    df = pd.DataFrame({"High": high, "Low": low, "Close": close}, index=idx)
    atr = TA.atr(df, 14)
    sma = TA.true_range(df).rolling(14).mean()
    assert float(sma.iloc[35]) == pytest.approx(float(sma.iloc[59]), abs=1e-9)  # spike gone
    assert float(atr.iloc[35]) > float(atr.iloc[59])  # still decaying


def test_atr_warmup_nans_unchanged():
    df = _ohlcv(60, seed=12)
    atr = TA.atr(df, 14)
    assert atr.iloc[:13].isna().all()
    assert atr.iloc[13:].notna().all()


def test_adx_uses_wilder_smoothing_at_all_three_stages():
    df = _ohlcv(200, seed=13)
    p = 14
    adx, di_p, di_n = TA.adx(df, p)
    atr_v = TA.atr(df, p).replace(0, np.nan)
    up = df["High"].diff()
    dn = -df["Low"].diff()
    dmp = up.where((up > dn) & (up > 0), 0.0)
    dmn = dn.where((dn > up) & (dn > 0), 0.0)
    exp_dip = 100 * pd.Series(_wilder_rma(dmp.to_numpy(dtype=float), p), index=df.index) / atr_v
    exp_din = 100 * pd.Series(_wilder_rma(dmn.to_numpy(dtype=float), p), index=df.index) / atr_v
    exp_dip.iloc[: p - 1] = np.nan
    exp_din.iloc[: p - 1] = np.nan
    pd.testing.assert_series_equal(di_p, exp_dip, check_names=False)
    pd.testing.assert_series_equal(di_n, exp_din, check_names=False)
    assert adx.dropna().between(0, 100).all()
    # differs from the old triple-SMA construction
    old = (100 * (di_p - di_n).abs() / (di_p + di_n).replace(0, np.nan)).rolling(p).mean()
    assert not np.allclose(
        adx.dropna().tail(50).to_numpy(), old.dropna().tail(50).to_numpy(), rtol=1e-6
    )


def test_adx_still_returns_three_aligned_series():
    df = _ohlcv(120, seed=14)
    adx, di_p, di_n = TA.adx(df)
    for s in (adx, di_p, di_n):
        assert isinstance(s, pd.Series) and len(s) == len(df)
        assert s.index.equals(df.index)


# --------------------------------------------------------------------------------------
# Correlation matrix observation count
# --------------------------------------------------------------------------------------
def _closes(n, seed, start="2024-01-01"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.Series(100 + np.cumsum(rng.normal(0, 1.0, n)), index=idx)


def test_correlation_matrix_keeps_ffd_warmup_on_top_of_the_lookback():
    """A '90-day' matrix must rest on ~90 innovations, not 39."""
    d = {"AAA": _closes(400, 1), "BBB": _closes(400, 2)}
    mat = TA.get_correlation_matrix(d, lookback_days=90)
    assert not mat.empty
    assert mat.attrs["n_obs"] >= 60
    assert mat.attrs["n_obs"] == pytest.approx(90, abs=2)
    assert mat.attrs["insufficient_observations"] is False


def test_correlation_matrix_refuses_when_too_few_observations_survive():
    """39 observations give Pearson SE ~= 0.167 against 0.75/0.80 cutoffs — refuse instead."""
    d = {"AAA": _closes(95, 3), "BBB": _closes(95, 4)}
    mat = TA.get_correlation_matrix(d, lookback_days=90)
    assert mat.empty  # callers read empty as "apply no correlation penalty"
    assert mat.attrs["insufficient_observations"] is True
    assert mat.attrs["n_obs"] < 60
    assert mat.attrs["min_obs_required"] == 60


def test_correlation_matrix_min_obs_is_tunable():
    d = {"AAA": _closes(95, 5), "BBB": _closes(95, 6)}
    assert not TA.get_correlation_matrix(d, lookback_days=90, min_obs=10).empty


def test_correlation_matrix_values_remain_valid_pearson():
    d = {"AAA": _closes(400, 7), "BBB": _closes(400, 8)}
    mat = TA.get_correlation_matrix(d, lookback_days=90)
    assert mat.shape == (2, 2)
    assert float(mat.loc["AAA", "AAA"]) == pytest.approx(1.0)
    assert -1.0 <= float(mat.loc["AAA", "BBB"]) <= 1.0


# --------------------------------------------------------------------------------------
# ffd_returns_from_closes — short-history tickers are flagged, not silently dropped
# --------------------------------------------------------------------------------------
def test_ffd_returns_flags_dropped_short_history_tickers():
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    rng = np.random.default_rng(21)
    wide = pd.DataFrame(
        {
            "AAA": 100 + np.cumsum(rng.normal(0, 1, 200)),
            "BBB": 100 + np.cumsum(rng.normal(0, 1, 200)),
            "NEWCO": np.concatenate([np.full(160, np.nan), 100 + np.cumsum(rng.normal(0, 1, 40))]),
        },
        index=idx,
    )
    out = TA.ffd_returns_from_closes(wide)
    assert "NEWCO" not in out.columns
    assert out.attrs["ffd_dropped_insufficient"] == ["NEWCO"]
    assert out.attrs["ffd_min_closes_required"] == 65


def test_ffd_returns_flag_survives_to_the_correlation_matrix():
    d = {
        "AAA": _closes(400, 31),
        "BBB": _closes(400, 32),
        "NEWCO": _closes(400, 33).tail(20),
    }
    mat = TA.get_correlation_matrix(d, lookback_days=90)
    # inner join across dates leaves only NEWCO's 20 shared bars, so nothing is measurable
    assert mat.attrs["insufficient_observations"] is True
    assert "NEWCO" in mat.attrs["ffd_dropped_insufficient"]


def test_ffd_returns_no_flag_when_nothing_dropped():
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    rng = np.random.default_rng(41)
    wide = pd.DataFrame(
        {"AAA": 100 + np.cumsum(rng.normal(0, 1, 200)), "BBB": 100 + np.cumsum(rng.normal(0, 1, 200))},
        index=idx,
    )
    out = TA.ffd_returns_from_closes(wide)
    assert out.attrs["ffd_dropped_insufficient"] == []
    assert not out.empty


def test_ffd_returns_empty_frame_still_carries_attrs():
    out = TA.ffd_returns_from_closes(pd.DataFrame())
    assert out.empty
    assert out.attrs["ffd_dropped_insufficient"] == []
