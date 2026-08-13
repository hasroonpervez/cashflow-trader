"""Robinhood venue stub — read/watchlist posture; live refused."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from venues.base import Fill, Mode, OrderRequest, VenueAdapter


class RobinhoodReadAdapter(VenueAdapter):
    name = "robinhood"

    def __init__(self, mode: Mode | str = Mode.PAPER) -> None:
        mode_obj = Mode(mode) if not isinstance(mode, Mode) else mode
        if mode_obj is Mode.LIVE:
            raise ValueError("RobinhoodReadAdapter: live trading not enabled")
        super().__init__(mode_obj)

    def fetch_markets(self) -> Sequence[Mapping[str, Any]]:
        return ()

    def _place_paper(self, order: OrderRequest) -> Fill:
        return Fill(
            order_id=f"rh-paper-{order.signal_id or 'na'}",
            market=order.market,
            side=order.side,
            size=float(order.size),
            price=float(order.price or 0.0),
            mode=self.mode,
            raw={"adapter": self.name, "stub": True, "read_first": True},
        )
