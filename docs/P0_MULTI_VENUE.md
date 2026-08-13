# P0: Multi-venue paper scaffold

**Status:** paper / dry-run only. Live venue orders are **not** implemented.

Default `MODE=paper`. `place_order` raises `PermissionError` unless mode is in `{paper, dry_run}`.

## Layout

| Path | Role |
|---|---|
| `signals/schema.py` | Unified `Signal` (+ aliases: instrument/market_id, p_model, source_node, edge) |
| `signals/producers/` | Sig_* producers -> `Signal` (equity wrappers + Kalshi event helper) |
| `risk/kelly.py` | Fractional / fee-aware Kelly |
| `risk/sizing.py` | Thin paper Kelly adapter wrapping existing helpers |
| `risk/promotion_gate.py` | Annotates promote/hold (does **not** block paper fills) |
| `risk/stage2.py` | Annotate-only DSR/PBO overfitting hook (placeholders; does not block paper fills) |
| `risk/calib.py` | Thin ledger -> gate_stats read-back (settled pnls only) |
| `risk/edge.py` | Betting/edge annotate from settled PnL (mean + hit rate; fail closed on small n) |
| `risk/portfolio_risk.py` | Advisory PortfolioRisk stub (haircut only) |
| `execution/paper_ledger.py` | Signals / orders / fills / **outcomes** (PnL stub + settle); optional SQLite persist |
| `execution/pipeline.py` | Signal -> gate annotate -> stage2 annotate -> size_paper -> PortfolioRisk -> venue -> ledger |
| `venues/kalshi/adapter.py` | Deterministic dry-run fills |
| `venues/coinbase/adapter.py` | Paper stub; live refused |
| `venues/robinhood/adapter.py` | Paper/read stub; live refused |

## Gate vs paper fills

Promotion gate marks `promoted` true/false and may research-haircut size when held.
Paper fills **still record** so the outcome ledger can grow past min_n (no chicken-and-egg).

Stage-1 paper gate now also requires bootstrap 95% CI lo>0 (reuse
`modules.validated_signals.bootstrap_ci`). Hold remains annotate-only;
paper fills still record.

Stage-1 (`risk/promotion_gate.py`) annotates promote/hold from sample quality
(min_n, split-half, concentration, bootstrap CI). Stage-2 (`risk/stage2.py`) is
an annotate-only overfitting hook: `evaluate_stage2` returns placeholder DSR/PBO
plus reasons and never blocks paper fills. PBO stays None without a 2D
`returns_matrix` (N>=2) and that absence does not fail the hook. The 0.25
research haircut applies only to a stage-1 hold.

## Settlement -> calib

Settlement to calib is a thin ledger feedback hook, not Platt/Brier/ECE.
The paper pipeline writes an unsettled outcome stub (`pnl: None`);
`PaperLedger.settle_outcome` appends a settled row with numeric PnL, and
`risk.calib.gate_stats_from_ledger` reads those PnLs back as `gate_stats["outcomes"]`
for the next `run_paper_pipeline` call. `risk.edge.edge_from_stats` then annotates
realized mean PnL / hit rate vs the signal's model edge. Fail closed when n is
small. It does **not** change stake or block paper fills. Live path is unchanged.

The Phase B API seeds `gate_stats` from the SQLite paper ledger on
`/paper/preview` and `/paper/place` (`gate_stats_from_ledger`). Body knobs
(min_n, etc.) pass through; settled `outcomes` always come from the ledger
so calib/edge compound across API restart. Preview still uses a throwaway
in-memory ledger so it does not persist fills. `POST /paper/settle` writes
settled PnL onto that ledger (paper only) so OpenClaw can close place→settle→calib.

## Sizing

The paper pipeline sizes via `risk.sizing.size_paper`, a thin adapter that wraps
existing helpers (`risk.kelly.fractional_kelly` for Kalshi/default binary markets,
`modules.asymmetry.kelly_fraction_skewed` for Robinhood/Coinbase). It is not a
port of kalshi-bot `math_engine`. Gate hold still haircuts stake by 0.25; PortfolioRisk
runs after sizing.

## Sig_* producers

Producers emit unified paper `Signal` records that feed `run_paper_pipeline`
(`execution/pipeline.py`). They do **not** place live orders.

| Producer | Source node | Venue (paper) | Input |
|---|---|---|---|
| `produce_orb30` | `Sig_orb30` | `robinhood` | One session of 5m OHLCV (+ optional prior_close) via `modules.validated_signals.orb30_signal` |
| `produce_swing_pullback` | `Sig_swing_pullback` | `robinhood` | Daily OHLCV via `swing_pullback_signal` |
| `produce_kalshi_event` | `Sig_K.*` / caller `source_node` | `kalshi` | Supplied `p_true`, `market_price`, `market_id`: **no network, no secrets** |

Equity producers return `None` when the validated rule does not fire (or ORB
gap-skips). Kalshi helper always builds a `Signal` and sets `edge` from
`p_true` vs `market_price`. Pass the resulting `Signal` into
`run_paper_pipeline(...)` with the matching paper adapter
(`RobinhoodReadAdapter` / `KalshiDryRunAdapter`) and a `PaperLedger`.

Pattern features (paper annotate only) live in `signals/producers/patterns.py`:
equity producers attach `metadata["patterns"]` from OHLCV (`inside_bar`,
`range_compression`, `hh_count`/`hl_count`, `close_location`); Kalshi attaches
book-shape tags (`price_extreme`, `edge_sign`, crowded yes/no). These are
`unvalidated` and must not size live.

## Mode

Supported: `paper`, `dry_run`. Live enumerated for future dual-OK only.

Do not stage live API keys or `.env` / `*.pem` in this repo.

## Paper ledger persist

`PaperLedger()` stays in-memory (tests). `PaperLedger(db_path=..., persist=True)` writes
SQLite WAL at `data/paper_ledger.sqlite` (or `CASHFLOW_PAPER_LEDGER_DB`). The Phase B
API uses the SQLite ledger so positions/calib/edge survive process restart. Paper only.
