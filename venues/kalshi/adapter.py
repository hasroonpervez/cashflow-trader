"""Kalshi dry-run adapter - deterministic fake fills, zero network I/O."""
from __future__ import annotations

import hashlib
from dataclasses import asdict

from venues.base import OrderRequest, OrderResult, VenueAdapter, utcnow


def _request_digest(request: OrderRequest) -> str:
    return hashlib.sha256(
        f"{request.client_order_id}|{request.market_id}|{request.side}|"
        f"{request.price:.6f}|{request.quantity}".encode()
    ).hexdigest()[:12]


def _deterministic_fill(request: OrderRequest) -> tuple[int, float]:
    """Derive a stable fill from the request (no RNG, no network).

    Always fills the full quantity at the requested price when the price is
    a valid binary-contract quote in (0, 1).
    """
    px = float(request.price)
    qty = int(request.quantity)
    if px <= 0.0 or px >= 1.0:
        return 0, 0.0
    return qty, px


class KalshiDryRunAdapter(VenueAdapter):
    """Paper/dry-run Kalshi stub. Never opens sockets or reads credentials."""

    name = "kalshi"

    def __init__(self, mode: str = "dry_run") -> None:
        if mode not in {"paper", "dry_run"}:
            raise ValueError(
                f"KalshiDryRunAdapter only supports paper/dry_run, got {mode!r}"
            )
        super().__init__(mode=mode)  # type: ignore[arg-type]

    def _place_order_impl(self, request: OrderRequest) -> OrderResult:
        digest = _request_digest(request)
        order_id = f"dry-{digest}"
        filled_qty, avg_px = _deterministic_fill(request)
        if filled_qty <= 0:
            return OrderResult(
                ok=False,
                mode=self.mode,
                venue=self.name,
                order_id=order_id,
                client_order_id=request.client_order_id,
                market_id=request.market_id,
                side=request.side,
                requested_price=float(request.price),
                requested_qty=int(request.quantity),
                filled_qty=0,
                avg_fill_price=0.0,
                status="rejected",
                ts_utc=utcnow(),
                reason="price must be in (0, 1) for binary contracts",
                raw={"digest": digest},
            )
        return OrderResult(
            ok=True,
            mode=self.mode,
            venue=self.name,
            order_id=order_id,
            client_order_id=request.client_order_id,
            market_id=request.market_id,
            side=request.side,
            requested_price=float(request.price),
            requested_qty=int(request.quantity),
            filled_qty=filled_qty,
            avg_fill_price=avg_px,
            status="filled",
            ts_utc=utcnow(),
            reason="dry-run deterministic fill",
            raw={"digest": digest, "request": asdict(request)},
        )
