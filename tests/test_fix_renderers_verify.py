"""Independent verification of the `renderers` engineer's AUDIT fixes.

Owned by the verifier. Does not modify any source file.
"""
import ast
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "modules" / "renderers.py"
SOURCE = SRC.read_text()
TREE = ast.parse(SOURCE)


def _pre_diamond_key_used_by_watchlist_rank_writer():
    """Return the dict key the watchlist-rank radar writer reads off pre_diamond_status."""
    for call in [n for n in ast.walk(TREE) if isinstance(n, ast.Call)]:
        if not (isinstance(call.func, ast.Name) and call.func.id == "radar_add_hit"):
            continue
        if not call.args or not isinstance(call.args[0], ast.Dict):
            continue
        payload = call.args[0]
        srcs = [
            v.value
            for k, v in zip(payload.keys, payload.values)
            if isinstance(k, ast.Constant) and k.value == "source" and isinstance(v, ast.Constant)
        ]
        if "scanner_watchlist_rank" not in srcs:
            continue
        for k, v in zip(payload.keys, payload.values):
            if isinstance(k, ast.Constant) and k.value == "pre_diamond":
                # bool((r.get(...) or {}).get(<KEY>, False))
                for inner in ast.walk(v):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "get"
                        and inner.args
                        and isinstance(inner.args[0], ast.Constant)
                        and inner.args[0].value != "pre_diamond_status"
                    ):
                        return inner.args[0].value
    return None


def test_watchlist_rank_writer_reads_a_key_that_actually_exists():
    """REGRESSION: the AUDIT #22 rewrite swapped a hardcoded True for a nonexistent key.

    `detect_pre_diamond` returns dicts keyed `is_pre_diamond` (options.py:1985/2039/2046),
    and the Tier-2 radar writer in the very same file reads `is_pre_diamond`. The
    watchlist-rank writer reads `"fired"`, which no producer in the repo ever sets, so
    every persisted watchlist-rank row now records pre_diamond=False unconditionally —
    the mirror image of the hardcoded True the audit flagged, and still contradictory
    with the Tier-2 rows for the same ticker.
    """
    key = _pre_diamond_key_used_by_watchlist_rank_writer()
    assert key is not None, "could not locate the watchlist-rank radar_add_hit payload"
    assert key == "is_pre_diamond", (
        f"watchlist-rank writer reads pre_diamond_status[{key!r}]; the producer emits "
        f"'is_pre_diamond' and the Tier-2 writer in this file reads 'is_pre_diamond'"
    )


def test_no_producer_in_the_repo_emits_a_fired_key():
    """Corroborates the above from the producer side."""
    opts = (Path(__file__).resolve().parents[1] / "modules" / "options.py").read_text()
    assert '"fired"' not in opts and "'fired'" not in opts


# ── Confirmations of the claims that DO hold ────────────────────────────────


def test_iv_rank_call_arity_is_three():
    for call in [n for n in ast.walk(TREE) if isinstance(n, ast.Call)]:
        if isinstance(call.func, ast.Name) and call.func.id == "compute_iv_rank_proxy":
            assert len(call.args) == 3
            break
    else:
        pytest.fail("compute_iv_rank_proxy call not found")


def test_compounding_helper_matches_the_audit_number():
    from modules.renderers import compound_cumulative_return_pct

    s = pd.Series([8.0] * 12 + [-20.0] * 4)
    assert compound_cumulative_return_pct(s).iloc[-1] == pytest.approx(3.14, abs=0.02)
    assert s.cumsum().iloc[-1] == 16.0  # the old, wrong number


def test_expected_value_refuses_the_fabricated_covered_call_inputs():
    from modules.renderers import expected_value_dollars

    # old code: max_loss = prem_100 * 3, pop = min(85, max(50, 100 - otm*5))
    assert expected_value_dollars(100.0, 0.0, 70.0) is None
    assert expected_value_dollars(100.0, None, 70.0) is None
    assert expected_value_dollars(100.0, 300.0, 70.0) == pytest.approx(-20.0)


def test_call_skew_is_not_painted_balanced():
    from modules.renderers import classify_vol_skew

    assert classify_vol_skew(-12.0)["label"] == "Heavy Call Skew"
    assert classify_vol_skew(-6.0)["label"] == "Elevated Call Skew"
    assert classify_vol_skew(None) is None
