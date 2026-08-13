"""Sig_* producers: validated / event inputs → unified paper Signal."""
from __future__ import annotations

from signals.producers.equity import (
    produce_orb30,
    produce_swing_pullback,
)
from signals.producers.kalshi import produce_kalshi_event
from signals.producers.patterns import bar_patterns, event_patterns

__all__ = [
    "produce_orb30",
    "produce_swing_pullback",
    "produce_kalshi_event",
    "bar_patterns",
    "event_patterns",
]
