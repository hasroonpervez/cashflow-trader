"""Canonical Signal dataclass for the paper pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Signal:
    """Venue-agnostic trading signal.

    ``p_true`` is model probability of the YES outcome in [0, 1].
    ``market_price`` is the quoted YES price in (0, 1).
    """

    signal_id: str
    strategy: str
    market_id: str
    venue: str
    side: Literal["yes", "no"]
    p_true: float
    market_price: float
    ts_utc: datetime = field(default_factory=utcnow)
    bucket: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def effective_price(self) -> float:
        """Price of the contract side being bought."""
        if self.side == "yes":
            return float(self.market_price)
        return 1.0 - float(self.market_price)

    def effective_p_true(self) -> float:
        if self.side == "yes":
            return float(self.p_true)
        return 1.0 - float(self.p_true)
