"""Pulse paper path: movers scan → Sig_orb_rvol_vwap → risk annotate → ledger.

Paper / dry-run only. Uses RobinhoodReadAdapter by default (live refused).
Does not enable live place_order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from execution.paper_ledger import PaperLedger
from execution.pipeline import PaperPipelineResult, run_paper_pipeline
from signals.producers.equity import produce_orb_rvol_vwap
from signals.scanner import MoverCandidate, ScannerConfig, scan_universe
from signals.schema import Signal
from venues.base import VenueAdapter
from venues.robinhood.adapter import RobinhoodReadAdapter


@dataclass(frozen=True)
class PulsePaperRun:
    candidates: tuple[MoverCandidate, ...]
    signals: tuple[Signal, ...]
    results: tuple[PaperPipelineResult, ...]
    paper_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "signals": [s.to_ledger_dict() for s in self.signals],
            "results": [
                {
                    "accepted": r.accepted,
                    "promoted": r.promoted,
                    "stake": r.stake,
                    "fill": dict(r.fill) if r.fill else None,
                    "reasons": list(r.reasons),
                }
                for r in self.results
            ],
            "paper_only": self.paper_only,
            "live": False,
        }


def run_movers_scan(
    frames: Mapping[str, pd.DataFrame],
    *,
    config: ScannerConfig | None = None,
    hints: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[MoverCandidate]:
    return scan_universe(frames, config=config, hints=hints)


def produce_movers_signals(
    frames: Mapping[str, pd.DataFrame],
    *,
    config: ScannerConfig | None = None,
    hints: Mapping[str, Mapping[str, Any]] | None = None,
    p_true: float | None = None,
    edge: float | None = None,
) -> tuple[list[MoverCandidate], list[Signal]]:
    extra = hints or {}
    norm_frames = {str(k).upper().strip(): v for k, v in frames.items()}
    norm_hints = {str(k).upper().strip(): dict(v) for k, v in extra.items()}
    candidates = run_movers_scan(norm_frames, config=config, hints=norm_hints)
    signals: list[Signal] = []
    for cand in candidates:
        if not cand.in_play:
            continue
        hint = norm_hints.get(cand.symbol) or {}
        bars = norm_frames.get(cand.symbol)
        if bars is None:
            continue
        sig = produce_orb_rvol_vwap(
            bars,
            symbol=cand.symbol,
            p_true=p_true,
            edge=edge,
            prior_close=hint.get("prior_close"),
            avg_volume=hint.get("avg_volume"),
            scanner_config=config,
        )
        if sig is not None:
            signals.append(sig)
    return candidates, signals


def run_movers_paper(
    frames: Mapping[str, pd.DataFrame],
    ledger: PaperLedger,
    bankroll: float,
    *,
    adapter: VenueAdapter | None = None,
    gate_stats: Mapping[str, Any] | None = None,
    hints: Mapping[str, Mapping[str, Any]] | None = None,
    config: ScannerConfig | None = None,
    fee_rate: float = 0.0,
    slippage_bps: float = 0.0,
    odds_b: float = 1.0,
    kelly_fraction: float = 0.25,
    open_exposure: float = 0.0,
    p_true: float | None = None,
    edge: float | None = None,
) -> PulsePaperRun:
    """Scan → Sig_orb_rvol_vwap → annotate gates → paper fill. Never live."""
    venue = adapter or RobinhoodReadAdapter()
    candidates, signals = produce_movers_signals(
        frames, config=config, hints=hints, p_true=p_true, edge=edge
    )
    results: list[PaperPipelineResult] = []
    stats = dict(gate_stats or {"outcomes": []})
    for sig in signals:
        results.append(
            run_paper_pipeline(
                sig,
                stats,
                venue,
                ledger,
                bankroll,
                odds_b=odds_b,
                fee_rate=fee_rate,
                slippage_bps=slippage_bps,
                kelly_fraction=kelly_fraction,
                open_exposure=open_exposure,
            )
        )
    return PulsePaperRun(
        candidates=tuple(candidates),
        signals=tuple(signals),
        results=tuple(results),
    )
