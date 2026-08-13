"""Kalshi / event Sig_* helper: pure local Signal builder (no network)."""
from __future__ import annotations

from typing import Any, Mapping

from signals.schema import Signal

_VENUE = "kalshi"


def produce_kalshi_event(
    *,
    p_true: float,
    market_price: float,
    market_id: str,
    strategy: str | None = None,
    source_node: str | None = None,
    side: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Signal:
    """Build a paper ``Signal`` from supplied event probabilities.

    No network, no secrets, no venue API calls. Edge defaults to
    ``p_true - market_price`` for the chosen side (yes ⇒ model vs ask;
    no ⇒ (1 - p_true) - market_price when market_price is the no ask).

    ``source`` / ``source_node`` resolve from ``source_node`` or ``strategy``
    (prefixed ``Sig_K.`` when a bare strategy name is given).
    """
    p = float(p_true)
    px = float(market_price)
    if not 0.0 <= px <= 1.0:
        raise ValueError("market_price must be in [0, 1]")

    if source_node:
        source = str(source_node)
    elif strategy:
        s = str(strategy)
        source = s if s.startswith("Sig_") else f"Sig_K.{s}"
    else:
        source = "Sig_K.event"

    chosen_side = (side or "yes").lower()
    if chosen_side not in {"yes", "no"}:
        raise ValueError("side must be 'yes' or 'no'")

    if chosen_side == "yes":
        edge = p - px
    else:
        edge = (1.0 - p) - px

    meta: dict[str, Any] = {
        "market_price": px,
        "paper_only": True,
        "no_network": True,
    }
    if strategy:
        meta["strategy"] = str(strategy)
    if metadata:
        meta.update(dict(metadata))

    return Signal(
        venue=_VENUE,
        market=str(market_id),
        side=chosen_side,
        p_true=p,
        source=source,
        edge=edge,
        metadata=meta,
    )
