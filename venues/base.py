"""VenueAdapter ABC - live place_order is hard-refused at P0."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

Mode = Literal["paper", "dry_run", "live"]

ALLOWED_ORDER_MODES = frozenset({"paper", "dry_run"})
LIVE_MODES_REFUSED = frozenset({"live"})


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OrderRequest:
    """Venue-agnostic order intent."""

    market_id: str
    side: Literal["yes", "no", "buy", "sell"]
    price: float
    quantity: int
    client_order_id: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    """Fill / reject result from a venue adapter."""

    ok: bool
    mode: str
    venue: str
    order_id: str
    client_order_id: str
    market_id: str
    side: str
    requested_price: float
    requested_qty: int
    filled_qty: int
    avg_fill_price: float
    status: str
    ts_utc: datetime
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class VenueAdapter(ABC):
    """Shared venue interface.

    ``place_order`` refuses unless ``mode`` is in {paper, dry_run}.
    Subclasses implement ``_place_order_impl`` for the safe paths only.
    """

    name: str = "base"

    def __init__(self, mode: Mode = "dry_run") -> None:
        self.mode: Mode = mode

    def place_order(self, request: OrderRequest) -> OrderResult:
        if self.mode not in ALLOWED_ORDER_MODES:
            raise RuntimeError(
                f"{self.name}: place_order refused for mode={self.mode!r}; "
                f"allowed={sorted(ALLOWED_ORDER_MODES)}. No live trading at P0."
            )
        if request.quantity <= 0:
            return OrderResult(
                ok=False,
                mode=self.mode,
                venue=self.name,
                order_id="",
                client_order_id=request.client_order_id,
                market_id=request.market_id,
                side=request.side,
                requested_price=float(request.price),
                requested_qty=int(request.quantity),
                filled_qty=0,
                avg_fill_price=0.0,
                status="rejected",
                ts_utc=utcnow(),
                reason="quantity must be > 0",
            )
        return self._place_order_impl(request)

    @abstractmethod
    def _place_order_impl(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError
