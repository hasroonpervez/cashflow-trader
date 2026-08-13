# Phase A: SQLite ingest snapshots

**Status:** ingest + read helper only. Paper / dry-run path is unchanged. No live orders.

Clicking a ticker in Streamlit used to hit Yahoo on every cold cache. Phase A
decouples the **daily** path: a worker writes OHLCV bars into a local SQLite WAL
file, and the read helper returns the snapshot when present. Daily `fetch_stock`
and the pages.py boot path skip Yahoo when a snapshot exists. Other tabs (desk
tape bundle, options, news, earnings, weekly/intraday) may still network. If
the DB is missing or empty (Streamlit Cloud, fresh clone), the existing Yahoo /
Alpha Vantage fetch runs. The fallback **must not hard-fail**.

## Layout

| Path | Role |
|---|---|
| `workers/ingest_bars.py` | CLI: write provided bars (default) or `--fetch` Yahoo |
| `workers/store.py` | WAL connect, upsert, `latest_bars`, `has_snapshot` |
| `modules/snapshot_bars.py` | `load_bars(symbol)` / `try_snapshot_bars` |
| `modules/data.py` `fetch_stock` | Daily bars prefer snapshot, else Yahoo |
| `modules/pages.py` `boot_daily_ohlcv` / `build_context` | Boot/click daily OHLCV prefers snapshot over Yahoo panel |
| `data/snapshots.sqlite*` | Local WAL DB (gitignored) |

## Schema

```sql
CREATE TABLE bars (
    symbol TEXT NOT NULL,
    ts     TEXT NOT NULL,
    open   REAL,
    high   REAL,
    low    REAL,
    close  REAL,
    volume REAL,
    source TEXT,
    PRIMARY KEY (symbol, ts)
);
```

Journal mode is `WAL`. `ts` is ISO date (`YYYY-MM-DD`) for daily bars.

## CLI

Offline / tests (no network):

```bash
python -m workers.ingest_bars --db data/snapshots.sqlite --symbols AAPL --bars-json bars.json
```

`--bars-json` is a list of `{ts,open,high,low,close,volume}` or an object keyed
by symbol. Tests can also call `workers.ingest_bars.ingest_provided`.

Yahoo (explicit only):

```bash
python -m workers.ingest_bars --db data/snapshots.sqlite --symbols AAPL --fetch
```

`--fetch` is **off** by default. The test path never fetches.

Override the default DB with `--db` or `CASHFLOW_SNAPSHOTS_DB`.

## Read path

`modules.snapshot_bars.load_bars(symbol)`:

1. If `data/snapshots.sqlite` exists and has rows for `symbol`, return them
   (Open/High/Low/Close/Volume, tz-naive index, `attrs["source"]="snapshot"`).
2. Else call existing `fetch_stock` (Yahoo, then Alpha Vantage).

`fetch_stock(..., interval="1d")` and pages.py `boot_daily_ohlcv` /
`build_context` use the same snapshot check so the Streamlit daily boot/click
path does not fetch Yahoo when a snapshot is present. The desk tape
(`fetch_global_market_bundle`), weekly/intraday, options, news, and earnings
may still network.

A missing file, empty table, or read error → `None` / fallback. Never raises
into the UI.

## Out of scope (not Phase A)

- SvelteKit / Litestar rewrite (Phase B)
- LaunchAgent, OpenClaw, Tailscale, live orders, secrets / `.env` / `*.pem`
