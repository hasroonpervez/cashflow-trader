"""Unified paper Signal record."""
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

    Fields: id, ts (UTC), venue, market, side, p_true, source, metadata.
    """

    venue: str
    market: str
    side: str
    p_true: float
    source: str
    id: str = field(default_factory=lambda: uuid4().hex)
    ts: datetime = field(default_factory=_utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.p_true) <= 1.0:
            raise ValueError("p_true must be in [0, 1]")
        if self.ts.tzinfo is None:
            object.__setattr__(self, "ts", self.ts.replace(tzinfo=timezone.utc))
