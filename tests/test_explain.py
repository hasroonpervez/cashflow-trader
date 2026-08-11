"""Tests for modules/explain.py — the shared progressive-disclosure toolkit.

Two jobs:
  1. Guard the TERMS registry: every entry fully populated, keys consistent,
     no duplicate labels or aliases, glosses short enough to fit a tooltip.
  2. Cover the pure helpers (lookup, tooltip, tone, formatters) with
     hand-checked expected values.

Everything here runs WITHOUT a Streamlit runtime — that is the point of the
module's import discipline, so this file asserts it explicitly.

Run:  python -m pytest tests/test_explain.py -q
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules import explain
from modules.explain import (
    TERMS,
    TONE_GLYPH,
    TONES,
    Term,
    all_keys,
    check_registry,
    compact,
    get,
    has,
    lookup,
    missing_terms,
    money,
    normalize_key,
    pct,
    ratio,
    require,
    score,
    search,
    signed,
    tone_label,
    tooltip,
    verdict_text,
)

MIN_TERMS = 25


# ═══════════════════════════════════════════════════════════════════════
#  Registry integrity
# ═══════════════════════════════════════════════════════════════════════

def test_registry_is_healthy():
    # The module's own self-check must report zero defects.
    assert check_registry() == []


def test_registry_has_enough_terms():
    assert len(TERMS) >= MIN_TERMS, f"only {len(TERMS)} terms registered"


def test_every_key_is_lowercase_snake_case():
    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    bad = [k for k in TERMS if not pattern.match(k)]
    assert bad == [], f"non-snake_case keys: {bad}"


def test_every_field_is_a_non_empty_string():
    for key, t in TERMS.items():
        for field in ("short", "plain", "detail", "formula", "label"):
            val = getattr(t, field)
            assert isinstance(val, str), f"{key}.{field} is {type(val).__name__}"
            assert val.strip(), f"{key}.{field} is empty"


def test_short_gloss_fits_a_tooltip():
    # "3-6 word gloss" — allow a little slack, but nothing sentence-length.
    for key, t in TERMS.items():
        n = len(t.short.split())
        assert 2 <= n <= 8, f"{key}.short is {n} words: {t.short!r}"


def test_short_gloss_is_not_a_sentence():
    for key, t in TERMS.items():
        assert not t.short.endswith("."), f"{key}.short should not end with a period"


def test_plain_is_one_complete_sentence_a_normal_person_can_read():
    for key, t in TERMS.items():
        assert t.plain.strip().endswith((".", "!", "?")), f"{key}.plain is not a sentence"
        # One idea per sentence: at most one full stop that is not an abbreviation.
        assert t.plain.count(". ") <= 1, f"{key}.plain packs in more than one sentence"


def test_detail_adds_depth_beyond_plain():
    for key, t in TERMS.items():
        assert len(t.detail) > len(t.plain), f"{key}.detail adds nothing over .plain"
        assert len(t.detail) >= 120, f"{key}.detail is too thin to be the real explanation"


def test_formula_cites_the_implementation():
    # Every formula must point at the module/function it was read from, so a
    # future code change can be traced back to the definition it invalidates.
    for key, t in TERMS.items():
        assert "modules/" in t.formula, f"{key}.formula does not cite a source file"


def test_labels_are_unique():
    labels = [normalize_key(t.label) for t in TERMS.values()]
    dupes = {x for x in labels if labels.count(x) > 1}
    assert dupes == set(), f"duplicate labels: {dupes}"


def test_aliases_are_unique_across_terms():
    owner = {}
    for key, t in TERMS.items():
        for alias in t.aliases:
            n = normalize_key(alias)
            assert n, f"{key} has an empty alias"
            assert n not in owner or owner[n] == key, (
                f"alias {alias!r} claimed by both {owner.get(n)!r} and {key!r}"
            )
            owner[n] = key


def test_no_term_explains_itself_with_its_own_acronym():
    # "GEX means gamma exposure" is not an explanation. The plain sentence
    # must not simply restate the label.
    for key, t in TERMS.items():
        assert normalize_key(t.plain) != normalize_key(t.label), key


def test_core_jargon_from_the_app_is_covered():
    # These strings all appear in the live UI; every one must resolve.
    required = [
        "gex", "vanna", "charm", "wilson", "hmm_regime", "rs_spy", "iv_rank",
        "theta", "dte", "delta", "gamma", "vega", "theta_gamma_ratio",
        "gold_zone", "confluence", "edge_score", "hurst", "poc", "hvn",
        "expected_move", "mc_pop", "kelly", "opex_pin", "gamma_flip",
        "shadow_move", "whale_zscore", "skew_regime", "var_95", "ffd",
    ]
    assert missing_terms(required) == ()


def test_ugly_ui_spellings_resolve_through_aliases():
    # The exact strings that appear in renderers.py / ui_helpers.py today.
    cases = {
        "Θ/Γ": "theta_gamma_ratio",
        "MC PoP": "mc_pop",
        "Quant Edge": "edge_score",
        "QE": "edge_score",
        "IV rank": "iv_rank",
        "Δ": "delta",
        "bbw_pctile": "bbw_percentile",
        "dark pool proxy": "whale_zscore",
        "coil_active": "pre_diamond",
        "rs_spy_ratio": "rs_spy",
        "Gold Zone": "gold_zone",
        "10x Potential": "tenx_score",
    }
    for spelling, expected in cases.items():
        t = lookup(spelling)
        assert t is not None, f"{spelling!r} does not resolve"
        assert t is TERMS[expected], f"{spelling!r} resolved to {t.label!r}, wanted {expected!r}"


# ═══════════════════════════════════════════════════════════════════════
#  Definitions match the implementation
# ═══════════════════════════════════════════════════════════════════════

def test_definitions_quote_this_apps_actual_constants():
    # Spot-checks: if someone changes a constant in options.py without
    # updating the glossary, these fail.
    assert "0.62" in TERMS["edge_score"].formula      # _QUANT_BLEND_W_RETAIL
    assert "0.38" in TERMS["edge_score"].formula      # _QUANT_BLEND_W_INST
    assert "1.35" in TERMS["gold_zone"].formula       # POC / HVN weight
    assert "0.55" in TERMS["gold_zone"].formula       # Gann Sq9 weight
    assert "0.16" in TERMS["delta"].detail            # Opt.DELTA_TARGET
    assert "10000" in TERMS["mc_pop"].formula         # MonteCarloEngine simulations
    assert "1.96" in TERMS["wilson"].formula          # WILSON_Z
    assert "0.30" in TERMS["sentiment_score"].formula  # WEIGHTS["velocity"]
    assert "1.65" in TERMS["var_95"].formula          # 95% one-tailed z
    assert "0.4" in TERMS["ffd"].formula              # FFD d parameter


def test_registry_constants_still_match_the_source_modules():
    """Read the real constants and assert the glossary quotes them."""
    from modules import sentiment_radar as sr

    assert str(sr.WILSON_Z) in TERMS["wilson"].formula
    assert str(sr.WEIGHTS["velocity"]) in TERMS["sentiment_score"].formula
    assert str(sr.WEIGHTS["wilson"]) in TERMS["sentiment_score"].formula


# ═══════════════════════════════════════════════════════════════════════
#  Lookup helpers
# ═══════════════════════════════════════════════════════════════════════

def test_normalize_key_folds_case_and_whitespace():
    assert normalize_key("  IV   Rank ") == "iv rank"
    assert normalize_key("Θ/Γ") == "θ/γ"
    assert normalize_key(None) == ""
    assert normalize_key(123) == "123"


def test_get_is_exact_key_only():
    assert get("edge_score") is TERMS["edge_score"]
    assert get("Edge Score") is TERMS["edge_score"]   # space-folded to the key
    assert get("definitely_not_a_term") is None


def test_lookup_accepts_key_label_and_alias():
    t = TERMS["theta_gamma_ratio"]
    assert lookup("theta_gamma_ratio") is t
    assert lookup("Theta / Gamma ratio") is t
    assert lookup("tgr") is t
    assert lookup("Θ/Γ") is t


def test_lookup_passthrough_and_none():
    t = TERMS["gex"]
    assert lookup(t) is t
    assert lookup(None) is None
    assert lookup("") is None
    assert lookup("no such thing") is None


def test_require_raises_on_unknown():
    assert require("gex") is TERMS["gex"]
    with pytest.raises(KeyError):
        require("no_such_term")


def test_has_and_all_keys():
    assert has("Gold Zone") is True
    assert has("nonsense") is False
    keys = all_keys()
    assert keys == tuple(sorted(TERMS))
    assert len(keys) == len(TERMS)


def test_search_matches_label_and_body():
    assert "gex" in search("dealer")
    assert "hurst" in search("mean-reverting")
    # Empty query returns everything.
    assert search("") == all_keys()
    assert search("zzzz-not-present") == ()


def test_missing_terms_reports_only_the_unknown():
    assert missing_terms(["gex", "delta"]) == ()
    assert missing_terms(["gex", "flurb"]) == ("flurb",)


# ═══════════════════════════════════════════════════════════════════════
#  Tooltip / tone
# ═══════════════════════════════════════════════════════════════════════

def test_tooltip_combines_short_and_plain():
    t = TERMS["mc_pop"]
    tip = tooltip("mc_pop")
    assert t.short.rstrip(".") in tip
    assert t.plain in tip


def test_tooltip_appends_extra_context():
    tip = tooltip("delta", "This row uses the 30-day chain.")
    assert tip.endswith("This row uses the 30-day chain.")


def test_tooltip_degrades_instead_of_raising():
    # Unknown term with no extra -> None (renders as "no tooltip").
    assert tooltip("not_a_term") is None
    # Unknown term with extra -> still shows the extra.
    assert tooltip("not_a_term", "raw note") == "raw note"


def test_term_tooltip_method_matches_module_helper():
    assert TERMS["gamma"].tooltip() == tooltip("gamma")


def test_tone_label_prefixes_the_right_glyph():
    assert tone_label("Edge Score", "good") == "🟢 Edge Score"
    assert tone_label("Edge Score", "warn") == "🟡 Edge Score"
    assert tone_label("Edge Score", "bad") == "🔴 Edge Score"
    assert tone_label("Edge Score", "neutral") == "⚪ Edge Score"


def test_tone_label_is_a_no_op_for_missing_or_unknown_tone():
    assert tone_label("Edge Score") == "Edge Score"
    assert tone_label("Edge Score", None) == "Edge Score"
    assert tone_label("Edge Score", "chartreuse") == "Edge Score"


def test_every_declared_tone_has_a_glyph():
    for tone in TONES:
        assert tone in TONE_GLYPH
        assert TONE_GLYPH[tone].strip()
    # Glyphs are distinct, so tone is readable without relying on colour alone.
    assert len(set(TONE_GLYPH.values())) == len(TONE_GLYPH)


def test_verdict_text_attaches_tone_and_trims():
    assert verdict_text("  Sell the 30-day call.  ", "good") == "🟢 Sell the 30-day call."
    assert verdict_text("Wait.", None) == "Wait."
    assert verdict_text("", "good") == ""
    assert verdict_text(None) == ""


# ═══════════════════════════════════════════════════════════════════════
#  Canonical formatters
# ═══════════════════════════════════════════════════════════════════════

def test_money_formats_with_thousands_and_sign_outside():
    assert money(1234.5) == "$1,234.50"
    assert money(-1234.5) == "-$1,234.50"
    assert money(0) == "$0.00"
    # Python's format uses banker's rounding on .5 — assert on an unambiguous value.
    assert money(1234.6, decimals=0) == "$1,235"


def test_pct_and_ratio():
    assert pct(67.34) == "67.3%"
    assert pct(67.34, decimals=0) == "67%"
    assert ratio(2.0) == "2.00x"
    assert ratio(0.456, decimals=1) == "0.5x"


def test_score_shows_the_denominator():
    assert score(72) == "72 / 100"
    assert score(7, out_of=9) == "7 / 9"
    assert score(7.6, out_of=9, decimals=1) == "7.6 / 9"


def test_compact_handles_gex_sized_numbers():
    assert compact(-2_300_000_000) == "-2.3B"
    assert compact(1_500_000) == "1.5M"
    assert compact(2_400) == "2.4K"
    assert compact(1_000_000_000_000) == "1.0T"
    assert compact(12.3) == "12.3"


def test_signed_always_shows_the_sign():
    assert signed(0.4) == "+0.40"
    assert signed(-0.4) == "-0.40"
    assert signed(0) == "+0.00"


def test_formatters_return_a_dash_for_unusable_input():
    for fn in (money, pct, ratio, score, compact, signed):
        assert fn(None) == "—"
        assert fn(float("nan")) == "—"
        assert fn(float("inf")) == "—"
        assert fn("not a number") == "—"


def test_formatters_accept_a_custom_dash():
    assert money(None, dash="n/a") == "n/a"
    assert compact(None, dash="n/a") == "n/a"


# ═══════════════════════════════════════════════════════════════════════
#  Import discipline — the module must work with no Streamlit runtime
# ═══════════════════════════════════════════════════════════════════════

def test_streamlit_is_not_imported_at_module_scope():
    src = (Path(__file__).parent.parent / "modules" / "explain.py").read_text()
    head = src.split("#  RENDERING")[0]
    for line in head.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import streamlit"), (
            "streamlit must only be imported inside render functions"
        )
        assert not stripped.startswith("from streamlit"), (
            "streamlit must only be imported inside render functions"
        )


def test_module_imports_with_streamlit_blocked():
    """Import modules.explain in a subprocess where `import streamlit` raises."""
    root = str(Path(__file__).parent.parent)
    code = (
        "import sys, builtins\n"
        "_real = builtins.__import__\n"
        "def _blocked(name, *a, **k):\n"
        "    if name == 'streamlit' or name.startswith('streamlit.'):\n"
        "        raise ImportError('streamlit is not available')\n"
        "    return _real(name, *a, **k)\n"
        "builtins.__import__ = _blocked\n"
        "sys.path.insert(0, %r)\n"
        "import modules.explain as e\n"
        "assert 'streamlit' not in sys.modules\n"
        "assert len(e.TERMS) >= %d\n"
        "assert e.check_registry() == []\n"
        "assert e.tooltip('gex')\n"
        "assert e.money(1234.5) == '$1,234.50'\n"
        "print('OK')\n" % (root, MIN_TERMS)
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=root,
    )
    assert out.returncode == 0, f"stdout={out.stdout!r} stderr={out.stderr[-2000:]!r}"
    assert "OK" in out.stdout


def test_render_functions_exist_and_are_callable():
    for name in ("metric", "explain", "verdict_line", "glossary", "term_badge"):
        fn = getattr(explain, name)
        assert callable(fn), name


def test_public_api_is_exported():
    for name in explain.__all__:
        assert hasattr(explain, name), f"__all__ lists missing name {name!r}"


def test_term_dataclass_is_immutable():
    t = TERMS["delta"]
    with pytest.raises(Exception):
        t.plain = "something else"  # frozen dataclass


def test_term_title_falls_back_to_empty_when_unlabelled():
    t = Term(short="a b c", plain="A sentence.", detail="d" * 200, formula="f")
    assert t.title == ""
    assert "A sentence." in t.tooltip()
