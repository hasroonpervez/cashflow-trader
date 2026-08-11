"""Asymmetry engine: rank by PAYOFF, not by score points.

Why this module exists
----------------------
The app's existing "10x Potential" / ``explosion_score`` machinery is an
ATTENTION + TREND composite wearing an asymmetry label. It adds up points
(buzz, volume, trend health) and calls the top of the list "10x candidates".
Points are not convexity. A screen that sums seven bullish indicators tells
you a stock is *popular and going up*; it says nothing about whether the
payoff distribution is skewed in your favour, nothing about how much you lose
when you are wrong, and nothing about how often this screen has actually been
right before.

This module measures the thing the label claims:

  * **Expected value** over an explicit discrete outcome distribution
    (``expected_value`` / ``ev_rank``): no additive scores anywhere.
  * **Convexity**: a KNOWN, bounded loss against a large upside, with an
    explicit flag when the downside is not actually bounded
    (``convexity_score``).
  * **Cheap optionality**: the classic IV rank / IV percentile screen
    (``iv_rank``, ``iv_percentile``, ``iv_rank_series``).
  * **The coiled-spring setup** that precedes violent moves: low IV rank +
    volatility compression + small float / high short interest + a catalyst
    window (``coiled_spring_score``, ``catalyst_window``).
  * **Position size** under a power-law payoff (``kelly_fraction_skewed``).
  * **Honesty**: precision / recall / empirical base rates of the screen,
    gated through the same ``validated_signals.promotion_gate`` bar
    (CI>0, split-half, n>=100) that the research program uses
    (``base_rate_report``). A screen that has not been base-rated reports as
    ``unvalidated``. It never reports as anything else by default.

Conventions used everywhere in this module
------------------------------------------
* **Returns are FRACTIONAL total returns of the position.** ``+9.0`` is a
  10-bagger (price x10), ``-1.0`` is a total loss, ``-0.25`` is a -25% stop.
* **Optional in -> Optional out.** Missing data returns ``None`` or lowers a
  ``confidence`` field and appends a flag. Nothing is ever silently imputed
  as zero, and no verdict is ever upgraded by data we do not have.
* **No lookahead.** Every function that takes a price series takes an
  ``index`` and slices ``[: index + 1]`` *before* computing anything, so a
  future row cannot influence a past evaluation even by accident.
  ``tests/test_asymmetry.py::test_no_lookahead_*`` proves it.
* **No Streamlit.** The whole module is pure logic and imports headless.

Reuse
-----
* ATR comes from ``modules.ta.TA.atr`` (the single ATR implementation in the
  codebase). This module only adapts column casing and enforces causality.
* The promotion gate comes from ``modules.validated_signals.promotion_gate``.
* Implied move is deliberately NOT re-derived here:
  ``modules.options.Opt.calc_expected_move`` already implements
  ``price * (iv/100) * sqrt(dte/365.25)``. ``modules.options`` imports
  Streamlit, so this module cannot import it without breaking headless use;
  callers who have IV should compute the move there and pass the resulting
  price level in as ``upside_target``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

import numpy as np
import pandas as pd

from .ta import TA
from .validated_signals import promotion_gate

__all__ = [
    "EVResult",
    "expected_value",
    "ev_rank",
    "ConvexityResult",
    "convexity_score",
    "iv_rank",
    "iv_percentile",
    "iv_rank_series",
    "CoiledSpringResult",
    "coiled_spring_score",
    "catalyst_window",
    "catalyst_component",
    "KellyResult",
    "kelly_fraction_skewed",
    "BaseRateReport",
    "base_rate_report",
    "AsymmetryVerdict",
    "asymmetry_verdict",
    "atr_at",
    "atr_upside_target",
    "support_from_swing_low",
    "realized_vol_compression",
    "MULTIPLE_THRESHOLDS",
]


# ---------------------------------------------------------------------------
# Small shared helpers (causality + column casing)
# ---------------------------------------------------------------------------

_OHLC_ALIASES = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "adj close": "Close",
    "volume": "Volume",
}


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Rename OHLCV columns to the Capitalized form ``modules.ta.TA`` expects."""
    ren = {c: _OHLC_ALIASES[str(c).strip().lower()]
           for c in df.columns if str(c).strip().lower() in _OHLC_ALIASES}
    return df.rename(columns=ren)


def _slice_causal(df: pd.DataFrame, index: Optional[int]) -> pd.DataFrame:
    """Return rows ``[0 .. index]`` positionally, the ONLY data a function may see.

    This is the structural anti-lookahead guarantee: every series function in
    this module calls ``_slice_causal`` first and computes second, so rows
    after the evaluation index are physically absent from the computation.
    Negative indices count from the end (``-1`` = latest completed bar).
    """
    d = df.reset_index(drop=True)
    n = len(d)
    if n == 0:
        return d
    i = n - 1 if index is None else int(index)
    if i < 0:
        i += n
    if i < 0 or i >= n:
        raise IndexError(f"evaluation index out of range: {index} for {n} rows")
    return d.iloc[: i + 1].copy()


def _finite(x) -> Optional[float]:
    """float(x) if finite, else None. The 'never fabricate a zero' primitive."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(f) or math.isinf(f)) else f


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


# ---------------------------------------------------------------------------
# 1. Expected value, the replacement for additive score points
# ---------------------------------------------------------------------------

@dataclass
class EVResult:
    """Expected value of a discrete payoff distribution.

    ``ev``               E[r]  = sum_i p_i * payoff_i
    ``upside_capture``   U     = sum_{payoff_i > 0} p_i * payoff_i
    ``downside_capture`` D     = sum_{payoff_i < 0} p_i * |payoff_i|
    ``asymmetry_ratio``  U / D (None when no loss outcome was modelled)
    Identity: ``ev == upside_capture - downside_capture``.
    """
    ev: float
    upside_capture: float
    downside_capture: float
    asymmetry_ratio: Optional[float]
    p_win: float
    p_loss: float
    n_outcomes: int
    best_payoff: float
    worst_payoff: float
    flags: list[str] = field(default_factory=list)


def _parse_outcomes(outcomes) -> list[tuple[float, float]]:
    """Accept [(p, payoff), ...] or [{'p':..,'payoff':..}, ...] or {label: (p, payoff)}."""
    if outcomes is None:
        return []
    if isinstance(outcomes, Mapping):
        items = list(outcomes.values())
    else:
        items = list(outcomes)
    parsed: list[tuple[float, float]] = []
    for it in items:
        if isinstance(it, Mapping):
            p = it.get("p", it.get("prob", it.get("probability")))
            payoff = it.get("payoff", it.get("ret", it.get("r")))
        else:
            seq = list(it)
            if len(seq) < 2:
                raise ValueError(f"outcome needs (probability, payoff), got {it!r}")
            p, payoff = seq[0], seq[1]
        pf, yf = _finite(p), _finite(payoff)
        if pf is None or yf is None:
            raise ValueError(f"non-finite outcome: {it!r}")
        if pf < 0:
            raise ValueError(f"negative probability: {pf}")
        parsed.append((pf, yf))
    return parsed


def expected_value(outcomes, *, prob_tolerance: float = 1e-6) -> Optional[EVResult]:
    """E[return] over a discrete outcome distribution. NOT a score.

    Formula
    -------
        EV = sum_i p_i * payoff_i
        U  = sum_{payoff_i > 0} p_i * payoff_i          (upside capture)
        D  = sum_{payoff_i < 0} p_i * |payoff_i|        (downside capture)
        asymmetry_ratio = U / D                          (None if D == 0)

    ``payoff_i`` is a fractional total return: ``+9.0`` = 10-bagger,
    ``-1.0`` = total loss, ``-0.25`` = stopped out for -25%.

    The asymmetry ratio is reported *explicitly and separately* from EV
    because they answer different questions. EV says "is this worth doing";
    U/D says "is the payoff shaped like a lottery ticket or like a coin
    flip". A 55/45 coin flip can have positive EV and no asymmetry at all;
    a 12%-probability 10-bagger has an enormous U/D and can still be
    negative-EV. Ranking by either one alone gets you hurt.

    Probabilities must sum to 1 within ``prob_tolerance``, they are NOT
    renormalized, because renormalizing silently invents a distribution the
    caller did not specify.

    Returns None for an empty distribution. Raises ValueError on malformed
    input (negative probability, probabilities that do not sum to 1).
    """
    parsed = _parse_outcomes(outcomes)
    if not parsed:
        return None

    p = np.array([x[0] for x in parsed], dtype=float)
    y = np.array([x[1] for x in parsed], dtype=float)
    total = float(p.sum())
    if abs(total - 1.0) > prob_tolerance:
        raise ValueError(
            f"probabilities must sum to 1.0 (got {total:.6f}); "
            "this function does not renormalize: fix the distribution"
        )

    up_mask = y > 0
    dn_mask = y < 0
    upside = float((p[up_mask] * y[up_mask]).sum())
    downside = float((p[dn_mask] * -y[dn_mask]).sum())
    ev = upside - downside

    flags: list[str] = []
    ratio: Optional[float]
    if downside > 0:
        ratio = upside / downside
    else:
        ratio = None
        flags.append("no-modeled-downside")
    if not up_mask.any():
        flags.append("no-modeled-upside")
    if len(parsed) < 3:
        flags.append("coarse-distribution")

    return EVResult(
        ev=ev,
        upside_capture=upside,
        downside_capture=downside,
        asymmetry_ratio=ratio,
        p_win=float(p[up_mask].sum()),
        p_loss=float(p[dn_mask].sum()),
        n_outcomes=len(parsed),
        best_payoff=float(y.max()),
        worst_payoff=float(y.min()),
        flags=flags,
    )


def ev_rank(candidates, *, prob_tolerance: float = 1e-6) -> list[dict]:
    """Rank candidates by E[return], with the asymmetry ratio carried alongside.

    ``candidates``: ``{name: outcomes}`` or ``[(name, outcomes), ...]``.

    Sort key: EV descending, then asymmetry ratio descending, then name.
    Candidates whose distribution cannot be evaluated (empty) are appended
    last with ``ev=None`` and flag ``unrankable``: never silently dropped
    and never ranked as if they scored zero.

    This is the whole point of the module in one function: two names with the
    same "10x score" can sit at opposite ends of this list.
    """
    if isinstance(candidates, Mapping):
        pairs = list(candidates.items())
    else:
        pairs = [(n, o) for n, o in candidates]

    rankable: list[dict] = []
    unrankable: list[dict] = []
    for name, outcomes in pairs:
        try:
            res = expected_value(outcomes, prob_tolerance=prob_tolerance)
        except ValueError as exc:
            unrankable.append({"name": str(name), "ev": None, "asymmetry_ratio": None,
                               "result": None, "flags": ["unrankable", str(exc)]})
            continue
        if res is None:
            unrankable.append({"name": str(name), "ev": None, "asymmetry_ratio": None,
                               "result": None, "flags": ["unrankable", "empty-distribution"]})
            continue
        rankable.append({
            "name": str(name),
            "ev": res.ev,
            "asymmetry_ratio": res.asymmetry_ratio,
            "upside_capture": res.upside_capture,
            "downside_capture": res.downside_capture,
            "p_win": res.p_win,
            "result": res,
            "flags": list(res.flags),
        })

    rankable.sort(key=lambda r: (-r["ev"],
                                 -(r["asymmetry_ratio"] if r["asymmetry_ratio"] is not None else -1.0),
                                 r["name"]))
    unrankable.sort(key=lambda r: r["name"])
    out = rankable + unrankable
    for i, row in enumerate(out, start=1):
        row["rank"] = i
    return out


# ---------------------------------------------------------------------------
# 2. Convexity, bounded KNOWN loss vs large upside
# ---------------------------------------------------------------------------

DEFAULT_ATR_EXPANSION = 3.0   # a range-expansion day/leg is ~3 ATR, not 1
CONVEX_MIN_RATIO = 3.0        # below 3:1 the payoff is not meaningfully convex


@dataclass
class ConvexityResult:
    """Is the payoff genuinely convex, or just 'a stock we like'?"""
    convexity_ratio: Optional[float]
    bounded_loss_frac: Optional[float]
    upside_frac: Optional[float]
    upside_source: str
    downside_bounded: Optional[bool]
    risk_adjusted_ratio: Optional[float]
    confidence: float
    components: dict = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    @property
    def is_convex(self) -> bool:
        """True only with a ratio above the bar AND a downside we KNOW is bounded."""
        return bool(
            self.convexity_ratio is not None
            and self.convexity_ratio >= CONVEX_MIN_RATIO
            and self.downside_bounded is True
        )


def convexity_score(
    entry_price: float,
    stop_price: Optional[float] = None,
    *,
    upside_target: Optional[float] = None,
    atr: Optional[float] = None,
    atr_expansion_mult: float = DEFAULT_ATR_EXPANSION,
    prior_range_expansion_frac: Optional[float] = None,
    gap_risk: Optional[bool] = None,
    liquid_stop: Optional[bool] = None,
) -> Optional[ConvexityResult]:
    """Convexity = (realistic upside) / (bounded, KNOWN downside).

    Formula
    -------
        bounded_loss_frac = (entry - stop) / entry
        upside_frac       = (target - entry) / entry
        convexity_ratio   = upside_frac / bounded_loss_frac

    Upside source, in priority order:
      1. ``upside_target``, an explicit price level from the caller
         (e.g. the implied move via ``Opt.calc_expected_move``, a measured
         move, a prior high).
      2. otherwise the SMALLER of the two structural estimates that are
         available: ``atr * atr_expansion_mult`` and
         ``entry * prior_range_expansion_frac``. Taking the smaller is a
         deliberate honesty default: the optimistic estimate is still
         reported in ``components``, but the headline ratio does not get to
         pick whichever number flatters the setup.

    The downside is only "bounded" if you can actually get out at the stop:
      * ``gap_risk=True``   -> overnight/binary gap can jump the stop
      * ``liquid_stop=False`` -> no liquid market to exit into
      Either one sets ``downside_bounded=False``, flags it, and reports
      ``risk_adjusted_ratio`` against a -100% loss instead of the stop
      distance, because that is what an unbounded downside actually means.
      Leaving them as ``None`` means UNKNOWN: ``downside_bounded`` stays
      ``None`` and confidence drops. Unknown is never treated as safe.

    Returns None when the loss cannot be defined (no/invalid stop) or when no
    upside estimate is available (e.g. ATR is zero on a flat, halted name).
    """
    entry = _finite(entry_price)
    if entry is None or entry <= 0:
        return None

    stop = _finite(stop_price)
    flags: list[str] = []
    if stop is None:
        return None
    if stop >= entry:
        return ConvexityResult(
            convexity_ratio=None, bounded_loss_frac=None, upside_frac=None,
            upside_source="none", downside_bounded=None, risk_adjusted_ratio=None,
            confidence=0.0, components={"entry": entry, "stop": stop},
            flags=["invalid-stop-above-entry"],
        )
    if stop <= 0:
        return ConvexityResult(
            convexity_ratio=None, bounded_loss_frac=None, upside_frac=None,
            upside_source="none", downside_bounded=False, risk_adjusted_ratio=None,
            confidence=0.0, components={"entry": entry, "stop": stop},
            flags=["stop-at-or-below-zero", "downside-unbounded"],
        )

    loss_frac = (entry - stop) / entry

    # ---- upside -----------------------------------------------------------
    components: dict = {"entry": entry, "stop": stop}
    atr_up = None
    a = _finite(atr)
    if a is not None and a > 0 and atr_expansion_mult > 0:
        atr_up = (a * float(atr_expansion_mult)) / entry
        components["upside_frac_atr"] = atr_up
    range_up = _finite(prior_range_expansion_frac)
    if range_up is not None and range_up > 0:
        components["upside_frac_prior_range"] = range_up
    else:
        range_up = None

    target = _finite(upside_target)
    if target is not None and target > entry:
        upside_frac = (target - entry) / entry
        source = "explicit_target"
        components["upside_frac_explicit"] = upside_frac
    else:
        if target is not None:
            flags.append("upside-target-below-entry-ignored")
        cands = [x for x in (atr_up, range_up) if x is not None]
        if not cands:
            return ConvexityResult(
                convexity_ratio=None, bounded_loss_frac=loss_frac, upside_frac=None,
                upside_source="none", downside_bounded=None, risk_adjusted_ratio=None,
                confidence=0.0, components=components,
                flags=flags + ["no-upside-estimate"],
            )
        upside_frac = min(cands)
        if len(cands) == 2:
            source = "conservative_of_atr_and_prior_range"
            flags.append("upside-conservative-of-two-estimates")
        else:
            source = "atr_expansion" if atr_up is not None else "prior_range_expansion"
        flags.append("upside-estimated-not-observed")

    ratio = upside_frac / loss_frac

    # ---- is the downside actually bounded? --------------------------------
    confidence = 1.0
    unbounded_reasons: list[str] = []
    if gap_risk is None:
        flags.append("gap-risk-unknown")
        confidence *= 0.70
    elif bool(gap_risk):
        unbounded_reasons.append("gap-risk")
    if liquid_stop is None:
        flags.append("stop-liquidity-unknown")
        confidence *= 0.80
    elif not bool(liquid_stop):
        unbounded_reasons.append("no-liquid-stop")

    if unbounded_reasons:
        downside_bounded: Optional[bool] = False
        flags.append("downside-unbounded")
        flags.extend(unbounded_reasons)
        risk_adjusted = upside_frac / 1.0   # worst case is -100%, not the stop
    elif gap_risk is None or liquid_stop is None:
        downside_bounded = None             # unknown is NOT bounded
        flags.append("downside-boundedness-unknown")
        risk_adjusted = upside_frac / 1.0
    else:
        downside_bounded = True
        risk_adjusted = ratio

    components["upside_frac_used"] = upside_frac
    return ConvexityResult(
        convexity_ratio=ratio,
        bounded_loss_frac=loss_frac,
        upside_frac=upside_frac,
        upside_source=source,
        downside_bounded=downside_bounded,
        risk_adjusted_ratio=risk_adjusted,
        confidence=round(confidence, 4),
        components=components,
        flags=flags,
    )


# ---------------------------------------------------------------------------
# 3. IV rank / IV percentile, the classic cheap-optionality screen
# ---------------------------------------------------------------------------

IV_LOOKBACK = 252          # one trading year, the industry convention
IV_MIN_OBSERVATIONS = 20   # below this the min/max range is noise, not a range


def _iv_window(iv_history, lookback: int) -> Optional[np.ndarray]:
    if iv_history is None:
        return None
    arr = np.asarray(list(iv_history), dtype=float) if not isinstance(iv_history, np.ndarray) \
        else iv_history.astype(float)
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    if lookback and lookback > 0:
        arr = arr[-int(lookback):]
    return arr


def iv_rank(
    iv_history,
    iv_now: Optional[float] = None,
    *,
    lookback: int = IV_LOOKBACK,
    min_observations: int = IV_MIN_OBSERVATIONS,
) -> Optional[float]:
    """Classic IV Rank in [0, 1]: where today's IV sits in its own range.

    Formula
    -------
        IVR = (iv_now - min(iv_lookback)) / (max(iv_lookback) - min(iv_lookback))

    Low IVR is the cheap-optionality screen: options are priced near the
    quietest they have been for this name, so a convex bet costs little and
    a volatility expansion pays twice (direction AND vega).

    ``iv_now`` defaults to the last observation of ``iv_history``. Only the
    trailing ``lookback`` observations are used: the input is assumed to end
    at "now", so this is causal by construction.

    Degenerate cases return **None**, never 0.0 and never a ZeroDivisionError:
      * empty / all-non-finite history
      * fewer than ``min_observations`` usable points
      * ``max == min`` (a flat IV history has no rank; 0.0 would read as
        "cheapest ever", which is a lie)
    """
    arr = _iv_window(iv_history, lookback)
    if arr is None or arr.size < max(1, int(min_observations)):
        return None
    now = _finite(iv_now) if iv_now is not None else float(arr[-1])
    if now is None:
        return None
    lo, hi = float(arr.min()), float(arr.max())
    rng = hi - lo
    if rng <= 0:
        return None
    return _clip01((now - lo) / rng)


def iv_percentile(
    iv_history,
    iv_now: Optional[float] = None,
    *,
    lookback: int = IV_LOOKBACK,
    min_observations: int = IV_MIN_OBSERVATIONS,
) -> Optional[float]:
    """Fraction of the lookback spent BELOW today's IV, in [0, 1].

    Formula (mid-rank / tie-corrected, the standard definition)
    -----------------------------------------------------------
        IVP = ( #{iv_i < iv_now} + 0.5 * #{iv_i == iv_now} ) / n

    IV rank is a min/max range statistic and is therefore hostage to a single
    spike; IV percentile is a distributional statistic and is not. They
    disagree most exactly when it matters (one crisis print in the window),
    which is why both are exposed rather than one "IV score".

    Same Optional discipline as :func:`iv_rank`: empty history, too few
    observations, or an all-equal history return None.
    """
    arr = _iv_window(iv_history, lookback)
    if arr is None or arr.size < max(1, int(min_observations)):
        return None
    now = _finite(iv_now) if iv_now is not None else float(arr[-1])
    if now is None:
        return None
    if float(arr.max()) == float(arr.min()):
        return None
    below = float(np.count_nonzero(arr < now))
    ties = float(np.count_nonzero(arr == now))
    return _clip01((below + 0.5 * ties) / float(arr.size))


def iv_rank_series(
    iv_history,
    *,
    lookback: int = IV_LOOKBACK,
    min_observations: int = IV_MIN_OBSERVATIONS,
) -> pd.Series:
    """Vectorized rolling IV rank for a whole history, O(n), no python loop.

    Uses pandas trailing ``rolling(lookback)`` min/max, so element ``i`` is
    computed from ``[i-lookback+1 .. i]`` only: causal by construction, and
    proven so in ``test_no_lookahead_iv_rank_series``.

    Returns a float Series aligned to the input, with ``NaN`` wherever the
    rank is undefined (warm-up, or a flat window where max == min).
    """
    s = pd.Series(list(iv_history), dtype=float) if not isinstance(iv_history, pd.Series) \
        else iv_history.astype(float)
    if s.empty:
        return pd.Series(dtype=float, name="iv_rank")
    win = max(1, int(lookback))
    mp = max(1, int(min_observations))
    lo = s.rolling(win, min_periods=mp).min()
    hi = s.rolling(win, min_periods=mp).max()
    rng = (hi - lo).replace(0.0, np.nan)     # flat window -> NaN, never 0/0
    out = ((s - lo) / rng).clip(0.0, 1.0)
    out.name = "iv_rank"
    return out


# ---------------------------------------------------------------------------
# 5. Catalyst window (defined before the coiled spring, which consumes it)
# ---------------------------------------------------------------------------

CATALYST_PEAK_DAYS = 3.0     # optionality is worth most a few days BEFORE
CATALYST_PEAK_MULT = 1.5     # ...and is worth 1.5x its baseline there
CATALYST_PRE_SIGMA = 10.0    # gaussian width of the pre-event ramp (days)
CATALYST_POST_FLOOR = 0.6    # the IV crush: the morning after, optionality is cheap-but-dead
CATALYST_POST_TAU = 10.0     # ...and normalizes back to 1.0 with this time constant


def catalyst_window(days_to_event: Optional[float]) -> Optional[float]:
    """Multiplier on the VALUE of optionality as an event approaches and passes.

    ``days_to_event``: positive = event is in the future, 0 = event day,
    negative = days since the event. ``None`` -> ``None`` (no event known is
    not the same as no event).

    Formula
    -------
        d >= 0 :  m = 1 + (PEAK_MULT - 1) * exp( -(d - PEAK_DAYS)^2 / (2*SIGMA^2) )
        d <  0 :  m = POST_FLOOR + (1 - POST_FLOOR) * (1 - exp(-|d| / TAU))

    Shape and why:
      * Peaks at ``PEAK_DAYS`` (3) before the event, not on the day. By the
        event the premium is fully priced; the asymmetry lives in the ramp,
        where you can still buy the move before everyone else bids for it.
      * There is a deliberate DISCONTINUITY at d=0. That is not a modelling
        artefact: the implied-vol crush after an event genuinely is a jump,
        and smoothing it would misprice the single most predictable event in
        the options calendar.
      * After the event the multiplier starts at ``POST_FLOOR`` (0.6) and
        recovers asymptotically to 1.0: the catalyst is spent, and the name
        is simply an ordinary name again a few weeks later.
    """
    d = _finite(days_to_event)
    if d is None:
        return None
    if d >= 0:
        z = (d - CATALYST_PEAK_DAYS) / CATALYST_PRE_SIGMA
        return float(1.0 + (CATALYST_PEAK_MULT - 1.0) * math.exp(-0.5 * z * z))
    elapsed = -d
    return float(CATALYST_POST_FLOOR
                 + (1.0 - CATALYST_POST_FLOOR) * (1.0 - math.exp(-elapsed / CATALYST_POST_TAU)))


def catalyst_component(days_to_event: Optional[float]) -> Optional[float]:
    """:func:`catalyst_window` rescaled to [0, 1] for use inside composites.

        c = (m - POST_FLOOR) / (PEAK_MULT - POST_FLOOR)
    """
    m = catalyst_window(days_to_event)
    if m is None:
        return None
    return _clip01((m - CATALYST_POST_FLOOR) / (CATALYST_PEAK_MULT - CATALYST_POST_FLOOR))


# ---------------------------------------------------------------------------
# 4. Coiled spring, the structural setup that precedes violent moves
# ---------------------------------------------------------------------------

SPRING_WEIGHTS = {
    "cheap_optionality": 0.30,   # low IV rank
    "compression": 0.25,         # realized vol squeezed vs its own baseline
    "small_float": 0.15,         # fewer shares to move
    "short_interest": 0.15,      # fuel for a squeeze
    "catalyst": 0.15,            # a dated reason for the spring to release
}
SPRING_FULL_COMPRESSION = 0.40   # fast vol at 40% of baseline = fully coiled
SPRING_SMALL_FLOAT = 20e6        # <= 20M shares free float = full marks
SPRING_LARGE_FLOAT = 500e6       # >= 500M shares = no float edge at all
SPRING_SI_SATURATION = 20.0      # 20% of float short = full marks
SPRING_MIN_CONFIDENCE = 0.60     # below this the composite is a guess, and says so


@dataclass
class CoiledSpringResult:
    """The setup score, with an explicit confidence for what we actually knew."""
    score: float                       # 0-100 over the components we HAVE
    confidence: float                  # 0-1: share of the weight that was observable
    components: dict = field(default_factory=dict)   # name -> 0..1 (present only)
    missing: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        return self.confidence >= SPRING_MIN_CONFIDENCE


def coiled_spring_score(
    *,
    iv_rank_value: Optional[float] = None,
    vol_compression_ratio: Optional[float] = None,
    float_shares: Optional[float] = None,
    short_interest_pct: Optional[float] = None,
    days_to_event: Optional[float] = None,
) -> Optional[CoiledSpringResult]:
    """The coiled-spring setup: cheap optionality + compression + fuel + a date.

    Component formulas (each mapped to 0..1)
    ----------------------------------------
      cheap_optionality = 1 - iv_rank_value
      compression       = clip01( (1 - vol_compression_ratio) / (1 - 0.40) )
                          where vol_compression_ratio = fast RV / slow RV
      small_float       = clip01( log10(500M / float) / log10(500M / 20M) )
      short_interest    = clip01( short_interest_pct / 20 )
      catalyst          = catalyst_component(days_to_event)

    Aggregation: the part that matters
    -----------------------------------
        score      = 100 * sum_{present} w_i c_i / sum_{present} w_i
        confidence = sum_{present} w_i          (1.0 only when all are known)

    A missing input is NOT scored 0. Scoring it 0 would quietly punish a name
    for the data vendor's gaps and would make an unknown look like a measured
    negative. Instead the weight is removed from the denominator and the
    absence is recorded in ``missing`` and reflected in ``confidence``.
    Symmetrically, a missing input never *helps* either.

    Returns None only when nothing at all was supplied.
    """
    comps: dict[str, float] = {}
    missing: list[str] = []

    ivr = _finite(iv_rank_value)
    if ivr is None:
        missing.append("cheap_optionality")
    else:
        comps["cheap_optionality"] = _clip01(1.0 - _clip01(ivr))

    comp_ratio = _finite(vol_compression_ratio)
    if comp_ratio is None or comp_ratio < 0:
        missing.append("compression")
    else:
        comps["compression"] = _clip01((1.0 - comp_ratio) / (1.0 - SPRING_FULL_COMPRESSION))

    flt = _finite(float_shares)
    if flt is None or flt <= 0:
        missing.append("small_float")
    else:
        span = math.log10(SPRING_LARGE_FLOAT / SPRING_SMALL_FLOAT)
        comps["small_float"] = _clip01(math.log10(SPRING_LARGE_FLOAT / flt) / span)

    si = _finite(short_interest_pct)
    if si is None or si < 0:
        missing.append("short_interest")
    else:
        comps["short_interest"] = _clip01(si / SPRING_SI_SATURATION)

    cat = catalyst_component(days_to_event)
    if cat is None:
        missing.append("catalyst")
    else:
        comps["catalyst"] = cat

    if not comps:
        return None

    w_present = sum(SPRING_WEIGHTS[k] for k in comps)
    weighted = sum(SPRING_WEIGHTS[k] * v for k, v in comps.items())
    score = 100.0 * weighted / w_present

    flags = [f"missing:{m}" for m in missing]
    if w_present < SPRING_MIN_CONFIDENCE:
        flags.append("low-confidence")
    if missing:
        flags.append("partial-data")

    return CoiledSpringResult(
        score=round(float(score), 2),
        confidence=round(float(w_present), 4),
        components={k: round(v, 4) for k, v in comps.items()},
        missing=missing,
        flags=flags,
    )


# ---------------------------------------------------------------------------
# 6. Kelly for power-law payoffs
# ---------------------------------------------------------------------------

DEFAULT_KELLY_FRACTION = 0.25   # quarter-Kelly: the standard fractional haircut
MAX_KELLY_FRACTION = 0.20       # hard cap of bankroll in any one convex bet


@dataclass
class KellyResult:
    full_kelly: float
    recommended_fraction: float
    fraction_of_full: float
    edge_per_unit: float
    capped: bool
    flags: list[str] = field(default_factory=list)


def kelly_fraction_skewed(
    p_win: Optional[float],
    win_mult: Optional[float],
    loss_frac: Optional[float] = 1.0,
    *,
    fraction_of_full: float = DEFAULT_KELLY_FRACTION,
    max_fraction: float = MAX_KELLY_FRACTION,
) -> Optional[KellyResult]:
    """Kelly for a two-point ASYMMETRIC payoff: not the symmetric approximation.

    Parameters
    ----------
    p_win     : probability of the winning outcome, in [0, 1].
    win_mult  : NET profit multiple ``b`` on the staked capital. A 10-bagger
                (price x10) is ``win_mult=9.0``, because you get your stake
                back plus 9x. Must be > 0.
    loss_frac : fraction ``a`` of the stake lost in the losing outcome, in
                (0, 1]. ``1.0`` = total loss (the correct default for a long
                option or a gap-risk microcap); ``0.25`` = a stop that
                actually works.

    Formula (exact, from maximizing E[log wealth])
    ---------------------------------------------
        maximize  p*log(1 + f*b) + (1-p)*log(1 - f*a)
        d/df = 0  ->   f* = (p*b - (1-p)*a) / (a*b)

    With ``a = 1`` this collapses to the familiar ``f* = p - (1-p)/b``. The
    symmetric "edge/odds" shortcut ``(p*b - q)/b`` is only correct for
    ``a = 1`` and quietly over-bets whenever the real loss is partial, which
    is exactly the case this module cares about. Note the shape at large
    ``b``: ``f*`` converges to ``p``, a 100x payoff does NOT justify a
    bigger bet than a 10x payoff at the same win probability. That is the
    result additive "10x potential" scores never encode.

    Why full Kelly is wrong here (and the haircut is not timidity)
    --------------------------------------------------------------
    1. ``p`` is estimated, and in a fat-tailed setting it is estimated badly.
       Kelly's growth curve is asymmetric in the error: over-betting is
       punished far harder than under-betting, and betting 2x Kelly gives
       ZERO long-run growth. Halve the true edge and full Kelly becomes
       double Kelly.
    2. The real payoff is not two points. Actual outcomes have more mass at
       total loss than any tidy distribution admits (halts, dilution, fraud,
       expiry), so the modelled ``a`` is optimistic.
    3. Kelly assumes infinite repetitions of an i.i.d. bet with no path
       dependence. Real accounts have margin calls, correlated positions and
       a finite career: ruin is absorbing, and the log-utility argument
       does not price that.
    Hence ``fraction_of_full=0.25`` (quarter Kelly, the standard practitioner
    haircut: ~94% of the growth at ~44% of the volatility under a correct
    ``p``, and it survives a ``p`` that is wrong by half), and a hard
    ``max_fraction`` cap on top.

    Returns None if any input is missing. Raises ValueError on out-of-domain
    inputs. ``recommended_fraction`` is 0.0 whenever the edge is non-positive
: no edge means no bet, however large the payoff multiple.
    """
    p = _finite(p_win)
    b = _finite(win_mult)
    a = _finite(loss_frac)
    if p is None or b is None or a is None:
        return None
    if not (0.0 <= p <= 1.0):
        raise ValueError(f"p_win must be in [0, 1], got {p}")
    if b <= 0:
        raise ValueError(f"win_mult (net profit multiple) must be > 0, got {b}")
    if not (0.0 < a <= 1.0):
        raise ValueError(f"loss_frac must be in (0, 1], got {a}")
    if not (0.0 < fraction_of_full <= 1.0):
        raise ValueError(f"fraction_of_full must be in (0, 1], got {fraction_of_full}")

    q = 1.0 - p
    edge = p * b - q * a
    f_star = edge / (a * b)

    flags: list[str] = []
    if f_star <= 0:
        return KellyResult(full_kelly=0.0, recommended_fraction=0.0,
                           fraction_of_full=float(fraction_of_full),
                           edge_per_unit=float(edge), capped=False,
                           flags=["no-edge", "do-not-bet"])

    # f * a < 1 is required for log(1 - f*a) to be defined at all.
    full = min(f_star, 1.0 / a)
    if f_star > 1.0 / a:
        flags.append("kelly-clamped-to-solvency-limit")
    if p >= 1.0:
        flags.append("p_win=1-is-not-a-real-estimate")
    if b >= 5.0:
        flags.append("power-law-payoff-p-estimate-dominates-sizing")

    rec = full * float(fraction_of_full)
    capped = rec > max_fraction
    if capped:
        rec = float(max_fraction)
        flags.append("capped-at-max-fraction")

    return KellyResult(
        full_kelly=float(full),
        recommended_fraction=float(rec),
        fraction_of_full=float(fraction_of_full),
        edge_per_unit=float(edge),
        capped=bool(capped),
        flags=flags,
    )


# ---------------------------------------------------------------------------
# 7. Base rates, the honesty layer
# ---------------------------------------------------------------------------

# Fractional TOTAL return thresholds. +1.0 = doubled, +9.0 = 10-bagger.
MULTIPLE_THRESHOLDS = {"2x": 1.0, "5x": 4.0, "10x": 9.0}

STATUS_VALIDATED = "validated"
STATUS_REJECTED = "rejected"
STATUS_UNVALIDATED = "unvalidated"


@dataclass
class BaseRateReport:
    """What the screen has ACTUALLY done, and whether it is allowed to be trusted."""
    screen_name: str
    validation_status: str
    n_candidates: Optional[int] = None
    n_flagged: Optional[int] = None
    outcomes: dict = field(default_factory=dict)
    gate: Optional[dict] = None
    flags: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def is_validated(self) -> bool:
        return self.validation_status == STATUS_VALIDATED


def base_rate_report(
    screen_name: str,
    flags=None,
    forward_returns=None,
    *,
    min_trades: int = 100,
    thresholds: Optional[Mapping[str, float]] = None,
) -> BaseRateReport:
    """Precision, recall and the empirical base rate of 2x / 5x / 10x outcomes.

    Parameters
    ----------
    flags           : boolean per historical candidate, did the screen fire?
    forward_returns : realized forward FRACTIONAL return for the same
                      candidate (``+9.0`` = 10-bagger, ``-1.0`` = wipeout).

    Per multiple ``m`` with threshold ``t`` (2x -> +1.0, 5x -> +4.0, 10x -> +9.0)
    ------------------------------------------------------------------------
        base_rate = P(r >= t)                     -- how often it happens anyway
        precision = P(r >= t | flagged)           -- how often YOUR picks do it
        recall    = P(flagged | r >= t)           -- how many you actually caught
        lift      = precision / base_rate         -- the only number that matters

    Lift <= 1 means the screen is decoration: you would have done as well
    picking at random from the same universe.

    Validation
    ----------
    The flagged subset's returns are pushed through
    ``validated_signals.promotion_gate``, the SAME bar as every other
    strategy in this codebase: n >= ``min_trades``, bootstrap 95% CI strictly
    above zero, and positive expectancy in BOTH chronological halves (the
    check that caught Blue Diamond v2's fake t=2.98).

      * no history supplied            -> ``unvalidated``
      * fewer than ``min_trades`` fires -> ``unvalidated`` (+ insufficient-sample)
      * gate passes                    -> ``validated``
      * gate fails with enough n       -> ``rejected``

    ``unvalidated`` is the default state of the world. A screen does not get
    the benefit of the doubt for never having been measured.
    """
    thr = dict(thresholds) if thresholds else dict(MULTIPLE_THRESHOLDS)

    if flags is None or forward_returns is None:
        return BaseRateReport(
            screen_name=str(screen_name),
            validation_status=STATUS_UNVALIDATED,
            flags=["never-base-rated"],
            note="No historical flags/returns supplied: this screen has never been measured.",
        )

    f = np.asarray(list(flags)).astype(bool)
    r = np.asarray(list(forward_returns), dtype=float)
    if f.size != r.size:
        raise ValueError(f"flags and forward_returns length mismatch: {f.size} vs {r.size}")

    finite = np.isfinite(r)
    dropped = int((~finite).sum())
    f, r = f[finite], r[finite]
    n = int(r.size)
    if n == 0:
        return BaseRateReport(
            screen_name=str(screen_name),
            validation_status=STATUS_UNVALIDATED,
            n_candidates=0, n_flagged=0,
            flags=["never-base-rated", "empty-history"],
            note="History supplied but empty after dropping non-finite returns.",
        )

    n_flag = int(f.sum())
    out_flags: list[str] = []
    if dropped:
        out_flags.append(f"dropped-non-finite:{dropped}")

    outcomes: dict[str, dict] = {}
    for name, t in thr.items():
        hit = r >= float(t)
        n_hit = int(hit.sum())
        n_hit_flagged = int((hit & f).sum())
        base = n_hit / n
        precision = (n_hit_flagged / n_flag) if n_flag > 0 else None
        recall = (n_hit_flagged / n_hit) if n_hit > 0 else None
        lift = (precision / base) if (precision is not None and base > 0) else None
        outcomes[name] = {
            "threshold_return": float(t),
            "base_rate": base,
            "precision": precision,
            "recall": recall,
            "lift": lift,
            "n_hits": n_hit,
            "n_hits_flagged": n_hit_flagged,
        }

    flagged_returns = r[f]
    gate = promotion_gate(flagged_returns, min_trades=min_trades) if n_flag > 0 else None

    if n_flag < min_trades:
        status = STATUS_UNVALIDATED
        out_flags.append("insufficient-sample")
        note = (f"Only {n_flag} historical fires (< {min_trades}); not enough evidence "
                f"to validate or reject. Treat as unvalidated.")
    elif gate is not None and gate.get("pass"):
        status = STATUS_VALIDATED
        note = (f"Passed the promotion gate on {n_flag} fires: CI above zero and both "
                f"halves positive.")
    else:
        status = STATUS_REJECTED
        out_flags.append("failed-promotion-gate")
        note = (f"{n_flag} fires but the promotion gate failed "
                f"(CI_low>0 and both-halves-positive required).")

    return BaseRateReport(
        screen_name=str(screen_name),
        validation_status=status,
        n_candidates=n,
        n_flagged=n_flag,
        outcomes=outcomes,
        gate=gate,
        flags=out_flags,
        note=note,
    )


# ---------------------------------------------------------------------------
# 8. The verdict, combiner that CANNOT be confident on partial data
# ---------------------------------------------------------------------------

PILLAR_WEIGHTS = {"ev": 0.30, "convexity": 0.25, "spring": 0.20, "base_rate": 0.25}
CONFIDENT_THRESHOLD = 0.70      # at/above this a verdict may call itself confident
PARTIAL_DATA_CAP = 0.40         # any missing pillar hard-caps confidence here
UNVALIDATED_CAP = 0.50          # an unvalidated screen can never be confident
UNBOUNDED_DOWNSIDE_CAP = 0.35   # nor can an unbounded / unknown downside


@dataclass
class AsymmetryVerdict:
    """Top-level answer: is this an asymmetric bet, and how much do we know?"""
    ticker: str
    ev: Optional[float]
    asymmetry_ratio: Optional[float]
    convexity_ratio: Optional[float]
    kelly_fraction: Optional[float]
    spring_score: Optional[float]
    confidence: float
    validation_status: str
    flags: list[str] = field(default_factory=list)
    verdict: str = ""
    pillars_present: list[str] = field(default_factory=list)

    @property
    def is_confident(self) -> bool:
        """Confident requires: every pillar present, validated, bounded downside.

        The property is deliberately a conjunction of the raw preconditions
        AND the numeric threshold, so no future tweak to the confidence
        arithmetic can accidentally let partial data through.
        """
        return bool(
            self.confidence >= CONFIDENT_THRESHOLD
            and len(self.pillars_present) == len(PILLAR_WEIGHTS)
            and self.validation_status == STATUS_VALIDATED
            and "partial-data" not in self.flags
            and "downside-unbounded" not in self.flags
            and "downside-boundedness-unknown" not in self.flags
        )

    @property
    def actionable(self) -> bool:
        return bool(self.is_confident and (self.ev or 0.0) > 0)


def asymmetry_verdict(
    ticker: str,
    *,
    ev_result: Optional[EVResult] = None,
    outcomes=None,
    convexity: Optional[ConvexityResult] = None,
    spring: Optional[CoiledSpringResult] = None,
    base_rate: Optional[BaseRateReport] = None,
    kelly: Optional[KellyResult] = None,
) -> AsymmetryVerdict:
    """Combine the pillars into one verdict, with confidence you can trust.

    Four pillars, weighted by how much they change a decision:
        ev 0.30 | convexity 0.25 | base_rate 0.25 | spring 0.20

        confidence = ( sum of weights of PRESENT pillars )
                     * convexity.confidence * spring.confidence
        then hard-capped by:
            any pillar missing            -> <= 0.40
            screen not `validated`        -> <= 0.50
            downside unbounded/unknown    -> <= 0.35

    ``is_confident`` additionally requires all four pillars, a ``validated``
    base rate and a bounded downside as *preconditions*, not as arithmetic
    so partial data cannot produce a confident verdict under any weighting.
    That invariant is asserted in
    ``test_verdict_partial_data_can_never_be_confident``.

    ``ev_result`` may be passed directly or derived from ``outcomes``.
    """
    flags: list[str] = []
    if ev_result is None and outcomes is not None:
        try:
            ev_result = expected_value(outcomes)
        except ValueError as exc:
            flags.append(f"bad-outcome-distribution:{exc}")
            ev_result = None

    present = [k for k, v in (("ev", ev_result), ("convexity", convexity),
                              ("spring", spring), ("base_rate", base_rate)) if v is not None]
    missing = [k for k in PILLAR_WEIGHTS if k not in present]
    for m in missing:
        flags.append(f"missing-pillar:{m}")

    confidence = sum(PILLAR_WEIGHTS[k] for k in present)
    if convexity is not None:
        confidence *= float(convexity.confidence)
        flags.extend(convexity.flags)
    if spring is not None:
        confidence *= float(spring.confidence)
        flags.extend(spring.flags)

    status = base_rate.validation_status if base_rate is not None else STATUS_UNVALIDATED
    if base_rate is None:
        flags.append("never-base-rated")

    if missing:
        flags.append("partial-data")
        confidence = min(confidence, PARTIAL_DATA_CAP)
    if status != STATUS_VALIDATED:
        flags.append(f"screen-{status}")
        confidence = min(confidence, UNVALIDATED_CAP)
    if convexity is not None and convexity.downside_bounded is not True:
        confidence = min(confidence, UNBOUNDED_DOWNSIDE_CAP)

    # de-dupe while preserving order
    seen: set[str] = set()
    flags = [f for f in flags if not (f in seen or seen.add(f))]

    ev = ev_result.ev if ev_result is not None else None
    ratio = ev_result.asymmetry_ratio if ev_result is not None else None
    cvx = convexity.convexity_ratio if convexity is not None else None
    kf = kelly.recommended_fraction if kelly is not None else None
    ss = spring.score if spring is not None else None

    v = AsymmetryVerdict(
        ticker=str(ticker).upper(),
        ev=ev,
        asymmetry_ratio=ratio,
        convexity_ratio=cvx,
        kelly_fraction=kf,
        spring_score=ss,
        confidence=round(float(_clip01(confidence)), 4),
        validation_status=status,
        flags=flags,
        pillars_present=present,
    )
    v.verdict = _verdict_line(v, convexity)
    return v


def _verdict_line(v: AsymmetryVerdict, cvx: Optional[ConvexityResult]) -> str:
    """One plain-English line. No jargon, no false confidence."""
    if v.ev is None:
        return ("No expected value could be computed: supply an outcome distribution. "
                "Ranking without one is just score points again.")
    if v.ev <= 0:
        return (f"SKIP: expected value is {v.ev * 100:.0f}%, the payoff does not "
                f"pay for the losses, however exciting the setup looks.")
    if cvx is not None and cvx.downside_bounded is False:
        why = ", ".join(x for x in cvx.flags if x in ("gap-risk", "no-liquid-stop")) or "unbounded"
        return (f"NOT ASYMMETRIC: the downside is not actually bounded ({why}) "
                f"you cannot rely on the stop, so treat the loss as total.")
    if v.validation_status == STATUS_UNVALIDATED:
        return (f"UNVALIDATED: +{v.ev * 100:.0f}% expected value on paper, but this "
                f"screen has never been base-rated. Paper-trade it, do not size it.")
    if v.validation_status == STATUS_REJECTED:
        return (f"REJECTED SCREEN: historically this filter failed the promotion gate. "
                f"The +{v.ev * 100:.0f}% expected value is a model output, not evidence.")
    if not v.is_confident:
        gaps = ", ".join(f.split(":", 1)[1] for f in v.flags if f.startswith("missing-pillar"))
        return (f"PARTIAL: +{v.ev * 100:.0f}% expected value, but confidence is only "
                f"{v.confidence:.0%}, missing {gaps or 'inputs'}.")
    risk = f"{cvx.bounded_loss_frac * 100:.0f}%" if cvx and cvx.bounded_loss_frac else "the stop"
    up = f"{cvx.upside_frac * 100:.0f}%" if cvx and cvx.upside_frac else "the target"
    size = f", size ~{v.kelly_fraction:.1%} of bankroll" if v.kelly_fraction else ""
    return (f"ASYMMETRIC: risk {risk} to make {up} "
            f"({v.convexity_ratio:.1f}:1), validated screen, "
            f"expected value +{v.ev * 100:.0f}%{size}.")


# ---------------------------------------------------------------------------
# Price-series inputs: every one of these is causal by construction
# ---------------------------------------------------------------------------

def atr_at(daily: pd.DataFrame, index: Optional[int] = None, *, period: int = 14) -> Optional[float]:
    """ATR at row ``index`` using ONLY rows ``[0 .. index]``.

    Reuses ``modules.ta.TA.atr`` (the codebase's single ATR implementation);
    this wrapper adds nothing but column-case normalization and the causal
    slice. Returns None when there is not enough history or the frame lacks
    High/Low/Close.
    """
    d = _slice_causal(daily, index)
    if len(d) < int(period) + 1:
        return None
    d = _normalize_ohlc(d)
    if not {"High", "Low", "Close"}.issubset(d.columns):
        return None
    return _finite(TA.atr(d, int(period)).iloc[-1])


def atr_upside_target(
    daily: pd.DataFrame,
    index: Optional[int] = None,
    *,
    period: int = 14,
    expansion_mult: float = DEFAULT_ATR_EXPANSION,
) -> Optional[float]:
    """Upside price target from ATR expansion: ``close_i + mult * ATR_i``.

    Causal: computed from rows ``[0 .. index]`` only. Returns None when ATR
    is unavailable or zero (a flat or halted name has no expansion target,
    and pretending otherwise is how a stop-less "10x candidate" gets born).
    """
    d = _slice_causal(daily, index)
    a = atr_at(d, None, period=period)
    if a is None or a <= 0:
        return None
    dn = _normalize_ohlc(d)
    close = _finite(dn["Close"].iloc[-1]) if "Close" in dn.columns else None
    if close is None:
        return None
    return float(close + float(expansion_mult) * a)


def support_from_swing_low(
    daily: pd.DataFrame,
    index: Optional[int] = None,
    *,
    lookback: int = 20,
) -> Optional[float]:
    """Hard support = the lowest low of the trailing ``lookback`` bars up to ``index``.

    This is the "bounded loss" input to :func:`convexity_score`: a level the
    market has actually defended, not a round number. Causal by construction.
    """
    d = _slice_causal(daily, index)
    dn = _normalize_ohlc(d)
    if "Low" not in dn.columns or len(dn) == 0:
        return None
    lb = max(1, int(lookback))
    return _finite(dn["Low"].iloc[-lb:].min())


def realized_vol_compression(
    daily: pd.DataFrame,
    index: Optional[int] = None,
    *,
    fast: int = 20,
    slow: int = 100,
) -> Optional[float]:
    """Volatility compression ratio = stdev(logret, fast) / stdev(logret, slow).

    Below 1.0 means the name is quieter than its own baseline, the squeeze
    that precedes range expansion. Feed it straight into
    ``coiled_spring_score(vol_compression_ratio=...)``.

    Vectorized (numpy stdev over two trailing slices, no rolling python
    loop) and causal: rows after ``index`` are sliced away before any
    computation. Returns None on insufficient history or a zero baseline
    (a perfectly flat series has no compression ratio, and 0/0 is not 1.0).
    """
    d = _slice_causal(daily, index)
    dn = _normalize_ohlc(d)
    if "Close" not in dn.columns:
        return None
    c = pd.to_numeric(dn["Close"], errors="coerce").to_numpy(dtype=float)
    if c.size < int(slow) + 1 or np.any(~np.isfinite(c)) or np.any(c <= 0):
        return None
    logret = np.diff(np.log(c))
    if logret.size < int(slow):
        return None
    sd_fast = float(np.std(logret[-int(fast):], ddof=1)) if int(fast) > 1 else 0.0
    sd_slow = float(np.std(logret[-int(slow):], ddof=1))
    if not np.isfinite(sd_slow) or sd_slow <= 0:
        return None
    if not np.isfinite(sd_fast):
        return None
    return sd_fast / sd_slow
