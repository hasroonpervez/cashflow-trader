"""Regression tests for the AUDIT_2026-08 data-layer fixes (modules/data.py).

Covers: #16 partial intraday bar, #17 tz-aware earnings comparison, #25 efficiency-ratio
sign guard, plus the medium items, rate-limit caching/thread-safety, unaligned RS-vs-SPY,
and tape % change reporting the prior session.
"""
import threading

import numpy as np
import pandas as pd
import pytest

from modules import data as D


# ─────────────────────────────────────────────────────────────────────────
# #16: partial intraday bar must not be consumed as a completed session
# ─────────────────────────────────────────────────────────────────────────
def _bdays(n, end="2026-08-10"):
    return pd.bdate_range(end=pd.Timestamp(end), periods=n)


def test_last_bar_is_partial_true_during_the_session():
    idx = _bdays(30)
    now = pd.Timestamp("2026-08-10 10:30", tz="America/New_York")
    assert D.last_bar_is_partial(idx, now=now) is True


def test_last_bar_is_partial_false_after_the_close():
    idx = _bdays(30)
    assert D.last_bar_is_partial(idx, now=pd.Timestamp("2026-08-10 16:00", tz="America/New_York")) is False
    assert D.last_bar_is_partial(idx, now=pd.Timestamp("2026-08-10 20:15", tz="America/New_York")) is False


def test_last_bar_is_partial_false_for_a_prior_session():
    """Yesterday's bar is complete however early in today's session we ask (weekends included)."""
    idx = _bdays(30)
    assert D.last_bar_is_partial(idx, now=pd.Timestamp("2026-08-11 09:45", tz="America/New_York")) is False
    # Saturday: last bar is Friday, still complete.
    assert D.last_bar_is_partial(idx, now=pd.Timestamp("2026-08-15 11:00", tz="America/New_York")) is False


def test_last_bar_is_partial_handles_tz_aware_index_and_empty_input():
    idx = _bdays(30).tz_localize("America/New_York")
    assert D.last_bar_is_partial(idx, now=pd.Timestamp("2026-08-10 10:30", tz="America/New_York")) is True
    assert D.last_bar_is_partial(pd.DatetimeIndex([]), now=pd.Timestamp("2026-08-10 10:30")) is False
    assert D.last_bar_is_partial(None) is False


def test_drop_partial_last_bar_only_drops_when_in_progress():
    s = pd.Series(np.arange(30.0), index=_bdays(30))
    mid = pd.Timestamp("2026-08-10 10:30", tz="America/New_York")
    after = pd.Timestamp("2026-08-10 18:00", tz="America/New_York")
    assert len(D.drop_partial_last_bar(s, now=mid)) == 29
    assert D.drop_partial_last_bar(s, now=mid).index[-1] == s.index[-2]
    assert len(D.drop_partial_last_bar(s, now=after)) == 30
    assert len(D.drop_partial_last_bar(pd.Series(dtype=float), now=mid)) == 0


# ─────────────────────────────────────────────────────────────────────────
# radar_broad_filter: partial bar (#16) + inner-joined RS vs SPY (medium)
# ─────────────────────────────────────────────────────────────────────────
def _panel(index, volumes, closes, spy_closes):
    """``Price`` x ``Ticker`` MultiIndex panel in the real ``yf.download`` shape."""
    cols = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], ["AAA", "SPY"]], names=["Price", "Ticker"]
    )
    out = pd.DataFrame(index=index, columns=cols, dtype=float)
    for field in ("Open", "High", "Low", "Close"):
        out[(field, "AAA")] = closes
        out[(field, "SPY")] = spy_closes
    out[("Volume", "AAA")] = volumes
    out[("Volume", "SPY")] = 1_000_000.0
    return out


def _run_radar(monkeypatch, panel, now_et, universe, spy_closes=None):
    monkeypatch.setattr(D, "_now_et", lambda now=None: now_et)
    monkeypatch.setattr(D.yf, "download", lambda *a, **k: panel)
    # Bypass Streamlit's memo so each scenario really re-runs the body.
    return D.radar_broad_filter.__wrapped__(universe, spy_closes)


def test_radar_volume_z_ignores_the_in_progress_bar(monkeypatch):
    """#16: an in-progress bar at ~25% of a normal day must not score as a volume collapse."""
    idx = _bdays(200)
    closes = pd.Series(np.linspace(10.0, 30.0, 200), index=idx)
    spy = pd.Series(np.linspace(100.0, 105.0, 200), index=idx)
    rng = np.random.default_rng(11)
    vols = pd.Series(1_000_000.0 + rng.normal(0, 20_000, 200), index=idx)
    vols.iloc[-2] = 5_000_000.0  # yesterday: a completed accumulation day
    vols.iloc[-1] = 250_000.0  # today, 10:30 ET, a quarter of a session printed

    open_now = pd.Timestamp("2026-08-10 10:30", tz="America/New_York")
    closed = pd.Timestamp("2026-08-10 18:30", tz="America/New_York")
    panel = _panel(idx, vols, closes, spy)

    intraday = _run_radar(monkeypatch, panel, open_now, "AAA,SPY")
    after_close = _run_radar(monkeypatch, panel, closed, "AAA,SPY")
    assert intraday and after_close
    # Intraday now scores the last *completed* session (the 5x accumulation day) instead of a
    # quarter-formed bar that reads as a volume collapse.
    assert intraday[0]["vol_z"] > 3.0
    assert after_close[0]["vol_z"] < 0.0
    # The 15-point volume band was unreachable before 16:00 ET; it is reachable now.
    assert intraday[0]["pre_score"] - after_close[0]["pre_score"] == pytest.approx(15.0)


def test_radar_rs_vs_spy_is_date_aligned_not_positional(monkeypatch):
    """Medium: an externally-fetched SPY with a different calendar must be inner-joined."""
    idx = _bdays(200)
    closes = pd.Series(np.linspace(10.0, 20.0, 200), index=idx)
    spy_panel = pd.Series(np.linspace(100.0, 110.0, 200), index=idx)
    panel = _panel(idx, pd.Series(1_000_000.0, index=idx), closes, spy_panel)

    # Same SPY prices on the same dates, but the series starts 40 sessions earlier, so a
    # positional ``tail(90)`` on it lands on different dates than the stock's ``tail(90)``.
    long_idx = _bdays(240)
    spy_ext = pd.Series(np.linspace(80.0, 110.0, 240), index=long_idx)
    spy_ext.loc[idx] = spy_panel.values

    now = pd.Timestamp("2026-08-10 18:30", tz="America/New_York")
    rows = _run_radar(monkeypatch, panel, now, "AAA", spy_closes=spy_ext)
    assert rows and rows[0]["ticker"] == "AAA"

    expected = D.rs_spy_ratio_map_from_close_matrix(
        pd.DataFrame({"AAA": closes, "SPY": spy_panel}),
        ("AAA",),
        sessions=D._RS_SPY_LOOKBACK_SESSIONS,
    )["AAA"]
    assert rows[0]["rs_spy"] == pytest.approx(round(float(expected), 3))


def test_close_matrix_with_spy_aligns_tz_aware_benchmark():
    idx = _bdays(120)
    close = pd.DataFrame({"AAA": np.linspace(10, 20, 120)}, index=idx)
    spy = pd.Series(np.linspace(100, 110, 120), index=idx.tz_localize("America/New_York"))
    out = D._close_matrix_with_spy(close, spy)
    assert out is not None and "SPY" in out.columns
    assert out["SPY"].notna().sum() == 120  # aligned, not all-NaN from a tz mismatch
    assert D._close_matrix_with_spy(close, None) is None


# ─────────────────────────────────────────────────────────────────────────
# #17: tz-aware earnings_dates index must not blank the crush proxy
# ─────────────────────────────────────────────────────────────────────────
def _crush_frame(n=200, end="2026-08-10"):
    idx = _bdays(n, end=end)
    rng = np.random.default_rng(7)
    return pd.DataFrame({"Close": 100.0 + np.cumsum(rng.normal(0, 0.6, n))}, index=idx)


def test_crush_proxy_accepts_tz_aware_earnings_dates():
    """#17: the naive/aware comparison used to raise TypeError and return None forever."""
    df = _crush_frame()
    edates = pd.DatetimeIndex(
        ["2026-02-10 16:30", "2026-05-12 16:30"], tz="America/New_York"
    )
    val = D.post_earnings_vol_crush_pct_from_dates(
        df, list(edates), n_cycles=4, now=pd.Timestamp("2026-08-10")
    )
    assert val is not None
    assert np.isfinite(val)


def test_crush_proxy_matches_naive_and_aware_dates():
    df = _crush_frame()
    naive = [pd.Timestamp("2026-02-10"), pd.Timestamp("2026-05-12")]
    aware = [pd.Timestamp(t, tz="America/New_York") + pd.Timedelta(hours=16) for t in naive]
    now = pd.Timestamp("2026-08-10")
    a = D.post_earnings_vol_crush_pct_from_dates(df, naive, now=now)
    b = D.post_earnings_vol_crush_pct_from_dates(df, aware, now=now)
    assert a is not None and b is not None
    assert a == pytest.approx(b)


def test_crush_proxy_sign_follows_the_realized_vol_regime():
    """A calm pre-print window into a violent post-print window is a *positive* delta."""
    idx = _bdays(200)
    rng = np.random.default_rng(3)
    steps = rng.normal(0, 0.1, 200)
    edate = idx[120]
    steps[121:135] = rng.normal(0, 3.0, 14)  # post-print vol explosion
    df = pd.DataFrame({"Close": 100.0 + np.cumsum(steps)}, index=idx)
    val = D.post_earnings_vol_crush_pct_from_dates(
        df, [edate], n_cycles=1, now=pd.Timestamp("2026-08-10")
    )
    assert val is not None and val > 0


def test_crush_proxy_returns_none_without_usable_history():
    assert D.post_earnings_vol_crush_pct_from_dates(None, [pd.Timestamp("2026-01-05")]) is None
    assert D.post_earnings_vol_crush_pct_from_dates(_crush_frame(), []) is None
    # All earnings dates in the future → nothing to measure.
    assert (
        D.post_earnings_vol_crush_pct_from_dates(
            _crush_frame(), [pd.Timestamp("2027-01-05")], now=pd.Timestamp("2026-08-10")
        )
        is None
    )


# ─────────────────────────────────────────────────────────────────────────
# #25: efficiency ratio sign guard
# ─────────────────────────────────────────────────────────────────────────
def test_efficiency_ratio_none_when_the_business_is_collapsing():
    """#25: EBITDA −50% over assets −10% used to read +5.0 and flag a 10x candidate."""
    out = D.fundamental_sieve_from_inputs(fcf=20.0, ev=100.0, ebitda_yoy=-0.50, asset_yoy=-0.10)
    assert out is not None
    assert out["fcf_yield"] == pytest.approx(0.20)
    assert out["efficiency_ratio"] is None
    assert out["ten_x_candidate"] is False


def test_efficiency_ratio_kept_for_genuine_growth():
    out = D.fundamental_sieve_from_inputs(fcf=20.0, ev=100.0, ebitda_yoy=0.50, asset_yoy=0.10)
    assert out["efficiency_ratio"] == pytest.approx(5.0)
    assert out["ten_x_candidate"] is True


@pytest.mark.parametrize(
    "eb,ay",
    [(0.50, -0.10), (-0.50, 0.10), (0.0, 0.10), (0.50, 0.0)],
)
def test_efficiency_ratio_requires_both_legs_growing(eb, ay):
    out = D.fundamental_sieve_from_inputs(fcf=20.0, ev=100.0, ebitda_yoy=eb, asset_yoy=ay)
    assert out is not None
    assert out["efficiency_ratio"] is None
    assert out["ten_x_candidate"] is False


def test_fundamental_sieve_none_on_missing_inputs():
    assert D.fundamental_sieve_from_inputs(None, 100.0, 0.5, 0.1) is None
    assert D.fundamental_sieve_from_inputs(20.0, 0.0, 0.5, 0.1) is None
    assert D.fundamental_sieve_from_inputs(20.0, 100.0, None, 0.1) is None


def test_ten_x_requires_the_fcf_leg_too():
    out = D.fundamental_sieve_from_inputs(fcf=5.0, ev=100.0, ebitda_yoy=0.50, asset_yoy=0.10)
    assert out["efficiency_ratio"] == pytest.approx(5.0)
    assert out["ten_x_candidate"] is False


# ─────────────────────────────────────────────────────────────────────────
# Medium: transient rate-limits must not be cached as durable answers
# ─────────────────────────────────────────────────────────────────────────
class _RateLimited(Exception):
    """Shaped like yfinance's throttling error for ``_is_yahoo_rate_limit_error``."""

    def __str__(self):
        return "Too Many Requests. Rate limited. Try after a while."


@pytest.fixture(autouse=True)
def _clean_rl_state():
    D._FETCH_INFO_RL_UNTIL.clear()
    yield
    D._FETCH_INFO_RL_UNTIL.clear()


def test_cooldown_is_checked_outside_the_cache(monkeypatch):
    """Medium: the check used to sit inside a 300s-TTL cached body, so it never ran."""
    calls = []
    monkeypatch.setattr(D, "_fetch_info_cached", lambda sym: calls.append(sym) or {"x": 1})
    D._mark_fetch_info_rate_limited("AAA")
    assert D.fetch_info("AAA") == {}
    assert calls == []  # cooldown short-circuits before the cached fetch


def test_rate_limit_marks_cooldown_and_is_not_cached(monkeypatch):
    hits = []

    def _boom(sym):
        hits.append(sym)
        raise _RateLimited()

    monkeypatch.setattr(D, "_fetch_info_cached", _boom)
    assert D.fetch_info("AAA") == {}
    assert D._fetch_info_cooling_down("AAA") is True
    assert hits == ["AAA"]


def test_cooldown_expires_and_clears_the_stamp():
    D._mark_fetch_info_rate_limited("AAA", now_ts=1000.0)
    assert D._fetch_info_cooling_down("AAA", now_ts=1000.0 + 1.0) is True
    later = 1000.0 + D._FETCH_INFO_RL_COOLDOWN_SEC + 1.0
    assert D._fetch_info_cooling_down("AAA", now_ts=later) is False
    assert "AAA" not in D._FETCH_INFO_RL_UNTIL


def test_successful_fetch_clears_a_prior_cooldown(monkeypatch):
    monkeypatch.setattr(D, "_fetch_info_cached", lambda sym: {"ok": True})
    D._mark_fetch_info_rate_limited("AAA", now_ts=0.0)  # already expired
    assert D.fetch_info("AAA") == {"ok": True}
    assert "AAA" not in D._FETCH_INFO_RL_UNTIL


def test_rate_limit_map_is_thread_safe():
    """Medium: ``_FETCH_INFO_RL_UNTIL`` is mutated from the scanner/bundle pools."""
    syms = [f"S{i}" for i in range(200)]
    errors = []

    def worker(offset):
        try:
            for i, s in enumerate(syms):
                D._mark_fetch_info_rate_limited(s)
                D._fetch_info_cooling_down(s)
                if (i + offset) % 3 == 0:
                    D._clear_fetch_info_rate_limit(s)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(isinstance(v, float) for v in D._FETCH_INFO_RL_UNTIL.values())


def test_fundamental_sieve_does_not_cache_a_rate_limited_blank(monkeypatch):
    """Medium: one 429 used to blank fundamentals for an hour via the ttl=3600 sieve."""
    monkeypatch.setattr(D, "fetch_info", lambda sym: {})
    D._mark_fetch_info_rate_limited("AAA")
    with pytest.raises(D._TransientFetchError):
        D._evaluate_fundamental_sieve_cached.__wrapped__("AAA")
    assert D.evaluate_fundamental_sieve("AAA") is None


def test_fundamental_sieve_caches_a_genuine_no_data(monkeypatch):
    """A real 'Yahoo has nothing' answer is still a durable ``None``, not a transient."""
    monkeypatch.setattr(D, "fetch_info", lambda sym: {})
    assert D._evaluate_fundamental_sieve_cached.__wrapped__("AAA") is None


def test_fetch_info_keeps_its_clear_api():
    assert callable(getattr(D.fetch_info, "clear", None))
    assert callable(getattr(D.evaluate_fundamental_sieve, "clear", None))


# ─────────────────────────────────────────────────────────────────────────
# Medium: tape % change must be None when today's bar is missing
# ─────────────────────────────────────────────────────────────────────────
def test_tape_pct_none_when_symbol_missing_the_newest_bar():
    idx = _bdays(5)
    close = pd.DataFrame(
        {"AAA": [10.0, 11.0, 12.0, 13.0, np.nan], "BBB": [20.0, 20.0, 20.0, 20.0, 22.0]},
        index=idx,
    )
    out = D._tape_pcts_from_close_matrix(close, ("AAA", "BBB"))
    assert out["AAA"] is None  # not +8.3% from the prior session
    assert out["BBB"] == pytest.approx(10.0)


def test_tape_pct_none_for_unknown_or_single_bar_symbols():
    idx = _bdays(2)
    close = pd.DataFrame({"AAA": [np.nan, 10.0]}, index=idx)
    out = D._tape_pcts_from_close_matrix(close, ("AAA", "ZZZ"))
    assert out["AAA"] is None
    assert out["ZZZ"] is None
    assert D._tape_pcts_from_close_matrix(pd.DataFrame(), ("AAA",)) == {"AAA": None}
