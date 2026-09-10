"""Offline movers scanner + optional Pulse paper path.

No network. Inject bars via --bars-json or use --demo synthetic frames.

    python -m tools.scanner_dry_run --demo
    python -m tools.scanner_dry_run --bars-json path.json
    python -m tools.scanner_dry_run --demo --paper

``mode=live`` is not a flag here. Live place_order stays refused (API 403 /
adapter construction).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from execution.paper_ledger import PaperLedger
from execution.pulse import run_movers_paper, run_movers_scan
from signals.scanner import ScannerConfig, demo_universe, frames_from_payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m tools.scanner_dry_run",
        description="Paper/research movers scanner. Injected bars only — no Yahoo.",
    )
    p.add_argument(
        "--bars-json",
        default=None,
        help="JSON object {SYM: {bars, prior_close?, avg_volume?}} or {SYM: [bars]}",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Use built-in synthetic PLAY/DEAD/CHEAP frames (no network)",
    )
    p.add_argument(
        "--paper",
        action="store_true",
        help="Also run Sig_orb_rvol_vwap through the paper pipeline (Robinhood stub)",
    )
    p.add_argument("--bankroll", type=float, default=10_000.0)
    p.add_argument("--fee-rate", type=float, default=0.0)
    p.add_argument("--slippage-bps", type=float, default=0.0)
    p.add_argument("--min-gap-pct", type=float, default=3.0)
    p.add_argument("--min-rvol", type=float, default=2.0)
    p.add_argument("--min-price", type=float, default=5.0)
    p.add_argument("--min-dollar-volume", type=float, default=2_000_000.0)
    return p.parse_args(list(argv) if argv is not None else None)


def _load(args: argparse.Namespace):
    if args.demo:
        return demo_universe()
    if not args.bars_json:
        raise SystemExit("provide --demo or --bars-json")
    payload = json.loads(Path(args.bars_json).read_text(encoding="utf-8"))
    return frames_from_payload(payload)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    frames, hints = _load(args)
    cfg = ScannerConfig(
        min_gap_pct=args.min_gap_pct,
        min_rvol=args.min_rvol,
        min_price=args.min_price,
        min_dollar_volume=args.min_dollar_volume,
    )
    if args.paper:
        run = run_movers_paper(
            frames,
            PaperLedger(),
            args.bankroll,
            hints=hints,
            config=cfg,
            fee_rate=args.fee_rate,
            slippage_bps=args.slippage_bps,
        )
        payload: dict[str, Any] = run.to_dict()
        payload["sig"] = "Sig_orb_rvol_vwap"
        payload["mode"] = "paper"
    else:
        scored = run_movers_scan(frames, config=cfg, hints=hints)
        payload = {
            "candidates": [c.to_dict() for c in scored],
            "in_play": [c.symbol for c in scored if c.in_play],
            "sig": "Sig_orb_rvol_vwap",
            "paper_only": True,
            "live": False,
            "mode": "dry_run",
        }
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
