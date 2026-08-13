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
| `risk/stage2.py` | Stage-2 DSR / PBO overfitting stats (annotate-only) |
| `risk/portfolio_risk.py` | Advisory PortfolioRisk stub (haircut only) |
| `execution/paper_ledger.py` | Signals / orders / fills / **outcomes** (PnL stub) |
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

Stage-1 (`risk/promotion_gate.py`) is sample-quality: min_n, split-half, concentration,
bootstrap CI. Stage-2 (`risk/stage2.py`) is the overfitting hook: stats lifted from
kalshi-bot/backtest.py (Bailey / Lopez de Prado) for deflated Sharpe (DSR) and optional
CSCV PBO when a 2D `returns_matrix` is supplied. `run_paper_pipeline` calls
`evaluate_stage2` after the promotion gate and appends `stage2:` reasons. Stage-2 is
annotate-only: it never blocks paper fills, and the 0.25 research haircut applies only
to a stage-1 hold. Missing PBO (no matrix) does not fail the hook; DSR still applies
once n is sufficient.

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

## Mode

Supported: `paper`, `dry_run`. Live enumerated for future dual-OK only.

Do not stage live API keys or `.env` / `*.pem` in this repo.
