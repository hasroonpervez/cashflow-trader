"""Litestar snapshot API + paper/dry-run tools.

Reads SQLite WAL bars via ``workers.store`` / ``modules.snapshot_bars``.
Handlers never call Yahoo / yfinance. Missing snapshot → 404 JSON.

Bind locally to 127.0.0.1 (see docs/PHASE_B_DESK.md). This module does not
open ports; the ASGI server does.

    granian --interface asgi --host 127.0.0.1 --port 8000 api.app:app
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Union

from litestar import Litestar, get, post
from litestar.config.cors import CORSConfig
from litestar.datastructures import State
from litestar.exceptions import HTTPException, NotFoundException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_409_CONFLICT

from modules.snapshot_bars import has_snapshot as helper_has_snapshot
from modules.snapshot_bars import try_snapshot_bars
BIND_HOST = "127.0.0.1"
BIND_PORT = 8000

PathLike = Union[str, Path]


def _json_num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ts_iso(ts: Any) -> str:
    if hasattr(ts, "strftime"):
        hour = int(getattr(ts, "hour", 0) or 0)
        minute = int(getattr(ts, "minute", 0) or 0)
        second = int(getattr(ts, "second", 0) or 0)
        if hour or minute or second:
            return ts.strftime("%Y-%m-%dT%H:%M:%S")
        return ts.strftime("%Y-%m-%d")
    s = str(ts).strip().replace(" ", "T")
    return s[:19] if "T" in s else s[:10]


def _db_path(state: State) -> Optional[PathLike]:
    path = getattr(state, "db_path", None)
    if path:
        return path
    return None


def _bars_json(symbol: str, df, n: int) -> dict[str, Any]:
    bars: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        bars.append(
            {
                "ts": _ts_iso(ts),
                "open": _json_num(row.get("Open")),
                "high": _json_num(row.get("High")),
                "low": _json_num(row.get("Low")),
                "close": _json_num(row.get("Close")),
                "volume": _json_num(row.get("Volume")),
            }
        )
    return {
        "symbol": str(symbol).upper().strip(),
        "source": str(df.attrs.get("source") or "snapshot"),
        "count": len(bars),
        "n": int(n),
        "bars": bars,
    }


def _public(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj) and not isinstance(obj, type):
        raw = asdict(obj)
        return {k: list(v) if isinstance(v, tuple) else v for k, v in raw.items()}
    return {
        "ok": bool(getattr(obj, "ok", False)),
        "reasons": list(getattr(obj, "reasons", ()) or ()),
    }


def _refuse_live(payload: Mapping[str, Any] | None) -> None:
    mode = str((payload or {}).get("mode") or "dry_run").strip().lower().replace("-", "_")
    if mode == "live":
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="live place_order is refused; paper/dry-run only",
        )


def _signal_from_body(body: Mapping[str, Any]):
    from signals.schema import Signal

    market = str(body.get("market") or body.get("instrument") or "").strip()
    side = str(body.get("side") or "").strip()
    if not market or not side:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="market and side are required",
        )
    try:
        p_true = float(body.get("p_true", body.get("p_model", 0.55)))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="p_true must be a number"
        ) from exc
    kwargs: dict[str, Any] = {
        "venue": str(body.get("venue") or "kalshi"),
        "market": market,
        "side": side,
        "p_true": p_true,
        "source": str(body.get("source") or body.get("source_node") or "api.paper"),
        "edge": body.get("edge"),
    }
    if body.get("id"):
        kwargs["id"] = str(body["id"])
    try:
        return Signal(**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _pipeline_kwargs(body: Mapping[str, Any]) -> dict[str, Any]:
    def _f(key: str, default: float) -> float:
        try:
            return float(body.get(key, default))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST, detail=f"{key} must be a number"
            ) from exc

    gate_stats = body.get("gate_stats")
    if gate_stats is None:
        gate_stats = {}
    if not isinstance(gate_stats, Mapping):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="gate_stats must be an object"
        )
    return {
        "gate_stats": dict(gate_stats),
        "bankroll": _f("bankroll", 1000.0),
        "odds_b": _f("odds_b", 1.0),
        "fee_rate": _f("fee_rate", 0.0),
        "kelly_fraction": _f("kelly_fraction", 0.25),
        "open_exposure": _f("open_exposure", 0.0),
    }


def _seeded_pipeline_kwargs(body: Mapping[str, Any], ledger) -> dict[str, Any]:
    """Body knobs pass through; settled ledger outcomes always win."""
    from risk.calib import gate_stats_from_ledger

    kw = _pipeline_kwargs(body)
    extra = dict(kw["gate_stats"])
    extra.pop("outcomes", None)
    kw["gate_stats"] = gate_stats_from_ledger(ledger, **extra)
    return kw


def _result_json(result, *, preview: bool) -> dict[str, Any]:
    fill = dict(result.fill) if result.fill else None
    return {
        "accepted": bool(result.accepted),
        "promoted": bool(result.promoted),
        "stake": float(result.stake),
        "fill": fill,
        "reasons": list(result.reasons),
        "decision": _public(result.decision),
        "stage2": _public(result.stage2),
        "edge": _public(getattr(result, "edge", None)),
        "portfolio_risk": _public(result.portfolio_risk),
        "mode": "dry_run",
        "preview": bool(preview),
        "live": False,
    }


async def _health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "paper",
        "bind": f"{BIND_HOST}:{BIND_PORT}",
        "live": False,
    }


async def _get_bars(symbol: str, state: State, n: int = 252) -> dict[str, Any]:
    """Latest snapshot bars. 404 JSON if missing — never fetches Yahoo."""
    sym = str(symbol).upper().strip()
    if not sym:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="symbol required")
    limit = max(int(n), 1)
    df = try_snapshot_bars(sym, n=limit, db_path=_db_path(state))
    if df is None:
        raise NotFoundException(detail=f"snapshot not found for {sym}")
    return _bars_json(sym, df, limit)


async def _snapshot_exists(symbol: str, state: State) -> dict[str, Any]:
    """Whether a SQLite snapshot exists for ``symbol`` (no network)."""
    sym = str(symbol).upper().strip()
    if not sym:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="symbol required")
    exists = helper_has_snapshot(sym, db_path=_db_path(state))
    return {"symbol": sym, "exists": bool(exists)}


async def _paper_preview(data: dict[str, Any] | None, state: State) -> dict[str, Any]:
    """Size + gate a paper signal. No venue call, no network.

    Seeds gate_stats from the SQLite paper ledger (annotate only). Uses a
    throwaway in-memory ledger so preview never persists a fill.
    """
    body = data or {}
    _refuse_live(body)
    from execution.paper_ledger import PaperLedger
    from execution.pipeline import run_paper_pipeline
    from venues.kalshi.adapter import KalshiDryRunAdapter

    signal = _signal_from_body(body)
    kw = _seeded_pipeline_kwargs(body, _session_ledger(state))
    # Dry-run adapter: deterministic fake fill, no network. Preview still wraps
    # the existing pipeline so sizing/gate/stage2 stay in one place.
    result = run_paper_pipeline(
        signal,
        kw["gate_stats"],
        KalshiDryRunAdapter(),
        PaperLedger(),
        kw["bankroll"],
        odds_b=kw["odds_b"],
        fee_rate=kw["fee_rate"],
        kelly_fraction=kw["kelly_fraction"],
        open_exposure=kw["open_exposure"],
    )
    payload = _result_json(result, preview=True)
    payload["signal_id"] = signal.id
    return payload


def _session_ledger(state: State):
    """Paper ledger: SQLite if ledger_path/env set, else memory."""
    from execution.paper_ledger import PaperLedger

    led = getattr(state, "paper_ledger", None)
    if led is None:
        path = getattr(state, "ledger_path", None)
        led = PaperLedger(db_path=path, persist=True) if path else PaperLedger()
        state.paper_ledger = led
    return led


def _killed_ids(state: State) -> list[str]:
    return list(_session_ledger(state).killed_order_ids())


def _fill_order_id(payload: Mapping[str, Any]) -> str:
    return str(payload.get("order_id") or payload.get("id") or "").strip()


async def _paper_place(data: dict[str, Any] | None, state: State) -> dict[str, Any]:
    """Paper/dry-run place via run_paper_pipeline + KalshiDryRunAdapter."""
    body = data or {}
    _refuse_live(body)
    from execution.pipeline import run_paper_pipeline
    from venues.base import Mode
    from venues.kalshi.adapter import KalshiDryRunAdapter

    signal = _signal_from_body(body)
    kw = _seeded_pipeline_kwargs(body, _session_ledger(state))
    mode_raw = str(body.get("mode") or "dry_run").strip().lower().replace("-", "_")
    mode = Mode.PAPER if mode_raw == "paper" else Mode.DRY_RUN
    adapter = KalshiDryRunAdapter(mode=mode)
    result = run_paper_pipeline(
        signal,
        kw["gate_stats"],
        adapter,
        _session_ledger(state),
        kw["bankroll"],
        odds_b=kw["odds_b"],
        fee_rate=kw["fee_rate"],
        kelly_fraction=kw["kelly_fraction"],
        open_exposure=kw["open_exposure"],
    )
    payload = _result_json(result, preview=False)
    payload["signal_id"] = signal.id
    payload["mode"] = adapter.mode.value
    return payload



async def _paper_outcomes(state: State) -> dict[str, Any]:
    """Settled paper PnL from the SQLite ledger. Read-only. Never live."""
    from risk.calib import outcomes_from_ledger

    ledger = _session_ledger(state)
    rows: list[dict[str, Any]] = []
    for ev in ledger.list_outcomes():
        payload = dict(ev.payload)
        if not payload.get("settled"):
            continue
        pnl = payload.get("pnl")
        if pnl is None:
            continue
        rows.append(
            {
                "order_id": payload.get("order_id"),
                "signal_id": payload.get("signal_id"),
                "pnl": float(pnl),
                "settled": True,
            }
        )
    pnls = outcomes_from_ledger(ledger)
    return {
        "outcomes": rows,
        "pnls": pnls,
        "count": len(pnls),
        "mode": "paper",
        "live": False,
    }


async def _paper_positions(state: State) -> dict[str, Any]:
    """Open paper fills in this API process. Never hits a live venue."""
    killed = set(_killed_ids(state))
    positions: list[dict[str, Any]] = []
    for ev in _session_ledger(state).list_fills():
        payload = dict(ev.payload)
        oid = _fill_order_id(payload)
        if oid and oid in killed:
            continue
        positions.append(payload)
    return {
        "positions": positions,
        "count": len(positions),
        "mode": "paper",
        "live": False,
    }


async def _paper_kill(data: dict[str, Any] | None, state: State) -> dict[str, Any]:
    """Cancel paper fills in this API process. mode=live → 403. No venue call."""
    body = data or {}
    _refuse_live(body)
    target = str(body.get("order_id") or body.get("id") or "").strip()
    killed = set(_killed_ids(state))
    cancelled: list[str] = []
    ledger = _session_ledger(state)
    for ev in ledger.list_fills():
        oid = _fill_order_id(dict(ev.payload))
        if not oid or oid in killed:
            continue
        if target and oid != target:
            continue
        ledger.record_kill(oid)
        killed.add(oid)
        cancelled.append(oid)
    return {
        "ok": True,
        "cancelled": cancelled,
        "count": len(cancelled),
        "mode": "paper",
        "live": False,
    }



def _event_keys(payload: Mapping[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("order_id", "id", "signal_id", "fill_id"):
        val = str(payload.get(field) or "").strip()
        if val:
            keys.add(val)
    return keys


def _settled_outcome(ledger, target: str):
    """Last settled outcome matching target, or None."""
    last = None
    for ev in ledger.list_outcomes():
        payload = dict(ev.payload)
        if not payload.get("settled"):
            continue
        if target in _event_keys(payload):
            last = ev
    return last


async def _paper_settle(data: dict[str, Any] | None, state: State) -> dict[str, Any]:
    """Record settled paper PnL on the SQLite ledger. mode=live → 403."""
    body = data or {}
    _refuse_live(body)
    target = str(
        body.get("order_id") or body.get("id") or body.get("signal_id") or ""
    ).strip()
    if not target:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="order_id is required"
        )
    if "pnl" not in body:
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="pnl is required")
    try:
        pnl = float(body["pnl"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST, detail="pnl must be a number"
        ) from exc
    ledger = _session_ledger(state)
    keys: set[str] = set()
    for ev in list(ledger.list_fills()) + list(ledger.list_outcomes()):
        keys |= _event_keys(dict(ev.payload))
    if target not in keys:
        raise NotFoundException(detail=f"paper fill not found for {target}")
    existing = _settled_outcome(ledger, target)
    if existing is not None:
        prev = float(existing.payload["pnl"])
        if prev == pnl:
            return {
                "ok": True,
                "settled": True,
                "idempotent": True,
                "order_id": target,
                "signal_id": existing.payload.get("signal_id"),
                "pnl": prev,
                "payload": dict(existing.payload),
                "mode": "paper",
                "live": False,
            }
        raise HTTPException(
            status_code=HTTP_409_CONFLICT,
            detail=f"already settled ({prev}); will not append a second outcome",
        )
    from risk.calib import apply_settlement

    ev = apply_settlement(ledger, target, pnl)
    return {
        "ok": True,
        "settled": True,
        "idempotent": False,
        "order_id": target,
        "signal_id": ev.payload.get("signal_id"),
        "pnl": float(ev.payload["pnl"]),
        "payload": dict(ev.payload),
        "mode": "paper",
        "live": False,
    }


def create_app(db_path: Optional[PathLike] = None, ledger_path: Optional[PathLike] = None) -> Litestar:
    """Build the Litestar app. ``db_path`` overrides CASHFLOW_SNAPSHOTS_DB."""
    from execution.paper_ledger import resolve_ledger_path
    resolved = str(db_path) if db_path is not None else None
    led_path = str(resolve_ledger_path(ledger_path))
    cors = CORSConfig(
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    handlers = [
        get(["/health", "/api/health"])(_health),
        get(["/bars/{symbol:str}", "/api/bars/{symbol:str}"])(_get_bars),
        get(["/snapshot/{symbol:str}", "/api/snapshot/{symbol:str}"])(_snapshot_exists),
        post(["/paper/preview", "/api/paper/preview"])(_paper_preview),
        post(["/paper/place", "/api/paper/place"])(_paper_place),
        get(["/paper/positions", "/api/paper/positions"])(_paper_positions),
        get(["/paper/outcomes", "/api/paper/outcomes"])(_paper_outcomes),
        post(["/paper/kill", "/api/paper/kill"])(_paper_kill),
        post(["/paper/settle", "/api/paper/settle"])(_paper_settle),
    ]
    return Litestar(
        route_handlers=handlers,
        cors_config=cors,
        state=State({"db_path": resolved, "ledger_path": led_path, "paper_ledger": None}),
    )


app = create_app()


def main() -> None:
    """Serve on 127.0.0.1:8000 via Granian (uvicorn fallback)."""
    try:
        from granian import Granian

        Granian(
            "api.app:app",
            address=BIND_HOST,
            port=BIND_PORT,
            interface="asgi",
        ).serve()
        return
    except ImportError:
        pass
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "Install Phase B deps: pip install -r requirements-web.txt "
            "(granian) or pip install uvicorn"
        ) from exc
    uvicorn.run("api.app:app", host=BIND_HOST, port=BIND_PORT, reload=False)


if __name__ == "__main__":
    main()
