# P0: Multi-venue paper scaffold

**Status:** paper / dry-run only. No live orders. No venue credentials.

## What landed

| Path | Role |
|---|---|
| `signals/schema.py` | Shared `Signal` dataclass |
| `risk/kelly.py` | Fee-aware fractional Kelly (binary contracts) |
| `risk/promotion_gate.py` | min-n + split-half + concentration → promote/hold |
| `venues/base.py` | `VenueAdapter`; `place_order` refuses unless mode ∈ {paper, dry_run} |
| `venues/kalshi/adapter.py` | Deterministic dry-run fills; **no network** |
| `execution/paper_ledger.py` | SQLite/in-memory paper signals/orders/fills (UTC) |
| `execution/pipeline.py` | Signal → gate → Kelly → Kalshi dry-run → ledger |

## Persistence choice (no Alembic paper migration)

`db/` Alembic migrations already model **Postgres partitioned market-data**
tables (`bars_daily`, `options_snapshot`, …). Coupling paper accounting into
that chain would force Postgres + partition DDL for a unit-testable stub.

P0 therefore uses **`execution/paper_ledger.PaperLedger`**:

- default `:memory:` SQLite for tests
- optional on-disk SQLite path for local paper runs
- UTC timestamps (`…Z`)

A future P1 can add a dedicated Alembic revision for paper tables once the
write-path schema is settled — without blocking this scaffold.

## Safety

- `VenueAdapter.place_order` raises if `mode` is not `paper` / `dry_run`.
- `KalshiDryRunAdapter` refuses construction with `mode="live"`.
- Streamlit `app.py` is untouched.
- No secrets, PEM keys, or env files are read.

## Quick exercise

```python
from execution.pipeline import PaperPipeline
from signals.schema import Signal

pipe = PaperPipeline(skip_gate=True, bankroll=10_000)
sig = Signal(
    signal_id="demo-1",
    strategy="demo",
    market_id="KX-DEMO",
    venue="kalshi",
    side="yes",
    p_true=0.65,
    market_price=0.45,
)
print(pipe.run(sig))
```

## Tests

```bash
python3 -m pytest tests/test_kelly.py tests/test_promotion_gate.py \
  tests/test_paper_ledger.py tests/test_kalshi_dry_run.py \
  tests/test_paper_pipeline.py -q
```
