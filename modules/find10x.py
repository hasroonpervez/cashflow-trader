"""
Find 10x: the asymmetric-opportunity tab.

One screen that answers one question: **which name is worth looking at today, and why?**

It fuses the four evidence streams the app already computes, each of which is
independently unit-tested in its own module:

  * ``sentiment_radar``  retail attention (Reddit / StockTwits / Google Trends)
  * ``creator_signals``  independent financial creators (free RSS + Reddit DD)
  * ``asymmetry``        convexity: bounded downside vs a real upside target
  * ``dossier``          on-demand fundamentals + narrative

--------------------------------------------------------------------------
Why the ranking is what it is
--------------------------------------------------------------------------
The audit's central finding was that the app's "10x Potential" score summed
points for *attention* and *trend* and then called the result asymmetry. It had
no payoff term and no probability term, so a name that had already run scored
highest: precisely the wrong end of the move.

This tab ranks on ``opportunity = convexity x confirmation``:

    convexity     from asymmetry.convexity_score, (target-entry)/(entry-stop).
                  A pure payoff-shape number. No attention in it at all.
    confirmation  blended attention: radar score and creator consensus.
                  This is a TIE-BREAKER on top of payoff shape, never a
                  substitute for it. A loud name with no room to run ranks low.

Both are needed. Convexity alone finds every illiquid falling knife with a
tight stop; attention alone rediscovers momentum. The product only scores when
the payoff shape is genuinely skewed *and* something is waking the name up.

--------------------------------------------------------------------------
Honesty rules (inherited from the modules, enforced again here)
--------------------------------------------------------------------------
1. Missing evidence lowers CONFIDENCE and is named on the row. It never scores
   zero silently, and it never scores as if the evidence were bearish.
2. ``validation_status`` is displayed verbatim. Nothing here has cleared
   ``validated_signals.promotion_gate`` on live forward returns yet, so every
   row reads ``unvalidated`` until an outcome ledger exists. That word is the
   point: see Stage 2 of the roadmap in AUDIT_2026-08.md.
3. This tab suggests what to RESEARCH. It sizes nothing and places nothing.

Pure ranking logic lives above the Streamlit import so it is testable headless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .utils import safe_float, log_warn

# Ranking weights. Convexity dominates deliberately: payoff shape is the thing
# the audit found missing, and attention is abundant and cheap.
W_CONVEXITY = 0.60
W_CONFIRMATION = 0.40

# A convexity ratio of this or better earns full marks. 5:1 is the classic
# asymmetric-bet threshold: risk 1 to make 5.
CONVEXITY_SATURATION = 5.0

# Below this, a row is noise and is not shown at all.
MIN_DISPLAY_SCORE = 15.0

# Confirmation blend: radar is broader (whole universe), creators are sparser
# but higher-signal when present.
W_RADAR = 0.55
W_CREATOR = 0.45


def clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def convexity_component(ratio: Optional[float]) -> Optional[float]:
    """Map a convexity ratio to 0..1, saturating at ``CONVEXITY_SATURATION``.

    ``None`` in, ``None`` out, an unknown payoff shape is not a bad one, and
    must not be scored as 0.
    """
    r = safe_float(ratio, None)
    if r is None or r <= 0:
        return None
    return clip01(r / CONVEXITY_SATURATION)


def confirmation_component(
    radar_score: Optional[float], creator_score: Optional[float]
) -> Optional[float]:
    """Blend the two attention sources over whichever are actually present.

    Re-weights across present sources rather than treating an absent source as
    zero interest: one source at 80 reads 0.80, not 0.44.
    """
    parts = []
    if radar_score is not None:
        parts.append((W_RADAR, clip01(safe_float(radar_score, 0.0) / 100.0)))
    if creator_score is not None:
        parts.append((W_CREATOR, clip01(safe_float(creator_score, 0.0) / 100.0)))
    if not parts:
        return None
    wsum = sum(w for w, _ in parts)
    return sum(w * v for w, v in parts) / wsum if wsum > 0 else None


def opportunity_score(
    convexity_ratio: Optional[float],
    radar_score: Optional[float],
    creator_score: Optional[float],
) -> tuple[float, float, list[str]]:
    """``(score_0_100, confidence_0_1, flags)``.

    Confidence is the fraction of the two pillars actually present. A row built
    on one pillar can still rank, but it announces that it is half-blind.
    """
    flags: list[str] = []
    cx = convexity_component(convexity_ratio)
    cf = confirmation_component(radar_score, creator_score)

    if cx is None:
        flags.append("no-convexity-data")
    if cf is None:
        flags.append("no-attention-data")
    if radar_score is None:
        flags.append("no-radar")
    if creator_score is None:
        flags.append("no-creator-coverage")

    present = [(W_CONVEXITY, cx), (W_CONFIRMATION, cf)]
    live = [(w, v) for w, v in present if v is not None]
    if not live:
        return 0.0, 0.0, flags + ["no-evidence"]

    wsum = sum(w for w, _ in live)
    raw = sum(w * v for w, v in live) / wsum
    confidence = wsum  # W_CONVEXITY + W_CONFIRMATION == 1.0 when both present
    return 100.0 * raw, confidence, flags


@dataclass
class OpportunityRow:
    """One ranked candidate. Every optional field is genuinely optional."""

    ticker: str
    score: float = 0.0
    confidence: float = 0.0
    convexity_ratio: Optional[float] = None
    upside_frac: Optional[float] = None
    downside_frac: Optional[float] = None
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    radar_score: Optional[float] = None
    creator_score: Optional[float] = None
    creator_sources: int = 0
    spring_score: Optional[float] = None
    validation_status: str = "unvalidated"
    flags: list[str] = field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        return self.confidence < 1.0 or bool(self.flags)


def plain_verdict(row: OpportunityRow) -> tuple[str, str]:
    """``(sentence, tone)``, the plain-English "so what" for one row.

    House rule from modules/explain.py: no card ships without one of these.
    Deliberately written for someone who does not know what convexity means.
    """
    if row.score <= 0 or "no-evidence" in row.flags:
        return "Nothing to go on for this name right now.", "neutral"

    cx = row.convexity_ratio
    if cx is not None and row.upside_frac is not None and row.downside_frac is not None:
        shape = (
            f"Risking about {row.downside_frac * 100:.0f}% to reach a "
            f"{row.upside_frac * 100:.0f}% target, roughly {cx:.1f} to 1."
        )
    else:
        shape = "Payoff shape unknown: no clear support level to risk against."

    if row.creator_sources >= 2 and (row.radar_score or 0) >= 50:
        who = " Independent creators and retail chatter are both picking it up."
        tone = "good"
    elif row.creator_sources >= 2:
        who = f" {row.creator_sources} independent creators are talking about it."
        tone = "good"
    elif (row.radar_score or 0) >= 50:
        who = " Retail chatter is building, but no creator coverage yet."
        tone = "warn"
    else:
        who = " Nobody is talking about it yet: early, or nothing there."
        tone = "neutral"

    if cx is not None and cx < 2.0:
        tone = "warn"
        who += " The reward does not clearly beat the risk here."

    return shape + who, tone


def rank_opportunities(rows: list[OpportunityRow], limit: Optional[int] = None) -> list[OpportunityRow]:
    """Highest score first; confidence breaks ties so half-blind rows sink."""
    out = sorted(
        [r for r in rows if r.score >= MIN_DISPLAY_SCORE],
        key=lambda r: (r.score, r.confidence),
        reverse=True,
    )
    return out[:limit] if limit else out


def build_opportunity_row(
    ticker: str,
    *,
    daily=None,
    radar_score: Optional[float] = None,
    creator_score: Optional[float] = None,
    creator_sources: int = 0,
    spring_score: Optional[float] = None,
) -> OpportunityRow:
    """Assemble one row. Pure given ``daily``; never raises.

    Convexity is derived causally from the price frame: support comes from the
    trailing swing low (the bounded downside) and the target from ATR expansion
    (the realistic upside). Both come from ``modules.asymmetry``, which pins
    the no-lookahead property with a test that poisons all future rows.
    """
    from .asymmetry import atr_upside_target, convexity_score, support_from_swing_low

    row = OpportunityRow(
        ticker=str(ticker).upper().strip(),
        radar_score=radar_score,
        creator_score=creator_score,
        creator_sources=int(creator_sources or 0),
        spring_score=spring_score,
    )

    if daily is not None and len(daily) > 0:
        try:
            entry = float(daily["Close"].iloc[-1])
            stop = support_from_swing_low(daily)
            target = atr_upside_target(daily)
            row.entry, row.stop, row.target = entry, stop, target
            cx = convexity_score(entry, stop, upside_target=target)
            if cx is not None:
                row.convexity_ratio = cx.convexity_ratio
                row.upside_frac = cx.upside_frac
                row.downside_frac = cx.bounded_loss_frac
                row.flags.extend(cx.flags)
        except Exception as _e:
            log_warn("find10x build_opportunity_row convexity", _e, ticker=row.ticker)
            row.flags.append("convexity-error")

    row.score, row.confidence, extra = opportunity_score(
        row.convexity_ratio, radar_score, creator_score
    )
    row.flags.extend(extra)
    return row


# ---------------------------------------------------------------------------
# Streamlit tab: streamlit imported inside so the ranking math above stays
# importable headless (same pattern as modules/sentiment_radar.py).
# ---------------------------------------------------------------------------

def render_find10x_tab(universe_csv: str) -> None:
    """Entry point wired into app.py."""
    try:
        _render(universe_csv)
    except Exception as _e:  # a tab must never take the whole app down
        import streamlit as st

        log_warn("render_find10x_tab", _e)
        st.error("Find 10x hit an unexpected error. Details are in the app log.")


def _render(universe_csv: str) -> None:
    import streamlit as st

    from . import explain as X

    st.subheader("Find 10x")
    st.caption(
        "Names where the possible gain is much larger than the risk, and "
        "something is starting to wake them up."
    )

    symbols = [s.strip().upper() for s in str(universe_csv or "").split(",") if s.strip()]
    if not symbols:
        st.info("No tickers configured. Add some in the sidebar watchlist.")
        return

    X.verdict_line(
        "This tab tells you what to RESEARCH, not what to buy. Nothing here has "
        "been proven on forward returns yet: every row is marked 'unvalidated' "
        "on purpose until an outcome ledger exists.",
        "neutral",
    )

    scan = st.button("Find opportunities", type="primary", key="f10x_scan")

    if not scan:
        cached = st.session_state.get("f10x_results")
        if cached:
            _render_rows(st, X, cached["rows"], cached["when"], cached.get("health", {}))
        else:
            st.caption(
                f"Press **Find opportunities** to scan {len(symbols)} tickers. "
                "Takes ~30-60s: the free data sources are rate-limited."
            )
        return

    rows, health, when = _scan(st, symbols)
    st.session_state["f10x_results"] = {"rows": rows, "when": when, "health": health}
    _render_rows(st, X, rows, when, health)


def _scan(st, symbols: list[str]):
    """Fetch every stream, assemble rows. Each source fails soft and is reported."""
    from datetime import datetime

    from .data import fetch_stock

    health: dict[str, Any] = {}
    radar_scores: dict[str, float] = {}
    creator_rows: dict[str, Any] = {}

    with st.spinner("Reading the tape, Reddit, and the creator feeds..."):
        # --- attention: retail ------------------------------------------------
        try:
            from .sentiment_radar import (
                build_row, fetch_apewisdom, fetch_stocktwits_many, reddit_recount,
            )

            ape_all = fetch_apewisdom("all-stocks", 5)
            st_all = fetch_stocktwits_many(symbols)
            recount = reddit_recount(symbols)
            for sym in symbols:
                r = build_row(
                    sym,
                    ape=(ape_all or {}).get(sym),
                    st_sent=(st_all or {}).get(sym),
                    reddit_count=(recount or {}).get(sym),
                    vol_today=None, prior_vols=None,
                    close_today=None, close_5d_ago=None,
                    ape_available=ape_all is not None,
                )
                radar_scores[sym] = r.score
            health["radar"] = "ok" if ape_all is not None else "apewisdom failed"
        except Exception as _e:
            log_warn("find10x radar", _e)
            health["radar"] = "unavailable"

        # --- attention: creators ---------------------------------------------
        try:
            from .creator_signals import scan_creators

            c_rows, c_health = scan_creators()
            for cr in c_rows or []:
                creator_rows[cr.ticker] = cr
            health["creators"] = c_health
        except Exception as _e:
            log_warn("find10x creators", _e)
            health["creators"] = "unavailable"

        # --- payoff shape -----------------------------------------------------
        rows = []
        for sym in symbols:
            daily = None
            try:
                daily = fetch_stock(sym, "1y", "1d")
            except Exception as _e:
                log_warn("find10x fetch_stock", _e, ticker=sym)
            cr = creator_rows.get(sym)
            rows.append(
                build_opportunity_row(
                    sym,
                    daily=daily,
                    radar_score=radar_scores.get(sym),
                    creator_score=(cr.score if cr else None),
                    creator_sources=(cr.source_count if cr else 0),
                )
            )

    return rank_opportunities(rows), health, datetime.now().strftime("%Y-%m-%d %H:%M")


def _render_rows(st, X, rows: list[OpportunityRow], when: str, health: dict) -> None:
    st.caption(f"Scanned {when}")

    bad = [k for k, v in (health or {}).items() if v not in ("ok", None) and "fail" in str(v).lower()]
    if bad:
        st.warning(
            f"Some sources did not answer ({', '.join(bad)}). Rows below are scored on "
            "what we could actually read: the missing pieces are named on each card."
        )

    if not rows:
        st.info(
            "Nothing cleared the bar this scan. That is a real answer, not an error, "
            "most days there is no asymmetric setup in a small watchlist."
        )
        return

    for r in rows:
        sentence, tone = plain_verdict(r)
        with st.container(border=True):
            head = f"### {r.ticker}"
            if r.is_partial:
                head += "  ·  ⚠︎ partial data"
            st.markdown(head)
            X.verdict_line(sentence, tone)

            c1, c2, c3 = st.columns(3)
            with c1:
                X.metric(
                    "Reward vs risk",
                    X.ratio(r.convexity_ratio) if r.convexity_ratio else "n/a",
                    hint="How many dollars of upside per dollar risked.",
                    help_extra=(
                        "(target - entry) / (entry - support). Support is the trailing "
                        "20-day swing low; target is ATR-expansion based. Computed "
                        "point-in-time: no future bars are used."
                    ),
                )
            with c2:
                X.metric(
                    "Chatter",
                    X.score(r.radar_score) if r.radar_score is not None else "n/a",
                    hint="Retail attention: Reddit mentions, StockTwits, searches.",
                )
            with c3:
                X.metric(
                    "Creators",
                    str(r.creator_sources) if r.creator_sources else "n/a",
                    hint="Independent creators calling it. Two or more is the bar.",
                )

            with st.expander("Why this ranks here"):
                st.markdown(
                    f"- **Entry / support / target:** "
                    f"{X.money(r.entry)} / {X.money(r.stop)} / {X.money(r.target)}\n"
                    f"- **Opportunity score:** {r.score:.0f} / 100 "
                    f"(convexity {W_CONVEXITY:.0%}, attention {W_CONFIRMATION:.0%})\n"
                    f"- **Confidence:** {r.confidence:.0%} of the evidence was available\n"
                    f"- **Proven on forward returns?** `{r.validation_status}`"
                )
                if r.flags:
                    st.caption("Missing or capped: " + ", ".join(sorted(set(r.flags))))
                st.caption(
                    "Ranking is convexity x confirmation. Attention breaks ties between "
                    "good payoff shapes; it can never create one."
                )

            with st.expander("Deep dive (fundamentals)"):
                if st.button("Build dossier", key=f"f10x_dos_{r.ticker}"):
                    _render_dossier(st, X, r.ticker)


def _render_dossier(st, X, ticker: str) -> None:
    try:
        from .dossier import get_dossier
    except Exception as _e:
        log_warn("find10x dossier import", _e)
        st.info("Dossier module unavailable.")
        return

    with st.spinner(f"Building {ticker} dossier..."):
        try:
            d = get_dossier(ticker)
        except Exception as _e:
            log_warn("find10x get_dossier", _e, ticker=ticker)
            st.info("Could not build a dossier for this name.")
            return

    st.caption(f"Generated by `{getattr(d, 'generated_by', 'unknown')}` at {getattr(d, 'generated_at', 'n/a')}")
    facts = getattr(d, "facts", {}) or {}
    shown = [f for f in facts.values() if getattr(f, "value", None) is not None]
    if shown:
        for f in shown[:24]:
            st.markdown(f"- **{f.label}:** {f.value}{(' ' + f.unit) if getattr(f, 'unit', None) else ''}  ")
    else:
        st.caption("No fundamentals available for this ticker.")

    narrative = getattr(d, "narrative", None)
    if narrative is not None:
        st.markdown("**Generated summary**: prose only; every figure above comes from the data layer.")
        st.markdown(getattr(narrative, "text", "") or "")
    else:
        st.caption(
            "Narrative unavailable: the `claude` CLI is not signed in. "
            "Run `claude` in a terminal to authenticate; the numbers above do not need it."
        )
