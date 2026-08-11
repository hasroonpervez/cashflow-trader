"""Regression tests for the August 2026 audit fixes in ``modules/renderers.py``.

Covers findings #12 (IV-Rank arity), #19 (equity capital literal), #22 (Blue Diamond
relabelled as a ranker), #24 (fabricated expected value) and the four medium items
called out on the same file: the three inconsistent skew readouts, the cumsum equity
curve, the discarded ``journal_add_entry`` return, and the fictional auto-refresh timer.

Several checks are structural (AST / source scans) because the defects live inside
Streamlit render functions that cannot be invoked headlessly. They assert the exact
shape of the bug the audit documented, so a re-introduction fails the suite.
"""
from __future__ import annotations

import ast
import inspect
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules import renderers as R
from modules.data import compute_iv_rank_proxy
from modules.options import calc_ev

RENDERERS_PATH = Path(R.__file__)
SOURCE = RENDERERS_PATH.read_text()
TREE = ast.parse(SOURCE)


# Copy assertions must read what the app *renders*, not what the comments explain
# the fix comments quote the old wording verbatim, so a raw-text scan would match them.
RENDERED_TEXT = "\n".join(
    n.value for n in ast.walk(TREE) if isinstance(n, ast.Constant) and isinstance(n.value, str)
)


def _calls_named(name: str):
    """Every ast.Call in renderers.py whose callee is the bare name ``name``."""
    return [
        n
        for n in ast.walk(TREE)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
    ]


# ─────────────────────────── #12 IV-Rank gate arity ───────────────────────────


def test_iv_rank_proxy_requires_three_positional_args():
    """The callee's real contract: three required positionals, no defaults."""
    params = list(inspect.signature(compute_iv_rank_proxy).parameters.values())
    required = [p for p in params if p.default is inspect.Parameter.empty]
    assert [p.name for p in required] == ["sym", "spot", "ref_iv_pct"]


def test_renderers_calls_iv_rank_proxy_with_correct_arity():
    """AUDIT #12: the two-arg call raised TypeError into a bare except that pinned
    the rank at 50.0 forever, making the sub-30 desk warning unreachable."""
    calls = _calls_named("compute_iv_rank_proxy")
    assert calls, "expected renderers.py to still perform the IVR environment check"
    for call in calls:
        assert not call.keywords, "IVR proxy is called positionally in this file"
        assert len(call.args) == 3, (
            f"compute_iv_rank_proxy called with {len(call.args)} args at "
            f"renderers.py:{call.lineno}, the function needs three"
        )


def test_iv_rank_check_does_not_default_to_fifty():
    """A missing reference IV must suppress the card, not fabricate a neutral 50."""
    assert "_ivr_val = 50.0" not in SOURCE
    assert "_ivr_val = None" in SOURCE
    # The copy no longer claims a 52-week rank; the proxy is a term-structure read.
    assert "cheap relative to the past year" not in RENDERED_TEXT


# ───────────────────────── #19 equity capital literal ─────────────────────────


def test_renderers_has_no_hardcoded_equity_capital():
    """AUDIT #19 lives in render_pre_tabs.py, but renderers.py must not grow its own
    copy: capital is bound from DeskLocals, never from a 10000 literal."""
    offenders = [
        (i + 1, line.strip())
        for i, line in enumerate(SOURCE.splitlines())
        if "equity_capital" in line and re.search(r"10_?000", line)
    ]
    assert not offenders, f"hard-coded capital literal in renderers.py: {offenders}"
    assert SOURCE.count("equity_capital = d.equity_capital") >= 1


# ──────────────────── #22 Blue Diamond is a ranker, not a buy ────────────────────


def test_blue_diamond_screen_is_not_badged_as_a_conviction_buy():
    """AUDIT #22: RESEARCH_UPGRADE.md records Blue confluence *as an entry* as regime
    beta: t=2.98 full sample, negative in the second half of all 12 configs. The
    screen survives as a watchlist ranker; the buy framing does not."""
    assert "💎 CONVICTION: Blue Diamond" not in RENDERED_TEXT
    assert '"signal": "💎 CONVICTION"' not in SOURCE
    assert "WATCHLIST RANK" in RENDERED_TEXT
    assert '"source": "scanner_watchlist_rank"' in SOURCE


def test_blue_diamond_ui_cites_the_repo_research():
    """The honest relabel must name the evidence, not just soften the wording."""
    assert "RESEARCH_UPGRADE.md" in RENDERED_TEXT
    assert "negative in the second half" in RENDERED_TEXT
    assert "This is a ranking, not an entry." in RENDERED_TEXT
    # The old unsupported claim under the Blue Diamond suggestion block is gone.
    assert "Historically, similar setups have a strong track record" not in RENDERED_TEXT


# ─────────────────────────── #24 expected value ───────────────────────────


def test_expected_value_matches_calc_ev_when_inputs_are_real():
    assert R.expected_value_dollars(100.0, 400.0, 80.0) == pytest.approx(calc_ev(100.0, 400.0, 80.0))
    assert R.expected_value_dollars(100.0, 400.0, 80.0) == pytest.approx(100 * 0.8 - 400 * 0.2)


@pytest.mark.parametrize(
    "credit,max_loss,pop",
    [
        (100.0, None, 70.0),      # covered call: no contractual max loss
        (100.0, 0.0, 70.0),       # zero downside is not a real downside
        (100.0, -50.0, 70.0),     # nonsense downside
        (100.0, 400.0, None),     # no modelled probability
        (100.0, 400.0, 140.0),    # probability out of range
        (100.0, 400.0, -1.0),
        (100.0, float("nan"), 70.0),
        (None, 400.0, 70.0),
    ],
)
def test_expected_value_returns_none_rather_than_a_fabricated_number(credit, max_loss, pop):
    """AUDIT #24: an unsourceable EV must be Optional-None so the UI can print 'n/a'."""
    assert R.expected_value_dollars(credit, max_loss, pop) is None


def test_fabricated_covered_call_pop_and_max_loss_are_gone():
    """The exact fabrication: pop = 100 − 5·OTM% clamped to [50, 85], max loss = 3×premium.
    Together they reduced EV to P·(4·pop − 3), zero exactly at otm_pct == 5."""
    assert 'min(85, max(50, 100 - b0["otm_pct"] * 5))' not in SOURCE
    assert 'b0["prem_100"] * 3' not in SOURCE
    assert "Positive means edge. Negative means walk away." not in RENDERED_TEXT


def test_defined_risk_spread_still_prints_a_number():
    """The put spread has a contractual max loss and a modelled POP, it must survive."""
    ev = R.expected_value_dollars(150.0, 350.0, 75.0)
    assert ev is not None and ev == pytest.approx(150 * 0.75 - 350 * 0.25)


# ─────────────────── medium: one skew verdict, not three ───────────────────


@pytest.mark.parametrize(
    "skew,label",
    [
        (25.0, "Heavy Put Skew"),
        (10.1, "Heavy Put Skew"),
        (5.0, "Elevated Put Skew"),
        (3.1, "Elevated Put Skew"),
        (0.0, "Balanced Skew"),
        (-3.0, "Balanced Skew"),
        (-4.0, "Elevated Call Skew"),
        (-11.0, "Heavy Call Skew"),
    ],
)
def test_skew_classification_tiers(skew, label):
    verdict = R.classify_vol_skew(skew)
    assert verdict is not None
    assert verdict["label"] == label
    assert verdict["skew"] == pytest.approx(skew)


def test_call_skew_is_never_reported_as_balanced():
    """The Greeks-row tile used a one-sided `> 10 / > 5` test, so every negative skew
: however extreme the call bid: rendered green 'Balanced'."""
    for skew in (-4.0, -12.0, -40.0):
        assert R.classify_vol_skew(skew)["label"] != "Balanced Skew"
        assert "call" in R.classify_vol_skew(skew)["label"].lower()


@pytest.mark.parametrize("bad", [None, "", float("nan"), float("inf"), "abc"])
def test_skew_classification_is_optional_not_balanced(bad):
    assert R.classify_vol_skew(bad) is None


def test_single_skew_verdict_drives_every_readout():
    """AUDIT (medium): three verdicts on one tab reconciled to one classifier."""
    assert len(_calls_named("classify_vol_skew")) == 1, "classify once, render three times"
    # The median-ratio regime badge (1.25/1.08/0.85) is no longer rendered as a
    # competing headline verdict.
    assert not _calls_named("calc_skew_regime")
    # And the tile's old one-sided thresholds are gone.
    assert 'sm = "Institutions hedging heavily"' not in SOURCE


# ─────────────────── medium: equity curve must compound ───────────────────


def test_cumulative_return_compounds_not_sums():
    """AUDIT (medium): 12×(+8%) then 4×(−20%) summed to +16%; the truth is +3.1%."""
    rets = [8.0] * 12 + [-20.0] * 4
    curve = R.compound_cumulative_return_pct(rets)
    expected = ((1.08 ** 12) * (0.8 ** 4) - 1.0) * 100.0
    assert curve.iloc[-1] == pytest.approx(expected, abs=1e-9)
    assert curve.iloc[-1] == pytest.approx(3.1, abs=0.1)
    assert curve.iloc[-1] != pytest.approx(float(np.sum(rets)))


def test_compounding_understates_nothing_on_drawdowns():
    """A −50% then +50% round trip is −25%, not 0%."""
    curve = R.compound_cumulative_return_pct([-50.0, 50.0])
    assert curve.iloc[-1] == pytest.approx(-25.0)


def test_compound_curve_preserves_index_and_length():
    s = pd.Series([1.0, 2.0, 3.0], index=pd.Index(["a", "b", "c"]))
    curve = R.compound_cumulative_return_pct(s)
    assert list(curve.index) == ["a", "b", "c"]
    assert len(curve) == 3
    assert curve.iloc[0] == pytest.approx(1.0)


def test_compound_curve_handles_empty_input():
    curve = R.compound_cumulative_return_pct(pd.Series(dtype=float))
    assert curve.empty


def test_compound_curve_skips_nan_like_cumsum_did():
    curve = R.compound_cumulative_return_pct([10.0, float("nan"), 10.0])
    assert math.isnan(curve.iloc[1])
    assert curve.iloc[2] == pytest.approx(21.0)


def test_equity_curve_call_site_uses_the_compounding_helper():
    assert 'br["ret_pct"].cumsum()' not in SOURCE
    assert 'compound_cumulative_return_pct(br["ret_pct"])' in SOURCE
    assert 'title_text="Cumulative return (%)"' not in SOURCE


# ─────────────── medium: journal write failures must be surfaced ───────────────


def test_journal_add_entry_return_is_never_discarded():
    """AUDIT (medium): on a read-only host the ledger row appeared and nothing reached
    trade_journal.json. The close path already handled this; both Track Trade sites
    must too: the return value may not be a bare expression statement."""
    discarded = [
        node.lineno
        for node in ast.walk(TREE)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "journal_add_entry"
    ]
    assert not discarded, f"journal_add_entry result discarded at renderers.py:{discarded}"


def test_journal_add_entry_failures_are_reported_to_the_user():
    calls = _calls_named("journal_add_entry")
    assert len(calls) == 2, "expected the CC and CSP Track Trade sites"
    assert SOURCE.count("_jrnl_ok = journal_add_entry(") == 2
    assert SOURCE.count("if _jrnl_ok:") == 2
    assert SOURCE.count("Tracked in this session only") == 2


# ─────────────── medium: no fictional auto-refresh timer in the copy ───────────────


def test_auto_refresh_copy_does_not_claim_a_timer():
    """AUDIT (medium): no run_every and no st_autorefresh exists anywhere in the repo,
    so 'Auto refresh every 300s · next in Ns' described a timer that does not run."""
    assert "Auto refresh every" not in RENDERED_TEXT
    assert "next in {_remaining}s" not in RENDERED_TEXT
    assert "there is no background timer" in RENDERED_TEXT


def test_no_autorefresh_mechanism_was_silently_assumed():
    assert "st_autorefresh" not in RENDERED_TEXT and not [n for n in ast.walk(TREE) if isinstance(n, ast.Name) and "autorefresh" in n.id.lower()]
    assert not [k for n in ast.walk(TREE) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "run_every"]
