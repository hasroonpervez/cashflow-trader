# P0 — Multi-venue paper scaffold

**Status:** paper / dry-run only. Live venue orders are **not** implemented.

Default `MODE=paper`. `place_order` raises `PermissionError` unless mode is in `{paper, dry_run}`.

## Layout

| Path | Role |
|---|---|
| `signals/schema.py` | Unified `Signal` (+ aliases: instrument/market_id, p_model, source_node, edge) |
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

## Mode

Supported: `paper`, `dry_run`. Live enumerated for future dual-OK only.

Do not stage live API keys or `.env` / `*.pem` in this repo.
