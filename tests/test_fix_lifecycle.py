"""Regression tests for the August-2026 audit fixes in config / pages / ui_helpers /
render_pre_tabs / validated_signals / signal_desk / app.

Every test here pins a behaviour that was provably wrong before the fix, and names the
audit finding it guards.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Finding #3: journal realized P&L used expiry intrinsic against an option price
# ─────────────────────────────────────────────────────────────────────────────

_CSP = {
    "ticker": "PLTR",
    "strike": 30,
    "premium_100": 350,
    "option_type": "put",
    "contracts": 1,
    "status": "open",
}


def test_buyback_close_of_a_csp_is_a_profit_not_a_catastrophe():
    """The exact audit scenario: strike-30 CSP bought back at $1.20/share.

    Old formula recorded -$2,530 (it read 1.20 as the *underlying* at expiry and
    settled 28.80 of intrinsic). Truth: +$230 of the $350 credit kept.
    """
    from modules.config import realized_pnl_for_close

    assert realized_pnl_for_close(_CSP, 1.20) == pytest.approx(230.0)


def test_expiry_basis_still_available_and_still_settles_intrinsic():
    from modules.config import realized_pnl_for_close, CLOSE_BASIS_EXPIRY

    # Same inputs, but now explicitly declared as "underlying at expiry".
    assert realized_pnl_for_close(_CSP, 1.20, CLOSE_BASIS_EXPIRY) == pytest.approx(-2530.0)
    # Expired worthless: keep the whole credit.
    assert realized_pnl_for_close(_CSP, 35.0, CLOSE_BASIS_EXPIRY) == pytest.approx(350.0)


def test_buyback_scales_with_contracts_and_handles_calls_identically():
    from modules.config import realized_pnl_for_close

    three = {**_CSP, "contracts": 3}
    assert realized_pnl_for_close(three, 1.20) == pytest.approx(690.0)
    # A short call bought back is the same credit-minus-debit arithmetic.
    call = {**_CSP, "option_type": "call"}
    assert realized_pnl_for_close(call, 1.20) == pytest.approx(230.0)


def test_buyback_above_credit_is_a_loss():
    from modules.config import realized_pnl_for_close

    # Paid $6.00/share to close a $3.50/share credit.
    assert realized_pnl_for_close(_CSP, 6.00) == pytest.approx(-250.0)


def test_missing_premium_returns_none_not_a_fake_zero():
    from modules.config import realized_pnl_for_close

    assert realized_pnl_for_close({"contracts": 1}, 1.20) is None
    assert realized_pnl_for_close({"premium_100": None}, 1.20) is None


def test_unknown_close_basis_is_rejected_loudly():
    from modules.config import realized_pnl_for_close

    with pytest.raises(ValueError):
        realized_pnl_for_close(_CSP, 1.20, "guess")


def test_journal_close_records_the_convention_it_used(tmp_path, monkeypatch):
    import modules.config as cfg

    monkeypatch.setattr(cfg, "JOURNAL_PATH", tmp_path / "trade_journal.json")
    assert cfg.journal_add_entry(dict(_CSP))

    assert cfg.journal_close_trade(0, 1.20)
    row = cfg.load_journal()[0]
    assert row["status"] == "closed"
    assert row["close_basis"] == cfg.CLOSE_BASIS_BUYBACK
    assert row["realized_pnl"] == pytest.approx(230.0)


def test_journal_close_honours_an_explicit_expiry_basis(tmp_path, monkeypatch):
    import modules.config as cfg

    monkeypatch.setattr(cfg, "JOURNAL_PATH", tmp_path / "trade_journal.json")
    cfg.journal_add_entry(dict(_CSP))

    assert cfg.journal_close_trade(0, 28.00, basis=cfg.CLOSE_BASIS_EXPIRY)
    row = cfg.load_journal()[0]
    assert row["close_basis"] == cfg.CLOSE_BASIS_EXPIRY
    # $2.00 of intrinsic against $3.50 of credit.
    assert row["realized_pnl"] == pytest.approx(150.0)


def test_journal_close_with_bad_basis_writes_nothing(tmp_path, monkeypatch):
    import modules.config as cfg

    monkeypatch.setattr(cfg, "JOURNAL_PATH", tmp_path / "trade_journal.json")
    cfg.journal_add_entry(dict(_CSP))

    assert cfg.journal_close_trade(0, 1.20, basis="nonsense") is False
    assert cfg.load_journal()[0]["status"] == "open"


def test_unknowable_pnl_leaves_the_key_absent_rather_than_reporting_break_even(tmp_path, monkeypatch):
    """`renderers` reads `.get('realized_pnl', 0)`; an absent key must mean "unknown"."""
    import modules.config as cfg

    monkeypatch.setattr(cfg, "JOURNAL_PATH", tmp_path / "trade_journal.json")
    cfg.journal_add_entry({"ticker": "X", "status": "open"})  # no premium_100

    assert cfg.journal_close_trade(0, 1.20)
    row = cfg.load_journal()[0]
    assert "realized_pnl" not in row
    assert row["realized_pnl_unavailable"]


# ─────────────────────────────────────────────────────────────────────────────
# Finding #20: ConfigTransaction.flush() wrote a construction-time snapshot
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def config_at(tmp_path, monkeypatch):
    import modules.config as cfg

    path = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_PATH", path)
    monkeypatch.setattr(cfg, "_streamlit_secrets_flat", lambda: {})
    return cfg, path


def test_flush_does_not_revert_a_key_another_writer_changed_on_disk(config_at):
    cfg, path = config_at
    cfg.save_config({**cfg.DEFAULT_CONFIG, "scanner_mode": "📈 Options Yield", "watchlist": "AAA"})

    tx = cfg.ConfigTransaction()  # snapshots the config as it stands now
    # A second writer (the scanner-mode toggle / the overlay on_change callback) commits
    # a different key straight to disk while the transaction is open.
    cfg.save_config({**cfg.load_config(), "scanner_mode": "🎯 Equity Radar"})

    tx.update(watchlist="BBB")
    assert tx.flush()

    on_disk = json.loads(path.read_text())
    assert on_disk["watchlist"] == "BBB", "the transaction's own mutation must land"
    assert on_disk["scanner_mode"] == "🎯 Equity Radar", "the other writer must not be reverted"


def test_flush_writes_nothing_when_there_are_no_mutations(config_at):
    cfg, path = config_at
    cfg.save_config({**cfg.DEFAULT_CONFIG, "watchlist": "AAA"})
    mtime = path.stat().st_mtime_ns

    assert cfg.ConfigTransaction().flush()
    assert path.stat().st_mtime_ns == mtime


# ─────────────────────────────────────────────────────────────────────────────
# Finding #21: st.secrets scalars persisted into the git-tracked config.json
# ─────────────────────────────────────────────────────────────────────────────

def test_secrets_are_usable_in_memory_but_never_written_to_disk(tmp_path, monkeypatch):
    import modules.config as cfg

    path = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_PATH", path)
    monkeypatch.setattr(
        cfg,
        "_streamlit_secrets_flat",
        lambda: {"discord_webhook_url": "https://hook", "alpha_vantage_key": "AV123", "watchlist": "AAA,BBB"},
    )

    loaded = cfg.load_config()
    assert loaded["discord_webhook_url"] == "https://hook", "secrets stay usable in memory"
    assert loaded["watchlist"] == "AAA,BBB"

    # The read-modify-write cycle that used to leak them.
    assert cfg.save_config(loaded)
    on_disk = json.loads(path.read_text())
    assert "discord_webhook_url" not in on_disk
    assert "alpha_vantage_key" not in on_disk
    assert on_disk["watchlist"] == "AAA,BBB", "ordinary settings still persist"


def test_credential_shaped_keys_are_stripped_even_without_a_secrets_file(config_at):
    cfg, path = config_at

    assert cfg.save_config({**cfg.DEFAULT_CONFIG, "discord_webhook_url": "https://hook", "api_token": "t"})
    on_disk = json.loads(path.read_text())
    assert "discord_webhook_url" not in on_disk
    assert "api_token" not in on_disk


def test_strip_secrets_is_pure_and_keeps_ordinary_settings(config_at):
    cfg, _ = config_at

    out = cfg.strip_secrets({"watchlist": "AAA", "mini_mode": True, "openai_api_key": "sk-x"})
    assert out == {"watchlist": "AAA", "mini_mode": True}


# ─────────────────────────────────────────────────────────────────────────────
# Finding #7: a previous ticker's OpEx pin survived into the next ticker's render
# ─────────────────────────────────────────────────────────────────────────────

def _synth_daily(n=300, start=100.0):
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = pd.Series(start + np.linspace(0, 20, n), index=idx)
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(n, 1_000_000, dtype="int64"),
        },
        index=idx,
    )


def test_absent_options_chain_clears_the_opex_pin_instead_of_keeping_the_last_ticker(monkeypatch):
    """A $12 stock must never inherit NVDA's $178 pin (charted, then written to the ledger)."""
    import streamlit as st

    import modules.pages as pages
    from modules.data import DeskMarketSnapshot, GlobalMarketSnapshot

    daily = _synth_daily()
    weekly = daily.resample("W").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna()

    snap = GlobalMarketSnapshot(
        DeskMarketSnapshot({}, {"VIX": {"price": None}, "10Y Yield": {"price": None}}, None),
        pd.DataFrame(),
        daily,
        weekly,
        daily.iloc[-30:],
        None,
        ("TINY",),
        (),
        {},
        {},
    )

    monkeypatch.setattr(pages, "fetch_earnings_date", lambda *a, **k: None)

    st.session_state["_cf_opex_pin"] = 178.0          # left over from the previous ticker
    st.session_state["_cf_opex_pin_map"] = {"NVDA": 178.0}

    ctx = pages.build_context(
        "TINY",
        {"use_quant_models": False},
        global_snapshot=snap,
        defer_headlines_earnings=True,
        defer_options_fetch=True,          # exactly the first-pass case that leaked
    )

    assert ctx is not None
    assert st.session_state["_cf_opex_pin"] is None
    # The ticker-keyed map is the authoritative source and simply has no entry for TINY.
    assert (st.session_state.get("_cf_opex_pin_map") or {}).get("TINY") is None


# ─────────────────────────────────────────────────────────────────────────────
# Sparkline: an empty series used to render a confident rising line
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_series_draws_nothing_at_all():
    from modules.ui_helpers import _glance_sparkline_svg

    assert _glance_sparkline_svg([]) == ""
    assert _glance_sparkline_svg(pd.Series(dtype="float64")) == ""
    assert _glance_sparkline_svg([None, None]) == ""          # VIX feed down
    assert _glance_sparkline_svg([np.nan, np.inf]) == ""


def test_a_single_observation_is_a_flat_line_not_a_slope():
    from modules.ui_helpers import _glance_sparkline_svg

    svg = _glance_sparkline_svg([20.0])
    ys = [float(p.split(",")[1]) for p in svg.split('d="M ')[1].split('"')[0].split(" L ")]
    assert len(set(round(y, 3) for y in ys)) == 1, "a lone value must not imply direction"


def test_a_real_series_still_draws():
    from modules.ui_helpers import _glance_sparkline_svg

    assert "<path" in _glance_sparkline_svg([1.0, 2.0, 1.5])


def test_glance_card_labels_a_missing_series_instead_of_faking_one():
    from modules.ui_helpers import _glance_metric_card

    html = _glance_metric_card("MARKET MOOD (VIX)", "<div>-</div>", "<div>n/a</div>", [], "#fff")
    assert "NO SERIES" in html
    assert "<path" not in html


# ─────────────────────────────────────────────────────────────────────────────
# Rolling edge capture: no timer, re-scanned the whole watchlist on every rerun
# ─────────────────────────────────────────────────────────────────────────────

def test_edge_scan_is_not_due_again_immediately_after_a_scan():
    from modules.ui_helpers import edge_scan_due

    key = (("AAA", "BBB"), True, 18.0, "📈 Options Yield")
    assert edge_scan_due(None, 1000.0, key, None) is True            # first ever
    assert edge_scan_due(1000.0, 1000.5, key, key) is False          # a widget click
    assert edge_scan_due(1000.0, 1089.0, key, key) is False          # still inside 90s
    assert edge_scan_due(1000.0, 1090.0, key, key) is True           # interval elapsed


def test_edge_scan_reruns_immediately_when_the_inputs_change():
    from modules.ui_helpers import edge_scan_due

    old = (("AAA",), True, 18.0, "📈 Options Yield")
    new = (("AAA", "CCC"), True, 18.0, "📈 Options Yield")
    assert edge_scan_due(1000.0, 1000.1, new, old) is True


def test_rolling_edge_capture_is_actually_a_fragment_on_a_timer():
    from modules.ui_helpers import _fragment_rolling_edge_capture, _EDGE_SCAN_INTERVAL_S

    assert _EDGE_SCAN_INTERVAL_S == 90.0, "the caption promises about 90 seconds"
    # `st.fragment` wraps the callable; a bare function has no `__wrapped__`. The name
    # claimed "fragment" for months while the function was an ordinary call.
    inner = getattr(_fragment_rolling_edge_capture, "__wrapped__", None)
    assert inner is not None and inner is not _fragment_rolling_edge_capture


# ─────────────────────────────────────────────────────────────────────────────
# Global bundle timeout: both arms of the reuse ternary were identical
# ─────────────────────────────────────────────────────────────────────────────

def test_a_snapshot_from_a_different_watchlist_is_not_reused_on_timeout():
    from modules.render_pre_tabs import _reusable_snapshot

    prev = object()
    key_a = (("AAA", "BBB"), "AAA", "full")
    key_b = (("CCC",), "CCC", "full")

    assert _reusable_snapshot(prev, key_a, key_a) is prev
    assert _reusable_snapshot(prev, key_a, key_b) is None
    assert _reusable_snapshot(None, key_a, key_a) is None


# ─────────────────────────────────────────────────────────────────────────────
# Finding #19: equity_capital hard-coded to 10000 and clobbering the saved value
# ─────────────────────────────────────────────────────────────────────────────

def test_saved_capital_is_read_from_config_not_a_literal():
    from modules.config import DEFAULT_CONFIG
    from modules.render_pre_tabs import saved_equity_capital

    assert saved_equity_capital({"equity_capital": 100000}) == 100000
    assert saved_equity_capital({}) == DEFAULT_CONFIG["equity_capital"]
    assert saved_equity_capital({"equity_capital": "junk"}) == DEFAULT_CONFIG["equity_capital"]
    assert saved_equity_capital({"equity_capital": 0}) == DEFAULT_CONFIG["equity_capital"]


def test_saved_capital_survives_a_config_transaction_round_trip(config_at):
    """Reproduces the loss: a hemisphere switch drops the widget, then flush() rewrites disk."""
    cfg, path = config_at
    cfg.save_config({**cfg.DEFAULT_CONFIG, "equity_capital": 100000})

    from modules.render_pre_tabs import saved_equity_capital

    tx = cfg.ConfigTransaction()
    # No `sb_equity_capital` in session: the fallback is now the persisted value.
    tx.update(equity_capital=saved_equity_capital(tx.current))
    assert tx.flush()

    assert json.loads(path.read_text())["equity_capital"] == 100000


# ─────────────────────────────────────────────────────────────────────────────
# mechanical_exit: inclusive entry-bar slice, and a stop that latched forever
# ─────────────────────────────────────────────────────────────────────────────

def _exit_frame(breach_at=None, n=60, breach_low=90.0):
    """Flat 99-101 tape (ATR14 = 2.0, so a 2.5x stop from 100 sits at 95.0), with an
    optional single bar whose low punches through."""
    lows = np.full(n, 99.0)
    if breach_at is not None:
        lows[breach_at] = breach_low
    return pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": np.full(n, 101.0),
            "low": lows,
            "close": np.full(n, 100.0),
        }
    )


def test_the_entry_bar_low_cannot_stop_you_out_before_you_are_in():
    from modules.validated_signals import mechanical_exit

    # The entry bar itself printed below the stop: before the position existed.
    out = mechanical_exit(
        _exit_frame(breach_at=30, n=40), entry_price=100.0, entry_index=30, max_hold_sessions=15
    )

    assert out["directive"] == "hold"


def test_a_stop_after_the_time_exit_does_not_retroactively_close_the_trade():
    from modules.validated_signals import mechanical_exit

    # Breach 20 sessions after entry: the 15-session time exit already closed it.
    out = mechanical_exit(_exit_frame(breach_at=50), entry_price=100.0, entry_index=30, max_hold_sessions=15)

    assert out["directive"] == "exit_time"
    assert out["held_sessions"] == 15
    assert out["exit_index"] == 45


def test_a_stop_inside_the_hold_window_reports_the_bar_it_happened_on():
    from modules.validated_signals import mechanical_exit

    out = mechanical_exit(_exit_frame(breach_at=35), entry_price=100.0, entry_index=30, max_hold_sessions=15)

    assert out["directive"] == "exit_stop"
    assert out["exit_index"] == 35
    assert out["held_sessions"] == 5
    assert out["stop"] == pytest.approx(95.0)


def test_an_untouched_position_inside_the_window_still_holds():
    from modules.validated_signals import mechanical_exit

    out = mechanical_exit(_exit_frame(n=40), entry_price=100.0, entry_index=30, max_hold_sessions=15)

    assert out["directive"] == "hold"
    assert out["held_sessions"] == 9


# ─────────────────────────────────────────────────────────────────────────────
# Consensus score was drawn 0-100 while structurally confined to ~7-96
# ─────────────────────────────────────────────────────────────────────────────

def test_the_raw_consensus_sum_really_cannot_span_zero_to_one_hundred():
    from modules.signal_desk import CONSENSUS_RAW_BOUNDS

    lo, hi = CONSENSUS_RAW_BOUNDS
    assert lo == pytest.approx(7.12, abs=0.01), "structure+weekly floors are unreachable-by-zero"
    assert hi == pytest.approx(95.58, abs=0.01)


def test_the_displayed_score_now_actually_reaches_both_ends():
    from modules.signal_desk import CONSENSUS_RAW_BOUNDS, scale_consensus_score

    lo, hi = CONSENSUS_RAW_BOUNDS
    assert scale_consensus_score(lo) == pytest.approx(0.0)
    assert scale_consensus_score(hi) == pytest.approx(100.0)
    # Clamped, never out of range.
    assert scale_consensus_score(-50.0) == 0.0
    assert scale_consensus_score(500.0) == 100.0


def test_scaling_is_monotonic():
    from modules.signal_desk import scale_consensus_score

    xs = [10.0, 25.0, 40.0, 62.0, 80.0, 95.0]
    ys = [scale_consensus_score(x) for x in xs]
    assert ys == sorted(ys)
    assert len(set(ys)) == len(ys)


def test_band_cutoffs_are_published_on_the_same_scale_as_the_score():
    """The 40/62 cutoffs were tuned on the raw sum; the UI must not compare them to a
    number drawn on a different scale."""
    from modules.signal_desk import (
        CONSENSUS_BAND_CUTOFFS,
        scale_consensus_score,
        _CONSENSUS_RAW_CUT_HIGH_RISK,
        _CONSENSUS_RAW_CUT_CONVICTION,
    )

    lo_cut, hi_cut = CONSENSUS_BAND_CUTOFFS
    assert lo_cut == pytest.approx(scale_consensus_score(_CONSENSUS_RAW_CUT_HIGH_RISK))
    assert hi_cut == pytest.approx(scale_consensus_score(_CONSENSUS_RAW_CUT_CONVICTION))
    assert 0.0 < lo_cut < hi_cut < 100.0


def test_consensus_exposes_the_raw_sum_next_to_the_scaled_score():
    from types import SimpleNamespace

    from modules.signal_desk import compute_desk_consensus, scale_consensus_score

    df = _synth_daily(n=120)
    ctx = SimpleNamespace(
        ticker="TEST",
        qs=55.0,
        cp_score=5,
        cp_max=9,
        fg=50.0,
        struct="BULLISH",
        wk_label="BULLISH",
        macd_bull=True,
        obv_up=True,
        price=float(df["Close"].iloc[-1]),
        gold_zone_price=float(df["Close"].iloc[-1]) * 0.98,
        rsi_v=55.0,
        chg_pct=1.0,
    )
    c = compute_desk_consensus(ctx, df)

    assert 0.0 <= c["score"] <= 100.0
    assert c["score"] == pytest.approx(scale_consensus_score(c["score_raw"]))
    assert c["score_raw_bounds"][0] < c["score_raw"] < c["score_raw_bounds"][1]


def test_banding_is_decided_on_the_raw_scale_so_verdicts_are_unchanged():
    """A raw sum of 62.0 was 'conviction' before the rescale and must stay so."""
    from modules.signal_desk import CONSENSUS_BAND_CUTOFFS, scale_consensus_score

    _lo_cut, hi_cut = CONSENSUS_BAND_CUTOFFS
    assert scale_consensus_score(62.0) >= hi_cut
    assert scale_consensus_score(61.9) < hi_cut


# ─────────────────────────────────────────────────────────────────────────────
# app.py, the deferred first pass had no banner and no rerun
# ─────────────────────────────────────────────────────────────────────────────

def test_deferred_first_pass_warns_and_schedules_a_rerun():
    """Source-level guard: the two things the deferred branch was missing."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(src.read_text())

    branches = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.Name)
        and n.test.id == "_defer_options_fetch"
    ]
    assert len(branches) == 2, "expect a banner branch and a rerun branch"

    calls = {
        node.func.attr
        for b in branches
        for node in ast.walk(b)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "rerun" in calls, "the partial pass must hydrate itself, not wait for a stray click"
    assert calls & {"info", "warning"}, "the partial pass must be labelled on screen"
