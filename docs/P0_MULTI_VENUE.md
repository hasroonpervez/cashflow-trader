# P0: Multi-venue paper scaffold

**Status:** paper / dry-run only. Live venue orders are **not** implemented.

Default `MODE=paper`. `place_order` raises `PermissionError` unless mode is in `{paper, dry_run}`.

## Layout

| Path | Role |
|---|---|
| `signals/schema.py` | Unified `Signal` (+ aliases: instrument/market_id, p_model, source_node, edge) |
| `signals/producers/` | Sig_* producers → `Signal` (equity wrappers + Kalshi event helper) |
| `risk/kelly.py` | Fractional / fee-aware Kelly |
| `risk/promotion_gate.py` | Annotates promote/hold (does **not** block paper fills) |
| `risk/portfolio_risk.py` | Advisory PortfolioRisk stub (haircut only) |
| `execution/paper_ledger.py` | Signals / orders / fills / **outcomes** (PnL stub) |
| `execution/pipeline.py` | Signal → gate annotate → Kelly → PortfolioRisk → venue → ledger |
| `venues/kalshi/adapter.py` | Deterministic dry-run fills |
| `venues/coinbase/adapter.py` | Paper stub; live refused |
| `venues/robinhood/adapter.py` | Paper/read stub; live refused |

## Gate vs paper fills

Promotion gate marks `promoted` true/false and may research-haircut size when held.
Paper fills **still record** so the outcome ledger can grow past min_n (no chicken-and-egg).

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
