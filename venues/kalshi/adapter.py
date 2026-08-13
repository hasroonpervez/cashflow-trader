"""Kalshi dry-run adapter — deterministic fake fills, no network."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

from venues.base import Fill, Mode, OrderRequest, VenueAdapter


class KalshiDryRunAdapter(VenueAdapter):
    """Paper/dry-run Kalshi adapter. Fills are derived from signal id hash."""

    name = "kalshi"

    def __init__(self, mode: Mode | str = Mode.DRY_RUN) -> None:
        mode_obj = Mode(mode) if not isinstance(mode, Mode) else mode
        if mode_obj is Mode.LIVE:
            raise ValueError("KalshiDryRunAdapter cannot be constructed in LIVE mode")
        super().__init__(mode_obj)

    def fetch_markets(self) -> Sequence[Mapping[str, Any]]:
        return (
            {"market": "DEMO-MARKET", "yes_ask": 0.45, "no_ask": 0.55},
        )

    def _place_paper(self, order: OrderRequest) -> Fill:
        seed = f"{order.signal_id or ''}|{order.market}|{order.side}|{order.size}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        price = order.price
        if price is None:
            # Deterministic mid-ish price in (0.05, 0.94] from hash
            price = (int(digest[:2], 16) % 89 + 5) / 100.0
        return Fill(
            order_id=f"dry-{digest[:12]}",
            market=order.market,
            side=order.side,
            size=float(order.size),
            price=float(price),
            mode=self.mode,
            raw={"adapter": self.name, "dry_run": True, "seed_hash": digest[:12]},
        )
