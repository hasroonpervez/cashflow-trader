"""Base venue adapter — paper/dry-run only at P0."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class Mode(str, Enum):
    PAPER = "paper"
    DRY_RUN = "dry_run"
    LIVE = "live"


_ALLOWED_PLACE = frozenset({Mode.PAPER, Mode.DRY_RUN})


@dataclass(frozen=True)
class OrderRequest:
    market: str
    side: str
    size: float
    price: float | None = None
    signal_id: str | None = None
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Fill:
    order_id: str
    market: str
    side: str
    size: float
    price: float
    mode: Mode
    raw: Mapping[str, Any] | None = None


class VenueAdapter(ABC):
    """Venue interface. ``place_order`` only allows paper/dry_run modes."""

    name: str

    def __init__(self, mode: Mode | str = Mode.PAPER) -> None:
        self.mode = Mode(mode) if not isinstance(mode, Mode) else mode

    @abstractmethod
    def fetch_markets(self) -> Sequence[Mapping[str, Any]]:
        raise NotImplementedError

    def place_order(self, order: OrderRequest) -> Fill:
        if self.mode not in _ALLOWED_PLACE:
            raise PermissionError(
                f"{self.name}: place_order refused unless mode in "
                f"{{paper, dry_run}}; got {self.mode.value!r}"
            )
        return self._place_paper(order)

    @abstractmethod
    def _place_paper(self, order: OrderRequest) -> Fill:
        raise NotImplementedError
