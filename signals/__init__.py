"""Shared signal types and Sig_* producers."""
from __future__ import annotations

from signals.schema import Signal

__all__ = ["Signal"]

try:
    from signals.producers import (  # noqa: F401
        produce_kalshi_event,
        produce_orb30,
        produce_swing_pullback,
    )

    __all__ += [
        "produce_orb30",
        "produce_swing_pullback",
        "produce_kalshi_event",
    ]
except ImportError:
    # producers may pull optional heavy deps; schema remains available
    pass
