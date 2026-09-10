# P0: Multi-venue paper scaffold

**Status:** paper / dry-run only. Live venue orders are **not** implemented.

Default `MODE=paper`. `place_order` raises `PermissionError` unless mode is in `{paper, dry_run}`.

## Layout

| Path | Role |
|---|---|
| `signals/schema.py` | Unified `Signal` (+ aliases: instrument/market_id, p_model, source_node, edge) |
| `signals/producers/` | Sig_* producers -> `Signal` (equity wrappers + Kalshi event helper) |
| `signals/scanner.py` | Paper/research movers universe (gap% / RVOL / $vol / price floor). Offline bars only. |
| `risk/kelly.py` | Fractional / fee-aware Kelly |
| `risk/sizing.py` | Thin paper Kelly adapter wrapping existing helpers |
| `risk/promotion_gate.py` | Annotates promote/hold (does **not** block paper fills) |
| `risk/stage2.py` | Annotate-only DSR/PBO overfitting hook (placeholders; does not block paper fills) |
| `risk/cpcv.py` | Annotate-only CPCV / deflated-Sharpe **stub** (no Bailey DSR; does not block fills) |
| `risk/calib.py` | Thin ledger -> gate_stats read-back (settled pnls only) |
| `risk/edge.py` | Betting/edge annotate from settled PnL (mean + hit rate; fail closed on small n) |
| `risk/portfolio_risk.py` | Advisory PortfolioRisk stub (haircut only) |
| `execution/paper_ledger.py` | Signals / orders / fills / **outcomes** (PnL stub + settle); optional SQLite persist |
| `execution/pipeline.py` | Signal -> gate annotate -> stage2 annotate -> CPCV stub -> size_paper -> PortfolioRisk -> venue -> ledger |
| `execution/friction.py` | `fee_rate` + `slippage_bps` fields; `apply_friction` for replay haircuts |
| `execution/replay.py` | Mark paper fills to last injected close (no network) |
| `execution/pulse.py` | Movers scan → `Sig_orb_rvol_vwap` → paper pipeline (Robinhood stub) |
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
A second settle on the same order_id with the same pnl is idempotent; a different pnl returns 409.
`GET /paper/outcomes` reads those settled PnLs so OpenClaw can see calib n without a dummy preview.

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
| `produce_orb_rvol_vwap` | `Sig_orb_rvol_vwap` | `robinhood` | Movers universe + ORB break + RVOL + last close above session VWAP. **Unvalidated** paper research. |
| `produce_swing_pullback` | `Sig_swing_pullback` | `robinhood` | Daily OHLCV via `swing_pullback_signal` |
| `produce_kalshi_event` | `Sig_K.*` / caller `source_node` | `kalshi` | Supplied `p_true`, `market_price`, `market_id`: **no network, no secrets** |

Equity producers return `None` when the validated rule does not fire (or ORB
gap-skips). Kalshi helper always builds a `Signal` and sets `edge` from
`p_true` vs `market_price`. Pass the resulting `Signal` into
`run_paper_pipeline(...)` with the matching paper adapter
(`RobinhoodReadAdapter` / `KalshiDryRunAdapter`) and a `PaperLedger`.

Pattern features (paper annotate only) live in `signals/producers/patterns.py`
for the **existing** `Sig_orb30` / `Sig_swing_pullback` / Kalshi helpers only.
`Sig_orb_rvol_vwap` does **not** attach pattern tags or named setups.

## Pulse movers scanner (paper)

**Scope of this layer:** movers universe filter + one Sig (`Sig_orb_rvol_vwap`).
No pattern library, no named-setup catalog, no nightly overfit job, no live
rails. A pattern library and settle→calib→edge learn loop are the **next**
paper layer, after the ledger has n>0.

**Roadmap (not this PR):** equity **day-trade** is the daily cashflow core.
Swing and options are later books on the same Pulse ledger/spine. Crypto is
later still. This first slice stays equity movers scanner + ORB/RVOL/VWAP
only — no swing, options, or crypto code here.

Universe filter for stocks-in-play that can print a large session range
(~20% class). The first Pulse Sig (`Sig_orb_rvol_vwap`) aims to capture a
**slice** of that move (ORB continuation still above VWAP), not the full 20%.

Pure functions in `signals/scanner.py`. **Inject bars** — do not scrape Yahoo
inside API request handlers.

Default floors (override via `ScannerConfig` or CLI flags):

| Filter | Default | Role |
|---|---|---|
| `min_gap_pct` | 3.0 | Absolute open-vs-prior-close gap |
| `min_rvol` | 2.0 | Session volume vs prior-session average (time-adjusted to 390m) |
| `min_price` | 5.0 | Last close floor |
| `min_dollar_volume` | 2_000_000 | Last close × session volume |

`score_symbol(symbol, bars, prior_close=..., avg_volume=...)` works offline
with one session plus hints, or a multi-session frame (prior sessions supply
prior close and average volume). `scan_universe` ranks `in_play` names.

`produce_orb_rvol_vwap` returns `None` unless: scanner `in_play`, ORB-30
break (gap-skip **off** — gappers *are* the universe), and last close **above**
session VWAP. Wire-up: `execution.pulse.run_movers_paper` → risk annotate
(gate / stage2 / edge / CPCV stub) → `RobinhoodReadAdapter` → `PaperLedger`.
Gates stay **annotate-only**; small-n holds do not block paper fills.
`mode=live` remains **403** on `/paper/*`. Live `place_order` is not enabled.

### Scanner dry-run (no network)

```bash
# Synthetic PLAY (in-play + Sig) / DEAD / CHEAP — no Yahoo
python -m tools.scanner_dry_run --demo

# Injected bars (JSON). Shapes:
#   {"PLAY": {"prior_close": 100, "avg_volume": 1e6, "bars": [{"ts": "...", "open": ...}]}}
#   {"PLAY": [{"ts": "...", "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]}
python -m tools.scanner_dry_run --bars-json path/to/bars.json

# Same, then paper pipeline (Robinhood stub, in-memory ledger)
python -m tools.scanner_dry_run --demo --paper --fee-rate 0.001 --slippage-bps 5
```

Fee/slippage are recorded on paper fills. `execution.replay.replay_fill_to_last_close`
marks a fill to the last injected close and applies those haircuts. CPCV /
deflated Sharpe is a **stub** (`risk/cpcv.py`) — annotate-only, not a live gate,
and not a nightly research loop.

## Mode

Supported: `paper`, `dry_run`. Live enumerated for future dual-OK only.

Do not stage live API keys or `.env` / `*.pem` in this repo.

## Paper ledger persist

`PaperLedger()` stays in-memory (tests). `PaperLedger(db_path=..., persist=True)` writes
SQLite WAL at `data/paper_ledger.sqlite` (or `CASHFLOW_PAPER_LEDGER_DB`). The Phase B
API uses the SQLite ledger so positions/calib/edge survive process restart. Paper only.
