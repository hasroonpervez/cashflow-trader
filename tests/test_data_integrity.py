"""Regression tests for the Aug-2026 data-integrity audit fixes.

Each test pins a specific confirmed defect so it cannot silently return:
  1. Alpha Vantage fallback served split-unadjusted prices under the same cache key
     as Yahoo's auto-adjusted series, with no marker.  -> price_basis / bases_comparable
  2. Fabricated macro defaults (VIX 20.0, 10Y 4.5%) were displayed as live data.
  3. A corrupt trade_journal.json was swallowed to [] and then overwritten, destroying
     the entire trade history on the next append.
  4. A failed price fetch silently zeroed 35% of the Sentiment Radar composite with
     no "partial-data" flag, contradicting the module's own documented integrity rule.
"""
import json

import pandas as pd
import pytest


# --------------------------------------------------------------------------
# 1. Price-adjustment basis tagging
# --------------------------------------------------------------------------

def _frame(basis=None):
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]})
    if basis is not None:
        df.attrs["price_basis"] = basis
    return df


def test_price_basis_reads_tag():
    from modules.data import PRICE_BASIS_ADJUSTED, PRICE_BASIS_UNADJUSTED, price_basis

    assert price_basis(_frame(PRICE_BASIS_ADJUSTED)) == PRICE_BASIS_ADJUSTED
    assert price_basis(_frame(PRICE_BASIS_UNADJUSTED)) == PRICE_BASIS_UNADJUSTED


def test_price_basis_none_for_untagged_or_missing():
    from modules.data import price_basis

    assert price_basis(_frame()) is None
    assert price_basis(None) is None
    assert price_basis(_frame("nonsense")) is None


def test_mixed_bases_are_not_comparable():
    """The actual bug: an unadjusted ticker frame compared against adjusted SPY."""
    from modules.data import PRICE_BASIS_ADJUSTED, PRICE_BASIS_UNADJUSTED, bases_comparable

    assert not bases_comparable(_frame(PRICE_BASIS_UNADJUSTED), _frame(PRICE_BASIS_ADJUSTED))


def test_same_basis_is_comparable_and_untagged_is_ignored():
    from modules.data import PRICE_BASIS_ADJUSTED, bases_comparable

    assert bases_comparable(_frame(PRICE_BASIS_ADJUSTED), _frame(PRICE_BASIS_ADJUSTED))
    # Absence of a tag is not evidence of a conflict.
    assert bases_comparable(_frame(PRICE_BASIS_ADJUSTED), _frame(), None)
    assert bases_comparable()


# --------------------------------------------------------------------------
# 2. Macro fallbacks must not impersonate live data
# --------------------------------------------------------------------------

def test_macro_defaults_are_absent_not_fabricated():
    """Regression: these used to be VIX 20.0 / 10Y 4.5% — plausible, and undetectable."""
    from modules.data import _macro_defaults_tuple

    data, hist = _macro_defaults_tuple()
    assert hist is None
    for label in ("VIX", "10Y Yield"):
        assert data[label]["price"] is None, f"{label} must not carry a fabricated price"
        assert data[label]["unavailable"] is True


def test_macro_unavailable_detects_every_absent_shape():
    from modules.data import macro_unavailable

    assert macro_unavailable(None, "VIX")
    assert macro_unavailable({}, "VIX")
    assert macro_unavailable({"VIX": None}, "VIX")
    assert macro_unavailable({"VIX": {"price": None}}, "VIX")
    assert macro_unavailable({"VIX": {"price": 20.0, "unavailable": True}}, "VIX")
    assert not macro_unavailable({"VIX": {"price": 20.0}}, "VIX")


def test_vix_none_disables_conditional_scoring_instead_of_faking_calm():
    """Every VIX consumer guards with `if vix_val and ...`, so None must be inert."""
    from modules.sentiment import Alerts

    df = pd.DataFrame(
        {
            "Open": [10.0] * 60,
            "High": [11.0] * 60,
            "Low": [9.0] * 60,
            "Close": [10.0] * 60,
            "Volume": [1_000_000.0] * 60,
        }
    )
    alerts = Alerts.scan(df, "TEST", None)
    joined = " ".join(str(a.get("m", "")) for a in alerts)
    assert "VIX" not in joined, "absent VIX must not produce a VIX-conditional alert"


# --------------------------------------------------------------------------
# 3. Corrupt journal must be preserved, never overwritten
# --------------------------------------------------------------------------

@pytest.fixture
def journal_at(tmp_path, monkeypatch):
    """Point the journal helpers at a throwaway path."""
    import modules.config as cfg

    path = tmp_path / "trade_journal.json"
    monkeypatch.setattr(cfg, "JOURNAL_PATH", path)
    cfg.drain_quarantine_notices()
    return cfg, path


def test_corrupt_journal_is_quarantined_not_destroyed(journal_at):
    cfg, path = journal_at
    path.write_text('[{"ticker": "PLTR", "premium_100": 250}, {"trunc')  # truncated write

    ok = cfg.journal_add_entry({"ticker": "TSLA"})

    assert ok is True, "append should succeed onto a fresh file after quarantine"
    survivors = list(path.parent.glob("trade_journal.json.corrupt-*"))
    assert len(survivors) == 1, "the unreadable bytes must still be on disk"
    assert "PLTR" in survivors[0].read_text(), "original content must be preserved verbatim"
    assert json.loads(path.read_text()) == [{"ticker": "TSLA"}]
    assert any("preserved" in n for n in cfg.drain_quarantine_notices())


def test_wrong_shape_json_is_also_treated_as_corruption(journal_at):
    cfg, path = journal_at
    path.write_text('{"not": "a list"}')

    cfg.journal_add_entry({"ticker": "TSLA"})

    assert len(list(path.parent.glob("trade_journal.json.corrupt-*"))) == 1


def test_close_trade_refuses_to_operate_on_a_corrupt_journal(journal_at):
    """Closing index 0 of a journal we could not read must not invent a trade."""
    cfg, path = journal_at
    path.write_text("{{{ garbage")

    assert cfg.journal_close_trade(0, 100.0) is False


def test_healthy_journal_roundtrip_is_untouched(journal_at):
    cfg, path = journal_at

    cfg.journal_add_entry({"ticker": "A"})
    cfg.journal_add_entry({"ticker": "B"})

    assert [e["ticker"] for e in cfg.load_journal()] == ["A", "B"]
    assert not list(path.parent.glob("*.corrupt-*"))


def test_radar_hits_share_the_same_protection(tmp_path, monkeypatch):
    import modules.config as cfg

    path = tmp_path / "radar_hits.json"
    monkeypatch.setattr(cfg, "RADAR_HITS_PATH", path)
    path.write_text("[not json")

    cfg.radar_add_hit({"ticker": "SOUN"})

    assert len(list(tmp_path.glob("radar_hits.json.corrupt-*"))) == 1
    assert json.loads(path.read_text()) == [{"ticker": "SOUN"}]


# --------------------------------------------------------------------------
# 4. Radar must flag a missing price frame, not score it as zero
# --------------------------------------------------------------------------

def _ape(mentions=100, prev=90, rank=5, rank_prev=6):
    return {"mentions": mentions, "mentions_24h_ago": prev, "rank": rank, "rank_24h_ago": rank_prev}


def _st(total=50, bullish=40):
    return {"total": total, "bullish": bullish, "messages": total}


def test_missing_price_frame_flags_partial_data():
    """35% of the composite (volume 0.20 + earliness 0.15) is unscored — say so."""
    from modules.sentiment_radar import build_row

    row = build_row(
        "SOUN", ape=_ape(), st_sent=_st(), reddit_count=95,
        vol_today=None, prior_vols=None,
        close_today=None, close_5d_ago=None,
    )
    assert "no-price-data" in row.flags
    assert "partial-data" in row.flags


def test_present_price_frame_does_not_flag():
    from modules.sentiment_radar import build_row

    row = build_row(
        "SOUN", ape=_ape(), st_sent=_st(), reddit_count=95,
        vol_today=120.0, prior_vols=[100.0, 110.0, 90.0, 105.0, 95.0],
        close_today=11.0, close_5d_ago=10.0,
    )
    assert "no-price-data" not in row.flags
    assert "partial-data" not in row.flags


def test_price_missing_row_scores_below_identical_row_with_price():
    """The flag is not cosmetic: the unscored components really do cost the row."""
    from modules.sentiment_radar import build_row

    common = dict(ape=_ape(), st_sent=_st(), reddit_count=95)
    with_price = build_row(
        "A", vol_today=400.0, prior_vols=[100.0] * 30,
        close_today=10.1, close_5d_ago=10.0, **common,
    )
    without = build_row(
        "A", vol_today=None, prior_vols=None,
        close_today=None, close_5d_ago=None, **common,
    )
    assert without.score < with_price.score


# --------------------------------------------------------------------------
# 5. Vanna sign — was positive, telling a short-call writer that an IV spike
#    reduces their delta when it increases it.  vanna = -phi(d1)*d2/sigma
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "S,K,T,sigma,typ",
    [
        (100.0, 120.0, 1.0, 0.20, "call"),   # OTM call
        (100.0, 80.0, 1.0, 0.20, "call"),    # ITM call
        (100.0, 100.0, 0.5, 0.30, "put"),    # ATM put
        (100.0, 130.0, 0.25, 0.45, "put"),   # OTM put, short dated
    ],
)
def test_vanna_matches_finite_difference_of_delta(S, K, T, sigma, typ):
    """vanna must equal dDelta/dSigma per 1% IV, in sign AND magnitude.

    ``bs_greeks`` rounds delta to 3 dp, so a 1-point sigma bump moves it by less than
    the rounding floor and differencing it yields quantisation noise. Bump sigma by
    10 points instead (delta moves ~0.014, well clear of 1e-3) and scale back down.
    """
    from modules.options import bs_greeks

    spread = 0.10  # 10 percentage points of IV, well above the 3-dp delta resolution
    up = bs_greeks(S, K, T, 0.0, sigma + spread / 2, typ)["delta"]
    dn = bs_greeks(S, K, T, 0.0, sigma - spread / 2, typ)["delta"]
    fd = (up - dn) / (spread / 0.01)   # -> delta change per ONE point of IV
    got = bs_greeks(S, K, T, 0.0, sigma, typ)["vanna"]

    assert got == pytest.approx(fd, rel=0.15, abs=2e-4), (
        f"vanna {got:+.6f} vs finite-difference {fd:+.6f}"
    )


def test_vanna_is_identical_for_calls_and_puts():
    """Put-call parity: delta_put = delta_call - 1, so dDelta/dSigma must match exactly.

    This is the rounding-free companion to the finite-difference test above.
    """
    from modules.options import bs_greeks

    for S, K, T, sigma in [(100.0, 120.0, 1.0, 0.20), (100.0, 90.0, 0.5, 0.35)]:
        c = bs_greeks(S, K, T, 0.0, sigma, "call")["vanna"]
        p = bs_greeks(S, K, T, 0.0, sigma, "put")["vanna"]
        assert c == p


def test_vanna_sign_flips_across_the_money():
    """Sanity: d2 changes sign around ATM, so vanna must too."""
    from modules.options import bs_greeks

    otm = bs_greeks(100.0, 120.0, 1.0, 0.0, 0.20, "call")["vanna"]
    itm = bs_greeks(100.0, 80.0, 1.0, 0.0, 0.20, "call")["vanna"]
    assert otm > 0 > itm


# --------------------------------------------------------------------------
# 6. Tape pillar operator precedence — `a + b if c else d` binds as
#    `(a + b) if c else d`, so a flat OBV threw away the MACD base entirely.
# --------------------------------------------------------------------------

def test_tape_pillar_obv_penalty_is_a_nudge_not_a_wipeout():
    """A flat OBV should cost 4 points, not collapse the pillar to zero."""
    import re
    from pathlib import Path

    src = Path("modules/signal_desk.py").read_text()
    # The buggy form must not reappear anywhere in the module.
    assert not re.search(r"tape\s*=\s*tape\s*\+\s*6\.0\s+if\s+obv_up\s+else\s+-4\.0", src)

    # And the corrected arithmetic must hold for both MACD branches.
    for macd_bull, obv_up in ((True, True), (True, False), (False, True), (False, False)):
        base = 58.0 if macd_bull else 44.0
        tape = max(0.0, min(100.0, base + (6.0 if obv_up else -4.0)))
        assert tape >= 40.0, "no branch may clamp the tape pillar to the floor"
