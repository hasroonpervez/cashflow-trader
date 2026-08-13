# Phase B: Litestar snapshot API + thin Svelte desk (repo only)

**Status:** local API + desk scaffold. Paper / dry-run only. No live orders.

Streamlit `app.py` is unchanged. Phase A SQLite snapshots stay the daily-bar
source. This PR adds a **read-only** Litestar API in front of those snapshots
and a thin SvelteKit page that does **not** fetch market data on click.

LaunchAgent, Tailscale, OpenClaw, Cloudflare, and secrets are **not** in this PR.


## Layout

| Path | Role |
|---|---|
| `api/app.py` | Litestar app: health, bars, snapshot, paper preview/place |
| `web/` | SvelteKit 5 desk: symbol input then GET /api/bars/{symbol} |
| `workers/store.py` | SQLite WAL (Phase A) |
| `modules/snapshot_bars.py` | try_snapshot_bars / has_snapshot (no live fetch in API) |

## Hard rules

- API request handlers must not call Yahoo, yfinance, or Alpha Vantage.
  Missing snapshot returns **404 JSON**, not a live fetch.
- POST /paper/* is paper/dry-run only. mode=live returns **403**.
  KalshiDryRunAdapter still refuses LIVE construction; place_order live
  still raises PermissionError.
- Bind **127.0.0.1** only. Do not expose 0.0.0.0 from this PR.


## Run locally

Use requirements-web.txt for the API extra (not the Cloud file).
Pandas comes from the existing app requirements.

Seed snapshots with workers.ingest_bars using --bars-json (default path, not --fetch).
Reuse data/snapshots.sqlite from Phase A, or set CASHFLOW_SNAPSHOTS_DB.

Start the API on loopback 127.0.0.1 port 8000 with Granian (ASGI) targeting api.app:app, or python -m api.app. Do not bind 0.0.0.0.

Start the desk from the web directory. Vite proxies /api to the loopback API on port 8000. The dev server listens on 127.0.0.1:5173.

Open that URL, enter a symbol, load bars. The page only calls /api/bars/{SYMBOL}. Missing snapshot is an API 404; the desk shows that error and does not call an external market API.

The API works standalone. The web tree is a scaffold committed without node_modules. A JS toolchain is required before the desk runs.

## Endpoints

Handlers are mounted at the root and under /api so the desk can fetch /api/bars/AAPL.

- GET /health — status ok, mode paper, live false
- GET /bars/{symbol} — latest snapshot bars; query n default 252; 404 if missing
- GET /snapshot/{symbol} — {symbol, exists}
- POST /paper/preview — wraps run_paper_pipeline + KalshiDryRunAdapter
- POST /paper/place — same pipeline; dry-run fill; mode live returns 403
- GET /paper/positions — paper fills from SQLite ledger (survive API restart)
- POST /paper/kill — cancel those paper fills (persisted); mode live returns 403

Paper JSON body (minimal): market, side, p_true, optional source, bankroll, edge, id, gate_stats, odds_b, fee_rate, kelly_fraction, open_exposure, mode (dry_run or paper only).

## Tests

API tests live in tests/test_phase_b_api.py. They use a tempfile SQLite via create_app(db_path=...) and patch external fetch helpers so a handler cannot silently hit the network. Install requirements-dev.txt then run pytest.

## Out of scope (not this PR)

- LaunchAgent plists, Tailscale, Cloudflare Tunnel, copying the skill onto the box
- Live venue keys, dotenv files, pem files
- Replacing Streamlit; app.py stays
- Postgres / Valkey (still SQLite snapshots from Phase A; paper ledger is SQLite too)
