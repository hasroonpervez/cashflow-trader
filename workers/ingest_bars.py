"""CLI: ingest OHLCV bars into a SQLite WAL snapshot.

Default path writes *provided* bars (JSON) and never touches the network.
Yahoo/yfinance runs only when ``--fetch`` is passed explicitly.

Examples
--------
    python -m workers.ingest_bars --db PATH --symbols AAPL --bars-json bars.json
    python -m workers.ingest_bars --db PATH --symbols AAPL --fetch
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from workers.store import connect, upsert_bars

# Yahoo fetch is imported only inside ``_bars_from_yahoo`` so the default
# (test) path cannot accidentally pull yfinance.


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m workers.ingest_bars",
        description="Write OHLCV bars into a SQLite WAL snapshot (no live orders).",
    )
    p.add_argument("--db", required=True, help="Path to snapshots SQLite file")
    p.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated symbols, e.g. AAPL or AAPL,MSFT",
    )
    p.add_argument(
        "--bars-json",
        default=None,
        help="JSON file of provided bars (list, or {SYMBOL: [bars...]}). No network.",
    )
    p.add_argument(
        "--fetch",
        action="store_true",
        default=False,
        help="Fetch daily bars from Yahoo via yfinance. Off by default.",
    )
    p.add_argument(
        "--source",
        default="provided",
        help="Source tag stored on provided bars (default: provided)",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def _parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in str(raw).split(",") if s.strip()]


def _load_bars_json(path: str, symbols: Sequence[str]) -> dict[str, list[Mapping[str, Any]]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, list[Mapping[str, Any]]] = {s: [] for s in symbols}
    if isinstance(payload, list):
        if len(symbols) == 1:
            out[symbols[0]] = payload
        else:
            for row in payload:
                if not isinstance(row, Mapping):
                    continue
                sym = str(row.get("symbol") or "").upper().strip()
                if sym in out:
                    out[sym].append(row)
        return out
    if isinstance(payload, dict):
        for key, rows in payload.items():
            sym = str(key).upper().strip()
            if sym in out and isinstance(rows, list):
                out[sym] = rows
        return out
    raise ValueError("--bars-json must be a list or object keyed by symbol")


def _bars_from_yahoo(symbol: str) -> list[dict[str, Any]]:
    """Optional network path. Only called when ``--fetch`` is set."""
    import yfinance as yf  # local import: default CLI path must not fetch

    ticker = yf.Ticker(symbol)
    df = ticker.history(period="1y", interval="1d", auto_adjust=True)
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        rows.append(
            {
                "ts": ts,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]) if "Volume" in row.index else 0.0,
                "source": "yahoo",
            }
        )
    return rows


def ingest_provided(
    db_path: str,
    symbol: str,
    bars: Sequence[Mapping[str, Any]],
    *,
    source: str = "provided",
) -> int:
    """Library entry used by tests: write provided bars with no network."""
    conn = connect(db_path, create=True)
    try:
        return upsert_bars(conn, bars, default_symbol=symbol, default_source=source)
    finally:
        conn.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = _parse_symbols(args.symbols)
    if not symbols:
        print("no symbols given", file=sys.stderr)
        return 2

    if args.fetch:
        conn = connect(args.db, create=True)
        try:
            written = 0
            for sym in symbols:
                rows = _bars_from_yahoo(sym)
                written += upsert_bars(conn, rows, default_symbol=sym, default_source="yahoo")
                print(f"{sym}: fetched {len(rows)} bars")
            print(f"wrote {written} rows to {args.db}")
        finally:
            conn.close()
        return 0

    if args.bars_json:
        grouped = _load_bars_json(args.bars_json, symbols)
        conn = connect(args.db, create=True)
        try:
            written = 0
            for sym in symbols:
                n = upsert_bars(
                    conn, grouped.get(sym, []), default_symbol=sym, default_source=args.source
                )
                written += n
                print(f"{sym}: wrote {n} provided bars")
            print(f"wrote {written} rows to {args.db}")
        finally:
            conn.close()
        return 0

    print(
        "no input bars: pass --bars-json PATH (tests / offline) or --fetch (Yahoo)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
