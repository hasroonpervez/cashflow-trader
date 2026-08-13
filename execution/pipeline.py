"""Paper pipeline: Signal -> promotion_gate -> kelly -> kalshi dry-run -> ledger."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import uuid4

from risk.kelly import KellySizing, fee_aware_kelly
from risk.promotion_gate import GateDecision, promotion_gate
from signals.schema import Signal
from venues.base import OrderRequest, OrderResult
from venues.kalshi.adapter import KalshiDryRunAdapter

from .paper_ledger import PaperLedger


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PipelineResult:
    """Outcome of one paper pipeline pass."""

    status: str  # held | sized_rejected | filled | rejected
    signal_id: str
    gate: GateDecision
    kelly: Optional[KellySizing] = None
    order: Optional[OrderResult] = None
    contracts: int = 0
    reasons: list[str] = field(default_factory=list)
    ledger_ids: dict[str, str] = field(default_factory=dict)


class PaperPipeline:
    """Compose gate + fee-aware Kelly + Kalshi dry-run + paper ledger.

    No network. Live mode is unreachable because the Kalshi adapter only
    constructs in paper/dry_run and VenueAdapter.place_order refuses live.
    """

    def __init__(
        self,
        ledger: Optional[PaperLedger] = None,
        venue: Optional[KalshiDryRunAdapter] = None,
        *,
        bankroll: float = 10_000.0,
        min_trades: int = 100,
        skip_gate: bool = False,
    ) -> None:
        self.ledger = ledger or PaperLedger()
        self.venue = venue or KalshiDryRunAdapter(mode="dry_run")
        self.bankroll = float(bankroll)
        self.min_trades = int(min_trades)
        self.skip_gate = bool(skip_gate)

    def run(
        self,
        signal: Signal,
        strategy_returns: Sequence[float] = (),
        strategy_buckets: Optional[Sequence] = None,
    ) -> PipelineResult:
        # 1) Always ledger the signal.
        sig_row = self.ledger.record_signal(
            {
                "signal_id": signal.signal_id,
                "strategy": signal.strategy,
                "market_id": signal.market_id,
                "venue": signal.venue,
                "side": signal.side,
                "p_true": signal.p_true,
                "market_price": signal.market_price,
                "bucket": signal.bucket,
                "meta": signal.meta,
                "ts_utc": signal.ts_utc.isoformat(),
            },
            signal_id=signal.signal_id,
            ts=signal.ts_utc if signal.ts_utc.tzinfo else signal.ts_utc.replace(tzinfo=timezone.utc),
        )

        # 2) Promotion gate on strategy history (hold keeps paper-only posture).
        if self.skip_gate:
            gate = GateDecision(
                decision="promote",
                passed=True,
                reasons=["gate skipped for unit test / explicit paper force"],
                n=len(list(strategy_returns)),
                expectancy=0.0,
                checks={"skipped": True},
            )
        else:
            gate = promotion_gate(
                strategy_returns,
                strategy_buckets,
                min_trades=self.min_trades,
            )

        if not gate.passed:
            return PipelineResult(
                status="held",
                signal_id=signal.signal_id,
                gate=gate,
                reasons=list(gate.reasons),
                ledger_ids={"signal": sig_row.row_id},
            )

        # 3) Fee-aware fractional Kelly.
        kelly = fee_aware_kelly(signal.effective_p_true(), signal.effective_price())
        if not kelly.should_trade:
            return PipelineResult(
                status="sized_rejected",
                signal_id=signal.signal_id,
                gate=gate,
                kelly=kelly,
                reasons=list(kelly.flags),
                ledger_ids={"signal": sig_row.row_id},
            )

        dollars = kelly.recommended_fraction * self.bankroll
        px = signal.effective_price()
        contracts = int(dollars // px) if px > 0 else 0
        if contracts <= 0:
            return PipelineResult(
                status="sized_rejected",
                signal_id=signal.signal_id,
                gate=gate,
                kelly=kelly,
                contracts=0,
                reasons=["contracts-rounded-to-zero"],
                ledger_ids={"signal": sig_row.row_id},
            )

        # 4) Dry-run venue order.
        client_oid = f"paper-{signal.signal_id}-{uuid4().hex[:8]}"
        req = OrderRequest(
            market_id=signal.market_id,
            side=signal.side,
            price=px,
            quantity=contracts,
            client_order_id=client_oid,
            meta={"strategy": signal.strategy, "signal_id": signal.signal_id},
        )
        order = self.venue.place_order(req)

        ord_row = self.ledger.record_order(
            {
                "order_id": order.order_id,
                "client_order_id": order.client_order_id,
                "signal_id": signal.signal_id,
                "market_id": order.market_id,
                "side": order.side,
                "price": order.requested_price,
                "quantity": order.requested_qty,
                "status": order.status,
                "mode": order.mode,
                "venue": order.venue,
                "reason": order.reason,
                "kelly": asdict(kelly),
            },
            order_id=order.order_id or client_oid,
            ts=order.ts_utc,
        )

        ledger_ids = {"signal": sig_row.row_id, "order": ord_row.row_id}
        if order.ok and order.filled_qty > 0:
            fill_row = self.ledger.record_fill(
                {
                    "fill_id": order.order_id,
                    "order_id": order.order_id,
                    "signal_id": signal.signal_id,
                    "market_id": order.market_id,
                    "side": order.side,
                    "filled_qty": order.filled_qty,
                    "avg_fill_price": order.avg_fill_price,
                    "venue": order.venue,
                    "mode": order.mode,
                },
                fill_id=order.order_id,
                ts=order.ts_utc,
            )
            ledger_ids["fill"] = fill_row.row_id
            return PipelineResult(
                status="filled",
                signal_id=signal.signal_id,
                gate=gate,
                kelly=kelly,
                order=order,
                contracts=order.filled_qty,
                reasons=["dry-run fill recorded"],
                ledger_ids=ledger_ids,
            )

        return PipelineResult(
            status="rejected",
            signal_id=signal.signal_id,
            gate=gate,
            kelly=kelly,
            order=order,
            contracts=0,
            reasons=[order.reason or "venue rejected"],
            ledger_ids=ledger_ids,
        )
