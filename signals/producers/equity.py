"""Equity Sig_* producers wrapping modules.validated_signals (paper-only)."""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from modules.validated_signals import orb30_signal, swing_pullback_signal
from signals.schema import Signal

# Paper venue for cash equities: Robinhood stub refuses LIVE.
_EQUITY_VENUE = "robinhood"

# Conservative paper priors when caller does not supply a calibrated p_true.
# These are wiring defaults for the paper ledger, not live sizing claims.
_DEFAULT_P_ORB30 = 0.58
_DEFAULT_P_SWING = 0.56


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
    return _as_buy_signal(
        market=symbol,
        source="Sig_orb30",
        raw=raw,
        p_true=p,
        edge=edge,
        extra_meta={"symbol": symbol, "family": "equity_day"},
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
    return _as_buy_signal(
        market=symbol,
        source="Sig_swing_pullback",
        raw=raw,
        p_true=p,
        edge=edge,
        extra_meta={"symbol": symbol, "family": "equity_swing"},
    )
