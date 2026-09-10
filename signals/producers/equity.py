"""Equity Sig_* producers wrapping modules.validated_signals (paper-only)."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from modules.validated_signals import orb30_signal, session_vwap, swing_pullback_signal
from signals.producers.patterns import bar_patterns
from signals.scanner import ScannerConfig, score_symbol, session_groups
from signals.schema import Signal

# Paper venue for cash equities: Robinhood stub refuses LIVE.
_EQUITY_VENUE = "robinhood"

# Conservative paper priors when caller does not supply a calibrated p_true.
# These are wiring defaults for the paper ledger, not live sizing claims.
_DEFAULT_P_ORB30 = 0.58
_DEFAULT_P_SWING = 0.56
_DEFAULT_P_ORB_RVOL_VWAP = 0.55


def _as_buy_signal(
    *,
    market: str,
    source: str,
    raw: Mapping[str, Any],
    p_true: float,
    edge: float | None,
    extra_meta: Mapping[str, Any] | None = None,
) -> Signal:
    meta: dict[str, Any] = {
        "strategy": source,
        "validated_raw": dict(raw),
        "paper_only": True,
    }
    if extra_meta:
        meta.update(dict(extra_meta))
    return Signal(
        venue=_EQUITY_VENUE,
        market=str(market),
        side="buy",
        p_true=float(p_true),
        source=source,
        edge=edge,
        metadata=meta,
    )


def produce_orb30(
    day_5m: pd.DataFrame,
    *,
    symbol: str,
    p_true: float | None = None,
    edge: float | None = None,
    prior_close: float | None = None,
    latest_entry: str = "14:00",
    gap_skip_pct: float = 2.0,
    tz: str = "America/New_York",
) -> Signal | None:
    """Wrap ``orb30_signal`` → paper ``Signal`` (venue=robinhood).

    Returns None when there is no actionable trade (including gap-skip).
    Source node: ``Sig_orb30``.
    """
    raw = orb30_signal(
        day_5m,
        latest_entry=latest_entry,
        gap_skip_pct=gap_skip_pct,
        prior_close=prior_close,
        tz=tz,
    )
    if not raw or raw.get("status") != "signal":
        return None
    p = _DEFAULT_P_ORB30 if p_true is None else float(p_true)
    extra = {"symbol": symbol, "family": "equity_day"}
    pats = bar_patterns(day_5m)
    if pats:
        extra["patterns"] = pats
    return _as_buy_signal(
        market=symbol,
        source="Sig_orb30",
        raw=raw,
        p_true=p,
        edge=edge,
        extra_meta=extra,
    )


def produce_swing_pullback(
    daily: pd.DataFrame,
    *,
    symbol: str,
    p_true: float | None = None,
    edge: float | None = None,
) -> Signal | None:
    """Wrap ``swing_pullback_signal`` → paper ``Signal`` (venue=robinhood).

    Returns None when the reclaim setup is not present.
    Source node: ``Sig_swing_pullback``.
    """
    raw = swing_pullback_signal(daily)
    if not raw or raw.get("status") != "signal":
        return None
    p = _DEFAULT_P_SWING if p_true is None else float(p_true)
    extra = {"symbol": symbol, "family": "equity_swing"}
    pats = bar_patterns(daily)
    if pats:
        extra["patterns"] = pats
    return _as_buy_signal(
        market=symbol,
        source="Sig_swing_pullback",
        raw=raw,
        p_true=p,
        edge=edge,
        extra_meta=extra,
    )


def produce_orb_rvol_vwap(
    bars: pd.DataFrame,
    *,
    symbol: str,
    p_true: float | None = None,
    edge: float | None = None,
    prior_close: float | None = None,
    avg_volume: float | None = None,
    latest_entry: str = "14:00",
    tz: str = "America/New_York",
    scanner_config: ScannerConfig | None = None,
) -> Signal | None:
    """ORB + RVOL + VWAP-side on the movers universe (paper, unvalidated).

    Source node: ``Sig_orb_rvol_vwap``.

    Requires an in-play scanner pass (gap% / RVOL / price / dollar volume),
    a validated-style ORB-30 *break* (gap-skip is **not** applied — the
    universe *is* gappers), and last close still above session VWAP so we
    take a slice of the move rather than a failed ORB fade.

    Returns None when any leg is missing. Never places a live order.
    """
    cfg = scanner_config or ScannerConfig(tz=tz)
    candidate = score_symbol(
        symbol,
        bars,
        prior_close=prior_close,
        avg_volume=avg_volume,
        config=cfg,
    )
    if not candidate.in_play:
        return None

    groups = session_groups(bars, tz=cfg.tz)
    if not groups:
        return None
    day_5m = groups[-1][1]
    # Gap filter is the scanner's job (require gap), not ORB's skip-gap-days.
    raw = orb30_signal(
        day_5m,
        latest_entry=latest_entry,
        gap_skip_pct=1e9,
        prior_close=None,
        tz=cfg.tz,
    )
    if not raw or raw.get("status") != "signal":
        return None

    try:
        vwap = session_vwap(day_5m, tz=cfg.tz)
        last_close = float(day_5m["close"].iloc[-1])
        last_vwap = float(vwap.iloc[-1])
    except Exception:
        return None
    if not (last_vwap == last_vwap) or last_vwap <= 0:
        return None
    if last_close <= last_vwap:
        return None

    p = _DEFAULT_P_ORB_RVOL_VWAP if p_true is None else float(p_true)
    extra: dict[str, Any] = {
        "symbol": symbol,
        "family": "equity_day",
        "unvalidated": True,
        "paper_only": True,
        "universe": candidate.to_dict(),
        "vwap_side": "above",
        "session_vwap": round(last_vwap, 4),
        "last_close": round(last_close, 4),
        "rvol": candidate.rvol,
        "gap_pct": candidate.gap_pct,
        "note": "slice of ~20% in-play range; not the full move",
    }
    # No pattern-library / named-setup tags on this Sig. That layer waits
    # until paper ledger n>0 (settle→calib→edge). Do not attach bar_patterns.
    return _as_buy_signal(
        market=symbol,
        source="Sig_orb_rvol_vwap",
        raw=raw,
        p_true=p,
        edge=edge,
        extra_meta=extra,
    )
