#!/bin/sh
# Paper/dry-run helper for the local CashFlow API. Loopback only.
set -e
BASE="${CASHFLOW_API_BASE:-http://127.0.0.1:8000}"
case "$BASE" in
  http://127.0.0.1:*|http://localhost:*) ;;
  *) echo "refusing non-loopback CASHFLOW_API_BASE=$BASE" >&2; exit 2 ;;
esac
cmd="${1:-}"
shift || true
DEMO='{"market":"DEMO-MARKET","side":"yes","p_true":0.65,"mode":"dry_run"}'
case "$cmd" in
  health) curl -sS "$BASE/health" ;;
  preview) curl -sS -X POST "$BASE/paper/preview" -H 'Content-Type: application/json' -d "${1:-$DEMO}" ;;
  place_paper|place) curl -sS -X POST "$BASE/paper/place" -H 'Content-Type: application/json' -d "${1:-$DEMO}" ;;
  positions) curl -sS "$BASE/paper/positions" ;;
  kill) curl -sS -X POST "$BASE/paper/kill" -H 'Content-Type: application/json' -d "${1:-{}}" ;;
  *) echo "usage: paper.sh health|preview|place_paper|positions|kill [json]" >&2; exit 1 ;;
esac
echo
