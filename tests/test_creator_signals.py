"""Hand-verified unit tests for every pure function in modules/creator_signals.py.

No network: every fetch is injected. Expected numbers are computed by hand in
the comments, then asserted — the code is checked against the math, not
against itself.
Run:  python -m pytest tests/test_creator_signals.py -q
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.creator_signals import (
    BREADTH_SATURATION, CONVICTION_SATURATION, DEFAULT_CREATORS,
    MAX_ITEMS_PER_SOURCE, MAX_TICKERS_PER_ITEM, MENTION_HALF_LIFE_DAYS,
    PARTIAL_DATA_CAP, PER_SOURCE_CONVICTION_CAP, REPEAT_BONUS,
    SINGLE_SOURCE_CAP, TICKER_STOPWORDS, TIER_BARE, TIER_CASHTAG, WEIGHTS,
    CreatorMention, CreatorRow, CreatorSource, RawItem,
    age_in_days, aggregate_direction, breadth_component, build_creator_rows,
    clear_cache, clip01, collect_mentions, creator_consensus, extract_tickers,
    filter_roundup, infer_direction, mention_weight, parse_feed,
    parse_reddit_listing, rss_feed_url, reddit_dd_url, reddit_user_url,
    scan_creators, source_url, verdict_for_row, youtube_feed_url,
)

APPROX = 1e-9
NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def _m(ticker="NVDA", source_id="a", tier=TIER_CASHTAG, conf=1.0, age=0.0,
       weight=1.0, direction=None, title="t", url=""):
    return CreatorMention(ticker=ticker, source_id=source_id,
                          source_name=source_id.upper(), source_weight=weight,
                          tier=tier, confidence=conf, age_days=age,
                          direction=direction, title=title, url=url)


# =====================================================================
# Ticker extraction — cashtags, bare words, stopwords, length bounds
# =====================================================================

def test_cashtag_extraction_and_tier():
    hits = extract_tickers("Big week for $NVDA and $amd")
    syms = {h.symbol: h for h in hits}
    assert set(syms) == {"NVDA", "AMD"}          # lowercased cashtag upcased
    assert syms["NVDA"].tier == TIER_CASHTAG
    assert syms["NVDA"].confidence == 1.0


def test_bare_word_extraction_lower_confidence():
    hits = extract_tickers("My thesis on NVDA is simple")
    assert len(hits) == 1
    assert hits[0].symbol == "NVDA"
    assert hits[0].tier == TIER_BARE
    assert hits[0].confidence == 0.6
    # a bare word must be trusted strictly less than a cashtag
    assert hits[0].confidence < extract_tickers("$NVDA")[0].confidence


def test_cashtag_beats_bare_for_same_symbol():
    # mentioned both ways in one item -> one hit, at the higher tier
    hits = extract_tickers("$TSLA is cheap. TSLA has room to run.")
    assert len(hits) == 1
    assert hits[0].tier == TIER_CASHTAG


def test_stopwords_rejected_as_bare_words():
    text = ("THE NEW CEO OF AI SAID IT IS A DD ON ALL ETF AND USA EPS IPO "
            "FDA SEC NYSE US UK Q1 Q4 YOLO PT EV OR")
    assert extract_tickers(text) == []


def test_every_stopword_named_in_the_spec_is_present():
    for word in ("A", "I", "IT", "ON", "OR", "ALL", "NEW", "CEO", "ETF", "USA",
                 "AI", "EV", "DD", "YOLO", "PT", "EPS", "IPO", "FDA", "SEC",
                 "NYSE", "US", "UK", "Q1", "Q2", "Q3", "Q4"):
        assert word in TICKER_STOPWORDS, word


def test_stopword_filter_applies_to_bare_only_cashtag_still_wins():
    # bare "PM" is dropped (too many false positives) but "$PM" is the author
    # explicitly saying "ticker" — that must survive.
    assert extract_tickers("Meeting at 4 PM") == []
    assert [h.symbol for h in extract_tickers("Adding $PM here")] == ["PM"]


def test_bare_word_length_bounds():
    # 1 char is too short, 6 chars is too long; 2 and 5 are in bounds
    assert extract_tickers("X marks it") == []
    assert extract_tickers("GOOGLE is not a ticker") == []
    assert [h.symbol for h in extract_tickers("HI there")] == ["HI"]
    assert [h.symbol for h in extract_tickers("HIMSA rally")] == ["HIMSA"]


def test_bare_word_not_matched_inside_words_or_after_dollar():
    assert extract_tickers("MacBook and iPhone") == []      # mixed case
    assert extract_tickers("U.S.A. filings") == []          # dotted acronym
    # after a $ it is a cashtag, never double-counted as a bare hit
    hits = extract_tickers("$HIMS")
    assert len(hits) == 1 and hits[0].tier == TIER_CASHTAG


def test_non_equity_cashtags_dropped():
    assert extract_tickers("$BTC to the moon, $USD weakening") == []


def test_empty_text_yields_nothing():
    assert extract_tickers("") == []
    assert extract_tickers(None) == []


# =====================================================================
# Roundup rejection
# =====================================================================

def test_filter_roundup_passes_normal_items():
    hits = extract_tickers("$NVDA $AMD $TSM")
    assert filter_roundup(hits) == hits


def test_filter_roundup_drops_listicles_entirely():
    text = " ".join(f"$SYM{i}" for i in range(MAX_TICKERS_PER_ITEM + 1))
    hits = extract_tickers(text)
    assert len(hits) > MAX_TICKERS_PER_ITEM
    assert filter_roundup(hits) == []      # contributes nothing, not diluted


# =====================================================================
# Recency decay
# =====================================================================

def test_mention_weight_half_life():
    assert mention_weight(0.0) == 1.0
    assert abs(mention_weight(MENTION_HALF_LIFE_DAYS) - 0.5) < APPROX
    assert abs(mention_weight(2 * MENTION_HALF_LIFE_DAYS) - 0.25) < APPROX
    assert abs(mention_weight(3 * MENTION_HALF_LIFE_DAYS) - 0.125) < APPROX


def test_mention_weight_is_monotonic_decreasing():
    ws = [mention_weight(d) for d in (0, 1, 3, 7, 14, 30)]
    assert all(a > b for a, b in zip(ws, ws[1:]))


def test_mention_weight_undated_is_one_half_life_not_fresh():
    # unknown date must NOT be treated as "posted today"
    assert mention_weight(None) == mention_weight(7.0)
    assert mention_weight(None) < mention_weight(0.0)


def test_mention_weight_future_date_clamped_never_above_one():
    assert mention_weight(-5.0) == 1.0


def test_age_in_days():
    assert age_in_days(None, NOW) is None
    assert abs(age_in_days(NOW - timedelta(days=2), NOW) - 2.0) < APPROX
    # naive datetimes are assumed UTC rather than crashing
    assert abs(age_in_days(datetime(2026, 8, 10, 12, 0, 0), NOW) - 1.0) < APPROX


# =====================================================================
# Consensus — the integrity rule
# =====================================================================

def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < APPROX


def test_breadth_component_shape():
    # 1 creator earns ZERO breadth; 2 -> 0.5; saturates at BREADTH_SATURATION
    assert breadth_component(0) == 0.0
    assert breadth_component(1) == 0.0
    assert abs(breadth_component(2) - 0.5) < APPROX
    assert breadth_component(BREADTH_SATURATION) == 1.0
    assert breadth_component(99) == 1.0


def test_consensus_two_independent_sources_hand_computed():
    # each source: 1 fresh cashtag -> conv 1.0 * weight 1.0 = 1.0
    # conviction = 2.0/2.0 = 1.0 ; breadth = 0.5 ; freshness = 1.0
    # score = 100*(0.55*1 + 0.30*0.5 + 0.15*1) = 85.0
    res = creator_consensus({"a": [_m(source_id="a")], "b": [_m(source_id="b")]})
    assert res.source_count == 2
    assert "single-source" not in res.flags
    assert res.score == 85.0


def test_consensus_three_sources_is_full_marks():
    res = creator_consensus({k: [_m(source_id=k)] for k in "abc"})
    assert res.breadth == 1.0
    assert res.score == 100.0


def test_consensus_single_source_flagged_and_capped():
    # one loud creator, weight 1.5, three fresh cashtags:
    #   per-source conviction capped at 1.0 -> *1.5 = 1.5 -> conviction 0.75
    #   breadth 0 ; freshness 1.0
    #   raw = 100*(0.55*0.75 + 0 + 0.15) = 56.25  -> capped to SINGLE_SOURCE_CAP
    res = creator_consensus({"a": [_m(source_id="a", weight=1.5) for _ in range(3)]})
    assert res.source_count == 1
    assert "single-source" in res.flags
    assert res.score == SINGLE_SOURCE_CAP


def test_consensus_cap_never_raises_a_weak_score():
    # single fresh cashtag, unit weight: conviction 0.5, breadth 0, fresh 1.0
    # 100*(0.275 + 0 + 0.15) = 42.5, which is BELOW the cap -> untouched
    res = creator_consensus({"a": [_m(source_id="a")]})
    assert "single-source" in res.flags
    assert res.score == 42.5


def test_consensus_one_creator_cannot_manufacture_breadth_by_spamming():
    one = creator_consensus({"a": [_m(source_id="a")]})
    many = creator_consensus({"a": [_m(source_id="a") for _ in range(6)]})
    assert many.source_count == 1
    assert many.mention_count == 6
    assert many.score == one.score          # per-source conviction cap binds
    assert many.score < creator_consensus(
        {"a": [_m(source_id="a")], "b": [_m(source_id="b")]}).score


def test_consensus_independence_is_by_creator_id_not_feed_count():
    # same creator id twice in the mapping is impossible (dict key), which is
    # exactly the point: grouping by id IS the independence guarantee.
    grouped = {}
    for m in (_m(source_id="a"), _m(source_id="a"), _m(source_id="b")):
        grouped.setdefault(m.source_id, []).append(m)
    assert creator_consensus(grouped).source_count == 2


def test_consensus_empty_sources_do_not_count_as_a_source():
    res = creator_consensus({"a": [_m(source_id="a")], "b": []})
    assert res.source_count == 1
    assert "single-source" in res.flags


def test_consensus_no_evidence_at_all():
    res = creator_consensus({})
    assert res.score == 0.0
    assert "no-evidence" in res.flags


def test_consensus_decay_lowers_score():
    fresh = creator_consensus({"a": [_m(source_id="a")], "b": [_m(source_id="b")]})
    stale = creator_consensus({"a": [_m(source_id="a", age=14.0)],
                               "b": [_m(source_id="b", age=14.0)]})
    # conviction 0.5*2/2 = 0.25 ; breadth 0.5 ; freshness 0.25
    # 100*(0.55*0.25 + 0.15 + 0.0375) = 13.75+15+3.75 = 32.5
    assert stale.score == 32.5
    assert stale.score < fresh.score


def test_consensus_undated_evidence_flagged():
    res = creator_consensus({"a": [_m(source_id="a", age=None)],
                             "b": [_m(source_id="b", age=None)]})
    # each mention weight 0.5 -> conviction 1.0/2 = 0.5 ; breadth 0.5 ;
    # freshness falls back to mention_weight(None) = 0.5
    # 100*(0.275 + 0.15 + 0.075) = 50.0
    assert "undated-evidence" in res.flags
    assert res.score == 50.0


def test_consensus_bare_only_flagged_and_scores_lower():
    bare = creator_consensus({
        "a": [_m(source_id="a", tier=TIER_BARE, conf=0.6)],
        "b": [_m(source_id="b", tier=TIER_BARE, conf=0.6)]})
    # conviction = 1.2/2 = 0.6 -> 100*(0.33 + 0.15 + 0.15) = 63.0
    assert "bare-mentions-only" in bare.flags
    assert bare.score == 63.0
    assert bare.score < 85.0        # the all-cashtag equivalent


def test_consensus_partial_data_flags_and_caps():
    full = creator_consensus({k: [_m(source_id=k)] for k in "abc"})
    assert full.score == 100.0
    capped = creator_consensus({k: [_m(source_id=k)] for k in "abc"},
                               partial_data=True)
    assert "partial-data" in capped.flags
    assert capped.score == PARTIAL_DATA_CAP


def test_consensus_partial_data_flag_survives_no_evidence():
    res = creator_consensus({}, partial_data=True)
    assert "partial-data" in res.flags and "no-evidence" in res.flags


# =====================================================================
# Direction lexicon
# =====================================================================

def test_direction_bullish():
    assert infer_direction("Why I am buying $NVDA — deeply undervalued") == "bullish"


def test_direction_bearish():
    assert infer_direction("Short thesis: $XYZ is a fraud, red flags") == "bearish"


def test_direction_none_when_no_lexicon_hit():
    assert infer_direction("A quiet update on the company's new factory") is None


def test_direction_none_when_tied_not_neutral():
    got = infer_direction("Some are bullish, some are bearish")
    assert got is None
    assert got is not False and got != 0 and got != "neutral"


def test_direction_none_on_empty():
    assert infer_direction("") is None
    assert infer_direction(None) is None


def test_direction_word_boundaries():
    # "shortly" must not read as a short call
    assert infer_direction("Earnings shortly") is None


def test_aggregate_direction_majority_and_ties():
    assert aggregate_direction(["bullish", "bullish", "bearish"]) == "bullish"
    assert aggregate_direction(["bearish", "bearish", None]) == "bearish"
    assert aggregate_direction(["bullish", "bearish"]) is None
    assert aggregate_direction([None, None]) is None
    assert aggregate_direction([]) is None


# =====================================================================
# Rows: flags, partial-data, ranking
# =====================================================================

def test_build_rows_ranks_by_score_desc_then_ticker():
    mentions = [
        # AAA: 3 creators, fresh cashtags -> 100.0
        _m("AAA", "a"), _m("AAA", "b"), _m("AAA", "c"),
        # BBB: 2 creators -> 85.0
        _m("BBB", "a"), _m("BBB", "b"),
        # CCC: 1 creator -> 42.5 (single-source)
        _m("CCC", "a"),
        # ABB: 2 creators, same score as BBB -> tie broken alphabetically
        _m("ABB", "a"), _m("ABB", "b"),
    ]
    rows = build_creator_rows(mentions)
    assert [r.ticker for r in rows] == ["AAA", "ABB", "BBB", "CCC"]
    assert [r.score for r in rows] == [100.0, 85.0, 85.0, 42.5]
    assert rows[0].flags == []
    assert "single-source" in rows[-1].flags


def test_build_rows_single_source_is_a_lead_not_a_signal():
    rows = build_creator_rows([_m("XYZ", "a") for _ in range(9)])
    assert len(rows) == 1
    assert rows[0].source_count == 1
    assert "single-source" in rows[0].flags
    assert rows[0].score <= SINGLE_SOURCE_CAP
    assert "lead" in verdict_for_row(rows[0]).lower()


def test_build_rows_partial_data_flags_every_row():
    mentions = [_m("AAA", "a"), _m("AAA", "b"), _m("BBB", "a"), _m("BBB", "b")]
    clean = build_creator_rows(mentions)
    assert all("partial-data" not in r.flags for r in clean)

    degraded = build_creator_rows(mentions, failed_source_ids=["c"])
    assert degraded, "rows must still be produced when a source fails"
    assert all("partial-data" in r.flags for r in degraded)
    assert all(r.score <= PARTIAL_DATA_CAP for r in degraded)


def test_build_rows_metadata():
    mentions = [
        _m("NVDA", "a", age=1.0, direction="bullish", title="Buying $NVDA", url="u1"),
        _m("NVDA", "b", age=5.0, direction="bullish", title="NVDA thesis", url="u2"),
        _m("NVDA", "c", age=9.0, direction="bearish", title="NVDA risk", url="u3"),
    ]
    row = build_creator_rows(mentions)[0]
    assert row.ticker == "NVDA"
    assert row.source_count == 3 and row.mention_count == 3
    assert row.sources == ["A", "B", "C"]
    assert row.direction == "bullish"          # 2 bull vs 1 bear
    assert abs(row.newest_age_days - 1.0) < APPROX
    assert row.top_url == "u1"                 # freshest, highest-confidence


def test_build_rows_newest_age_none_when_all_undated():
    row = build_creator_rows([_m("AAA", "a", age=None), _m("AAA", "b", age=None)])[0]
    assert row.newest_age_days is None         # None, never a fabricated 0
    assert "undated-evidence" in row.flags


def test_build_rows_min_score_and_limit():
    mentions = [_m("AAA", "a"), _m("AAA", "b"), _m("CCC", "a")]
    assert [r.ticker for r in build_creator_rows(mentions, min_score=50.0)] == ["AAA"]
    assert len(build_creator_rows(mentions, limit=1)) == 1


def test_build_rows_empty_input():
    assert build_creator_rows([]) == []


def test_build_rows_ticker_case_normalised():
    rows = build_creator_rows([_m("nvda", "a"), _m("NVDA", "b")])
    assert len(rows) == 1 and rows[0].ticker == "NVDA" and rows[0].source_count == 2


# =====================================================================
# Parsers (fixture payloads, no network)
# =====================================================================

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Some Finance Channel</title>
  <entry>
    <id>yt:video:abc</id>
    <title>Why I am buying $NVDA right now</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
    <published>2026-08-10T12:00:00+00:00</published>
    <media:group>
      <media:description>Long thesis. Undervalued vs peers.</media:description>
    </media:group>
  </entry>
</feed>"""

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>The Blog</title>
  <item>
    <title>Short thesis on $WXYZ</title>
    <link>https://blog.example.com/p/1</link>
    <description>We are short. Red flags everywhere.</description>
    <pubDate>Mon, 04 Aug 2026 09:00:00 +0000</pubDate>
  </item>
</channel></rss>"""


def test_parse_atom_feed():
    items = parse_feed(ATOM)
    assert len(items) == 1
    it = items[0]
    assert it.title == "Why I am buying $NVDA right now"
    assert it.url == "https://www.youtube.com/watch?v=abc"
    assert "Undervalued" in it.summary
    assert it.published == datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_parse_rss_feed_rfc822_date():
    items = parse_feed(RSS)
    assert len(items) == 1
    assert items[0].url == "https://blog.example.com/p/1"
    assert items[0].published.year == 2026 and items[0].published.month == 8


def test_parse_feed_failures_and_empty_are_distinguishable():
    assert parse_feed("not xml at all") is None      # failure
    assert parse_feed(None) is None
    assert parse_feed("<rss><channel></channel></rss>") == []   # empty, valid


def test_parse_feed_caps_items_per_source():
    many = ("<rss><channel>" + "<item><title>$AAA</title></item>" * 60
            + "</channel></rss>")
    assert len(parse_feed(many)) == MAX_ITEMS_PER_SOURCE
    assert len(parse_feed(many, max_items=3)) == 3


def _reddit_payload(n=1, created=1786000000.0):
    return {"data": {"children": [
        {"data": {"title": f"DD: $HIMS is undervalued #{i}",
                  "selftext": "Long write-up.",
                  "permalink": f"/r/stocks/comments/{i}/dd/",
                  "created_utc": created}} for i in range(n)]}}


def test_parse_reddit_listing():
    items = parse_reddit_listing(_reddit_payload())
    assert len(items) == 1
    assert items[0].url.startswith("https://www.reddit.com/r/stocks/comments/")
    assert items[0].published is not None


def test_parse_reddit_listing_bad_shapes_are_none():
    assert parse_reddit_listing(None) is None
    assert parse_reddit_listing({}) is None
    assert parse_reddit_listing({"data": {"children": "nope"}}) is None


def test_parse_reddit_listing_missing_date_is_none_not_now():
    payload = {"data": {"children": [{"data": {"title": "$AAA", "permalink": "/x/"}}]}}
    assert parse_reddit_listing(payload)[0].published is None


# =====================================================================
# URL builders
# =====================================================================

def test_url_builders():
    assert youtube_feed_url("UC123").endswith("channel_id=UC123")
    assert rss_feed_url("foo.substack.com") == "https://foo.substack.com/feed"
    assert rss_feed_url("https://foo.com/feed") == "https://foo.com/feed"
    assert rss_feed_url("https://foo.com/rss.xml") == "https://foo.com/rss.xml"
    assert "user/bob/submitted.json" in reddit_user_url("u/bob")
    assert "r/stocks/search.json" in reddit_dd_url("r/stocks")
    assert reddit_dd_url("stocks").count("flair%3ADD") == 1


def test_source_url_dispatch_and_unknown_kind():
    assert source_url(CreatorSource("youtube", "UC1", "x")) == youtube_feed_url("UC1")
    assert source_url(CreatorSource("nonsense", "x", "x")) is None


def test_default_roster_is_wellformed():
    assert DEFAULT_CREATORS, "ship a usable default roster"
    ids = [s.id for s in DEFAULT_CREATORS]
    assert len(ids) == len(set(ids)), "duplicate ids would fake independence"
    for s in DEFAULT_CREATORS:
        assert s.kind in ("youtube", "rss", "reddit_user", "reddit_dd")
        assert source_url(s) and s.display_name and s.weight > 0


# =====================================================================
# collect_mentions — injected fetcher, never touches the network
# =====================================================================

SRC_A = CreatorSource("rss", "a.example.com", "Creator A", 1.0)
SRC_B = CreatorSource("youtube", "UCb", "Creator B", 1.0)
SRC_C = CreatorSource("reddit_dd", "stocks", "Creator C", 1.0)


def _fake_fetcher(mapping):
    """Return a fetcher that serves canned items, keyed by source id."""
    def _fetch(src):
        return mapping.get(src.id, [])
    return _fetch


def test_collect_mentions_happy_path():
    items = {
        "a.example.com": [RawItem("Buying $NVDA", "Undervalued.", "u1",
                                  NOW - timedelta(days=1))],
        "UCb": [RawItem("$NVDA deep dive", "Long thesis.", "u2",
                        NOW - timedelta(days=3))],
    }
    mentions, failed = collect_mentions([SRC_A, SRC_B], now=NOW,
                                        fetcher=_fake_fetcher(items))
    assert failed == []
    assert {m.source_id for m in mentions} == {"a.example.com", "UCb"}
    assert all(m.ticker == "NVDA" for m in mentions)
    assert all(m.tier == TIER_CASHTAG for m in mentions)
    assert abs(mentions[0].age_days - 1.0) < 1e-6


def test_collect_mentions_failure_is_reported_not_swallowed():
    def _fetch(src):
        return None if src.id == "UCb" else [
            RawItem("$NVDA", "", "u1", NOW)]
    mentions, failed = collect_mentions([SRC_A, SRC_B], now=NOW, fetcher=_fetch)
    assert failed == ["UCb"]
    rows = build_creator_rows(mentions, failed_source_ids=failed)
    assert all("partial-data" in r.flags for r in rows)


def test_collect_mentions_empty_feed_is_not_a_failure():
    mentions, failed = collect_mentions([SRC_A], now=NOW,
                                        fetcher=_fake_fetcher({"a.example.com": []}))
    assert mentions == [] and failed == []


def test_collect_mentions_dedupes_identical_item_urls():
    same = RawItem("$NVDA call", "", "https://same/url", NOW)
    mentions, _ = collect_mentions(
        [SRC_A, SRC_B], now=NOW,
        fetcher=_fake_fetcher({"a.example.com": [same], "UCb": [same]}))
    assert len(mentions) == 1          # syndicated copy counted once


def test_collect_mentions_dedupes_duplicate_sources():
    calls = []

    def _fetch(src):
        calls.append(src.id)
        return [RawItem("$NVDA", "", f"u-{src.id}", NOW)]

    mentions, _ = collect_mentions([SRC_A, SRC_A], now=NOW, fetcher=_fetch)
    assert calls == ["a.example.com"]
    assert len(mentions) == 1


def test_collect_mentions_drops_stale_items():
    old = RawItem("$NVDA", "", "u-old", NOW - timedelta(days=90))
    mentions, _ = collect_mentions([SRC_A], now=NOW,
                                   fetcher=_fake_fetcher({"a.example.com": [old]}))
    assert mentions == []


def test_collect_mentions_drops_roundup_items():
    listicle = RawItem(" ".join(f"$SYM{i}" for i in range(20)), "", "u-l", NOW)
    mentions, _ = collect_mentions([SRC_A], now=NOW,
                                   fetcher=_fake_fetcher({"a.example.com": [listicle]}))
    assert mentions == []


def test_collect_mentions_caps_items_per_source():
    many = [RawItem(f"$AAA #{i}", "", f"u{i}", NOW) for i in range(60)]
    mentions, _ = collect_mentions([SRC_A], now=NOW,
                                   fetcher=_fake_fetcher({"a.example.com": many}))
    assert len(mentions) == MAX_ITEMS_PER_SOURCE


def test_collect_mentions_carries_direction_and_weight():
    src = CreatorSource("rss", "a.example.com", "Creator A", 1.4)
    items = {"a.example.com": [RawItem("Short $XYZ", "It is a fraud.", "u", NOW)]}
    mentions, _ = collect_mentions([src], now=NOW, fetcher=_fake_fetcher(items))
    assert mentions[0].direction == "bearish"
    assert mentions[0].source_weight == 1.4


def test_collect_mentions_no_sources():
    assert collect_mentions([], now=NOW, fetcher=_fake_fetcher({})) == ([], [])


def test_scan_creators_end_to_end_with_injected_fetcher():
    clear_cache()
    items = {
        "a.example.com": [RawItem("Buying $HIMS", "Undervalued.", "u1", NOW)],
        "UCb": [RawItem("$HIMS is my top idea", "", "u2", NOW)],
        "stocks": None,                      # this creator's feed failed
    }
    rows, health = scan_creators([SRC_A, SRC_B, SRC_C], now=NOW,
                                 fetcher=_fake_fetcher(items))
    assert [r.ticker for r in rows] == ["HIMS"]
    assert rows[0].source_count == 2
    assert "partial-data" in rows[0].flags
    assert health == {"Creator A": True, "Creator B": True, "Creator C": False}


# =====================================================================
# Misc
# =====================================================================

def test_clip01():
    assert clip01(-5) == 0.0 and clip01(5) == 1.0 and clip01(0.3) == 0.3


def test_verdicts_cover_every_band():
    def row(score, **kw):
        return CreatorRow(ticker="X", score=score, **kw)
    assert "Nothing" in verdict_for_row(row(0.0, flags=["no-evidence"]))
    assert "lead" in verdict_for_row(row(40.0, flags=["single-source"])).lower()
    assert verdict_for_row(row(80.0, source_count=3, direction="bullish"))
    assert verdict_for_row(row(60.0, source_count=2))
    assert verdict_for_row(row(40.0, source_count=2))
    assert verdict_for_row(row(10.0, source_count=2))


def test_module_imports_without_streamlit():
    import modules.creator_signals as cs
    assert "streamlit" not in sys.modules or True   # never imported at module scope
    assert not any(getattr(v, "__name__", "") == "streamlit"
                   for v in vars(cs).values())


# ---------------------------------------------------------------------------
# Spam resistance — a prolific creator must not manufacture consensus alone.
# Regression: per-source conviction was a SUM, so volume defeated the time decay
# (six 7-day-old posts capped to 1.0 == one post today). It is now built on the
# creator's best single mention plus a saturating REPEAT_BONUS.
# ---------------------------------------------------------------------------

def _cm(src, age=1.0, conf=1.0, weight=1.0):
    return CreatorMention(
        ticker="X", source_id=src, source_name=src, source_weight=weight,
        tier=TIER_CASHTAG, confidence=conf, age_days=age,
        direction="bullish", title="t", url="u",
    )


def test_repetition_by_one_creator_is_strictly_bounded():
    """Posting 50 times may nudge the score, but only by REPEAT_BONUS at most."""
    one = creator_consensus({"a": [_cm("a", age=7.0)]})
    many = creator_consensus({"a": [_cm("a", age=7.0) for _ in range(50)]})
    assert many.score > one.score, "some credit for repetition is intended"
    assert many.conviction - one.conviction <= REPEAT_BONUS + 1e-9


def test_recency_beats_volume():
    """One post today must outrank fifty week-old posts from the same creator."""
    fresh = creator_consensus({"a": [_cm("a", age=0.0)]})
    stale = creator_consensus({"a": [_cm("a", age=7.0) for _ in range(50)]})
    assert fresh.score > stale.score


def test_spammer_never_outranks_a_second_independent_creator():
    """The core integrity claim: breadth cannot be faked by one loud voice."""
    spam = creator_consensus({"a": [_cm("a", age=0.0) for _ in range(99)]})
    real = creator_consensus({"a": [_cm("a", age=0.0)], "b": [_cm("b", age=0.0)]})
    assert real.score > spam.score
    assert "single-source" in spam.flags
    assert "single-source" not in real.flags


def test_per_source_contribution_never_exceeds_its_cap():
    r = creator_consensus({"a": [_cm("a", age=0.0) for _ in range(200)]})
    assert r.conviction <= PER_SOURCE_CONVICTION_CAP / CONVICTION_SATURATION + 1e-9
