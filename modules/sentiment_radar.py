"""
Sentiment Radar — retail-buzz asymmetric signal engine (Asymmetrix-style).

Free data sources (no API keys, no subscriptions):
  * ApeWisdom  — pre-aggregated Reddit ticker mentions (r/wsb + all-stocks)
                 https://apewisdom.io/api/v1.0/filter/{filter}/page/{n}
  * StockTwits — per-symbol stream with user-labeled Bullish/Bearish tags
                 https://api.stocktwits.com/api/2/streams/symbol/{sym}.json
  * Reddit     — public JSON endpoints, used as a CROSS-CHECK on ApeWisdom
                 (mention counts re-derived independently from hot posts)
  * Yahoo      — price/volume via modules.data.fetch_stock (already in app)

Signal math (every formula unit-tested in tests/test_sentiment_radar.py):

  1. Mention velocity  v = mentions_now / max(1, mentions_24h_ago)
     vel_component = clip(log10(v), 0, 1)         # v=1 -> 0, v>=10 -> 1

  2. Sentiment conviction — Wilson score LOWER bound (95%, z=1.96) of the
     bullish proportion from StockTwits labeled messages. This is the
     anti-hallucination guard: 2-of-2 bullish msgs is NOT "100% bullish";
     Wilson(2/2) ~= 0.34, while Wilson(40/50) ~= 0.67.

  3. Volume anomaly  z = (vol_today - mean(prev 30)) / std(prev 30, ddof=1)
     volz_component = clip(z / 4, 0, 1)           # z>=4 -> saturated

  4. Earliness (are we late?)  r = close/close_5d_ago - 1
     early_component = clip(1 - |r| / 0.30, 0, 1) # +/-30% in 5d -> 0 (late)

  Composite Asymmetric Score (0-100):
     score = 100 * (0.35*vel + 0.25*wilson + 0.25*volz + 0.15*early)

  Cross-source integrity rules (anti-hallucination):
     * ApeWisdom hot (v >= 2) but StockTwits < MIN_CONFIRM_MSGS messages
       -> flag "thin-confirmation", score capped at 60.
     * Independent Reddit re-count disagrees with ApeWisdom by > 5x in
       either direction (when both have data) -> flag "source-disagreement",
       score capped at 50.
     * Any source fetch failure -> that component scores 0 and the ticker
       row is flagged "partial-data" — we never invent missing data.
"""
from __future__ import annotations

import json
import math
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/{flt}/page/{page}"
STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"
REDDIT_HOT_URL = "https://www.reddit.com/r/{sub}/hot.json?limit=100"
_UA = "Mozilla/5.0 (CashFlowCommandCenter SentimentRadar; personal research)"

WILSON_Z = 1.96          # 95% confidence
VOL_LOOKBACK = 30        # sessions for volume baseline
VOLZ_SATURATION = 4.0    # z-score that earns full volume marks
EARLY_ROC_DAYS = 5
EARLY_ROC_LIMIT = 0.30   # +/-30% in 5 sessions == fully "late"
MIN_CONFIRM_MSGS = 3     # StockTwits msgs needed to confirm a Reddit spike
THIN_CONFIRM_CAP = 60.0
DISAGREE_RATIO = 5.0
DISAGREE_CAP = 50.0
TRENDS_SATURATION = 3.0  # search interest 3x its own baseline = full marks
WEIGHTS = {
    "velocity": 0.30,   # Reddit mention acceleration (+ rank-jump evidence)
    "wilson": 0.20,     # StockTwits bullish conviction, small-sample discounted
    "volume_z": 0.20,   # real money confirmation vs 30d baseline
    "earliness": 0.15,  # price hasn't moved yet = the asymmetry
    "trends": 0.15,     # Google search attention — the cross-platform echo
}                        # (captures X/Twitter, TikTok, news spikes indirectly:
                         #  attention anywhere ends up as ticker searches)

# ---------------------------------------------------------------------------
# Pure math — no I/O, no Streamlit. Everything here is unit-tested.
# ---------------------------------------------------------------------------

def clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def mention_velocity(mentions_now: float, mentions_prev: float) -> float:
    """Ratio of current to prior-period mentions. Prior floored at 1."""
    m_now = max(0.0, float(mentions_now or 0))
    m_prev = max(1.0, float(mentions_prev or 0))
    return m_now / m_prev


RANK_JUMP_SPOTS = 20     # climbing this many ApeWisdom rank spots in 24h...
RANK_JUMP_BONUS = 0.15   # ...adds this to the velocity component (then capped)


def velocity_component(v: float, rank: Optional[int] = None,
                       rank_prev: Optional[int] = None) -> float:
    """log10 scaling: v=1 -> 0, v=10 -> 1, capped both ends.

    Secondary evidence: a jump of >= RANK_JUMP_SPOTS up the ApeWisdom
    leaderboard in 24h adds RANK_JUMP_BONUS. Rank is an independent,
    scale-free confirmation — raw counts can be noisy for small tickers,
    but climbing 20+ spots means the ticker is out-pacing the whole board.
    """
    base = math.log10(v) if v > 0 else 0.0
    bonus = 0.0
    if rank is not None and rank_prev is not None and (rank_prev - rank) >= RANK_JUMP_SPOTS:
        bonus = RANK_JUMP_BONUS
    return clip01(base + bonus)


def wilson_lower_bound(positives: int, total: int, z: float = WILSON_Z) -> float:
    """95% Wilson score interval lower bound for a Bernoulli proportion.

    Standard form (Wilson 1927):
      ( p + z^2/2n - z*sqrt( p(1-p)/n + z^2/4n^2 ) ) / ( 1 + z^2/n )
    Returns 0 when total == 0 (no data is NOT bullish).
    """
    n = int(total)
    if n <= 0:
        return 0.0
    p = min(max(int(positives), 0), n) / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * n * n)))
    return max(0.0, (centre - margin) / denom)


def volume_zscore(vol_today: float, prior_vols: list[float]) -> Optional[float]:
    """z of today's volume vs prior sessions (sample std, ddof=1).

    Returns None when there is not enough data or zero variance —
    caller must treat None as "no signal", never as 0-is-normal.
    """
    prior = [float(v) for v in prior_vols if v is not None and float(v) >= 0]
    if vol_today is None or len(prior) < 5:
        return None
    n = len(prior)
    mean = sum(prior) / n
    var = sum((v - mean) ** 2 for v in prior) / (n - 1)
    std = math.sqrt(var)
    if std <= 0:
        return None
    return (float(vol_today) - mean) / std


def volume_component(z: Optional[float]) -> float:
    if z is None or z <= 0:
        return 0.0
    return clip01(z / VOLZ_SATURATION)


def earliness_component(roc_5d: Optional[float]) -> float:
    """1 == price hasn't moved yet (early); 0 == already ran +/-30% in 5d."""
    if roc_5d is None:
        return 0.0
    return clip01(1.0 - abs(float(roc_5d)) / EARLY_ROC_LIMIT)


def trends_ratio(recent_mean: Optional[float], baseline_mean: Optional[float]) -> Optional[float]:
    """Google Trends: last-7-day mean interest vs the prior-baseline mean.

    Returns None (no signal) when either side is missing or baseline is ~0 —
    a dead baseline would make any blip look infinite.
    """
    if recent_mean is None or baseline_mean is None:
        return None
    if baseline_mean <= 1e-9:
        return None
    return max(0.0, float(recent_mean)) / float(baseline_mean)


def trends_component(ratio: Optional[float]) -> float:
    """ratio<=1 (search flat or falling) -> 0; ratio>=3x -> 1; linear between.

    (ratio-1)/(TRENDS_SATURATION-1): 2x -> 0.5, 3x -> 1.0.
    """
    if ratio is None or ratio <= 1.0:
        return 0.0
    return clip01((ratio - 1.0) / (TRENDS_SATURATION - 1.0))


def composite_score(
    vel_c: float, wilson_c: float, volz_c: float, early_c: float,
    trends_c: float = 0.0,
    thin_confirmation: bool = False, source_disagreement: bool = False,
) -> float:
    """Weighted composite, 0-100, with integrity caps applied AFTER weighting."""
    raw = 100.0 * (
        WEIGHTS["velocity"] * clip01(vel_c)
        + WEIGHTS["wilson"] * clip01(wilson_c)
        + WEIGHTS["volume_z"] * clip01(volz_c)
        + WEIGHTS["earliness"] * clip01(early_c)
        + WEIGHTS["trends"] * clip01(trends_c)
    )
    if source_disagreement:
        raw = min(raw, DISAGREE_CAP)
    if thin_confirmation:
        raw = min(raw, THIN_CONFIRM_CAP)
    return round(raw, 1)


def sources_disagree(apewisdom_mentions: Optional[int],
                     reddit_recount: Optional[int],
                     ratio: float = DISAGREE_RATIO) -> bool:
    """True when both sources report and differ by more than `ratio`x.

    Missing data on either side is NOT disagreement (it's partial data).
    Both floored at 1 so 0-vs-small doesn't explode the ratio.
    """
    if apewisdom_mentions is None or reddit_recount is None:
        return False
    a = max(1.0, float(apewisdom_mentions))
    b = max(1.0, float(reddit_recount))
    return (a / b > ratio) or (b / a > ratio)


# ---------------------------------------------------------------------------
# Fetchers — thin, defensive, each returns None on any failure.
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: float = 12.0) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception:
        return None


def fetch_apewisdom(flt: str = "all-stocks", pages: int = 5) -> Optional[dict[str, dict]]:
    """{TICKER: {mentions, mentions_24h_ago, upvotes, rank, rank_24h_ago}} or None.

    Pages are fetched IN PARALLEL. A ticker absent from the result means
    "not in Reddit's top ~{pages*100}" — i.e. genuinely low buzz, which is
    DATA, not a failure. Only a total fetch failure returns None.
    """
    from concurrent.futures import ThreadPoolExecutor
    urls = [APEWISDOM_URL.format(flt=flt, page=p) for p in range(1, pages + 1)]
    with ThreadPoolExecutor(max_workers=min(len(urls), 5)) as ex:
        results = list(ex.map(_get_json, urls))
    out: dict[str, dict] = {}
    got_any = False
    for data in results:
        if not data or "results" not in data:
            continue
        got_any = True
        for row in data.get("results", []):
            sym = str(row.get("ticker", "")).upper().strip()
            if not sym:
                continue
            out[sym] = {
                "mentions": _safe_int(row.get("mentions")),
                "mentions_24h_ago": _safe_int(row.get("mentions_24h_ago")),
                "upvotes": _safe_int(row.get("upvotes")),
                "rank": _safe_int(row.get("rank")),
                "rank_24h_ago": _safe_int(row.get("rank_24h_ago")),
            }
    return out if got_any else None


def fetch_google_trends(symbols: list[str]) -> Optional[dict[str, Optional[float]]]:
    """{SYM: trends_ratio or None} via pytrends, or None if the lib/service fails.

    Searches '<SYM> stock' (disambiguates tickers like IBM or HOOD) over the
    last 3 months, then compares the most recent 7 datapoints' mean to the
    prior baseline mean. Batches of 5 keywords per request (Google's limit).
    Fails soft: any error -> None for that batch, never fabricated data.
    """
    try:
        from pytrends.request import TrendReq
    except Exception:
        return None
    out: dict[str, Optional[float]] = {s: None for s in symbols}
    got_any = False
    try:
        py = TrendReq(hl="en-US", tz=0, timeout=(5, 12))
    except Exception:
        return None
    for i in range(0, len(symbols), 5):
        batch = symbols[i:i + 5]
        kws = [f"{s} stock" for s in batch]
        try:
            py.build_payload(kws, timeframe="today 3-m")
            df = py.interest_over_time()
            if df is None or df.empty:
                continue
            got_any = True
            for sym, kw in zip(batch, kws):
                if kw not in df.columns:
                    continue
                series = df[kw].astype(float)
                if len(series) < 12:
                    continue
                recent = series.iloc[-7:].mean()
                baseline = series.iloc[:-7].mean()
                out[sym] = trends_ratio(recent, baseline)
        except Exception:
            continue
    return out if got_any else None


def fetch_stocktwits_many(symbols: list[str]) -> dict[str, Optional[dict]]:
    """All symbols in parallel (8 workers). A burst of ~15 requests is well
    inside StockTwits' unauthenticated 200/hr budget."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(fetch_stocktwits, symbols))
    return dict(zip(symbols, results))


def fetch_stocktwits(symbol: str) -> Optional[dict]:
    """{'total': n_labeled, 'bullish': n_bull, 'messages': n_all} or None."""
    data = _get_json(STOCKTWITS_URL.format(sym=symbol.upper()))
    if not data or "messages" not in data:
        return None
    bullish = bearish = 0
    msgs = data.get("messages", [])
    for m in msgs:
        tag = (((m or {}).get("entities") or {}).get("sentiment") or {})
        basic = str(tag.get("basic", "")).lower() if isinstance(tag, dict) else ""
        if basic == "bullish":
            bullish += 1
        elif basic == "bearish":
            bearish += 1
    return {"total": bullish + bearish, "bullish": bullish, "messages": len(msgs)}


def reddit_recount(symbols: list[str],
                   subs: tuple[str, ...] = ("wallstreetbets", "stocks")) -> Optional[dict[str, int]]:
    """Independent mention re-count from Reddit hot titles (cross-check only).

    Counts a mention when the ticker appears as $TICK or as a standalone
    uppercase word in a post title. Deliberately crude — it exists to catch
    order-of-magnitude disagreement with ApeWisdom, not to be precise.
    """
    counts = {s.upper(): 0 for s in symbols}
    got_any = False
    for sub in subs:
        data = _get_json(REDDIT_HOT_URL.format(sub=sub))
        if not data:
            continue
        got_any = True
        try:
            children = data["data"]["children"]
        except Exception:
            continue
        for post in children:
            title = str(((post or {}).get("data") or {}).get("title", ""))
            words = set(title.replace("$", " $").split())
            for sym in counts:
                if f"${sym}" in words or sym in words:
                    counts[sym] += 1
    return counts if got_any else None


def _safe_int(x) -> Optional[int]:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Row assembly
# ---------------------------------------------------------------------------

@dataclass
class RadarRow:
    ticker: str
    mentions: Optional[int] = None
    mentions_prev: Optional[int] = None
    velocity: float = 0.0
    st_total: int = 0
    st_bullish: int = 0
    wilson: float = 0.0
    vol_z: Optional[float] = None
    roc_5d: Optional[float] = None
    trends: Optional[float] = None
    score: float = 0.0
    flags: list[str] = field(default_factory=list)


def build_row(
    ticker: str,
    ape: Optional[dict],
    st_sent: Optional[dict],
    reddit_count: Optional[int],
    vol_today: Optional[float],
    prior_vols: Optional[list[float]],
    close_today: Optional[float],
    close_5d_ago: Optional[float],
    ape_available: bool = True,
    trends: Optional[float] = None,
) -> RadarRow:
    """Combine all sources into one scored row. Pure given its inputs.

    Semantics matter: `ape is None` with `ape_available=True` means the
    ApeWisdom fetch SUCCEEDED but this ticker isn't in Reddit's top ranks —
    that is real information (low buzz -> velocity 0, mentions 0, NO flag).
    Only `ape_available=False` (the source itself failed) flags the row.
    """
    row = RadarRow(ticker=ticker.upper())
    _rank = _rank_prev = None

    if ape:
        row.mentions = ape.get("mentions")
        row.mentions_prev = ape.get("mentions_24h_ago")
        row.velocity = mention_velocity(row.mentions or 0, row.mentions_prev or 0)
        _rank, _rank_prev = ape.get("rank"), ape.get("rank_24h_ago")
    elif ape_available:
        row.mentions = 0
        row.mentions_prev = 0
        row.velocity = 0.0
    else:
        row.flags.append("no-reddit-data")

    if st_sent:
        row.st_total = st_sent.get("total", 0)
        row.st_bullish = st_sent.get("bullish", 0)
        row.wilson = wilson_lower_bound(row.st_bullish, row.st_total)
    else:
        row.flags.append("no-stocktwits-data")

    if vol_today is not None and prior_vols:
        row.vol_z = volume_zscore(vol_today, prior_vols)

    if close_today and close_5d_ago:
        try:
            row.roc_5d = float(close_today) / float(close_5d_ago) - 1.0
        except (TypeError, ZeroDivisionError, ValueError):
            row.roc_5d = None

    thin = row.velocity >= 2.0 and (st_sent is None or st_sent.get("messages", 0) < MIN_CONFIRM_MSGS)
    disagree = sources_disagree(row.mentions, reddit_count)
    if thin:
        row.flags.append("thin-confirmation")
    if disagree:
        row.flags.append("source-disagreement")
    if (not ape_available) or st_sent is None:
        if "partial-data" not in row.flags:
            row.flags.append("partial-data")

    row.trends = trends
    row.score = composite_score(
        velocity_component(row.velocity, _rank, _rank_prev),
        row.wilson,
        volume_component(row.vol_z),
        earliness_component(row.roc_5d),
        trends_component(trends),
        thin_confirmation=thin,
        source_disagreement=disagree,
    )
    return row


# ---------------------------------------------------------------------------
# Streamlit tab — imports kept inside so the math above stays test-importable
# ---------------------------------------------------------------------------

FIRE_MIN_VELOCITY = 2.0   # 🔥 needs buzz at least doubling...
FIRE_MIN_WILSON = 0.45    # ...AND real bullish conviction, not just one loud component

# --- Attention cascade (the "graph" logic) -------------------------------
# Attention propagates through a causal chain:
#   social buzz (Reddit/X) --> search interest (Google) --> volume --> price.
# The STAGE of that cascade is itself a signal: being early in the chain is
# where asymmetric returns live; the last node (price moved) means it's over.
STAGE_ATTENTION_VEL = 2.0    # buzz doubling counts as "attention lit"
STAGE_ATTENTION_TRENDS = 1.5 # or searches 1.5x baseline
STAGE_VOLUME_Z = 2.0         # volume node fires at z >= 2
STAGE_LATE_ROC = 0.15        # price node fires at +/-15% in 5d (half the cap)

STAGE_LABELS = {
    0: "💤 Dormant — no attention anywhere",
    1: "🌱 Smoldering — talk started, money hasn't moved (earliest edge)",
    2: "🚀 Igniting — talk AND volume, price still flat (confirmation)",
    3: "🌋 Erupted — price already moved (you're late)",
}


VIX_ELEVATED = 20.0
VIX_STRESS = 25.0


def macro_risk_level(vix_last: Optional[float]) -> str:
    """Macro overlay from VIX: 'calm' < 20 <= 'elevated' < 25 <= 'stress'.

    In stress regimes, retail-buzz spikes are unreliable longs (bear-market
    rallies attract the loudest crowds). Unknown VIX -> 'unknown', shown
    honestly rather than assumed calm.
    """
    if vix_last is None:
        return "unknown"
    v = float(vix_last)
    if v >= VIX_STRESS:
        return "stress"
    if v >= VIX_ELEVATED:
        return "elevated"
    return "calm"


def attention_stage(velocity: float, trends: Optional[float],
                    vol_z: Optional[float], roc_5d: Optional[float]) -> int:
    """Locate the ticker on the attention cascade. Pure + unit-tested.

    3: price node fired (|5d ROC| >= 15%) — regardless of the rest, it's late.
    2: attention lit AND volume confirming, price still early.
    1: attention lit, volume/price still quiet — the asymmetric sweet spot.
    0: nothing lit.
    """
    price_fired = roc_5d is not None and abs(roc_5d) >= STAGE_LATE_ROC
    if price_fired:
        return 3
    attention = (velocity >= STAGE_ATTENTION_VEL) or (
        trends is not None and trends >= STAGE_ATTENTION_TRENDS)
    volume = vol_z is not None and vol_z >= STAGE_VOLUME_Z
    if attention and volume:
        return 2
    if attention:
        return 1
    return 0


def verdict_for_row(r: RadarRow) -> str:
    """One plain-English line per ticker — no jargon.

    The 🔥 verdict is a CO-OCCURRENCE gate, not just score >= 70: weighted
    sums let a single screaming component fake a high score, but a true
    asymmetric setup needs buzz acceleration AND bullish conviction AND
    an early price. This is deliberate double-checking, not redundancy.
    """
    if "partial-data" in r.flags or "source-disagreement" in r.flags:
        return "⚠️ Weak data — ignore for now"
    if r.roc_5d is not None and abs(r.roc_5d) >= EARLY_ROC_LIMIT:
        return "🏃 Already ran — you'd be late"
    if "thin-confirmation" in r.flags:
        return "🤔 One loud corner of Reddit — wait for confirmation"
    if r.score >= 70 and r.velocity >= FIRE_MIN_VELOCITY and r.wilson >= FIRE_MIN_WILSON:
        return "🔥 Hot & still early — research this NOW"
    if r.score >= 70:
        return "💪 Strong score, mixed signals — verify by hand"
    if r.score >= 50:
        return "👀 Warming up — put on close watch"
    if r.score >= 30:
        return "🌤️ Mild buzz — nothing urgent"
    return "❄️ Quiet — no crowd interest yet"


def render_sentiment_radar_tab(universe_csv: str) -> None:
    """No-fail outer shell: whatever breaks inside, the app never crashes."""
    import streamlit as st
    try:
        _render_sentiment_radar_tab(universe_csv)
    except Exception as exc:  # last-resort layer — degrade, don't die
        st.error("📡 Sentiment Radar hit an unexpected error this scan. "
                 "Your other tabs are unaffected — try scanning again in a minute.")
        with st.expander("Technical details"):
            st.code(repr(exc))


def _render_sentiment_radar_tab(universe_csv: str) -> None:
    import streamlit as st
    import pandas as pd
    from modules.data import fetch_stock

    st.markdown('<div id="sentiment" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    st.markdown("### 📡 Sentiment Radar")
    st.caption(
        "**One question, answered simply: who is retail waking up to — before the price moves?** "
        "Free sources only (Reddit, StockTwits, Yahoo). High score = buzz building early. "
        "It's a research lead, never a buy signal."
    )

    with st.expander("❓ How to read this (30 seconds)"):
        st.markdown(
            """
| You see | It means |
|---|---|
| **Score 70+** 🔥 | Buzz accelerating, volume waking up, price hasn't moved yet — the asymmetric setup. Research it today. |
| **Score 50–70** 👀 | Warming up. Add to watch, check again tomorrow. |
| **Below 50** | Noise. Do nothing. |
| **"Already ran"** 🏃 | Buzz is high but the stock already jumped — the easy part is over. Chasing = being exit liquidity. |
| **"Weak data"** ⚠️ | Sources disagree or are missing — the score can't be trusted this scan. |
| **Stage 🌱→🚀→🌋** | Attention travels: talk → searches → volume → price. 🌱 = earliest edge, 🚀 = confirmed and still early, 🌋 = too late. |

**Workflow:** scan here → cross-check hot names in 🌎 Market Radar (technical coil) →
if BOTH agree and price is still flat, that's your candidate. Then usual rules: small size, confirm every order.
"""
        )

    symbols = [s.strip().upper() for s in universe_csv.split(",") if s.strip()]
    if not symbols:
        st.info("No symbols configured.")
        return

    scan_clicked = st.button("📡 Scan Now", type="primary", key="sr_scan")

    # Results persist across tab switches / reruns until the next scan.
    if not scan_clicked:
        cached = st.session_state.get("sr_results")
        if cached is not None:
            _render_results(st, cached["rows"], cached["when"],
                            cached.get("vix"), cached.get("health"))
        else:
            st.caption("Press **Scan Now** — takes ~30–60s (free sources are rate-limited).")
        return

    # One cached unit for the whole social fetch: within the 5-min TTL a
    # re-scan is near-instant, and the free APIs aren't hammered. Threads
    # live INSIDE the cached function (safe); cached calls from worker
    # threads would trip Streamlit's script context, so we don't do that.
    @st.cache_data(ttl=300, show_spinner=False)
    def _fetch_social_bundle(symbols_key: tuple):
        from concurrent.futures import ThreadPoolExecutor
        syms = list(symbols_key)
        with ThreadPoolExecutor(max_workers=4) as ex:
            f_ape = ex.submit(fetch_apewisdom, "all-stocks", 5)
            f_st = ex.submit(fetch_stocktwits_many, syms)
            f_rc = ex.submit(reddit_recount, syms)
            f_tr = ex.submit(fetch_google_trends, syms)
            return f_ape.result(), f_st.result(), f_rc.result(), f_tr.result()

    rows: list[RadarRow] = []
    with st.spinner("Scanning — Reddit, StockTwits, and prices fetched in parallel (~5s)..."):
        ape_all, st_all, recount, trends_all = _fetch_social_bundle(tuple(symbols))

        # One batch Yahoo download for every symbol + ^VIX macro overlay
        # (same pattern as radar tier-1; VIX rides along for free).
        frames: dict = {}
        vix_last = None
        try:
            import yfinance as yf
            from modules.data import _ticker_daily_ohlcv_from_raw
            raw = yf.download(symbols + ["^VIX"], period="3mo", interval="1d",
                              threads=True, progress=False, auto_adjust=True)
            for sym in symbols:
                frames[sym] = _ticker_daily_ohlcv_from_raw(raw, sym)
            vdf = _ticker_daily_ohlcv_from_raw(raw, "^VIX")
            if vdf is not None and not vdf.empty:
                vc = pd.to_numeric(vdf["Close"], errors="coerce").dropna()
                if len(vc):
                    vix_last = float(vc.iloc[-1])
        except Exception:
            for sym in symbols:  # fallback layer: cached per-ticker fetcher
                try:
                    frames[sym] = fetch_stock(sym, "3mo", "1d")
                except Exception:
                    frames[sym] = None

    for sym in symbols:
        vol_today = prior_vols = close_today = close_5d = None
        df = frames.get(sym)
        try:
            if df is not None and not df.empty and "Volume" in df.columns:
                vols = pd.to_numeric(df["Volume"], errors="coerce").dropna()
                closes = pd.to_numeric(df["Close"], errors="coerce").dropna()
                if len(vols) >= VOL_LOOKBACK + 1:
                    vol_today = float(vols.iloc[-1])
                    prior_vols = [float(v) for v in vols.iloc[-(VOL_LOOKBACK + 1):-1]]
                if len(closes) >= EARLY_ROC_DAYS + 1:
                    close_today = float(closes.iloc[-1])
                    close_5d = float(closes.iloc[-(EARLY_ROC_DAYS + 1)])
        except Exception:
            pass
        rows.append(build_row(
            sym,
            (ape_all or {}).get(sym),
            (st_all or {}).get(sym),
            (recount or {}).get(sym),
            vol_today, prior_vols, close_today, close_5d,
            ape_available=ape_all is not None,
            trends=(trends_all or {}).get(sym),
        ))

    rows.sort(key=lambda r: r.score, reverse=True)
    from datetime import datetime as _dt
    when = _dt.now().strftime("%b %d, %I:%M %p")
    health = {
        "Reddit ranks (ApeWisdom)": ape_all is not None,
        "StockTwits": any(v is not None for v in (st_all or {}).values()),
        "Yahoo prices": any(f is not None for f in frames.values()),
        "Reddit cross-check (optional)": recount is not None,
        "Google Trends (optional)": trends_all is not None,
    }
    st.session_state["sr_results"] = {
        "rows": rows, "when": when, "vix": vix_last, "health": health,
    }
    _render_results(st, rows, when, vix_last, health)


def _render_results(st, rows: list[RadarRow], when: str,
                    vix_last=None, health: Optional[dict] = None) -> None:
    import pandas as pd

    st.caption(f"Last scan: **{when}** — results stay until you scan again.")

    # ---- No-fail layer 1: show exactly which sources answered this scan
    if health:
        bits = " · ".join(("✅ " if ok else "⚠️ ") + name for name, ok in health.items())
        st.caption(f"Sources: {bits}")
        core_down = [n for n, ok in health.items() if not ok and "(optional)" not in n]
        opt_down = [n for n, ok in health.items() if not ok and "(optional)" in n]
        if core_down:
            st.info("A core source didn't answer — affected rows are flagged and their "
                    "scores capped, never guessed. Re-scan in a few minutes.")
        elif opt_down:
            st.caption("ℹ️ Optional cross-checks didn't answer (Reddit and Google often "
                       "block cloud servers — normal). Core signals are unaffected; "
                       "scores stand on Reddit ranks + StockTwits + prices.")

    # ---- Macro overlay: the market-wide weather report
    risk = macro_risk_level(vix_last)
    if risk == "stress":
        st.error(f"🌪️ **Macro: STRESS** (VIX {vix_last:.0f}). In fear regimes, buzz "
                 "spikes are usually bear-market rallies — treat every signal below "
                 "as research-only and cut size expectations in half.")
    elif risk == "elevated":
        st.warning(f"🌥️ **Macro: elevated risk** (VIX {vix_last:.0f}). Market is "
                   "jumpy — demand 🚀-stage confirmation before acting on anything.")
    elif risk == "calm":
        st.caption(f"☀️ Macro: calm (VIX {vix_last:.0f}) — normal conditions for buzz signals.")
    else:
        st.caption("Macro: VIX unavailable this scan — no market-weather adjustment shown.")

    # ---- Top-3 spotlight cards: the only thing a beginner needs to look at
    top = [r for r in rows if r.score > 0][:3]
    if top:
        st.markdown("#### 🏆 Today's top signals")
        cols = st.columns(len(top))
        for col, r in zip(cols, top):
            with col:
                st.metric(
                    label=r.ticker,
                    value=f"{r.score:.0f} / 100",
                    delta=f"{r.velocity:.1f}x buzz" if r.velocity > 1 else "flat buzz",
                    delta_color="normal" if r.velocity > 1 else "off",
                )
                st.caption(verdict_for_row(r))

    # ---- Full board, verdict first, numbers for those who want them.
    # Every column header has a hover tooltip in plain language (the ⓘ).
    df_out = pd.DataFrame([{
        "Ticker": r.ticker,
        "Verdict": verdict_for_row(r),
        "Stage": STAGE_LABELS[attention_stage(r.velocity, r.trends, r.vol_z, r.roc_5d)].split(" — ")[0],
        "Score": r.score,
        "Buzz": (f"{r.velocity:.1f}x" if r.velocity > 0 else "none"),
        "Bullish %": (f"{100 * r.st_bullish / r.st_total:.0f}% of {r.st_total}"
                      if r.st_total else "no votes yet"),
        "Volume": ("no data" if r.vol_z is None else
                   ("🔊 unusual" if r.vol_z >= 2 else "normal")),
        "Searches": ("no data" if r.trends is None else
                     (f"📈 rising {r.trends:.1f}x" if r.trends > 1.2 else
                      ("flat" if r.trends >= 0.8 else "fading"))),
        "5d move": "no data" if r.roc_5d is None else f"{100 * r.roc_5d:+.1f}%",
    } for r in rows])

    st.dataframe(
        df_out, use_container_width=True, hide_index=True,
        column_config={
            "Ticker": st.column_config.TextColumn(
                "Ticker", help="The stock's symbol."),
            "Verdict": st.column_config.TextColumn(
                "Verdict",
                help="The bottom line in plain English — what to do with this row. "
                     "🔥 only fires when buzz, bullishness AND an early price all line up."),
            "Stage": st.column_config.TextColumn(
                "Stage",
                help="Where the stock sits on the attention chain: talk → searches → "
                     "volume → price. 💤 Dormant: nothing yet. 🌱 Smoldering: people are "
                     "talking but money hasn't moved — the earliest (riskiest) edge. "
                     "🚀 Igniting: talk AND real volume, price still flat — the "
                     "confirmation sweet spot. 🌋 Erupted: price already jumped — late."),
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f",
                help="0–100 asymmetric-setup score: Reddit buzz speeding up + bullish "
                     "conviction + unusual volume + price that HASN'T moved yet. "
                     "70+ = worth researching today. Below 50 = noise."),
            "Buzz": st.column_config.TextColumn(
                "Buzz",
                help="Reddit chatter now vs 24 hours ago. '3.0x' = three times more "
                     "mentions than yesterday — the crowd is arriving. 'none' = Reddit "
                     "isn't talking about this stock (that's fine, just no signal)."),
            "Bullish %": st.column_config.TextColumn(
                "Bullish %",
                help="On StockTwits, of the posts that took a side: how many say UP? "
                     "'78% of 41' = 41 opinionated posts, 78% bullish. Few posts = "
                     "weak evidence, and the Score already discounts that automatically."),
            "Volume": st.column_config.TextColumn(
                "Volume",
                help="Today's trading volume vs the stock's own 30-day normal. "
                     "'🔊 unusual' = real money is moving, not just talk. Talk WITHOUT "
                     "volume is often just noise."),
            "Searches": st.column_config.TextColumn(
                "Searches",
                help="Google searches for '<ticker> stock' this week vs its own recent "
                     "normal. This catches attention from EVERYWHERE — X/Twitter, TikTok, "
                     "news — because people who see a stock anywhere go google it. "
                     "'📈 rising 2.0x' = twice the usual search interest."),
            "5d move": st.column_config.TextColumn(
                "5d move",
                help="Price change over the last 5 sessions. Near 0% = you'd still be "
                     "early (that's what you want). A big move = the easy gain may be "
                     "gone — chasing late is how buzz stocks burn people."),
        },
    )
    with st.expander("🔬 Nerd numbers (raw components & flags)"):
        st.dataframe(pd.DataFrame([{
            "Ticker": r.ticker,
            "Mentions": r.mentions,
            "Mentions 24h ago": r.mentions_prev,
            "Velocity": round(r.velocity, 2),
            "Bull/Labeled": f"{r.st_bullish}/{r.st_total}",
            "Wilson LB": round(r.wilson, 3),
            "Vol z": None if r.vol_z is None else round(r.vol_z, 2),
            "Trends ratio": None if r.trends is None else round(r.trends, 2),
            "5d ROC": None if r.roc_5d is None else round(r.roc_5d, 4),
            "Stage": attention_stage(r.velocity, r.trends, r.vol_z, r.roc_5d),
            "Flags": ", ".join(r.flags) if r.flags else "clean",
        } for r in rows]), use_container_width=True, hide_index=True)
        st.caption(
            f"Weights: velocity {WEIGHTS['velocity']:.0%} · sentiment (Wilson 95% LB) "
            f"{WEIGHTS['wilson']:.0%} · volume-z {WEIGHTS['volume_z']:.0%} · earliness "
            f"{WEIGHTS['earliness']:.0%}. Flagged rows are capped "
            f"(thin ≤ {THIN_CONFIRM_CAP:.0f}, disagreement ≤ {DISAGREE_CAP:.0f})."
        )
