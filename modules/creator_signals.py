"""
Elite Creator Signals — high-conviction stock calls from financial creators.

Answers ONE question: *which ticker are respected independent creators calling
right now, before the crowd?* This is deliberately different from
``modules.sentiment_radar``, which measures **aggregate** retail buzz. Here we
track a **named, hand-curated roster** — a handful of people whose calls are
worth reading — and we require agreement between them before we call anything
a signal.

Free data sources only (no API keys, no quotas, no paid tiers; the X/Twitter
API is deliberately not used because it is no longer free):

  * YouTube  — per-channel Atom feed, public and key-less:
               https://www.youtube.com/feeds/videos.xml?channel_id={UC...}
  * RSS      — any Substack / WordPress / blog feed: {domain}/feed
  * Reddit   — public JSON for a *named author*'s submissions, and per-sub
               DD-flair search:
               https://www.reddit.com/user/{u}/submitted.json?limit=50
               https://www.reddit.com/r/{sub}/search.json?q=flair:DD&...

--------------------------------------------------------------------------
Signal math (every formula unit-tested in tests/test_creator_signals.py)
--------------------------------------------------------------------------

1. Ticker extraction — ``extract_tickers(text)``
   Two confidence tiers, because they are NOT equally trustworthy:
     * ``cashtag`` ($TSLA)     confidence 1.00 — the author explicitly marked
                               it as a ticker. Trusted; the English stopword
                               list is NOT applied (so ``$PM``, ``$IT``,
                               ``$ALL``, ``$DD`` all survive), only the
                               non-equity blocklist (currencies, crypto).
     * ``bare`` (TSLA)         confidence 0.60 — inferred. Must be 2-5 chars
                               and must NOT be in ``TICKER_STOPWORDS``.
   The stopword list is the anti-hallucination guard. Without it, "THE NEW CEO
   OF AI" yields four fake tickers. The cost is real: bare ``PM``/``IT``/``ON``
   are dropped even though they are genuine tickers — we accept false
   negatives to eliminate false positives, and the cashtag path recovers them.

2. Roundup rejection — ``filter_roundup(hits)``
   An item mentioning more than ``MAX_TICKERS_PER_ITEM`` distinct tickers is a
   "top 40 stocks for 2026" listicle, not a conviction call. It contributes
   NOTHING rather than diluting every ticker it names.

3. Recency decay — ``mention_weight(age_days)``
     w = 0.5 ** (age_days / MENTION_HALF_LIFE_DAYS)      (half-life 7 days)
   0d -> 1.00, 7d -> 0.50, 14d -> 0.25. An undated item is scored as if it
   were ``UNDATED_AGE_DAYS`` old and the row is flagged ``undated-evidence`` —
   we never pretend an unknown date is "today".

4. Consensus — ``creator_consensus(mentions_by_source)``   **the integrity rule**
   Per source s (a *creator*, not a *post*):
     conv_s = min(PER_SOURCE_CONVICTION_CAP,
                  max over that source's mentions of confidence * w(age)
                  + REPEAT_BONUS * (1 - 1/n_mentions))
   so one creator posting daily cannot manufacture a signal alone.

   The per-source term is built on the creator's *best single* mention, not a sum.
   A sum lets volume defeat the time decay: six 7-day-old posts (0.5 each -> 3.0,
   capped to 1.0) would otherwise score identically to one post today. Repetition
   earns a small, saturating REPEAT_BONUS instead — it can never substitute for
   recency, and it can never reach a second creator's worth of evidence.
     conviction = clip01( sum_s(conv_s * weight_s) / CONVICTION_SATURATION )
     breadth    = clip01( (n_sources - 1) / (BREADTH_SATURATION - 1) )
                  1 creator -> 0.00, 2 -> 0.50, 3+ -> 1.00
     freshness  = w(age of the newest mention)

     score = 100 * (0.55*conviction + 0.30*breadth + 0.15*freshness)

   A ticker called by ONE creator is a **lead, not a signal**: it earns zero
   breadth AND is flagged ``single-source`` with the score capped at
   ``SINGLE_SOURCE_CAP`` (mirrors sentiment_radar's ``THIN_CONFIRM_CAP``).
   Independence is by creator id — two feeds from the same person count once.

5. Direction — ``infer_direction(text)``
   Keyword lexicon over the title/summary. Returns ``"bullish"``/``"bearish"``,
   or **None** when the lexicon is silent or tied. Never ``0``, never
   ``"neutral"`` — an undeterminable direction is missing data, and the caller
   must be able to tell the difference. Direction is reported but deliberately
   NOT scored: a high-conviction short call is just as much a signal.

6. Failure semantics (the bug we are not repeating)
   Any source whose fetch fails contributes NOTHING and **every** row in that
   scan is flagged ``partial-data`` with the score capped at
   ``PARTIAL_DATA_CAP``. We flag every row, not just some, because a source
   that did not answer might have been the second creator that would have
   confirmed — or contradicted — any ticker on the board. A missing source is
   never silently scored as agreement, and never silently scored as zero.

Everything above ``# --- I/O ---`` is pure and Streamlit-free, so the whole
scoring path is importable and testable headless.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional, Sequence

from modules.utils import log_warn, safe_float

# ---------------------------------------------------------------------------
# Endpoints & fetch policy
# ---------------------------------------------------------------------------

YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
REDDIT_USER_URL = "https://www.reddit.com/user/{user}/submitted.json?limit=50"
REDDIT_DD_URL = ("https://www.reddit.com/r/{sub}/search.json"
                 "?q=flair%3ADD&restrict_sr=1&sort=new&limit=50")

_UA = "Mozilla/5.0 (CashFlowCommandCenter CreatorSignals; personal research)"
HTTP_TIMEOUT = 12.0
MAX_RESPONSE_BYTES = 2_000_000   # a feed bigger than this is not a feed
MAX_ITEMS_PER_SOURCE = 25        # hard cap on items parsed per source
MAX_AGE_DAYS = 30.0              # older than this is history, not a signal
CACHE_TTL_SECONDS = 300.0        # module-level TTL cache (no Streamlit here)
FETCH_WORKERS = 6

# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

MENTION_HALF_LIFE_DAYS = 7.0     # a call is worth half as much a week later
UNDATED_AGE_DAYS = 7.0           # conservative stand-in for an unknown date
MIN_INDEPENDENT_SOURCES = 2      # below this it is a lead, not a signal
BREADTH_SATURATION = 3           # 3 independent creators = full breadth marks
CONVICTION_SATURATION = 2.0      # 2 fully-convinced unit-weight creators = 1.0
PER_SOURCE_CONVICTION_CAP = 1.0  # one creator can never exceed one unit
# Repeating yourself is weak evidence of conviction, not of consensus. Saturates at
# REPEAT_BONUS as n -> inf, so a spammer gains strictly less than one extra creator.
REPEAT_BONUS = 0.15
MAX_TICKERS_PER_ITEM = 8         # more than this = listicle, not a call
SINGLE_SOURCE_CAP = 45.0         # cap when only one creator called it
PARTIAL_DATA_CAP = 70.0          # cap when any source failed this scan

WEIGHTS = {
    "conviction": 0.55,   # how hard, how recently, how many creators called it
    "breadth": 0.30,      # how many INDEPENDENT creators — the integrity term
    "freshness": 0.15,    # how fresh the newest call is
}

TIER_CASHTAG = "cashtag"
TIER_BARE = "bare"
TIER_CONFIDENCE = {TIER_CASHTAG: 1.0, TIER_BARE: 0.6}

# ---------------------------------------------------------------------------
# Creator roster
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreatorSource:
    """One tracked creator feed.

    kind:  ``"youtube"``  -> ``id`` is the opaque channel id (``UC...``)
           ``"rss"``      -> ``id`` is a domain (``foo.substack.com``) or a
                             full feed URL
           ``"reddit_user"`` -> ``id`` is a username (no ``u/`` prefix)
           ``"reddit_dd"``   -> ``id`` is a subreddit name (no ``r/`` prefix);
                                pulls only DD-flaired posts
    weight: relative trust, 1.0 = baseline. Two feeds sharing an ``id`` are
            ONE creator for the independence test.
    """
    kind: str
    id: str
    display_name: str
    weight: float = 1.0


# --- USER-EDITABLE ROSTER --------------------------------------------------
# Swap these for the creators *you* actually respect — the whole point of this
# module is that it tracks a curated shortlist, not the internet.
#
# NOTE ON YOUTUBE: the RSS endpoint needs a channel's opaque ``UC...`` id,
# which cannot be derived from an @handle offline, so none are shipped as
# defaults rather than shipping guesses that would 404. To add one: open the
# channel page, view source, search ``"channelId":"UC`` — or use
# ``youtube_feed_url(<id>)`` to check the feed by hand first. Then append
#     CreatorSource("youtube", "UCxxxxxxxxxxxxxxxxxxxxxx", "Their Name", 1.0)
DEFAULT_CREATORS: list[CreatorSource] = [
    # Independent equity-research newsletters with public RSS.
    CreatorSource("rss", "thebearcave.substack.com", "The Bear Cave", 1.2),
    CreatorSource("rss", "www.netinterest.co", "Net Interest", 1.0),
    CreatorSource("rss", "www.thediff.co", "The Diff", 1.0),
    CreatorSource("rss", "alphaarchitect.com/feed/", "Alpha Architect", 0.8),
    # DD-flaired posts only — the long-form corner of each sub, not the memes.
    CreatorSource("reddit_dd", "SecurityAnalysis", "r/SecurityAnalysis DD", 1.1),
    CreatorSource("reddit_dd", "ValueInvesting", "r/ValueInvesting DD", 1.0),
    CreatorSource("reddit_dd", "stocks", "r/stocks DD", 0.8),
    CreatorSource("reddit_dd", "wallstreetbets", "r/wallstreetbets DD", 0.6),
]

# ---------------------------------------------------------------------------
# Ticker extraction
# ---------------------------------------------------------------------------

# Uppercase English words, internet-speak and finance jargon that are NOT
# tickers. Applied to BARE words only — cashtags bypass this list entirely.
TICKER_STOPWORDS: frozenset[str] = frozenset("""
A I AN AS AT BE BY DO GO IF IN IS IT MY NO OF OK ON OR SO TO UP US WE HE ME
AM PM AH ID OH EX RE VS
THE ALL AND ANY ARE BAD BET BIG BUT BUY CAN DAY DID DIP END FAR FEW FOR GET GOT
HAS HAD HER HIM HIS HOT HOW ITS LET LOT LOW MAN MAY NEW NOT NOW OFF OLD ONE
OUR OUT OWN PER PUT RED RUN SAW SAY SEE SET SHE TOO TOP TWO USE VIA WAS WAY
WHO WHY WIN YES YET YOU
ALSO BACK BEEN BEST BOTH BULL BEAR CALL CASH DEBT DOWN EACH EASY EDIT ELSE
EVEN EVER FACT FEAR FREE FROM FULL GAIN GOOD GROW HAVE HERE HIGH HOLD HUGE
IDEA INTO JUST KEEP KNOW LAST LESS LIKE LONG LOOK LOSS MADE MAKE MANY MORE
MOST MOVE MUCH MUST NEAR NEED NEWS NEXT NICE NONE NOTE ONLY OPEN OVER PAID
SAID SAYS SEES DOES DONE GONE KEPT HELD SOLD LEFT ONCE UPON THUS THAN WHOM
PART PICK PLAN PLAY POST PUTS REAL RISK SAME SEEN SELL SOLD SOME SOON SUCH
SURE TAKE THAN THAT THEM THEN THEY THIS TIME TRUE TURN VERY WANT WEAK WELL
WENT WERE WHAT WHEN WILL WITH YOUR ZERO
ABOUT AFTER AGAIN ALPHA ASSET AVOID BEARS BELOW BONDS BOUGHT BRAND BUILD
BULLS CALLS CHART CHEAP CLOSE COULD COVER CRASH DEALS EARLY EVERY FIRST FOCUS
GOING GREAT GROSS GUIDE HEARD HEAVY HOLDS HOUSE HYPED INDEX ISSUE LARGE LATER
LEVEL LOWER MAJOR MARCH MONEY MONTH NEVER OFTEN OTHER OWNED PANIC PEAKS PLAYS
POINT PRICE QUICK RALLY RANGE RATIO RIGHT RISKY SALES SHARE SHORT SINCE SMALL
SOLID SPEND STILL STOCK TAKES THEIR THERE THESE THING THINK THOSE TODAY TOTAL
TRADE TREND UNDER UNTIL VALUE WATCH WHERE WHICH WHILE WORTH WOULD YIELD
CEO CFO COO CTO CIO CMO EPS PEG ROI ROE ROIC EBIT GAAP YOY QOQ TTM CAGR FCF
CAPEX OPEX MOIC NAV AUM DCF WACC EBIT
ETF ETFS IPO SPAC LEAP LEAPS ITM OTM ATM ATH ATL IV DTE OI PT TP SL TA FA
RSI MACD SMA EMA VWAP DMA ADX ATR
DD YOLO FOMO HODL MOASS WSB IMO IMHO TLDR TLDR LOL WTF OMG FYI ASAP AKA ETA
BTW IIRC NGL AFAIK EOD EOW EOY YTD MTD QTD FY
AI ML EV VR AR IOT LLM LLMS GPT GPU CPU API APIS SAAS B2B B2C RD IPOS
FED FOMC SEC FDA DOJ FTC IRS CPI PPI PCE GDP QE QT NYSE OTC
USA USD UK EU CN JP UAE NATO
Q1 Q2 Q3 Q4 H1 H2 FY24 FY25 FY26 1H 2H
CNBC WSJ NYT FT BBC CNN
""".split())

# Cashtags are trusted, but these are not equities.
NON_EQUITY_CASHTAGS: frozenset[str] = frozenset(
    "USD EUR GBP JPY CAD AUD CHF CNY INR BTC ETH SOL XRP DOGE USDT USDC".split()
)

# ``$`` + 1-5 alphanumerics starting with a letter, not glued to more word chars.
_CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{0,4})(?![A-Za-z0-9])")
# Bare uppercase run of 2-5 chars, not preceded by $ / word char / dot.
_BARE_RE = re.compile(r"(?<![A-Za-z0-9$.])([A-Z][A-Z0-9]{1,4})(?![A-Za-z0-9])")

_BULL_LEXICON = (
    "bullish", "buy", "buying", "long", "longs", "calls", "undervalued",
    "cheap", "accumulate", "accumulating", "adding", "upside", "breakout",
    "moon", "rip", "multibagger", "top pick", "conviction", "load up",
    "oversold", "turnaround", "beat", "outperform", "upgrade", "upgraded",
)
_BEAR_LEXICON = (
    "bearish", "short", "shorting", "shorts", "puts", "overvalued",
    "expensive", "sell", "selling", "avoid", "crash", "downside", "bubble",
    "trim", "trimming", "exit", "exiting", "fraud", "scam", "collapse",
    "overbought", "miss", "missed", "underperform", "downgrade", "downgraded",
    "red flag", "red flags", "warning",
)
_BULL_RE = re.compile(r"\b(" + "|".join(_BULL_LEXICON) + r")\b", re.IGNORECASE)
_BEAR_RE = re.compile(r"\b(" + "|".join(_BEAR_LEXICON) + r")\b", re.IGNORECASE)


@dataclass(frozen=True)
class TickerHit:
    """One ticker found in one piece of text, with how much we trust it."""
    symbol: str
    tier: str
    confidence: float


def clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def extract_tickers(text: Optional[str]) -> list[TickerHit]:
    """Tickers mentioned in ``text``, cashtags first, deduped by symbol.

    Cashtags ($TSLA) are returned at confidence 1.0 and skip the English
    stopword list — the ``$`` is the author explicitly saying "this is a
    ticker". Bare uppercase words are returned at confidence 0.6, must be 2-5
    characters, and must survive ``TICKER_STOPWORDS``.

    When a symbol appears both ways, the cashtag (higher confidence) wins.
    Returns ``[]`` for empty/None text — never a guess.
    """
    if not text:
        return []
    s = str(text)
    out: dict[str, TickerHit] = {}

    for m in _CASHTAG_RE.finditer(s):
        sym = m.group(1).upper()
        if sym in NON_EQUITY_CASHTAGS:
            continue
        out.setdefault(sym, TickerHit(sym, TIER_CASHTAG, TIER_CONFIDENCE[TIER_CASHTAG]))

    for m in _BARE_RE.finditer(s):
        sym = m.group(1).upper()
        if len(sym) < 2 or len(sym) > 5:
            continue
        if sym in TICKER_STOPWORDS or sym in NON_EQUITY_CASHTAGS:
            continue
        if sym in out:
            continue
        out[sym] = TickerHit(sym, TIER_BARE, TIER_CONFIDENCE[TIER_BARE])

    return list(out.values())


def filter_roundup(hits: Sequence[TickerHit],
                   max_tickers: int = MAX_TICKERS_PER_ITEM) -> list[TickerHit]:
    """Drop the whole item when it names more than ``max_tickers`` symbols.

    "My top 30 stocks for 2026" is a listicle, not a conviction call. Letting
    it through would hand every one of those 30 tickers free evidence.
    """
    hits = list(hits)
    return [] if len(hits) > max_tickers else hits


def infer_direction(text: Optional[str]) -> Optional[str]:
    """``"bullish"`` / ``"bearish"`` / ``None``.

    ``None`` means *undeterminable* — no lexicon hits, or an exact tie. It is
    deliberately not ``"neutral"`` and not ``0``: the caller must be able to
    distinguish "the creator was balanced" from "we could not tell".
    """
    if not text:
        return None
    bull = len(_BULL_RE.findall(str(text)))
    bear = len(_BEAR_RE.findall(str(text)))
    if bull == bear:
        return None
    return "bullish" if bull > bear else "bearish"


def aggregate_direction(directions: Iterable[Optional[str]]) -> Optional[str]:
    """Majority direction across mentions; ``None`` on a tie or no opinions."""
    bull = bear = 0
    for d in directions:
        if d == "bullish":
            bull += 1
        elif d == "bearish":
            bear += 1
    if bull == bear:
        return None
    return "bullish" if bull > bear else "bearish"


# ---------------------------------------------------------------------------
# Recency
# ---------------------------------------------------------------------------

def mention_weight(age_days: Optional[float]) -> float:
    """Exponential decay, half-life ``MENTION_HALF_LIFE_DAYS`` (7d).

    0d -> 1.0, 7d -> 0.5, 14d -> 0.25. ``None`` (undated item) is scored as
    ``UNDATED_AGE_DAYS`` old rather than as fresh; callers flag the row.
    Future-dated items (clock skew) are clamped to age 0, never > 1.0.
    """
    age = UNDATED_AGE_DAYS if age_days is None else safe_float(age_days, UNDATED_AGE_DAYS)
    age = max(0.0, age)
    return clip01(0.5 ** (age / MENTION_HALF_LIFE_DAYS))


def age_in_days(published: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    """Age of a timestamp in days, or ``None`` when the date is unknown."""
    if published is None:
        return None
    ref = now or datetime.now(timezone.utc)
    try:
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return (ref - published).total_seconds() / 86400.0
    except (TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Consensus
# ---------------------------------------------------------------------------

@dataclass
class CreatorMention:
    """One ticker, called by one creator, in one item."""
    ticker: str
    source_id: str
    source_name: str = ""
    source_weight: float = 1.0
    tier: str = TIER_BARE
    confidence: float = TIER_CONFIDENCE[TIER_BARE]
    age_days: Optional[float] = None       # None == date unknown, not "today"
    direction: Optional[str] = None
    title: str = ""
    url: str = ""


@dataclass
class ConsensusResult:
    score: float = 0.0            # 0-100, integrity caps already applied
    conviction: float = 0.0       # 0-1 component
    breadth: float = 0.0          # 0-1 component
    freshness: float = 0.0        # 0-1 component
    source_count: int = 0         # distinct creator ids that contributed
    mention_count: int = 0
    flags: list[str] = field(default_factory=list)


def breadth_component(source_count: int) -> float:
    """1 creator -> 0.0, 2 -> 0.5, 3+ -> 1.0.

    A lone creator earns *zero* breadth. Combined with ``SINGLE_SOURCE_CAP``
    this is the module's core rule: one voice is a lead, not a signal.
    """
    n = int(source_count or 0)
    if n <= 1:
        return 0.0
    return clip01((n - 1) / float(BREADTH_SATURATION - 1))


def creator_consensus(
    mentions_by_source: Mapping[str, Sequence[CreatorMention]],
    partial_data: bool = False,
) -> ConsensusResult:
    """Score one ticker from its mentions, grouped by creator id.

    Independence is enforced by the grouping key: all mentions from creator X
    collapse into one capped contribution, so a prolific poster cannot
    manufacture consensus with themselves.

    Flags:
      ``single-source``     fewer than ``MIN_INDEPENDENT_SOURCES`` creators
                            -> score capped at ``SINGLE_SOURCE_CAP``
      ``partial-data``      caller reported a failed fetch this scan
                            -> score capped at ``PARTIAL_DATA_CAP``
      ``undated-evidence``  at least one item had no usable timestamp
      ``bare-mentions-only``no cashtag anywhere — inferred tickers only
      ``no-evidence``       nothing contributed (score stays 0)
    """
    res = ConsensusResult()
    weighted_sum = 0.0
    newest_age: Optional[float] = None
    saw_dated = False
    undated = False
    saw_cashtag = False

    for src_id, mentions in (mentions_by_source or {}).items():
        items = [m for m in (mentions or []) if m is not None]
        if not items:
            continue                      # a source with nothing to say is not a source
        res.source_count += 1
        res.mention_count += len(items)
        src_weight = max(0.0, safe_float(getattr(items[0], "source_weight", 1.0), 1.0))
        best = 0.0
        for m in items:
            conf = clip01(safe_float(m.confidence, 0.0))
            # Best single mention — a sum here would let volume out-vote the decay.
            best = max(best, conf * mention_weight(m.age_days))
            if m.tier == TIER_CASHTAG:
                saw_cashtag = True
            if m.age_days is None:
                undated = True
            else:
                a = safe_float(m.age_days, UNDATED_AGE_DAYS)
                saw_dated = True
                newest_age = a if newest_age is None else min(newest_age, a)
        # Saturating repeat term: 1 mention -> +0, 2 -> +half, inf -> +REPEAT_BONUS.
        repeat = REPEAT_BONUS * (1.0 - 1.0 / len(items)) if best > 0 else 0.0
        weighted_sum += min(PER_SOURCE_CONVICTION_CAP, best + repeat) * src_weight

    if res.source_count == 0:
        res.flags.append("no-evidence")
        if partial_data:
            res.flags.append("partial-data")
        return res

    res.conviction = clip01(weighted_sum / CONVICTION_SATURATION)
    res.breadth = breadth_component(res.source_count)
    # No dated item anywhere -> freshness falls back to the undated default,
    # exactly like mention_weight(None). We do not assume "today".
    res.freshness = mention_weight(newest_age if saw_dated else None)

    raw_score = 100.0 * (
        WEIGHTS["conviction"] * res.conviction
        + WEIGHTS["breadth"] * res.breadth
        + WEIGHTS["freshness"] * res.freshness
    )

    if res.source_count < MIN_INDEPENDENT_SOURCES:
        res.flags.append("single-source")
        raw_score = min(raw_score, SINGLE_SOURCE_CAP)
    if partial_data:
        res.flags.append("partial-data")
        raw_score = min(raw_score, PARTIAL_DATA_CAP)
    if undated:
        res.flags.append("undated-evidence")
    if not saw_cashtag:
        res.flags.append("bare-mentions-only")

    res.score = round(raw_score, 1)
    return res


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

@dataclass
class CreatorRow:
    ticker: str
    score: float = 0.0
    conviction: float = 0.0
    breadth: float = 0.0
    freshness: float = 0.0
    source_count: int = 0
    mention_count: int = 0
    sources: list[str] = field(default_factory=list)   # display names, sorted
    direction: Optional[str] = None                    # None == undeterminable
    newest_age_days: Optional[float] = None
    top_title: Optional[str] = None
    top_url: Optional[str] = None
    flags: list[str] = field(default_factory=list)


def build_creator_rows(
    mentions: Sequence[CreatorMention],
    failed_source_ids: Sequence[str] = (),
    min_score: float = 0.0,
    limit: Optional[int] = None,
) -> list[CreatorRow]:
    """Group mentions into ranked, scored, flagged rows. Pure given inputs.

    ``failed_source_ids`` is the list of creators whose fetch failed. Any
    failure flags **every** row ``partial-data`` and caps it: a source that did
    not answer could have been the confirming — or contradicting — second
    voice for any ticker on this board. Failures never quietly score 0.

    Ranking: score desc, then ticker asc for a stable, reproducible board.
    """
    partial = bool(failed_source_ids)
    grouped: dict[str, dict[str, list[CreatorMention]]] = {}
    for m in mentions or []:
        if m is None or not m.ticker:
            continue
        grouped.setdefault(m.ticker.upper(), {}).setdefault(m.source_id, []).append(m)

    rows: list[CreatorRow] = []
    for ticker, by_source in grouped.items():
        res = creator_consensus(by_source, partial_data=partial)
        flat = [m for ms in by_source.values() for m in ms]
        dated = [safe_float(m.age_days, UNDATED_AGE_DAYS)
                 for m in flat if m.age_days is not None]
        # Headline evidence = the freshest, most-trusted mention.
        best = min(flat, key=lambda m: (
            -m.confidence,
            UNDATED_AGE_DAYS if m.age_days is None else safe_float(m.age_days, UNDATED_AGE_DAYS),
        ))
        rows.append(CreatorRow(
            ticker=ticker,
            score=res.score,
            conviction=round(res.conviction, 4),
            breadth=round(res.breadth, 4),
            freshness=round(res.freshness, 4),
            source_count=res.source_count,
            mention_count=res.mention_count,
            sources=sorted({(m.source_name or m.source_id) for m in flat}),
            direction=aggregate_direction(m.direction for m in flat),
            newest_age_days=(min(dated) if dated else None),
            top_title=best.title or None,
            top_url=best.url or None,
            flags=list(res.flags),
        ))

    rows = [r for r in rows if r.score >= min_score]
    rows.sort(key=lambda r: (-r.score, r.ticker))
    return rows[:limit] if limit else rows


def verdict_for_row(r: CreatorRow) -> str:
    """One plain-English line — what to actually do with this row."""
    if "no-evidence" in r.flags:
        return "❄️ Nothing here"
    if "single-source" in r.flags:
        return "🔍 One creator only — a lead, not a signal. Wait for a second voice."
    if "partial-data" in r.flags and r.score < 50:
        return "⚠️ A source didn't answer — score is capped, re-scan later"
    side = "" if r.direction is None else (" (bullish)" if r.direction == "bullish"
                                           else " (bearish)")
    if r.score >= 75:
        return f"🔥 Multiple respected creators, fresh calls{side} — research today"
    if r.score >= 55:
        return f"👀 Real cross-creator agreement{side} — put on watch"
    if r.score >= 35:
        return f"🌤️ Some agreement, going stale{side} — low priority"
    return "💤 Faint chatter — ignore"


# ---------------------------------------------------------------------------
# --- I/O --- everything below touches the network. Injectable everywhere so
# tests never open a socket.
# ---------------------------------------------------------------------------

@dataclass
class RawItem:
    """One post/video/article before ticker extraction."""
    title: str = ""
    summary: str = ""
    url: str = ""
    published: Optional[datetime] = None


_CACHE: dict[str, tuple[float, str]] = {}
_MISS = object()


def _cache_get(key: str, ttl: float = CACHE_TTL_SECONDS):
    hit = _CACHE.get(key)
    if not hit:
        return _MISS
    stamp, value = hit
    if (time.time() - stamp) > ttl:
        _CACHE.pop(key, None)
        return _MISS
    return value


def _cache_put(key: str, value: str) -> None:
    _CACHE[key] = (time.time(), value)


def clear_cache() -> None:
    """Drop the TTL cache (tests, and the UI's 'force refresh')."""
    _CACHE.clear()


def _get_text(url: str, timeout: float = HTTP_TIMEOUT) -> Optional[str]:
    """GET a URL as text, TTL-cached. ``None`` on ANY failure — never a guess.

    Failures are deliberately not cached, so a transient blip does not poison
    the next five minutes of scans.
    """
    cached = _cache_get(url)
    if cached is not _MISS:
        return cached  # type: ignore[return-value]
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "application/atom+xml, application/rss+xml, application/json, text/xml, */*",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_RESPONSE_BYTES)
        text = body.decode("utf-8", errors="replace")
    except Exception as exc:
        log_warn(f"creator fetch {url}", exc)
        return None
    _cache_put(url, text)
    return text


def _get_json(url: str, timeout: float = HTTP_TIMEOUT) -> Optional[dict]:
    text = _get_text(url, timeout)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except Exception as exc:
        log_warn(f"creator json {url}", exc)
        return None
    return data if isinstance(data, dict) else None


# --- URL builders ----------------------------------------------------------

def youtube_feed_url(channel_id: str) -> str:
    return YOUTUBE_FEED_URL.format(cid=str(channel_id).strip())


def rss_feed_url(id_or_url: str) -> str:
    """Accept a bare domain, a domain+path, or a full feed URL."""
    s = str(id_or_url).strip().rstrip("/")
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    tail = s.rsplit("/", 1)[-1].lower()
    if tail in ("feed", "rss", "atom") or tail.endswith((".xml", ".rss", ".atom")):
        return s
    return s + "/feed"


def reddit_user_url(username: str) -> str:
    return REDDIT_USER_URL.format(user=str(username).strip().lstrip("u/"))


def reddit_dd_url(sub: str) -> str:
    return REDDIT_DD_URL.format(sub=str(sub).strip().lstrip("r/"))


def source_url(src: CreatorSource) -> Optional[str]:
    """Resolve a source to its single fetch URL, or ``None`` if unsupported."""
    if src.kind == "youtube":
        return youtube_feed_url(src.id)
    if src.kind == "rss":
        return rss_feed_url(src.id)
    if src.kind == "reddit_user":
        return reddit_user_url(src.id)
    if src.kind == "reddit_dd":
        return reddit_dd_url(src.id)
    return None


# --- Parsers (pure; unit-tested with fixture payloads) ---------------------

def _localname(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    """ISO-8601 (Atom) or RFC-822 (RSS) -> aware datetime, else ``None``."""
    if not raw:
        return None
    s = str(raw).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s)
    except Exception:
        return None


def parse_feed(xml_text: Optional[str],
               max_items: int = MAX_ITEMS_PER_SOURCE) -> Optional[list[RawItem]]:
    """Parse Atom (YouTube) or RSS 2.0 (Substack/blogs) into ``RawItem``s.

    Namespace-agnostic: matches on element local-names, so YouTube's Atom +
    media extensions and plain RSS both work through one code path.
    Returns ``None`` when the payload is not parseable XML — an EMPTY feed is
    a valid, distinguishable result (``[]``), not a failure.
    """
    if not xml_text:
        return None
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        log_warn("creator feed parse", exc)
        return None

    entries = [el for el in root.iter() if _localname(el.tag) in ("entry", "item")]
    items: list[RawItem] = []
    for el in entries[:max_items]:
        title = url = summary = ""
        date_raw = None
        for child in el.iter():
            name = _localname(child.tag)
            if child is el:
                continue
            text = (child.text or "").strip()
            if name == "title" and not title:
                title = text
            elif name == "link" and not url:
                url = (child.attrib.get("href") or text or "").strip()
            elif name in ("description", "summary", "content", "encoded") and not summary:
                summary = text
            elif name in ("published", "pubdate", "updated", "date") and date_raw is None:
                date_raw = text
        items.append(RawItem(title=title, summary=summary, url=url,
                             published=_parse_date(date_raw)))
    return items


def parse_reddit_listing(data: Optional[dict],
                         max_items: int = MAX_ITEMS_PER_SOURCE) -> Optional[list[RawItem]]:
    """Reddit listing JSON -> ``RawItem``s. ``None`` if the shape is wrong."""
    if not isinstance(data, dict):
        return None
    children = ((data.get("data") or {}).get("children")
                if isinstance(data.get("data"), dict) else None)
    if not isinstance(children, list):
        return None
    items: list[RawItem] = []
    for child in children[:max_items]:
        d = (child or {}).get("data") if isinstance(child, dict) else None
        if not isinstance(d, dict):
            continue
        created = d.get("created_utc")
        published = None
        if created is not None:
            try:
                published = datetime.fromtimestamp(float(created), tz=timezone.utc)
            except (TypeError, ValueError, OSError, OverflowError):
                published = None
        permalink = str(d.get("permalink") or "")
        items.append(RawItem(
            title=str(d.get("title") or ""),
            summary=str(d.get("selftext") or "")[:4000],
            url=("https://www.reddit.com" + permalink) if permalink else str(d.get("url") or ""),
            published=published,
        ))
    return items


# --- Fetchers --------------------------------------------------------------

def fetch_youtube_channel(channel_id: str) -> Optional[list[RawItem]]:
    return parse_feed(_get_text(youtube_feed_url(channel_id)))


def fetch_rss(id_or_url: str) -> Optional[list[RawItem]]:
    return parse_feed(_get_text(rss_feed_url(id_or_url)))


def fetch_reddit_user(username: str) -> Optional[list[RawItem]]:
    return parse_reddit_listing(_get_json(reddit_user_url(username)))


def fetch_reddit_dd(sub: str) -> Optional[list[RawItem]]:
    return parse_reddit_listing(_get_json(reddit_dd_url(sub)))


def fetch_source(src: CreatorSource) -> Optional[list[RawItem]]:
    """Dispatch one source to its fetcher. ``None`` == failure (never ``[]``)."""
    try:
        if src.kind == "youtube":
            return fetch_youtube_channel(src.id)
        if src.kind == "rss":
            return fetch_rss(src.id)
        if src.kind == "reddit_user":
            return fetch_reddit_user(src.id)
        if src.kind == "reddit_dd":
            return fetch_reddit_dd(src.id)
    except Exception as exc:
        log_warn(f"creator source {src.kind}:{src.id}", exc)
        return None
    log_warn(f"creator source {src.kind}:{src.id}", ValueError("unknown source kind"))
    return None


def collect_mentions(
    sources: Sequence[CreatorSource] = (),
    now: Optional[datetime] = None,
    fetcher=fetch_source,
    max_items_per_source: int = MAX_ITEMS_PER_SOURCE,
    max_age_days: float = MAX_AGE_DAYS,
    max_workers: int = FETCH_WORKERS,
) -> tuple[list[CreatorMention], list[str]]:
    """Fetch every source in parallel and flatten to ``CreatorMention``s.

    Returns ``(mentions, failed_source_ids)``. ``fetcher`` is injectable so
    tests (and dry runs) never touch the network.

    Efficiency & integrity:
      * sources deduped by resolved URL — the same feed listed twice is fetched
        and counted once, which also protects the independence test;
      * at most ``max_items_per_source`` items parsed per source;
      * items older than ``max_age_days`` dropped (history, not signal);
      * identical item URLs deduped globally (syndicated / cross-posted);
      * listicle items dropped by ``filter_roundup``;
      * a source returning ``None`` is a FAILURE and lands in
        ``failed_source_ids``; a source returning ``[]`` genuinely had nothing
        to say and is NOT a failure.
    """
    from concurrent.futures import ThreadPoolExecutor

    unique: list[CreatorSource] = []
    seen_urls: set[str] = set()
    for src in sources or []:
        url = source_url(src)
        key = url or f"{src.kind}:{src.id}"
        if key in seen_urls:
            continue
        seen_urls.add(key)
        unique.append(src)

    if not unique:
        return [], []

    with ThreadPoolExecutor(max_workers=max(1, min(len(unique), max_workers))) as ex:
        results = list(ex.map(fetcher, unique))

    mentions: list[CreatorMention] = []
    failed: list[str] = []
    seen_items: set[str] = set()

    for src, items in zip(unique, results):
        if items is None:
            failed.append(src.id)
            continue
        for item in list(items)[:max_items_per_source]:
            if item is None:
                continue
            if item.url:
                if item.url in seen_items:
                    continue
                seen_items.add(item.url)
            age = age_in_days(item.published, now)
            if age is not None and age > max_age_days:
                continue
            text = f"{item.title or ''}\n{item.summary or ''}"
            hits = filter_roundup(extract_tickers(text))
            if not hits:
                continue
            direction = infer_direction(text)
            for hit in hits:
                mentions.append(CreatorMention(
                    ticker=hit.symbol,
                    source_id=src.id,
                    source_name=src.display_name,
                    source_weight=safe_float(src.weight, 1.0),
                    tier=hit.tier,
                    confidence=hit.confidence,
                    age_days=age,
                    direction=direction,
                    title=item.title or "",
                    url=item.url or "",
                ))
    return mentions, failed


def scan_creators(
    sources: Optional[Sequence[CreatorSource]] = None,
    now: Optional[datetime] = None,
    fetcher=fetch_source,
    limit: Optional[int] = None,
) -> tuple[list[CreatorRow], dict]:
    """End-to-end scan -> (ranked rows, health dict). Network unless injected."""
    srcs = list(DEFAULT_CREATORS if sources is None else sources)
    mentions, failed = collect_mentions(srcs, now=now, fetcher=fetcher)
    rows = build_creator_rows(mentions, failed_source_ids=failed, limit=limit)
    health = {s.display_name: (s.id not in failed) for s in srcs}
    return rows, health


# ---------------------------------------------------------------------------
# Streamlit tab — imported inside the function so the logic above stays
# headless-importable (``from modules.creator_signals import *`` needs no UI).
# ---------------------------------------------------------------------------

def render_creator_signals_tab(sources: Optional[Sequence[CreatorSource]] = None) -> None:
    """No-fail outer shell: whatever breaks inside, the app never crashes."""
    import streamlit as st
    try:
        _render_creator_signals_tab(sources)
    except Exception as exc:
        st.error("🎙️ Creator Signals hit an unexpected error this scan. "
                 "Your other tabs are unaffected — try again in a minute.")
        with st.expander("Technical details"):
            st.code(repr(exc))


def _render_creator_signals_tab(sources: Optional[Sequence[CreatorSource]] = None) -> None:
    import streamlit as st
    import pandas as pd

    st.markdown('<div id="creators" style="position:relative;top:-80px"></div>',
                unsafe_allow_html=True)
    st.markdown("### 🎙️ Elite Creator Signals")
    st.caption(
        "**Which ticker are respected independent creators calling right now?** "
        "Free sources only (YouTube RSS, Substack/blog RSS, public Reddit JSON). "
        "One creator = a lead. Two or more independent creators = a signal. "
        "Research leads, never buy signals."
    )

    if not st.button("🎙️ Scan Creators", type="primary", key="cs_scan"):
        cached = st.session_state.get("cs_results")
        if cached is None:
            st.caption("Press **Scan Creators** — takes ~10-20s.")
            return
        rows, health = cached["rows"], cached["health"]
    else:
        with st.spinner("Reading creator feeds in parallel..."):
            rows, health = scan_creators(sources)
        st.session_state["cs_results"] = {"rows": rows, "health": health}

    down = [name for name, ok in (health or {}).items() if not ok]
    if down:
        st.info("These feeds didn't answer this scan: " + ", ".join(down) +
                ". Every row below is flagged `partial-data` and score-capped — "
                "missing evidence is never scored as agreement.")
    else:
        st.caption("✅ Every configured creator feed answered this scan.")

    if not rows:
        st.caption("No tickers called by your roster in the last "
                   f"{MAX_AGE_DAYS:.0f} days.")
        return

    st.dataframe(pd.DataFrame([{
        "Ticker": r.ticker,
        "Verdict": verdict_for_row(r),
        "Score": r.score,
        "Creators": r.source_count,
        "Who": ", ".join(r.sources),
        "Direction": r.direction or "unclear",
        "Newest": ("unknown" if r.newest_age_days is None
                   else f"{r.newest_age_days:.1f}d ago"),
        "Flags": ", ".join(r.flags) if r.flags else "clean",
    } for r in rows]), use_container_width=True, hide_index=True,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f",
                help="0-100. 55% conviction (how hard/recently creators called it) "
                     f"+ 30% breadth (independent creators; 1 caps at "
                     f"{SINGLE_SOURCE_CAP:.0f}) + 15% freshness."),
            "Direction": st.column_config.TextColumn(
                "Direction",
                help="'unclear' means the wording didn't state a side — it is "
                     "NOT the same as neutral."),
        })
