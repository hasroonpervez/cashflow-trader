"""Unified paper Signal record (Graph P0 contract + aliases)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Signal:
    """Cross-venue paper signal.

    Canonical: venue, market (instrument), side, p_true (p_model), source
    (source_node), edge, metadata. Aliases provided as properties.
    """

    venue: str
    market: str
    side: str
    p_true: float
    source: str
    id: str = field(default_factory=lambda: uuid4().hex)
    ts: datetime = field(default_factory=_utc_now)
    edge: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.p_true) <= 1.0:
            raise ValueError("p_true must be in [0, 1]")
        if self.ts.tzinfo is None:
            object.__setattr__(self, "ts", self.ts.replace(tzinfo=timezone.utc))

    # --- locked-contract aliases ---
    @property
    def instrument(self) -> str:
        return self.market

    @property
    def market_id(self) -> str:
        return self.market

    @property
    def p_model(self) -> float:
        return float(self.p_true)

    @property
    def source_node(self) -> str:
        return self.source

    def to_ledger_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "venue": self.venue,
            "market": self.market,
            "instrument": self.instrument,
            "market_id": self.market_id,
            "side": self.side,
            "p_true": self.p_true,
            "p_model": self.p_model,
            "edge": self.edge,
            "source": self.source,
            "source_node": self.source_node,
            "metadata": dict(self.metadata),
        }
