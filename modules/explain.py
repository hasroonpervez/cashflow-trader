"""
Progressive-disclosure toolkit: one shared way to show a number and explain it.

The product rule this module encodes:

    The plain answer is ALWAYS visible.
    The jargon, the math, and the caveats live one click away.
    Nothing is hidden; nothing is forced.

Three layers, in the order a normal person meets them:

    1. ``verdict_line(text, tone)``, the one-sentence "so what" that tops a card.
    2. ``metric(label, value, term=..., hint=...)``, the number, with a plain-English
       tooltip attached via Streamlit's native ``help=`` (no custom HTML, no injection
       surface) and an optional one-line ``hint`` caption underneath.
    3. ``explain(term_key)``, the "What does this mean?" expander:
       plain sentence -> real explanation -> the actual formula THIS app uses.

Design constraints (deliberate):

  * **Importable without Streamlit.** Everything above the RENDERING section is pure
    Python: the registry, the lookups, the formatters, the tone logic. ``import
    streamlit`` happens *inside* each render function, exactly like
    ``modules/sentiment_radar.py``. That keeps the registry unit-testable and keeps
    import cost off the cold-start path.
  * **No ``unsafe_allow_html``.** Every render function uses native Streamlit widgets.
    The rest of the app renders metric cards as hand-rolled HTML strings; this module
    exists partly to give those call sites a safe, consistent replacement.
  * **Definitions match the code, not a textbook.** Each ``formula`` was read out of
    ``modules/options.py`` / ``modules/ta.py`` / ``modules/sentiment_radar.py``. Where
    this app's version differs from the standard one (Gold Zone weights, the Edge Score
    blend, the IV-rank *proxy*, the Θ/Γ-weighted OpEx pin), the term says so.

Adoption is incremental. A renderer can switch a single number to
``explain.metric(...)`` without touching anything else on the screen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

__all__ = [
    "Term",
    "TERMS",
    "TONES",
    "TONE_GLYPH",
    "normalize_key",
    "get",
    "require",
    "lookup",
    "has",
    "all_keys",
    "search",
    "tooltip",
    "tone_label",
    "verdict_text",
    "check_registry",
    "missing_terms",
    "money",
    "pct",
    "ratio",
    "score",
    "compact",
    "signed",
    "metric",
    "explain",
    "verdict_line",
    "glossary",
    "term_badge",
]


# ═══════════════════════════════════════════════════════════════════════════
#  TERM MODEL
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Term:
    """One piece of jargon, explained at four depths.

    Attributes
    ----------
    short:
        3-6 word gloss. This is what fits in a tooltip next to a label.
    plain:
        One sentence a non-trader understands. No other jargon allowed inside it.
    detail:
        The real explanation: what it measures, how to read it, when it lies.
    formula:
        The math *as this codebase computes it*. For terms that are a labelled
        state rather than a number, this states the exact rule that produces
        the label. Never empty.
    label:
        Display name ("Gold Zone"). Falls back to a title-cased key.
    aliases:
        Other spellings seen in the UI, so migrating call sites can look a term
        up by whatever string the old code used ("Θ/Γ", "QE", "MC PoP").
    """

    short: str
    plain: str
    detail: str
    formula: str
    label: str = ""
    aliases: tuple[str, ...] = field(default=())

    @property
    def title(self) -> str:
        """Human-facing name for headings and expander titles."""
        return self.label or ""

    def tooltip(self, extra: Optional[str] = None) -> str:
        """Text for Streamlit's native ``help=`` parameter."""
        parts = [self.short.rstrip(".") + ".", self.plain]
        if extra:
            parts.append(str(extra))
        return "  \n".join(p for p in parts if p)


# ═══════════════════════════════════════════════════════════════════════════
#  THE REGISTRY
#
#  Keys are lowercase snake_case. Every entry was checked against the
#  implementation cited in its `formula` field.
# ═══════════════════════════════════════════════════════════════════════════

TERMS: dict[str, Term] = {

    # ── Composite scores this app invented ──────────────────────────────────
    "edge_score": Term(
        label="Edge Score",
        aliases=("quant edge", "quant edge score", "qe", "qs", "edge"),
        short="Overall setup quality, 0-100",
        plain="One number for how good the conditions are right now, above 70 is a green light, below 40 means wait.",
        detail=(
            "Five checks are scored 0-100 each and averaged: trend (where price sits "
            "versus its 20/50/200-day averages), momentum (RSI in the calm 40-60 band "
            "scores best), volume (is money accumulating), volatility (calm tape scores "
            "higher, because premium sellers want quiet), and structure (higher highs "
            "and higher lows). Turning on Quant mode mixes in a second, model-driven "
            "score rather than replacing the first one. Above 70 the app says PRIME "
            "SELLING ENVIRONMENT; 50-70 DECENT SETUP; below that, STAND DOWN."
        ),
        formula=(
            "mean(trend, momentum, volume, volatility, structure)\n"
            "Quant mode: 0.62 x retail_mean + 0.38 x institutional_signal\n"
            "  institutional_signal = clip(50 + tanh(ffd_last x 650) x 18 - p_high_vol x 18, 0, 100)\n"
            "Then + 0.25 x (average Monte-Carlo PoP of the top 8 strikes / 100)\n"
            "modules/options.py :: quant_edge_score"
        ),
    ),
    "confluence": Term(
        label="Confluence Points",
        aliases=("confluence points", "cp", "cp_score"),
        short="How many bullish checks pass, out of 9",
        plain="Nine independent bullish signals are checked; this is how many of them agree right now.",
        detail=(
            "Seven checks, worth 9 points in total: Supertrend direction (2), price "
            "above the Ichimoku cloud (2), ADX above 25 with buyers leading (1), OBV "
            "accumulating (1), a bullish divergence in the last three (1), price above "
            "the Gold Zone (1), and bullish market structure (1). 7+ is the Blue Diamond "
            "threshold. Below 4 is a caution zone. The point of counting independent "
            "signals is that one indicator can be fooled; six agreeing is harder to fake."
        ),
        formula=(
            "score = 2*supertrend_bull + 2*above_cloud + 1*(ADX>25 and +DI>-DI)\n"
            "      + 1*obv_rising_20d + 1*bullish_divergence + 1*(price>gold_zone)\n"
            "      + 1*(structure == BULLISH)     # max 9\n"
            "modules/options.py :: _calc_confluence_points_core"
        ),
    ),
    "gold_zone": Term(
        label="Gold Zone",
        aliases=("gold zone price", "gz"),
        short="The one price level that matters",
        plain="A single fair-value line: above it buyers are in control, below it sellers are.",
        detail=(
            "Rather than plotting five support levels and leaving you to pick, this "
            "blends them into one number and weights the ones that are backed by real "
            "traded volume the highest. Use it as the anchor for strike selection: sell "
            "puts below it, sell calls above it. It moves as the volume profile moves, "
            "so it is a level, not a prophecy."
        ),
        formula=(
            "weighted mean of whichever components exist:\n"
            "  POC 1.35, HVN (within 2% of spot) 1.35, SMA200 1.15,\n"
            "  Fib 61.8% of last 60 bars 1.00, Gamma Flip (within 5% of spot) 0.95,\n"
            "  nearest Gann Sq9 level 0.55\n"
            "modules/options.py :: calc_gold_zone"
        ),
    ),
    "blue_diamond": Term(
        label="Blue Diamond",
        aliases=("blue diamond signal", "blue"),
        short="Strong confirmed buy signal",
        plain="Everything lined up at once: the strongest bullish setup this app produces.",
        detail=(
            "A Blue Diamond needs four things simultaneously: confluence crossing up to "
            "7 or more out of 9, daily structure BULLISH, the weekly bias not BEARISH, "
            "and volume at least 90% of its 20-day average (so the move has real "
            "participation, not a thin-tape fake). A blow-off filter based on ATR "
            "removes manic single-bar spikes. It is a signal to act, not a guarantee, "
            "the app also shows the historical hit rate of past diamonds on this ticker."
        ),
        formula=(
            "confluence crosses up to >= 7/9 AND daily structure == BULLISH\n"
            "AND weekly bias != BEARISH AND volume >= 0.90 x SMA20(volume)\n"
            "AND not an ATR blow-off bar\n"
            "modules/options.py :: detect_diamonds, _blue_diamond_volume_gate"
        ),
    ),
    "pink_diamond": Term(
        label="Pink Diamond",
        aliases=("pink diamond signal", "pink"),
        short="Take-profit / exhaustion warning",
        plain="The easy money in this move is probably done, tighten stops or take profit.",
        detail=(
            "Fires when bullish confluence collapses, or when momentum is exhausted "
            "(RSI above 75 while confluence is weak). It is not a short signal. Treat it "
            "as the dashboard warning lights coming on: close, trim, sell aggressive "
            "covered calls, or move your stop up."
        ),
        formula=(
            "confluence collapse from a prior high, OR (RSI(14) > 75 AND weak confluence)\n"
            "modules/options.py :: detect_diamonds"
        ),
    ),
    "pre_diamond": Term(
        label="Pre-Diamond Coil",
        aliases=("pre diamond", "coil", "coil_active", "pre-diamond"),
        short="Quiet build-up before a breakout",
        plain="The stock is coiled and quietly being accumulated, a Blue Diamond may be close, but has not fired.",
        detail=(
            "An early-warning state, not a signal. All six conditions must hold: "
            "confluence sitting at 5-6 and rising, volatility squeezed into the bottom "
            "quarter of its 60-day range, the last 3 days' volume above the last 10 "
            "days' average, price hugging the Gold Zone or the Shadow low, and the "
            "weekly bias not bearish. If it is also outperforming SPY over 3 days it is "
            "labelled IMMINENT BREAKOUT, otherwise ACCUMULATING."
        ),
        formula=(
            "all of: 5 <= confluence <= 6; confluence rising; ATR percentile(60d) <= 0.25;\n"
            "  mean(volume, 3d) > mean(volume, 10d);\n"
            "  |close - gold_zone| / gold_zone < 2.5% OR |close - shadow_low| / close < 1.5%;\n"
            "  weekly bias != BEARISH\n"
            "modules/options.py :: Opt.detect_pre_diamond"
        ),
    ),
    "explosion_score": Term(
        label="Explosion Score",
        aliases=("explosion", "radar score"),
        short="Radar ranking, 0-100",
        plain="How explosive a Market Radar hit looks, so the list can be sorted best-first.",
        detail=(
            "A ranking number for the Radar tab only. It is a weighted roll-up of "
            "signals you can also see individually, so it never tells you anything the "
            "row does not: it just orders the list. Use it to decide what to read "
            "first, not what to buy."
        ),
        formula=(
            "pre-diamond 30 (imminent) or 20 (accumulating)\n"
            "+ min(25, 10x_score x 2.5) + min(20, edge_score x 0.2)\n"
            "+ 15 if Blue Diamond + 10 if GEX regime STABLE (5 if unknown)\n"
            "modules/options.py :: compute_explosion_score"
        ),
    ),
    "tenx_score": Term(
        label="10x Potential",
        aliases=("10x", "10x potential", "tenx"),
        short="Count of long-shot growth traits, 0-10",
        plain="How many high-upside characteristics a small company has, a research filter, not a forecast.",
        detail=(
            "One point each for: market cap under $10B, revenue growth over 25% (a "
            "second point over 50%), short interest over 15% of float, volatility "
            "squeezed into the bottom 10% of its range, 3-day volume more than 1.5x the "
            "20-day average, Hurst above 0.55, 90-day performance more than 1.2x SPY, "
            "positive free cash flow, and an active Blue or Pre-Diamond. High scores are "
            "lottery tickets with better-than-random odds, not safe trades."
        ),
        formula=(
            "sum of 10 boolean traits, each worth 1 point (hyper-growth adds a 2nd)\n"
            "modules/options.py :: score_10x_potential"
        ),
    ),

    # ── Options greeks, as this app computes them ───────────────────────────
    "delta": Term(
        label="Delta",
        aliases=("Δ", "delta_", "d"),
        short="Price sensitivity and rough assignment odds",
        plain="How much the option moves for a $1 move in the stock, and roughly the chance it ends up being exercised.",
        detail=(
            "A 0.16 delta call moves about 16 cents per $1 of stock, and has roughly a "
            "16% chance of finishing in the money. That is why this desk targets 0.16 "
            "delta for short premium: about an 84% chance the option expires worthless "
            "and you keep the credit. The app accepts 0.15-0.20 and penalises anything "
            "below 0.10 or above 0.30."
        ),
        formula=(
            "call: N(d1);  put: N(d1) - 1\n"
            "d1 = [ln(S/K) + (r + sigma^2/2)T] / (sigma*sqrt(T))\n"
            "modules/options.py :: bs_greeks  (desk target 0.16, band 0.15-0.20)"
        ),
    ),
    "gamma": Term(
        label="Gamma",
        aliases=("Γ",),
        short="How fast delta itself changes",
        plain="How quickly your risk changes as the stock moves, high gamma means today's small move becomes tomorrow's big problem.",
        detail=(
            "Gamma is highest at the money and in the last week before expiry. For a "
            "premium seller it is the enemy: it is what turns a safe-looking short "
            "option into a losing one overnight. It is also why the app watches the Θ/Γ "
            "ratio rather than theta alone."
        ),
        formula=(
            "gamma = phi(d1) / (S * sigma * sqrt(T))     # phi = standard normal pdf\n"
            "modules/options.py :: bs_greeks"
        ),
    ),
    "theta": Term(
        label="Theta",
        aliases=("Θ", "theta/day", "theta per day", "θ/day"),
        short="Dollars of time-decay per day",
        plain="How much the option loses in value every day just from time passing, if you sold it, that is your daily income.",
        detail=(
            "This app reports theta per calendar day, and the ledger flips the sign so a "
            "short position shows positive theta (money you collect). Theta accelerates "
            "into expiry, which is exactly when gamma risk also spikes, that trade-off "
            "is the whole game for premium sellers."
        ),
        formula=(
            "call: [-S*phi(d1)*sigma/(2*sqrt(T)) - r*K*e^(-rT)*N(d2)] / 365\n"
            "put:  [-S*phi(d1)*sigma/(2*sqrt(T)) + r*K*e^(-rT)*N(-d2)] / 365\n"
            "ledger shows -theta x 100 x contracts (income convention)\n"
            "modules/options.py :: bs_greeks; modules/ui_helpers.py :: ledger_theta_desk_day"
        ),
    ),
    "vega": Term(
        label="Vega",
        aliases=("v",),
        short="Sensitivity to a 1-point IV move",
        plain="How much the option's price changes if the market's fear level rises by one point.",
        detail=(
            "Short options have negative vega: if implied volatility spikes after you "
            "sell, your position loses money even if the stock has not moved. That is "
            "why the app prefers selling when IV rank is already high, there is more "
            "room for volatility to fall in your favour than to rise against you."
        ),
        formula=(
            "vega = S * phi(d1) * sqrt(T) / 100      # per 1 percentage point of IV\n"
            "modules/options.py :: bs_greeks"
        ),
    ),
    "vanna": Term(
        label="Vanna",
        aliases=(),
        short="Delta drift when volatility changes",
        plain="How your directional exposure quietly shifts when the market gets more or less fearful.",
        detail=(
            "A second-order greek. It matters mostly around events: a volatility crush "
            "after earnings changes your effective delta even with the stock unchanged. "
            "You do not need it to trade, which is why it lives behind an expander."
        ),
        formula=(
            "vanna = phi(d1) * d2 / sigma * 0.01     # per +1 percentage point of IV\n"
            "modules/options.py :: bs_greeks"
        ),
    ),
    "charm": Term(
        label="Charm",
        aliases=("delta decay",),
        short="Delta drift from one day passing",
        plain="How your directional exposure changes overnight purely because expiry got one day closer.",
        detail=(
            "Also called delta decay. Near expiry, out-of-the-money options bleed delta "
            "toward zero and in-the-money options creep toward 1, that drift is charm. "
            "It is one reason pin behaviour strengthens into expiry week."
        ),
        formula=(
            "charm_per_day = -phi(d1) * (2rT - d2*sigma*sqrt(T)) / (2T*sigma*sqrt(T)) / 365\n"
            "modules/options.py :: bs_greeks"
        ),
    ),
    "theta_gamma_ratio": Term(
        label="Theta / Gamma ratio",
        aliases=("Θ/Γ", "theta gamma", "theta/gamma", "tgr", "theta_gamma"),
        short="Income earned per unit of risk",
        plain="Whether the daily income you collect is worth the overnight risk you are carrying.",
        detail=(
            "Above 2.0 the app calls it high decay efficiency: you are being paid well "
            "for the risk. Below 0.5 it flags gamma risk, a squeeze is likely to hurt "
            "more than the decay pays. Between the two, no strong opinion. It is also "
            "the weight the app uses when predicting an OpEx pin: high Θ/Γ makes the "
            "gamma wall more magnetic."
        ),
        formula=(
            "theta / gamma  (both from bs_greeks, per-day theta)\n"
            "> 2.0 = high decay efficiency; < 0.5 = gamma risk\n"
            "modules/options.py :: _theta_gamma_ratio_from_greeks; modules/ui_helpers.py :: _theta_gamma_desk_line"
        ),
    ),

    # ── Dealer positioning ──────────────────────────────────────────────────
    "gex": Term(
        label="Gamma Exposure (GEX)",
        aliases=("gamma exposure", "dealer gex", "net gex"),
        short="Dealer hedging pressure by strike",
        plain="How much the big option dealers have to buy or sell to stay hedged, it tells you whether moves get damped or amplified.",
        detail=(
            "Positive GEX means dealers are long gamma: they sell into rallies and buy "
            "dips, which pins price and calms the tape. Negative GEX means the reverse "
            "they chase, which amplifies moves. The app signs calls positive and puts "
            "negative, and gives strikes sitting on a high-volume node a 1.2x weight, on "
            "the theory that those price levels attract real order flow. A figure like "
            "'-2.3B' is notional dollars of gamma, not money at risk."
        ),
        formula=(
            "per contract: gamma x openInterest x S^2 / 100 x (+1 call | -1 put) x liquidity\n"
            "liquidity = 1.2 if the strike sits within max(0.4% of S, $0.02) of an HVN, else 1.0\n"
            "then summed by strike\n"
            "modules/options.py :: Opt.calc_gamma_exposure"
        ),
    ),
    "gamma_flip": Term(
        label="Gamma Flip",
        aliases=("flip point", "zero gamma"),
        short="Price where dealer hedging reverses",
        plain="The price level above which moves get calmer and below which they get wilder.",
        detail=(
            "Found by walking up the strikes and adding GEX until the running total "
            "crosses from positive to negative, then interpolating between the two "
            "strikes. Above the flip, dealer hedging dampens moves; below it, hedging "
            "accelerates them. When it sits within 5% of spot, the app folds it into the "
            "Gold Zone as a support component."
        ),
        formula=(
            "linear interpolation of the strike where cumsum(GEX sorted by strike)\n"
            "crosses from positive to negative\n"
            "modules/options.py :: Opt.find_gamma_flip"
        ),
    ),
    "opex_pin": Term(
        label="Predicted OpEx Pin",
        aliases=("pin", "opex", "pin price", "predicted pin"),
        short="Where price may stick at expiry",
        plain="The price the stock may get magnetically stuck near as options expire.",
        detail=(
            "The app finds the gamma wall: the strike with the largest absolute dealer "
            "GEX, preferring one within 12% of spot if it carries at least a quarter of "
            "the peak: and then blends it toward the current price. Higher Θ/Γ pulls "
            "the estimate closer to the wall, because pins stick harder when short "
            "premium dominates. This is a positioning heuristic. It is not a settlement "
            "prediction and it fails on news."
        ),
        formula=(
            "wall = strike of max |GEX| (near-spot preferred)\n"
            "w = clip(theta_gamma_ratio / 2, 0.42, 0.97)\n"
            "pin = w x wall + (1 - w) x spot\n"
            "modules/options.py :: Opt.predict_opex_pin"
        ),
    ),

    # ── Volatility ──────────────────────────────────────────────────────────
    "iv": Term(
        label="Implied Volatility (IV)",
        aliases=("implied volatility", "atm iv"),
        short="The market's expected move, annualised",
        plain="How big a swing the options market is pricing in, higher IV means richer premium for sellers and more expected movement.",
        detail=(
            "IV is backed out of the option's price, so it is the market's opinion, not "
            "a measurement. It rises into earnings and macro events and collapses "
            "afterwards. Selling premium is a bet that realised movement comes in below "
            "the implied one. The app shows IV as a percentage; 30% means a one-standard-"
            "deviation move of 30% over a year."
        ),
        formula=(
            "taken from the Yahoo chain field impliedVolatility x 100;\n"
            "when a strike quotes 0 the app substitutes 0.50 (50%) for greek maths\n"
            "modules/data.py :: fetch_options; modules/options.py :: Opt.covered_calls"
        ),
    ),
    "iv_rank": Term(
        label="IV Rank (proxy)",
        aliases=("iv rank", "ivr", "iv rank proxy"),
        short="Is today's IV high or low, 0-100%",
        plain="Whether option premium is expensive or cheap right now compared to what is normally available on this stock.",
        detail=(
            "Above 70 the app says rich premium (good time to sell), below 25 lean "
            "premium (a bad time to sell, a better time to buy). Read the word 'proxy' "
            "literally: real IV rank compares today's IV against a full year of daily "
            "history. This app compares the reference IV against the IVs available "
            "across the currently listed expirations, because a free data feed does not "
            "give a year of IV history. It is directionally right and occasionally off."
        ),
        formula=(
            "rank of the reference IV within the IVs of the currently listed expiries\n"
            "> 70 = rich premium, < 25 = lean premium, else fair\n"
            "modules/data.py :: compute_iv_rank_proxy; modules/ui_helpers.py :: _iv_rank_pill_html"
        ),
    ),
    "iv_term_structure": Term(
        label="IV Term Structure",
        aliases=("term structure", "contango", "backwardation"),
        short="Near-dated vs far-dated IV",
        plain="Whether the market is more worried about the next two weeks or the next few months.",
        detail=(
            "Contango (near IV below far IV) is the normal, calm state and the better "
            "environment for selling near-dated premium. Backwardation (near IV above "
            "far IV) means something is expected soon: earnings, a court date, a Fed "
            "meeting. Selling into backwardation without knowing the catalyst is how "
            "premium sellers get run over."
        ),
        formula=(
            "compare ATM IV of the nearest listed expiry against the 3rd;\n"
            "near > far + 2 pts = backwardation; far > near + 2 pts = contango; else flat\n"
            "modules/renderers.py :: render_cashflow_tab (IV term structure mini-table)"
        ),
    ),
    "vol_skew": Term(
        label="Volatility Skew",
        aliases=("skew", "put skew", "call skew"),
        short="Put IV minus call IV, 10% out",
        plain="Whether crash insurance costs more than upside bets, a read on which way institutions are nervous.",
        detail=(
            "A positive number means the 10%-out-of-the-money put is pricier than the "
            "matching call: someone is paying up for downside protection. That makes put "
            "premium fat for sellers, but it is also a warning that the smart money is "
            "hedging. Negative skew (calls bid over puts) usually means a speculative "
            "melt-up or a takeover rumour."
        ),
        formula=(
            "skew = IV(put nearest to 0.90 x spot) - IV(call nearest to 1.10 x spot), in IV points\n"
            "modules/options.py :: calc_vol_skew"
        ),
    ),
    "skew_regime": Term(
        label="Skew Regime",
        aliases=("skew ratio", "crash hedging", "balanced smile"),
        short="Named state of the whole IV curve",
        plain="A one-word label for what the option market's mood is across every strike.",
        detail=(
            "Unlike the two-strike skew number, this uses the median IV of every "
            "out-of-the-money put versus every out-of-the-money call, so a single weird "
            "quote cannot move it. CRASH HEDGING and BEARISH SKEW mean protection is "
            "being bought. UPSIDE MANIA means calls are bid, which historically shows up "
            "near local tops in retail-heavy names. BALANCED SMILE is the boring, normal "
            "state."
        ),
        formula=(
            "ratio = median IV(OTM puts) / median IV(OTM calls), IV filtered to 0.05-3.00\n"
            "> 1.25 CRASH HEDGING | > 1.08 BEARISH SKEW | < 0.85 UPSIDE MANIA | else BALANCED SMILE\n"
            "modules/options.py :: calc_skew_regime"
        ),
    ),
    "expected_move": Term(
        label="Expected Move",
        aliases=("em", "1 sigma", "expected move range", "σ"),
        short="One-sigma implied move to expiry",
        plain="The range the options market expects the stock to stay inside about two-thirds of the time.",
        detail=(
            "The app draws this as gold rails on the chart and uses it as a safety "
            "check: a short strike OUTSIDE the expected move is the high-safety case, "
            "INSIDE it means you should watch gamma. Two-thirds is not certainty, one "
            "expiry in three lands outside by design, and earnings gaps ignore it "
            "entirely."
        ),
        formula=(
            "EM = S x (IV/100) x sqrt(days_to_expiry / 365.25)\n"
            "range = spot +/- EM\n"
            "modules/options.py :: Opt.calc_expected_move"
        ),
    ),
    "vix": Term(
        label="VIX",
        aliases=("^vix", "fear index"),
        short="Market-wide 30-day fear gauge",
        plain="How nervous the whole market is, not just this stock.",
        detail=(
            "Below 15 is complacent, above 20 is elevated, above 25 is stress. The app "
            "uses it two ways: as 40% of the volatility pillar in the Edge Score, and as "
            "a macro gate in Sentiment Radar, where a high VIX makes speculative buzz "
            "signals less trustworthy. When VIX is high, everything correlates and "
            "single-name analysis matters less."
        ),
        formula=(
            "vix_pillar = clip(50 + (VIX - 18) x 2.5, 20, 90), then 40% of the volatility pillar\n"
            "macro gate: > 20 elevated, > 25 stress\n"
            "modules/options.py :: _quant_edge_pillars; modules/sentiment_radar.py :: macro_risk_level"
        ),
    ),

    # ── Probability, expectancy and sizing ──────────────────────────────────
    "mc_pop": Term(
        label="Monte Carlo PoP",
        aliases=("mc pop", "pop", "probability of profit", "mc pop %"),
        short="Simulated chance of profit, %",
        plain="Out of 10,000 simulated futures, the share where this trade makes money.",
        detail=(
            "The app simulates 10,000 price paths with a fixed random seed (so the "
            "number does not jitter on every rerun) and counts how many finish on the "
            "profitable side of your breakeven: not merely out of the money, which is "
            "the softer number most brokers quote. Antithetic pairs halve the noise. It "
            "assumes lognormal returns, so it understates fat-tail and gap risk."
        ),
        formula=(
            "S_T = S x exp((r - q - sigma^2/2)T + sigma*sqrt(T)*Z), Z antithetic, seed 42, n=10000\n"
            "short put:  count(S_T >= K - premium) / n;  short call: count(S_T <= K + premium) / n\n"
            "modules/options.py :: MonteCarloEngine.calc_pop"
        ),
    ),
    "ev": Term(
        label="Expected Value",
        aliases=("expected value", "ev per contract"),
        short="Average profit per trade, long run",
        plain="What this trade earns on average if you took it hundreds of times, positive means a real edge.",
        detail=(
            "A high win rate is not the same as a good trade. Expected value weighs the "
            "size of the wins against the size of the losses. A 90% win rate that loses "
            "20x on the other 10% is a negative-EV trade. Negative EV means pass, no "
            "matter how comfortable the setup looks."
        ),
        formula=(
            "EV = (PoP x premium) - ((1 - PoP) x max_loss), per contract\n"
            "modules/options.py :: calc_ev"
        ),
    ),
    "kelly": Term(
        label="Kelly Size",
        aliases=("kelly criterion", "kelly %", "half kelly", "full kelly"),
        short="Mathematically optimal bet size",
        plain="The share of your account this trade mathematically justifies, and it is usually smaller than you would guess.",
        detail=(
            "Full Kelly maximises long-run growth but produces stomach-churning "
            "drawdowns, so the app also shows Half Kelly and caps what it displays. Two "
            "further haircuts apply: a correlation haircut if the position overlaps what "
            "you already hold, and a boost or cut based on the Monte Carlo PoP relative "
            "to a baseline of 85%. Treat the output as a ceiling, not a target."
        ),
        formula=(
            "f* = W - (1 - W)/R, where W = win probability, R = win/loss ratio\n"
            "x pop_mult = sqrt(avg_mc_pop / 85);  half Kelly = f*/2\n"
            "quant mode uses the Merton form: f* = (mu - r) / variance\n"
            "modules/options.py :: kelly_criterion, continuous_kelly"
        ),
    ),
    "kelly_haircut": Term(
        label="Correlation Haircut",
        aliases=("haircut", "overlap score", "risk multiplier", "correlation overlap"),
        short="Size cut for overlapping positions",
        plain="If this trade moves with things you already own, the app shrinks the suggested size.",
        detail=(
            "Owning five names that all move together is one position wearing five "
            "costumes. The app measures average correlation of this ticker against the "
            "rest of your watchlist and multiplies the suggested size down. A genuinely "
            "negatively correlated name gets a 20% boost instead, because it hedges what "
            "you hold. Correlations are computed on fractionally differenced returns, "
            "which keeps more of the trend information than plain returns do."
        ),
        formula=(
            "overlap = mean correlation of this ticker vs the rest of the matrix\n"
            ">= 0.8 -> x0.50 | >= 0.6 -> x0.75 | <= 0.0 -> x1.20 | else x1.00\n"
            "modules/options.py :: PortfolioRisk.get_overlap_score, calc_kelly_haircut"
        ),
    ),
    "var_95": Term(
        label="1-day 95% VaR",
        aliases=("var", "var_95_1d", "value at risk"),
        short="Bad-day loss estimate, 95% confidence",
        plain="On 19 days out of 20 your open positions should lose less than this in a single day.",
        detail=(
            "Computed from the dollar delta of every open leg, scaled by each name's "
            "20-day realised volatility, then combined through the correlation matrix so "
            "that positions moving together do not net each other out. The one day in "
            "twenty it is wrong is usually much worse than the number, VaR says nothing "
            "about how deep the tail goes."
        ),
        formula=(
            "e_i = position_delta_i x spot_i x realised_vol_20d_i\n"
            "VaR = 1.65 x sqrt(e' C e), C = correlation matrix\n"
            "modules/ui_helpers.py :: sentinel_ledger_metrics"
        ),
    ),
    "edge_realization": Term(
        label="Edge Realization",
        aliases=("edge realization %", "edge realisation"),
        short="Today's edge vs edge at entry",
        plain="Whether the setup that made you take the trade is still as good as it was when you took it.",
        detail=(
            "Above 100% the conditions improved after you entered. Well below 100% the "
            "reason you took the trade has decayed, which is a prompt to review rather "
            "than an automatic exit. Only applies to ledger rows on the currently "
            "selected ticker, and it is capped at 150% so one lucky day cannot dominate "
            "the display."
        ),
        formula=(
            "min(150, 100 x current_edge_score / edge_score_at_entry)\n"
            "modules/renderers.py :: render_ledger_tab"
        ),
    ),

    # ── Contract mechanics ──────────────────────────────────────────────────
    "dte": Term(
        label="DTE (Days to Expiry)",
        aliases=("days to expiry", "days to expiration", "dte days"),
        short="Calendar days until the option expires",
        plain="How many days are left before this contract expires.",
        detail=(
            "Short-premium desks usually work in the 21-45 day window: enough time value "
            "to be worth selling, not so close to expiry that gamma dominates. Under 14 "
            "days, decay is fastest but a single adverse move hurts disproportionately. "
            "The app counts calendar days, not trading days."
        ),
        formula=(
            "DTE = (expiration_date - today).days, floored at 1\n"
            "modules/renderers.py :: render_cashflow_tab"
        ),
    ),
    "otm_pct": Term(
        label="OTM %",
        aliases=("otm", "out of the money %", "otm_pct", "buffer"),
        short="Cushion between price and strike",
        plain="How far the stock has to move before your short option starts costing you money.",
        detail=(
            "Your safety buffer. Bigger is safer and pays less. The app scores this "
            "alongside yield so the recommended strike is not simply the fattest premium "
            "the contribution to the score is capped at 15%, past which extra distance "
            "buys nothing in ranking terms."
        ),
        formula=(
            "call: (strike - spot) / spot x 100;  put: (spot - strike) / spot x 100\n"
            "modules/options.py :: Opt.covered_calls, Opt.cash_secured_puts"
        ),
    ),
    "prem_yield": Term(
        label="Premium Yield",
        aliases=("premium yield", "prem yield", "yield", "py"),
        short="Credit as a % of stock price",
        plain="The cash you collect, as a percentage of what the shares are worth.",
        detail=(
            "This makes contracts on a $40 stock and a $400 stock comparable. It is a "
            "per-cycle figure, not annual, a 1.5% yield on a 30-day contract is a "
            "different animal to 1.5% on a 90-day one, which is what the annualised "
            "figure exists to fix."
        ),
        formula=(
            "premium_yield = mid_price / spot x 100,  mid = (bid + ask) / 2\n"
            "modules/options.py :: Opt.covered_calls, Opt.cash_secured_puts"
        ),
    ),
    "ann_yield": Term(
        label="Annualized Yield",
        aliases=("annualized yield", "annualised yield", "ann yield", "ann_yield"),
        short="Yield scaled to a full year",
        plain="What this trade would earn per year if you could repeat it over and over, a comparison tool, not a promise.",
        detail=(
            "Useful only for ranking one contract against another. Nobody achieves it: "
            "it assumes you re-sell instantly at identical terms, are never assigned, "
            "and never sit out a bad tape. A 200% annualised figure on a 3-day contract "
            "is telling you the contract is short, not that it is good."
        ),
        formula=(
            "annualized = premium_yield x 365 / max(DTE, 1)\n"
            "modules/options.py :: Opt.covered_calls, Opt.cash_secured_puts"
        ),
    ),
    "breakeven": Term(
        label="Breakeven",
        aliases=("be", "break-even"),
        short="Price where the trade nets zero",
        plain="The stock price at which you neither make nor lose money on this position.",
        detail=(
            "For a covered call the app reports spot minus the credit received: the "
            "premium lowers your effective cost basis, which is the real downside "
            "cushion. For a cash-secured put it is the strike minus the credit, the "
            "price you effectively pay if you are assigned."
        ),
        formula=(
            "covered call: spot - mid;  cash-secured put: strike - mid\n"
            "modules/options.py :: Opt.covered_calls, Opt.cash_secured_puts"
        ),
    ),
    "open_interest": Term(
        label="Open Interest",
        aliases=("oi", "open interest"),
        short="Contracts currently outstanding",
        plain="How many of this exact contract are being held right now, a proxy for how easily you can get out.",
        detail=(
            "Low open interest means wide spreads and a bad fill when you want to close "
            "early. The app requires at least 100 open interest and 10 daily volume, and "
            "only relaxes to 10 and 1 when a strict pass returns nothing at all (common "
            "after hours or on thin names). If you see relaxed-mode results, treat the "
            "quoted prices as indicative."
        ),
        formula=(
            "strict gate: openInterest >= 100 AND volume >= 10\n"
            "relaxed fallback: openInterest >= 10 AND volume >= 1\n"
            "modules/options.py :: Opt.MIN_OI, Opt.RELAXED_MIN_OI"
        ),
    ),
    "covered_call": Term(
        label="Covered Call",
        aliases=("cc", "covered calls"),
        short="Sell a call against 100 shares",
        plain="You own 100 shares and sell someone the right to buy them higher, you keep the cash either way.",
        detail=(
            "If the stock stays below the strike you keep both the cash and the shares, "
            "and you can do it again. If it goes above, your shares get sold at the "
            "strike, which caps your upside, you still profit, just less than holding. "
            "The realistic target here is 1-3% per month in cash income."
        ),
        formula=(
            "credit = mid x 100 per contract; the app targets the 0.16-delta strike\n"
            "modules/options.py :: Opt.covered_calls"
        ),
    ),
    "cash_secured_put": Term(
        label="Cash-Secured Put",
        aliases=("csp", "cash secured put", "the wheel", "wheel"),
        short="Sell a put, hold cash to buy",
        plain="You get paid now for agreeing to buy the stock cheaper later, with the cash set aside to do it.",
        detail=(
            "If the stock stays above your strike you keep the credit and repeat. If it "
            "falls below you buy the shares at the strike, minus the premium you already "
            "collected. Then you sell covered calls against those shares, that loop is "
            "the Wheel. Only sell puts on stock you actually want to own."
        ),
        formula=(
            "collateral = strike x 100 per contract; the app targets the 0.16-delta strike\n"
            "modules/options.py :: Opt.cash_secured_puts"
        ),
    ),
    "credit_spread": Term(
        label="Credit Spread",
        aliases=("bull put spread", "bear call spread", "spread"),
        short="Sell one option, buy protection",
        plain="Collect a credit like a naked option, but buy a cheaper far option so your worst case is capped.",
        detail=(
            "A bull put spread is the bullish version, a bear call spread the bearish "
            "one. You collect less than selling naked, but the maximum loss is fixed and "
            "known before you enter, and it ties up far less capital than a "
            "cash-secured put. This is the right structure when the weekly trend is "
            "against you."
        ),
        formula=(
            "max_loss = (width of strikes x 100) - credit received\n"
            "modules/options.py :: Opt.credit_spreads"
        ),
    ),

    # ── Technical indicators, as computed here ──────────────────────────────
    "rsi": Term(
        label="RSI",
        aliases=("relative strength index", "rsi14", "rsi(14)"),
        short="0-100 overbought / oversold meter",
        plain="An energy gauge: near 70 buyers are tired, near 30 sellers have panicked.",
        detail=(
            "This app uses Wilder's smoothing (matching TradingView and Bloomberg), not "
            "the simple moving average some libraries use: the two disagree enough to "
            "change signals. Above 70 is a good moment to sell calls, below 30 a good "
            "moment to sell puts, and 40-60 is the calm middle the Edge Score rewards "
            "most for premium selling."
        ),
        formula=(
            "RSI = 100 - 100/(1 + avg_gain/avg_loss), EWM with com = period - 1 (Wilder)\n"
            "modules/ta.py :: TA.rsi"
        ),
    ),
    "macd": Term(
        label="MACD",
        aliases=("macd line", "macd signal", "macd histogram"),
        short="Fast vs slow trend crossover",
        plain="Shows who is winning right now, buyers or sellers, by comparing recent momentum against the longer average.",
        detail=(
            "The MACD line crossing above its signal line means buyers are taking over; "
            "below means sellers are. Standard 12/26/9 settings. It lags by "
            "construction, so it confirms a move rather than predicting one, which is "
            "why it is one vote among four in the weekly bias, never the whole call."
        ),
        formula=(
            "macd = EMA(12) - EMA(26); signal = EMA(macd, 9); histogram = macd - signal\n"
            "modules/ta.py :: TA.macd"
        ),
    ),
    "adx": Term(
        label="ADX",
        aliases=("adx di", "average directional index", "+di", "-di"),
        short="Trend strength, no direction",
        plain="How strong the current move is: it does not say up or down, only strong or weak.",
        detail=(
            "Above 25 means a real trend is running and trend-following tools can be "
            "trusted. Below 20 means the market is drifting and those same tools "
            "generate noise. Direction comes from the two companion lines: +DI above -DI "
            "means buyers are in front. The confluence score requires both conditions "
            "together for its single point."
        ),
        formula=(
            "Wilder's ADX over 14 periods from smoothed +DM / -DM and ATR;\n"
            "confluence point requires ADX > 25 AND +DI > -DI\n"
            "modules/ta.py :: TA.adx"
        ),
    ),
    "obv": Term(
        label="OBV",
        aliases=("on balance volume", "on-balance volume"),
        short="Running volume-flow tally",
        plain="Tracks whether volume is arriving on up days or down days, a read on quiet institutional buying.",
        detail=(
            "Volume is added on up days and subtracted on down days. Rising OBV while "
            "price is flat suggests accumulation before a move. The most useful case is "
            "disagreement: if price makes a new high but OBV does not, the move is not "
            "supported by real participation. The app scores it by comparing today's OBV "
            "against 20 bars ago."
        ),
        formula=(
            "OBV_t = OBV_(t-1) + sign(close_t - close_(t-1)) x volume_t\n"
            "accumulation flag: OBV_today > OBV_20_bars_ago\n"
            "modules/ta.py :: TA.obv"
        ),
    ),
    "supertrend": Term(
        label="Supertrend",
        aliases=("super trend", "st"),
        short="ATR-based trailing trend line",
        plain="A moving floor under the price in an uptrend, or a ceiling above it in a downtrend, when it flips, act.",
        detail=(
            "Built from the ATR, so it widens automatically when volatility rises and "
            "tightens when the tape calms: that is why it whipsaws less than a fixed "
            "percentage stop. Green below price is bullish, red above is bearish. It is "
            "worth 2 of the 9 confluence points, the joint-largest single weight."
        ),
        formula=(
            "bands = (high + low)/2 +/- 3.0 x ATR(10), then trailed so they never loosen\n"
            "modules/ta.py :: TA.supertrend"
        ),
    ),
    "ichimoku": Term(
        label="Ichimoku Cloud",
        aliases=("cloud", "kumo", "above cloud"),
        short="Multi-line trend and support band",
        plain="A shaded band on the chart: price floating above it is bullish, price inside or below it is weak.",
        detail=(
            "Five components, but for scoring purposes only one question matters: is "
            "price above both cloud boundaries? The cloud is projected forward, so it "
            "shows where support is expected to be, not only where it was. Worth 2 of "
            "the 9 confluence points."
        ),
        formula=(
            "span A = (conversion + base)/2; span B = midpoint of the 52-period range;\n"
            "bullish when close > max(span A, span B)\n"
            "modules/ta.py :: TA.ichimoku"
        ),
    ),
    "atr": Term(
        label="ATR",
        aliases=("average true range", "atr14"),
        short="Average daily move, in dollars",
        plain="How much this stock typically moves in a day, in dollars, the unit for sizing stops sanely.",
        detail=(
            "A $2 ATR means a $2 move is an ordinary day, not an event. The app uses it "
            "for stop distance, position sizing, Supertrend bands, and as the squeeze "
            "detector behind the Pre-Diamond (ATR in the bottom quarter of its 60-day "
            "range means the spring is compressed)."
        ),
        formula=(
            "TR = max(high-low, |high-prev_close|, |low-prev_close|); ATR = SMA(TR, 14)\n"
            "modules/ta.py :: TA.atr"
        ),
    ),
    "market_structure": Term(
        label="Market Structure",
        aliases=("structure", "daily structure", "higher highs"),
        short="Higher highs or lower lows",
        plain="Whether each swing is landing higher than the last one, lower, or going nowhere.",
        detail=(
            "The simplest honest description of a trend, and it needs no indicator. The "
            "app looks at the last two swing highs and lows found with a 5-bar window: "
            "both higher is BULLISH, both lower is BEARISH, anything mixed is RANGING. "
            "Ranging is not a bad state for premium sellers, it is the best one."
        ),
        formula=(
            "swing points from a 5-bar lookback each side;\n"
            "BULLISH if last high > prior high AND last low > prior low; mirrored for BEARISH; else RANGING\n"
            "modules/ta.py :: TA.market_structure"
        ),
    ),
    "weekly_bias": Term(
        label="Weekly Bias",
        aliases=("weekly trend", "wk_label", "weekly"),
        short="Higher-timeframe direction vote",
        plain="What the weekly chart says, so a daily signal does not get taken against the bigger trend.",
        detail=(
            "Four weekly votes: MACD above its signal, price above the 20-week EMA, RSI "
            "above 55 or below 45 (a neutral RSI abstains), and OBV rising over eight "
            "bars. Three-quarters must agree or the answer is MIXED. When it reads "
            "BEARISH the app explicitly warns against selling naked puts and steers you "
            "to defined-risk spreads."
        ),
        formula=(
            "votes = [MACD > signal, close > EMA20, RSI > 55 (abstain 45-55), OBV rising 8 bars]\n"
            "BULLISH/BEARISH need >= max(2, 75% of cast votes); else MIXED\n"
            "modules/options.py :: weekly_trend_label"
        ),
    ),
    "hurst": Term(
        label="Hurst Exponent",
        aliases=("hurst exponent", "h", "r/s"),
        short="Trending vs mean-reverting, 0-1",
        plain="Tells you whether this stock tends to keep going in one direction or snap back, and whether trend indicators can be trusted at all.",
        detail=(
            "Above 0.55 the stock trends, so Supertrend, ADX and MACD are meaningful. "
            "Below 0.45 it mean-reverts, which favours selling options at extremes. "
            "Between the two it is a random walk and the app says so plainly: your trend "
            "tools are noise right now. Two estimators exist in the codebase, a fast "
            "single-window rescaled-range and a variance-ratio version; both need a "
            "year of data before they report anything."
        ),
        formula=(
            "H = log(R/S) / log(n) over the last 252 closes' log returns\n"
            "H > 0.55 trending | H < 0.45 mean-reverting | else random walk\n"
            "modules/ta.py :: TA.calculate_hurst_exponent, TA.hurst"
        ),
    ),
    "poc": Term(
        label="POC (Point of Control)",
        aliases=("point of control", "volume poc"),
        short="Price with the most traded volume",
        plain="The price level where the most shares actually changed hands, a magnet the stock keeps returning to.",
        detail=(
            "Real transactions, not a moving average, which is why it is the "
            "highest-weighted input to the Gold Zone. Price tends to gravitate back to "
            "the POC because that is where the largest number of positions were opened "
            "and therefore where the most people want to defend or exit."
        ),
        formula=(
            "bucket the range into 20 bins, sum volume per bin, take the midpoint of the fullest bin\n"
            "modules/ta.py :: TA.volume_profile"
        ),
    ),
    "hvn": Term(
        label="HVN (High Volume Node)",
        aliases=("high volume node", "hvn floor", "volume node"),
        short="Secondary heavy-volume price shelf",
        plain="Another price shelf where lots of trading happened, these act as support and resistance.",
        detail=(
            "Where the POC is the single fullest bin, HVNs are the other peaks in the "
            "volume profile. The app uses the nearest one within 2% of spot as a Gold "
            "Zone component, gives option strikes sitting on one a 1.2x weight in the "
            "GEX calculation, and awards a small bonus to strikes sitting between the "
            "POC and an HVN."
        ),
        formula=(
            "peaks of a 60-bin volume profile over 90 days; nearest node within +/-2% of spot\n"
            "modules/ta.py :: TA.get_volume_nodes; modules/options.py :: nearest_hvn_within_pct"
        ),
    ),
    "fib_618": Term(
        label="Fibonacci 61.8%",
        aliases=("fib", "fib 61.8%", "golden ratio", "fib retracement"),
        short="Golden-ratio pullback level",
        plain="After a big run, stocks often pull back about 62% of the way before continuing, this is that line.",
        detail=(
            "There is no physical law here; it works partly because a very large number "
            "of traders watch the same level and place orders there. The app computes it "
            "over the last 60 bars and feeds it into the Gold Zone at a lower weight than "
            "the volume-based components, precisely because it is a convention rather "
            "than a record of real trading."
        ),
        formula=(
            "level = high(60) - (high(60) - low(60)) x 0.618\n"
            "modules/options.py :: calc_gold_zone; modules/ta.py :: TA.fib_retracement"
        ),
    ),
    "gann_sq9": Term(
        label="Gann Square of 9",
        aliases=("gann", "square of 9", "gann sq9"),
        short="Geometric price levels",
        plain="Support and resistance prices derived from a mathematical spiral, the most speculative input the app uses.",
        detail=(
            "Included for completeness and weighted the lowest of every Gold Zone "
            "component (0.55 versus 1.35 for volume-based levels) because there is no "
            "order-flow reason for it to work. If it disagrees with the POC, trust the "
            "POC."
        ),
        formula=(
            "levels at (sqrt(price) +/- k x 0.125)^2 for k = 1..n; nearest level to spot is used\n"
            "modules/ta.py :: TA.gann_sq9"
        ),
    ),
    "whale_zscore": Term(
        label="Whale Volume Z-Score",
        aliases=("volume z", "volume z-score", "dark pool proxy", "whale alert", "volz"),
        short="How unusual today's volume is",
        plain="How far above normal today's volume is: above 2 means someone big is almost certainly trading.",
        detail=(
            "A z-score of 2 means volume is two standard deviations above its recent "
            "average, which happens rarely by chance. The lookback window adapts to the "
            "volatility regime: 10 days when short-horizon volatility dominates, 40 when "
            "the tape is calm, 30 otherwise. The 'dark pool' label in parts of the UI is "
            "a proxy inferred from public volume, not actual dark-pool print data."
        ),
        formula=(
            "z = (volume - rolling_mean(w)) / rolling_std(w), w in {10, 30, 40} by vol regime\n"
            "whale flag when z > 2.0\n"
            "modules/ta.py :: TA.get_dark_pool_proxy, TA._whale_zscore_window"
        ),
    ),
    "shadow_move": Term(
        label="Shadow Move",
        aliases=("shadow", "shadow band", "shadow low", "purple band"),
        short="Price range the whales traded in",
        plain="The purple band shows where the big-volume days actually traded, compare it to what options are pricing in.",
        detail=(
            "Only bars with a whale-level volume z-score count. Their closes are sorted "
            "by price and the middle 70% of that volume defines the band. The read is "
            "comparative: if the shadow is narrower than the options-implied expected "
            "move, volatility may be overpriced (good for sellers). If it is wider, a "
            "bigger move than options are pricing may be brewing. When spot breaks out "
            "of the shadow while still inside the expected move, big money has moved "
            "before options repriced."
        ),
        formula=(
            "take bars with volume z > 2 over the last 30; sort their closes by price;\n"
            "band = the central 70% of cumulative whale volume\n"
            "modules/ta.py :: TA.get_shadow_move"
        ),
    ),
    "rs_spy": Term(
        label="Relative Strength vs SPY",
        aliases=("rs", "rs spy", "rs_spy_ratio", "relative strength"),
        short="Performance versus the index",
        plain="Whether this stock is beating the overall market or just being carried by it.",
        detail=(
            "A ratio above 1.0 means outperformance. Leadership matters because "
            "institutions add to what is already working; a stock that cannot beat SPY "
            "in a rally usually cannot protect you in a selloff either. The app uses a "
            "90-day ratio for the 10x score and a 3-day comparison inside the "
            "Pre-Diamond check."
        ),
        formula=(
            "rs_ratio = (ticker_return over window) / (SPY_return over same window)\n"
            "10x score: 90-day window, point awarded above 1.2; pre-diamond: 3-day comparison\n"
            "modules/options.py :: score_10x_potential, Opt.detect_pre_diamond"
        ),
    ),
    "bbw_percentile": Term(
        label="Squeeze Percentile",
        aliases=("bbw", "bbw percentile", "bbw_pctile", "bollinger band width", "squeeze"),
        short="How compressed volatility is",
        plain="How tightly the price range has compressed compared to its own past year, low numbers mean a spring is loaded.",
        detail=(
            "Measures Bollinger band width and ranks it against its own history rather "
            "than an absolute threshold, so it works on both a sleepy utility and a "
            "volatile biotech. Below the 10th percentile counts as a squeeze for the 10x "
            "score; the strict convexity sieve wants below the 5th. A squeeze says "
            "'expect a big move', never which direction."
        ),
        formula=(
            "BBW = (upper - lower) / middle from a 20-period, 2 sd Bollinger;\n"
            "percentile rank over the last 252 bars\n"
            "modules/options.py :: _bbw_series, score_10x_potential"
        ),
    ),

    # ── Model-mode terms (Quant / Institutional toggle) ─────────────────────
    "ffd": Term(
        label="Stationary Signal (FFD)",
        aliases=("fractional differentiation", "ffd", "frac diff", "stationary signal"),
        short="De-trended price that keeps memory",
        plain="A cleaned-up version of the price series that removes the long-term drift without throwing away the pattern.",
        detail=(
            "Plain price data trends, which breaks most statistical models; converting to "
            "daily returns fixes that but discards nearly all the memory. Fractional "
            "differentiation sits between the two, keeping just enough history to remain "
            "informative while being statistically well-behaved. The UI calls it "
            "'Stationary Signal' to avoid the jargon. It feeds the Quant-mode Edge Score, "
            "the regime detector, and the correlation matrix."
        ),
        formula=(
            "weights w_k = -w_(k-1) x (d - k + 1)/k with d = 0.4, capped at 50 lags;\n"
            "output_t = sum_k w_k x price_(t-k)\n"
            "modules/ta.py :: TA.apply_ffd"
        ),
    ),
    "hmm_regime": Term(
        label="Market Regime",
        aliases=("hmm", "regime", "regime detection", "regime probability"),
        short="Calm / medium / stressed probability",
        plain="A model's read on whether the market is currently calm, choppy, or stressed, used to size positions down when it is stressed.",
        detail=(
            "A three-state hidden Markov model fitted to fractionally differenced returns "
            "and their rolling volatility. States are always sorted by volatility so "
            "state 0 is the calmest regardless of how the fit initialised, that makes "
            "the labels stable across tickers and reruns. High-vol probability directly "
            "reduces the institutional Edge Score, so the app shrinks conviction rather "
            "than merely warning you."
        ),
        formula=(
            "3-state Gaussian HMM on [FFD returns, 10-bar rolling std], states sorted by vol\n"
            "stress weight = P(state 2) + 0.35 x P(state 1); Edge penalty = stress x 18 pts\n"
            "modules/sentiment.py :: _regime_detection_cached; modules/options.py :: quant_edge_score"
        ),
    ),
    "corrado_su": Term(
        label="Fat-Tail Pricing",
        aliases=("corrado-su", "corrado su", "corrado_su"),
        short="Option pricing with skew and fat tails",
        plain="A pricing model that allows for crashes being more likely than the textbook assumes.",
        detail=(
            "Standard Black-Scholes assumes returns are normally distributed, which "
            "underprices the tails: real markets crash more often than the bell curve "
            "allows. The Corrado-Su expansion adds skew and kurtosis corrections on top "
            "of the Black-Scholes price. Only active when Quant mode is on."
        ),
        formula=(
            "price = BS + skew x Q3 + (kurtosis - 3) x Q4, the standard Corrado-Su terms\n"
            "modules/options.py :: bs_corrado_su"
        ),
    ),

    # ── Sentiment Radar ─────────────────────────────────────────────────────
    "wilson": Term(
        label="Crowd Conviction (Wilson)",
        aliases=("wilson", "wilson score", "wilson lower bound", "conviction"),
        short="Bullish share, penalised for small samples",
        plain="How bullish the crowd is, deliberately discounted when only a handful of people have posted.",
        detail=(
            "Two bullish messages out of two is not 100% bullish conviction, it is two "
            "people. The Wilson lower bound scores that around 0.34, while 40 bullish "
            "out of 50 scores about 0.67. This is the anti-hype guard in Sentiment "
            "Radar: it makes a genuinely broad bullish crowd score higher than a loud "
            "tiny one, which is the opposite of what a raw percentage does."
        ),
        formula=(
            "lower bound of the 95% Wilson interval (z = 1.96) on bullish/total StockTwits tags\n"
            "modules/sentiment_radar.py :: wilson_lower_bound"
        ),
    ),
    "mention_velocity": Term(
        label="Mention Velocity",
        aliases=("velocity", "buzz velocity", "mention acceleration"),
        short="Buzz growth versus yesterday",
        plain="How fast chatter about a ticker is accelerating, doubling matters more than being loud.",
        detail=(
            "Absolute mention counts favour the mega-caps that are always discussed. "
            "Velocity finds the names waking up. It is measured on a log scale so a "
            "10x jump saturates the component: beyond that the app stops rewarding "
            "extra noise. Climbing 20 or more spots in the ApeWisdom rank adds a small "
            "bonus as corroborating evidence."
        ),
        formula=(
            "v = mentions_now / max(1, mentions_24h_ago)\n"
            "component = clip(log10(v), 0, 1), + 0.15 if the rank climbed >= 20 spots\n"
            "modules/sentiment_radar.py :: mention_velocity, velocity_component"
        ),
    ),
    "attention_stage": Term(
        label="Attention Stage",
        aliases=("stage", "cascade stage", "attention cascade"),
        short="How far the hype has travelled",
        plain="Attention spreads in order: talk, then searches, then volume, then price. This says which step you are at.",
        detail=(
            "The seedling stage is the earliest and most valuable: people are talking but "
            "nothing has moved. The rocket stage means volume has confirmed the story but "
            "price has not fully run. The volcano stage means price already moved and you "
            "would be buying from the people who were early. Later is not better, it is "
            "the opposite."
        ),
        formula=(
            "nodes lit: attention (velocity >= 2 or trends >= 1.5x), volume (z >= 2), price (|5d move| >= 15%)\n"
            "stage = the furthest node lit along attention -> volume -> price\n"
            "modules/sentiment_radar.py :: attention_stage"
        ),
    ),
    "sentiment_score": Term(
        label="Sentiment Score",
        aliases=("asymmetric score", "buzz score", "sentiment radar score"),
        short="Composite retail-buzz score, 0-100",
        plain="One number for how early and how real the crowd interest is, high means buzz is building before the price moved.",
        detail=(
            "Five weighted components: mention velocity, crowd conviction, volume "
            "confirmation, earliness (has price already run?), and Google search "
            "interest. Two integrity caps apply: if Reddit is hot but StockTwits has "
            "fewer than three messages the score is capped at 60, and if the independent "
            "Reddit re-count disagrees with ApeWisdom by more than 5x it is capped at 50. "
            "It is a research lead, never a buy signal."
        ),
        formula=(
            "100 x (0.30 velocity + 0.20 wilson + 0.20 volume_z + 0.15 earliness + 0.15 trends)\n"
            "caps: thin confirmation -> 60, source disagreement -> 50\n"
            "modules/sentiment_radar.py :: composite_score, WEIGHTS"
        ),
    ),
    "news_bias": Term(
        label="News Bias",
        aliases=("headline bias", "news sentiment", "bayesian news"),
        short="Weighted headline tone score",
        plain="Reads the headlines and leans on forward-looking language more than on what already happened.",
        detail=(
            "Words about the future (guidance, outlook, forecast) are weighted about 1.45 "
            "while backward-looking words (beat, miss) get about 0.82. So 'missed "
            "earnings but raised guidance' tilts bullish, which is usually how the tape "
            "reacts too. It is a keyword lexicon, not a language model, sarcasm and "
            "unusual phrasing will fool it, and empty or neutral text scores zero."
        ),
        formula=(
            "sum of matched lexicon weights; forward terms x1.45, trailing terms x0.82\n"
            "modules/sentiment.py :: _NEWS_LEXICON, _FORWARD_W, _TRAIL_W"
        ),
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
#  PURE LOOKUP / FORMATTING HELPERS  (no Streamlit, fully unit-testable)
# ═══════════════════════════════════════════════════════════════════════════

TONES: tuple[str, ...] = ("good", "warn", "bad", "neutral")

TONE_GLYPH: dict[str, str] = {
    "good": "🟢",
    "warn": "🟡",
    "bad": "🔴",
    "neutral": "⚪",
}

#: Streamlit callable name used by :func:`verdict_line` for each tone.
_TONE_BOX: dict[str, str] = {
    "good": "success",
    "warn": "warning",
    "bad": "error",
    "neutral": "info",
}


def normalize_key(raw: Any) -> str:
    """Fold any label spelling to a registry-style key.

    ``"Θ/Γ"`` -> ``"θ/γ"``, ``"MC PoP %"`` -> ``"mc pop %"``. Used by
    :func:`lookup` so migrating call sites can pass whatever string the old
    code displayed.
    """
    s = str(raw or "").strip().lower()
    # Collapse internal whitespace so "IV  rank" == "IV rank".
    return " ".join(s.split())


def _alias_index() -> dict[str, str]:
    idx: dict[str, str] = {}
    for key, term in TERMS.items():
        idx[normalize_key(key)] = key
        idx[normalize_key(key.replace("_", " "))] = key
        if term.label:
            idx.setdefault(normalize_key(term.label), key)
        for alias in term.aliases:
            idx.setdefault(normalize_key(alias), key)
    return idx


_ALIASES: dict[str, str] = _alias_index()


def get(key: Any) -> Optional[Term]:
    """Return the :class:`Term` for an exact key, or ``None``."""
    return TERMS.get(normalize_key(key).replace(" ", "_"))


def lookup(key: Any) -> Optional[Term]:
    """Return the :class:`Term` for a key, label, or alias, or ``None``."""
    if key is None:
        return None
    if isinstance(key, Term):
        return key
    n = normalize_key(key)
    resolved = _ALIASES.get(n) or _ALIASES.get(n.replace("_", " "))
    return TERMS.get(resolved) if resolved else None


def require(key: Any) -> Term:
    """Like :func:`lookup` but raises ``KeyError``, use in tests and migrations."""
    t = lookup(key)
    if t is None:
        raise KeyError(f"explain: unknown term {key!r}")
    return t


def has(key: Any) -> bool:
    """True when a term (or one of its aliases) is registered."""
    return lookup(key) is not None


def all_keys() -> tuple[str, ...]:
    """Every registry key, sorted."""
    return tuple(sorted(TERMS))


def search(query: str) -> tuple[str, ...]:
    """Keys whose label, key, or plain sentence contains ``query`` (case-insensitive)."""
    q = normalize_key(query)
    if not q:
        return all_keys()
    hits = []
    for key, t in TERMS.items():
        blob = " ".join((key, t.label, t.short, t.plain, " ".join(t.aliases))).lower()
        if q in blob:
            hits.append(key)
    return tuple(sorted(hits))


def tooltip(key: Any, extra: Optional[str] = None) -> Optional[str]:
    """Text for a native Streamlit ``help=`` parameter, or ``None`` if unknown.

    Returning ``None`` rather than raising means an unrecognised term degrades
    to "no tooltip" instead of breaking a render.
    """
    t = lookup(key)
    if t is None:
        return str(extra) if extra else None
    return t.tooltip(extra)


def tone_label(label: str, tone: Optional[str] = None) -> str:
    """Prefix a label with its tone glyph. Unknown or ``None`` tone is a no-op."""
    text = str(label)
    if not tone:
        return text
    glyph = TONE_GLYPH.get(str(tone).strip().lower())
    return f"{glyph} {text}" if glyph else text


def verdict_text(text: str, tone: Optional[str] = None) -> str:
    """The plain-English verdict string, with its tone glyph attached."""
    body = str(text or "").strip()
    if not body:
        return ""
    return tone_label(body, tone)


def missing_terms(keys: Iterable[Any]) -> tuple[str, ...]:
    """Which of ``keys`` are NOT registered. Migration aid: feed it a screen's
    jargon list and get back what still needs a definition."""
    return tuple(str(k) for k in keys if not has(k))


def check_registry() -> list[str]:
    """Return a list of registry defects. Empty list means healthy.

    Checked here rather than only in the test file so a caller (or a future
    admin screen) can assert on it at runtime.
    """
    problems: list[str] = []
    seen_labels: dict[str, str] = {}
    seen_aliases: dict[str, str] = {}
    for key, t in TERMS.items():
        where = f"TERMS[{key!r}]"
        if key != key.lower():
            problems.append(f"{where}: key is not lowercase")
        if key.strip() != key or " " in key or "-" in key:
            problems.append(f"{where}: key must be snake_case with no spaces/dashes")
        if not isinstance(t, Term):
            problems.append(f"{where}: not a Term")
            continue
        for fname in ("short", "plain", "detail", "formula", "label"):
            val = getattr(t, fname)
            if not isinstance(val, str) or not val.strip():
                problems.append(f"{where}.{fname}: empty")
        if t.plain and not t.plain.strip().endswith((".", "!", "?")):
            problems.append(f"{where}.plain: should be a complete sentence")
        if len(t.short.split()) > 8:
            problems.append(f"{where}.short: too long for a tooltip ({len(t.short.split())} words)")
        if len(t.detail) < len(t.plain):
            problems.append(f"{where}.detail: shorter than .plain, no added depth")
        nl = normalize_key(t.label)
        if nl in seen_labels and seen_labels[nl] != key:
            problems.append(f"{where}.label: duplicate of {seen_labels[nl]!r}")
        seen_labels[nl] = key
        for alias in t.aliases:
            na = normalize_key(alias)
            if not na:
                problems.append(f"{where}.aliases: empty alias")
                continue
            if na in seen_aliases and seen_aliases[na] != key:
                problems.append(f"{where}.aliases: {alias!r} also claimed by {seen_aliases[na]!r}")
            seen_aliases[na] = key
    return problems


# ── Canonical value formatting ──────────────────────────────────────────────
# One implementation each, so "$1,234.50" looks the same on every screen.

def _finite(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def money(value: Any, decimals: int = 2, dash: str = "n/a") -> str:
    """``1234.5`` -> ``"$1,234.50"``. Non-numeric input returns ``dash``."""
    f = _finite(value)
    if f is None:
        return dash
    sign = "-" if f < 0 else ""
    return f"{sign}${abs(f):,.{decimals}f}"


def pct(value: Any, decimals: int = 1, dash: str = "n/a") -> str:
    """``67.3`` -> ``"67.3%"``. Expects an already-scaled percentage."""
    f = _finite(value)
    return dash if f is None else f"{f:.{decimals}f}%"


def ratio(value: Any, decimals: int = 2, dash: str = "n/a") -> str:
    """``2.0`` -> ``"2.00x"``."""
    f = _finite(value)
    return dash if f is None else f"{f:.{decimals}f}x"


def score(value: Any, out_of: int = 100, decimals: int = 0, dash: str = "n/a") -> str:
    """``72`` -> ``"72 / 100"``."""
    f = _finite(value)
    return dash if f is None else f"{f:.{decimals}f} / {out_of:g}"


def compact(value: Any, decimals: int = 1, dash: str = "n/a") -> str:
    """``-2_300_000_000`` -> ``"-2.3B"``. For GEX and other notional figures."""
    f = _finite(value)
    if f is None:
        return dash
    sign = "-" if f < 0 else ""
    a = abs(f)
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cutoff:
            return f"{sign}{a / cutoff:.{decimals}f}{suffix}"
    return f"{sign}{a:.{decimals}f}"


def signed(value: Any, decimals: int = 2, dash: str = "n/a") -> str:
    """``0.4`` -> ``"+0.40"``. For deltas where the sign is the point."""
    f = _finite(value)
    return dash if f is None else f"{f:+.{decimals}f}"


# ═══════════════════════════════════════════════════════════════════════════
#  RENDERING
#
#  ``import streamlit`` lives inside each function (house pattern, see
#  modules/sentiment_radar.py) so this module stays importable, and testable,
#  without a Streamlit runtime.
# ═══════════════════════════════════════════════════════════════════════════

def metric(
    label: str,
    value: Any,
    *,
    term: Optional[Any] = None,
    tone: Optional[str] = None,
    hint: Optional[str] = None,
    delta: Optional[Any] = None,
    delta_color: str = "normal",
    help_extra: Optional[str] = None,
) -> None:
    """Render one number, with its plain-English gloss attached.

    This is the single canonical way to put a figure on screen.

    Parameters
    ----------
    label:
        What the number is called. Keep it in plain words where possible
        ("Chance of profit", not "MC PoP") and pass the jargon via ``term``.
    value:
        Pre-formatted string, or a raw number. Use :func:`money`, :func:`pct`,
        :func:`compact` and friends so formatting is identical app-wide.
    term:
        Registry key, label, or alias. Drives the native ``help=`` tooltip.
        An unknown term degrades to no tooltip rather than raising.
    tone:
        ``"good" | "warn" | "bad" | "neutral"``. Adds a colour glyph to the
        label so the read is instant and does not depend on colour vision
        alone (the glyph shape differs too).
    hint:
        The one-line "so what" shown as a caption under the number. This is
        the difference between a dashboard and an explanation.
    delta / delta_color:
        Passed straight to ``st.metric``.
    """
    import streamlit as st

    st.metric(
        label=tone_label(label, tone),
        value=value,
        delta=delta,
        delta_color=delta_color,
        help=tooltip(term, help_extra) if (term or help_extra) else None,
    )
    if hint:
        st.caption(str(hint))


def explain(term_key: Any, *, expanded: bool = False, title: Optional[str] = None) -> bool:
    """Render the progressive-disclosure expander for one term.

    Layer order inside: plain sentence, then the real explanation, then the
    formula this codebase actually uses. Returns ``False`` (and renders
    nothing) when the term is unknown, so a call site can fall back quietly.
    """
    import streamlit as st

    t = lookup(term_key)
    if t is None:
        return False

    heading = title or f'What does "{t.title}" mean?'
    with st.expander(heading, expanded=expanded):
        st.markdown(f"**In plain English:** {t.plain}")
        st.markdown(t.detail)
        st.markdown("**How this app calculates it**")
        st.code(t.formula, language=None)
    return True


def verdict_line(text: str, tone: str = "neutral") -> None:
    """The one-sentence plain-English "so what" that tops every card.

    House rule: no card ships without one of these. If you cannot write the
    sentence, the card does not yet know what it is telling the user.
    """
    import streamlit as st

    body = verdict_text(text, tone)
    if not body:
        return
    box = getattr(st, _TONE_BOX.get(str(tone).strip().lower(), "info"), None)
    if box is None:
        st.write(body)
    else:
        box(body)


def term_badge(term_key: Any, *, prefix: str = "") -> bool:
    """Render just the short gloss as a caption: for tables and dense rows
    where a full expander would not fit. Returns ``False`` if unknown."""
    import streamlit as st

    t = lookup(term_key)
    if t is None:
        return False
    st.caption(f"{prefix}{t.title}: {t.short.rstrip('.')}. {t.plain}")
    return True


def glossary(*, columns: int = 2, query: str = "", keys: Optional[Iterable[Any]] = None) -> None:
    """Render the whole registry as a searchable reference.

    Intended to replace the hand-maintained HTML list behind
    Intel -> Quick Reference Guide, so there is exactly one glossary in the
    app and every tooltip is guaranteed to agree with it.
    """
    import streamlit as st

    if keys is not None:
        wanted = [k for k in (normalize_key(x).replace(" ", "_") for x in keys) if k in TERMS]
    else:
        wanted = list(search(query))

    if not wanted:
        st.caption("No terms match that search.")
        return

    ncol = max(1, int(columns))
    cols = st.columns(ncol)
    for i, key in enumerate(wanted):
        t = TERMS[key]
        with cols[i % ncol]:
            with st.expander(t.title, expanded=False):
                st.markdown(f"**In plain English:** {t.plain}")
                st.markdown(t.detail)
                st.markdown("**How this app calculates it**")
                st.code(t.formula, language=None)
