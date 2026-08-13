"""Paper pipeline: Signal -> gate (annotate) -> stage2 (annotate) -> Kelly -> PortfolioRisk -> venue -> ledger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from execution.paper_ledger import PaperLedger
from risk.portfolio_risk import PortfolioRiskAdvice, advise_portfolio_risk
from risk.promotion_gate import PromotionGateResult, gate_from_stats
from risk.sizing import size_paper
from risk.edge import EdgeModelResult, edge_from_stats
from risk.stage2 import Stage2Result, stage2_from_stats
from signals.schema import Signal
from venues.base import OrderRequest, VenueAdapter


@dataclass(frozen=True)
class PaperPipelineResult:
    accepted: bool
    decision: PromotionGateResult
    stake: float
    fill: Mapping[str, Any] | None
    reasons: tuple[str, ...]
    portfolio_risk: PortfolioRiskAdvice | None = None
    promoted: bool = False
    stage2: Stage2Result | None = None
    edge: EdgeModelResult | None = None


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
    open_exposure: float = 0.0,
) -> PaperPipelineResult:
    """Run one paper decision cycle.

    Promotion gate **annotates** promote/hold and may haircut size, but does
    **not** block paper fills (avoids chicken-and-egg while n < min_n).
    Stage-2 DSR/PBO also annotates only: holds append reasons and never block
    paper fills. The 0.25 research haircut applies only to the promotion gate.
    Live placement remains refused by the venue adapter.
    """
    ledger.record_signal(signal.to_ledger_dict())

    decision = gate_from_stats(gate_stats)
    promoted = bool(decision.ok)
    stage2 = stage2_from_stats(gate_stats)
    edge_note = edge_from_stats(gate_stats, model_edge=signal.edge)

    # Always size for paper; haircut when gate holds so research still accrues fills.
    sized = size_paper(
        signal,
        bankroll,
        odds_b=odds_b,
        fee_rate=fee_rate,
        kelly_fraction=kelly_fraction,
    )
    stake_frac = sized.stake_frac
    if not promoted:
        stake_frac *= 0.25  # research-size while gate holds

    stake = max(0.0, float(bankroll) * stake_frac)
    advice = advise_portfolio_risk(
        stake=stake, bankroll=bankroll, open_exposure=open_exposure
    )
    if advice.haircut > 0:
        stake *= max(0.0, 1.0 - advice.haircut)

    reasons: list[str] = list(sized.reasons)
    if not promoted:
        reasons.extend(decision.reasons)
        reasons.append("gate: annotate-hold; paper fill still recorded")
    if not stage2.ok:
        reasons.extend(stage2.reasons)
        reasons.append("stage2: annotate-hold; paper fill still recorded")
    if not edge_note.ok:
        reasons.extend(edge_note.reasons)
        reasons.append("edge: annotate-hold; paper fill still recorded")
    reasons.extend(f"portfolio_risk: {r}" for r in advice.reasons)

    if stake <= 0:
        return PaperPipelineResult(
            accepted=False,
            decision=decision,
            stake=0.0,
            fill=None,
            reasons=tuple(reasons) + ("kelly: non-positive stake",),
            portfolio_risk=advice,
            promoted=promoted,
            stage2=stage2,
            edge=edge_note,
        )

    order = OrderRequest(
        market=signal.market,
        side=signal.side,
        size=stake,
        price=None,
        signal_id=signal.id,
        metadata={
            "source": signal.source,
            "source_node": signal.source_node,
            "promoted": promoted,
            "edge": signal.edge,
        },
    )
    ledger.record_order(
        {
            "market": order.market,
            "instrument": order.market,
            "side": order.side,
            "size": order.size,
            "signal_id": order.signal_id,
            "mode": adapter.mode.value,
            "promoted": promoted,
        }
    )
    fill = adapter.place_order(order)
    fill_payload = {
        "order_id": fill.order_id,
        "market": fill.market,
        "instrument": fill.market,
        "side": fill.side,
        "size": fill.size,
        "price": fill.price,
        "mode": fill.mode.value,
        "promoted": promoted,
        "raw": dict(fill.raw or {}),
    }
    ledger.record_fill(fill_payload)
    # Outcome stub row so calib->gate has a write target (PnL filled later).
    ledger.record_outcome(
        {
            "signal_id": signal.id,
            "order_id": fill.order_id,
            "market": signal.market,
            "pnl": None,
            "settled": False,
            "promoted": promoted,
        }
    )
    return PaperPipelineResult(
        accepted=True,
        decision=decision,
        stake=stake,
        fill=fill_payload,
        reasons=tuple(reasons),
        portfolio_risk=advice,
        promoted=promoted,
        stage2=stage2,
        edge=edge_note,
    )
