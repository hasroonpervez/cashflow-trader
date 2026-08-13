"""Paper pipeline: Signal → gate → Kelly → venue dry-run → ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from execution.paper_ledger import PaperLedger
from risk.kelly import fractional_kelly
from risk.promotion_gate import PromotionGateResult, gate_from_stats
from signals.schema import Signal
from venues.base import OrderRequest, VenueAdapter


@dataclass(frozen=True)
class PaperPipelineResult:
    accepted: bool
    decision: PromotionGateResult
    stake: float
    fill: Mapping[str, Any] | None
    reasons: tuple[str, ...]


def run_paper_pipeline(
    signal: Signal,
    gate_stats: Mapping[str, Any] | None,
    adapter: VenueAdapter,
    ledger: PaperLedger,
    bankroll: float,
    *,
    odds_b: float = 1.0,
    fee_rate: float = 0.0,
    kelly_fraction: float = 0.25,
) -> PaperPipelineResult:
    """Run one paper decision cycle.

    ``gate_stats`` is a mapping consumed by :func:`risk.promotion_gate.gate_from_stats`
    (keys: ``outcomes``, optional ``labels`` / thresholds). Empty/missing
    outcomes fail the gate (no history yet).
    """
    ledger.record_signal(
        {
            "id": signal.id,
            "ts": signal.ts.isoformat(),
            "venue": signal.venue,
            "market": signal.market,
            "side": signal.side,
            "p_true": signal.p_true,
            "source": signal.source,
            "metadata": dict(signal.metadata),
        }
    )

    decision = gate_from_stats(gate_stats)
    if not decision.ok:
        return PaperPipelineResult(
            accepted=False,
            decision=decision,
            stake=0.0,
            fill=None,
            reasons=decision.reasons,
        )

    stake_frac = fractional_kelly(
        signal.p_true,
        odds_b,
        fraction=kelly_fraction,
        fee_rate=fee_rate,
    )
    stake = max(0.0, float(bankroll) * stake_frac)
    if stake <= 0:
        return PaperPipelineResult(
            accepted=False,
            decision=decision,
            stake=0.0,
            fill=None,
            reasons=("kelly: non-positive stake",),
        )

    order = OrderRequest(
        market=signal.market,
        side=signal.side,
        size=stake,
        price=None,
        signal_id=signal.id,
        metadata={"source": signal.source},
    )
    ledger.record_order(
        {
            "market": order.market,
            "side": order.side,
            "size": order.size,
            "signal_id": order.signal_id,
            "mode": adapter.mode.value,
        }
    )
    fill = adapter.place_order(order)
    fill_payload = {
        "order_id": fill.order_id,
        "market": fill.market,
        "side": fill.side,
        "size": fill.size,
        "price": fill.price,
        "mode": fill.mode.value,
        "raw": dict(fill.raw or {}),
    }
    ledger.record_fill(fill_payload)
    return PaperPipelineResult(
        accepted=True,
        decision=decision,
        stake=stake,
        fill=fill_payload,
        reasons=(),
    )
