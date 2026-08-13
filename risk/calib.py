"""Thin paper-ledger feedback into gate_stats (not a calibrator).

Settled numeric PnL from ``PaperLedger`` is exposed as ``outcomes`` for
``run_paper_pipeline``. This is ledger feedback only, not Platt scaling,
Brier, or ECE. Paper only.
"""
from __future__ import annotations

from typing import Any

from execution.paper_ledger import LedgerEvent, PaperLedger


def apply_settlement(
    ledger: PaperLedger,
    signal_or_fill_id: str,
    pnl: float,
) -> LedgerEvent:
    """Settle a paper outcome by signal_id or fill/order_id."""
    key = str(signal_or_fill_id)
    signal_id = key
    extra: dict[str, Any] = {}
    for ev in reversed(ledger.list_outcomes()):
        p = ev.payload
        oid = p.get("order_id") or p.get("fill_id")
        if p.get("signal_id") == key or oid == key:
            if p.get("signal_id") is not None:
                signal_id = str(p["signal_id"])
            for field in ("order_id", "market", "promoted"):
                if field in p:
                    extra[field] = p[field]
            if oid is not None:
                extra["order_id"] = oid
            break
    return ledger.settle_outcome(
        signal_id=signal_id, pnl=float(pnl), extra=extra or None
    )


def outcomes_from_ledger(ledger: PaperLedger) -> list[float]:
    """Return settled numeric PnL values from the paper ledger."""
    pnls: list[float] = []
    for ev in ledger.list_outcomes():
        payload = ev.payload
        if not payload.get("settled"):
            continue
        pnl = payload.get("pnl")
        if pnl is None:
            continue
        pnls.append(float(pnl))
    return pnls


def gate_stats_from_ledger(ledger: PaperLedger, **defaults: Any) -> dict[str, Any]:
    """Build a ``gate_stats`` mapping for ``run_paper_pipeline``.

    ``outcomes`` always come from settled ledger PnL. Other keys (``min_n``,
    ``labels``, ``split_half_corr``, stage-2 knobs, ...) pass through as
    defaults.
    """
    stats = dict(defaults)
    stats["outcomes"] = outcomes_from_ledger(ledger)
    return stats
