# P0 — Multi-venue paper scaffold

**Status:** paper / dry-run only. Live venue orders are **not** implemented.

Default `MODE=paper`. `place_order` refuses unless mode is in `{paper, dry_run}`.

## Layout

| Path | Role |
|---|---|
| `signals/schema.py` | Unified `Signal` record |
| `risk/kelly.py` | `fractional_kelly(p, b, fraction=0.25, fee_rate=0.0)` |
| `risk/promotion_gate.py` | `PromotionGateResult` + `check` (min_n / split-half / concentration) |
| `execution/paper_ledger.py` | In-memory `PaperLedger` |
| `execution/pipeline.py` | `run_paper_pipeline(signal, gate_stats, adapter, ledger, bankroll)` |
| `venues/base.py` | `VenueAdapter` ABC; live placement refused |
| `venues/kalshi/adapter.py` | Deterministic dry-run fills from signal id hash (no network) |

## Mode

Supported execution modes: `paper` and `dry_run`. Live is enumerated for future dual-OK enablement but is not implemented and cannot place orders.

Do not stage live API keys or `.env` / `*.pem` secrets in this repo.

## Next (not P0)

- Persist paper fills via Alembic / outcome ledger
- Wire desk signals into the pipeline
- Additional venue adapters (stubs later; live needs dual OK)
