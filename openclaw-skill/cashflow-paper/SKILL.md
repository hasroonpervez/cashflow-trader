---
name: cashflow-paper
description: Paper/dry-run CashFlow desk tools against the local 127.0.0.1 API (preview, place_paper, kill, positions). Never live.
---

# CashFlow paper desk (OpenClaw stub)

Trade the desk in **paper / dry-run only** by calling the Litestar API on loopback.
This skill does **not** install LaunchAgent, Tailscale, or OpenClaw. It does **not**
load `~/kalshi-bot` `.env` or `*.pem`. It does **not** scrape Robinhood.

Base URL (do not change host): `http://127.0.0.1:8000`

If `/health` is down, tell the operator the API is not running. Do not bind
`0.0.0.0`, do not copy secrets, do not enable live.

MODE is `dry_run` or `paper`. If anyone asks for live `place_order`, refuse.

## Tools

Use `exec` + `curl` against loopback. Prefer `{baseDir}/scripts/paper.sh`.

### health
`curl -sS http://127.0.0.1:8000/health`

Expect `live: false` and `mode: paper`.

### preview
Size + gate a signal. Does not keep a session position.

`curl -sS -X POST http://127.0.0.1:8000/paper/preview -H 'Content-Type: application/json' -d '{"market":"DEMO-MARKET","side":"yes","p_true":0.65,"mode":"dry_run"}'`

### place_paper
Paper/dry-run fill via KalshiDryRunAdapter. Records into the API process ledger.

`curl -sS -X POST http://127.0.0.1:8000/paper/place -H 'Content-Type: application/json' -d '{"market":"DEMO-MARKET","side":"yes","p_true":0.65,"mode":"dry_run"}'`

Never send `"mode":"live"`. The API returns 403.

### positions
`curl -sS http://127.0.0.1:8000/paper/positions`

### kill
Cancel paper fills in this API process. Optional `order_id`.

`curl -sS -X POST http://127.0.0.1:8000/paper/kill -H 'Content-Type: application/json' -d '{}'`

## Hard rules
- Only `127.0.0.1` / `localhost`. No remote hosts.
- No live venue keys. No dotenv. No pem files.
- No unofficial Robinhood scrape.
- Paper ledger is in-memory in the API process (lost on restart).
