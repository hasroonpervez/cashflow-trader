"""Movers universe scanner (paper / research).

Scores gap%, relative volume (RVOL), price floor, and dollar volume from
*provided* OHLCV. No network. Do not call this from API handlers that would
scrape Yahoo — inject bars (CLI ``--bars-json`` / ``--demo``, or a DataFrame).

Aim: stocks-in-play that can print a large session range (~20% class).
The matching Sig_* takes a *slice* of that move (ORB + RVOL + VWAP side),
not the full range.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping

import pandas as pd

_OHLCV = ("open", "high", "low", "close", "volume")
_TITLE = {c: c.title() for c in _OHLCV}
REGULAR_MINUTES = 390.0


@dataclass(frozen=True)
class ScannerConfig:
    """In-play floors. Defaults target liquid gappers, not penny noise."""

    min_gap_pct: float = 3.0
    min_rvol: float = 2.0
    min_price: float = 5.0
    min_dollar_volume: float = 2_000_000.0
    rvol_lookback: int = 20
    target_range_pct: float = 20.0
    tz: str = "America/New_York"
    regular_minutes: float = REGULAR_MINUTES


@dataclass(frozen=True)
class MoverCandidate:
    symbol: str
    gap_pct: float | None
    rvol: float | None
    price: float | None
    dollar_volume: float | None
    score: float
    in_play: bool
    reasons: tuple[str, ...]
    session_volume: float | None = None
    avg_volume: float | None = None
    session_range_pct: float | None = None
    paper_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["reasons"] = list(self.reasons)
        return raw


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case OHLCV + DatetimeIndex. Empty / missing cols → empty frame."""
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=list(_OHLCV))
    d = df.copy()
    rename: dict[str, str] = {}
    lower = {str(c).lower(): c for c in d.columns}
    for name in _OHLCV:
        if name in d.columns:
            continue
        if name in lower:
            rename[lower[name]] = name
        elif _TITLE[name] in d.columns:
            rename[_TITLE[name]] = name
    if rename:
        d = d.rename(columns=rename)
    if "timestamp" in d.columns and not isinstance(d.index, pd.DatetimeIndex):
        d = d.set_index(pd.DatetimeIndex(d["timestamp"]))
    elif "ts" in d.columns and not isinstance(d.index, pd.DatetimeIndex):
        d = d.set_index(pd.DatetimeIndex(d["ts"]))
    elif not isinstance(d.index, pd.DatetimeIndex):
        try:
            d.index = pd.DatetimeIndex(d.index)
        except (TypeError, ValueError):
            pass
    missing = [c for c in _OHLCV if c not in d.columns]
    if missing:
        return pd.DataFrame(columns=list(_OHLCV))
    out = d[list(_OHLCV)].astype(float).sort_index()
    return out


def _as_tz_index(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    d = normalize_ohlcv(df)
    if d.empty or not isinstance(d.index, pd.DatetimeIndex):
        return d
    idx = d.index
    if idx.tz is None:
        d.index = idx.tz_localize(tz)
    else:
        d.index = idx.tz_convert(tz)
    return d


def session_groups(df: pd.DataFrame, *, tz: str = "America/New_York") -> list[tuple[date, pd.DataFrame]]:
    """Split a bar frame into NY-session slices (oldest → newest)."""
    d = _as_tz_index(df, tz)
    if d.empty:
        return []
    out: list[tuple[date, pd.DataFrame]] = []
    for day, chunk in d.groupby(d.index.date, sort=True):
        out.append((day, chunk))
    return out


def session_elapsed_minutes(session: pd.DataFrame) -> float:
    if session is None or len(session) < 1:
        return 0.0
    if len(session) == 1:
        return 5.0
    delta = session.index[-1] - session.index[0]
    return max(float(delta.total_seconds() / 60.0) + 5.0, 5.0)


def relative_volume(
    session_volume: float,
    avg_volume: float,
    *,
    elapsed_minutes: float | None = None,
    regular_minutes: float = REGULAR_MINUTES,
) -> float | None:
    """RVOL vs prior full-session average; time-adjusts when elapsed is known."""
    sess = float(session_volume)
    avg = float(avg_volume)
    if avg <= 0 or sess < 0:
        return None
    if elapsed_minutes is not None and elapsed_minutes > 0 and regular_minutes > 0:
        expected = avg * (float(elapsed_minutes) / float(regular_minutes))
        if expected <= 0:
            return None
        return sess / expected
    return sess / avg


def _finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def score_symbol(
    symbol: str,
    bars: pd.DataFrame,
    *,
    prior_close: float | None = None,
    avg_volume: float | None = None,
    config: ScannerConfig | None = None,
) -> MoverCandidate:
    """Score one symbol from a bar frame (multi-session or one session + hints)."""
    cfg = config or ScannerConfig()
    reasons: list[str] = []
    groups = session_groups(bars, tz=cfg.tz)
    if not groups:
        return MoverCandidate(
            symbol=str(symbol).upper().strip(),
            gap_pct=None,
            rvol=None,
            price=None,
            dollar_volume=None,
            score=0.0,
            in_play=False,
            reasons=("scanner: no bars",),
        )

    _day, session = groups[-1]
    prior_sessions = groups[:-1]
    last_close = _finite(session["close"].iloc[-1])
    session_high = _finite(session["high"].max())
    session_low = _finite(session["low"].min())
    session_vol = _finite(session["volume"].sum()) or 0.0
    session_open = _finite(session["open"].iloc[0])

    inferred_prior = None
    if prior_sessions:
        inferred_prior = _finite(prior_sessions[-1][1]["close"].iloc[-1])
    px_prior = _finite(prior_close) if prior_close is not None else inferred_prior

    gap_pct = None
    if px_prior is not None and px_prior > 0 and session_open is not None:
        gap_pct = (session_open / px_prior - 1.0) * 100.0

    lookback = prior_sessions[-int(cfg.rvol_lookback) :] if prior_sessions else []
    inferred_avg = None
    if lookback:
        vols = [float(chunk["volume"].sum()) for _d, chunk in lookback]
        inferred_avg = sum(vols) / len(vols) if vols else None
    avg = _finite(avg_volume) if avg_volume is not None else inferred_avg

    elapsed = session_elapsed_minutes(session)
    rvol = None
    if avg is not None:
        rvol = relative_volume(
            session_vol,
            avg,
            elapsed_minutes=elapsed,
            regular_minutes=cfg.regular_minutes,
        )

    dollar_vol = None
    if last_close is not None and last_close > 0:
        dollar_vol = last_close * session_vol

    range_pct = None
    if (
        last_close is not None
        and last_close > 0
        and session_high is not None
        and session_low is not None
    ):
        range_pct = (session_high - session_low) / last_close * 100.0

    in_play = True
    if last_close is None or last_close < cfg.min_price:
        in_play = False
        reasons.append(f"scanner: price floor {cfg.min_price}")
    if gap_pct is None:
        in_play = False
        reasons.append("scanner: missing prior_close (inject or pass prior session)")
    elif abs(gap_pct) < cfg.min_gap_pct:
        in_play = False
        reasons.append(f"scanner: |gap| {gap_pct:.2f}% < {cfg.min_gap_pct}")
    if rvol is None:
        in_play = False
        reasons.append("scanner: missing avg_volume (inject or pass prior sessions)")
    elif rvol < cfg.min_rvol:
        in_play = False
        reasons.append(f"scanner: rvol {rvol:.2f} < {cfg.min_rvol}")
    if dollar_vol is None or dollar_vol < cfg.min_dollar_volume:
        in_play = False
        reasons.append(f"scanner: dollar volume floor {cfg.min_dollar_volume}")

    # Rank gappers that can extend toward a ~20% session-range class.
    gap_term = 0.0 if gap_pct is None else min(abs(gap_pct) / 8.0, 1.5)
    rvol_term = 0.0 if rvol is None else min(float(rvol) / 3.0, 1.5)
    dvol_term = 0.0 if dollar_vol is None else min(float(dollar_vol) / 10_000_000.0, 1.0)
    score = round(gap_term + rvol_term + dvol_term, 4)
    if in_play:
        reasons.append(
            f"scanner: in-play (target slice of ~{cfg.target_range_pct:.0f}% range class)"
        )

    return MoverCandidate(
        symbol=str(symbol).upper().strip(),
        gap_pct=None if gap_pct is None else round(float(gap_pct), 4),
        rvol=None if rvol is None else round(float(rvol), 4),
        price=None if last_close is None else round(float(last_close), 4),
        dollar_volume=None if dollar_vol is None else round(float(dollar_vol), 2),
        score=score,
        in_play=in_play,
        reasons=tuple(reasons),
        session_volume=round(session_vol, 2),
        avg_volume=None if avg is None else round(float(avg), 2),
        session_range_pct=None if range_pct is None else round(float(range_pct), 4),
    )


def scan_universe(
    frames: Mapping[str, pd.DataFrame],
    *,
    config: ScannerConfig | None = None,
    hints: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[MoverCandidate]:
    """Score many symbols. ``hints[SYM]`` may set prior_close / avg_volume."""
    cfg = config or ScannerConfig()
    extra = hints or {}
    scored: list[MoverCandidate] = []
    for raw_sym, bars in frames.items():
        sym = str(raw_sym).upper().strip()
        hint = extra.get(sym) or extra.get(raw_sym) or {}
        scored.append(
            score_symbol(
                sym,
                bars,
                prior_close=hint.get("prior_close"),
                avg_volume=hint.get("avg_volume"),
                config=cfg,
            )
        )
    scored.sort(key=lambda c: (not c.in_play, -c.score, c.symbol))
    return scored


def frames_from_payload(
    payload: Any,
) -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]]:
    """Parse CLI / fixture JSON into frames + hints. No network."""
    frames: dict[str, pd.DataFrame] = {}
    hints: dict[str, dict[str, Any]] = {}
    if isinstance(payload, list):
        by_sym: dict[str, list] = {}
        for row in payload:
            if not isinstance(row, Mapping):
                continue
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            by_sym.setdefault(sym, []).append(dict(row))
        for sym, rows in by_sym.items():
            frames[sym] = pd.DataFrame(rows)
        return frames, hints
    if not isinstance(payload, Mapping):
        raise ValueError("bars payload must be a list or object keyed by symbol")
    for key, value in payload.items():
        sym = str(key).upper().strip()
        if not sym:
            continue
        if isinstance(value, list):
            frames[sym] = pd.DataFrame(value)
            continue
        if not isinstance(value, Mapping):
            continue
        rows = value.get("bars") or value.get("ohlcv") or []
        if not isinstance(rows, list):
            raise ValueError(f"{sym}: bars must be a list")
        frames[sym] = pd.DataFrame(rows)
        hint: dict[str, Any] = {}
        if value.get("prior_close") is not None:
            hint["prior_close"] = float(value["prior_close"])
        if value.get("avg_volume") is not None:
            hint["avg_volume"] = float(value["avg_volume"])
        if hint:
            hints[sym] = hint
    return frames, hints


def demo_universe() -> tuple[dict[str, pd.DataFrame], dict[str, dict[str, Any]]]:
    """Synthetic in-play / reject names for offline CLI (no network)."""
    from signals.scanner_fixtures import build_demo_frames

    return build_demo_frames()
