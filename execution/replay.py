"""Paper replay hooks: mark a fill to last close and apply fee/slippage.

Offline. Caller injects bars. Does not fetch Yahoo or place live orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from execution.friction import apply_friction
from execution.paper_ledger import PaperLedger
from signals.scanner import normalize_ohlcv


@dataclass(frozen=True)
class ReplayMark:
    market: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    fee_rate: float
    slippage_bps: float
    paper_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "side": self.side,
            "size": self.size,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "fee_rate": self.fee_rate,
            "slippage_bps": self.slippage_bps,
            "paper_only": self.paper_only,
        }


def _side_sign(side: str) -> float:
    s = (side or "").strip().lower()
    if s in {"buy", "yes", "long"}:
        return 1.0
    if s in {"sell", "no", "short"}:
        return -1.0
    return 1.0


def mark_to_close_pnl(
    *,
    side: str,
    size: float,
    entry_price: float,
    exit_price: float,
    fee_rate: float = 0.0,
    slippage_bps: float = 0.0,
) -> tuple[float, float]:
    """Dollar stake ``size`` marked as a simple return. Returns (gross, net)."""
    entry = float(entry_price)
    exit_px = float(exit_price)
    if entry <= 0 or exit_px <= 0:
        raise ValueError("entry_price and exit_price must be > 0")
    ret = (exit_px / entry - 1.0) * _side_sign(side)
    gross = float(size) * ret
    net = apply_friction(
        gross, notional=float(size), fee_rate=fee_rate, slippage_bps=slippage_bps
    )
    return gross, net


def replay_fill_to_last_close(
    fill: Mapping[str, Any],
    bars: pd.DataFrame,
    *,
    fee_rate: float | None = None,
    slippage_bps: float | None = None,
    entry_price: float | None = None,
) -> ReplayMark:
    """Mark one paper fill to the last close of ``bars``."""
    d = normalize_ohlcv(bars)
    if d.empty:
        raise ValueError("replay: no bars")
    exit_px = float(d["close"].iloc[-1])
    raw_entry = entry_price
    if raw_entry is None:
        raw_entry = fill.get("price")
    try:
        entry = float(raw_entry or 0.0)
    except (TypeError, ValueError):
        entry = 0.0
    if entry <= 0:
        entry = float(d["close"].iloc[0])
    fee = float(fill.get("fee_rate") or 0.0) if fee_rate is None else float(fee_rate)
    slip = (
        float(fill.get("slippage_bps") or 0.0)
        if slippage_bps is None
        else float(slippage_bps)
    )
    size = float(fill.get("size") or 0.0)
    side = str(fill.get("side") or "buy")
    gross, net = mark_to_close_pnl(
        side=side,
        size=size,
        entry_price=entry,
        exit_price=exit_px,
        fee_rate=fee,
        slippage_bps=slip,
    )
    return ReplayMark(
        market=str(fill.get("market") or fill.get("instrument") or ""),
        side=side,
        size=size,
        entry_price=entry,
        exit_price=exit_px,
        gross_pnl=gross,
        net_pnl=net,
        fee_rate=fee,
        slippage_bps=slip,
    )


def replay_ledger(
    ledger: PaperLedger,
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    fee_rate: float | None = None,
    slippage_bps: float | None = None,
) -> list[ReplayMark]:
    """Replay every ledger fill that has injected bars. Skip missing symbols."""
    out: list[ReplayMark] = []
    for ev in ledger.list_fills():
        payload = dict(ev.payload)
        market = str(payload.get("market") or payload.get("instrument") or "").upper()
        bars = bars_by_symbol.get(market) or bars_by_symbol.get(
            str(payload.get("market") or "")
        )
        if bars is None:
            continue
        out.append(
            replay_fill_to_last_close(
                payload, bars, fee_rate=fee_rate, slippage_bps=slippage_bps
            )
        )
    return out
