"""Paper Kelly sizing adapter.

Binary/event formulas are lifted from kalshi-bot ``math_engine``
(``kelly_criterion``, ``adjusted_kelly``, ``fee_per_contract``, and the
net-edge Kelly used in ``size_position``). Implemented as pure functions
in this repo; do not import the sibling kalshi-bot package at runtime.

Skewed/equity path calls ``modules.asymmetry.kelly_fraction_skewed`` when
that import is safe. Otherwise falls back to binary Kelly with a reason
string. This module itself does not import pandas or other heavy deps.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from risk.kelly import fractional_kelly
from signals.schema import Signal

# Lifted from kalshi-bot math_engine.DEFAULT_FEE_RATE.
DEFAULT_FEE_RATE = 0.07

_BINARY_VENUES = frozenset({"kalshi", "event", "binary"})
_SKEWED_VENUES = frozenset({"robinhood", "coinbase", "equity", "skewed"})


@dataclass(frozen=True)
class KellySizing:
    """Stake fraction/size only. Never places orders."""

    fraction: float
    stake: float
    kelly_raw: float
    kelly_adj: float
    mode: str
    reason: str
    p_true: float
    p_implied: float
    fallback: bool = False

    @property
    def stake_frac(self) -> float:
        return self.fraction

    @property
    def method(self) -> str:
        if self.mode == "skewed" and not self.fallback:
            return "skewed_kelly"
        return "binary_fee_aware_kelly"

    @property
    def reasons(self) -> tuple[str, ...]:
        return (self.reason,) if self.reason else ()


# Alias kept so call sites can say PaperSize or KellySizing.
PaperSize = KellySizing


def kelly_criterion(p_true: float, p_implied: float) -> float:
    """Full Kelly fraction for a binary contract. Lifted from math_engine."""
    if p_implied >= 1.0 or p_implied <= 0.0:
        return 0.0
    edge = p_true - p_implied
    if edge <= 0:
        return 0.0
    return edge / (1.0 - p_implied)


def adjusted_kelly(
    p_true: float, p_implied: float, kelly_frac: float = 0.5
) -> float:
    """Fractional Kelly. Lifted from math_engine.adjusted_kelly."""
    return kelly_frac * kelly_criterion(p_true, p_implied)


def fee_per_contract(price: float, rate: float = DEFAULT_FEE_RATE) -> float:
    """Marginal (un-rounded) fee per contract = rate * P * (1-P).

    Lifted from math_engine.fee_per_contract (Kalshi-style binary fee).
    """
    if price <= 0 or price >= 1:
        return 0.0
    return rate * price * (1.0 - price)


def _load_skewed() -> tuple[Callable[..., Any] | None, str | None]:
    """Import kelly_fraction_skewed only if deps resolve; else explain fallback."""
    try:
        from modules.asymmetry import kelly_fraction_skewed
    except Exception as exc:  # ImportError / missing pandas / heavy import chain
        return (
            None,
            f"skewed unavailable ({type(exc).__name__}: {exc}); "
            "falling back to binary Kelly",
        )
    return kelly_fraction_skewed, None


def resolve_sizing_mode(signal: Signal, mode: str | None = None) -> str:
    """kalshi/event -> binary; robinhood/coinbase/equity -> skewed."""
    if mode:
        key = str(mode).strip().lower()
        if key in _BINARY_VENUES or key == "binary":
            return "binary"
        if key in _SKEWED_VENUES or key == "skewed":
            return "skewed"
    venue = str(getattr(signal, "venue", "") or "").strip().lower()
    if venue in _SKEWED_VENUES:
        return "skewed"
    return "binary"


def _binary_p_and_implied(signal: Signal, odds_b: float) -> tuple[float, float]:
    """Return (p_use, p_implied) for the chosen side."""
    meta: Mapping[str, Any] = getattr(signal, "metadata", None) or {}
    side = str(getattr(signal, "side", "yes") or "yes").lower()
    p_true = float(signal.p_true)

    market_price = meta.get("market_price") if isinstance(meta, Mapping) else None
    if market_price is not None:
        px = float(market_price)
        if side == "no":
            # produce_kalshi_event stores the no-ask as market_price.
            return 1.0 - p_true, px
        return p_true, px

    edge = getattr(signal, "edge", None)
    if edge is not None and "market_price" not in (meta or {}):
        # Prefer odds_b when edge is only a residual and no quoted price.
        pass

    b = float(odds_b)
    if b <= 0:
        return p_true, 1.0
    return p_true, 1.0 / (1.0 + b)


def _binary_kelly(
    p_true: float,
    p_implied: float,
    *,
    kelly_fraction: float,
    fee_rate: float,
) -> tuple[float, float]:
    """Fee-aware Kelly (math_engine.size_position net-edge semantics).

    kelly_raw = max(0, (p_true - p_implied) - fee_pc) / (1 - p_implied)
    kelly_adj = kelly_fraction * kelly_raw  (adjusted_kelly on the net edge)
    """
    fee_pc = fee_per_contract(p_implied, fee_rate) if fee_rate else 0.0
    if p_implied >= 1.0 or p_implied <= 0.0:
        return 0.0, 0.0
    net_edge = (p_true - p_implied) - fee_pc
    kelly_raw = max(0.0, net_edge) / (1.0 - p_implied)
    kelly_adj = max(0.0, min(1.0, kelly_fraction * kelly_raw))
    return kelly_raw, kelly_adj


def _size_binary(
    signal: Signal,
    bankroll: float,
    *,
    odds_b: float,
    fee_rate: float,
    kelly_fraction: float,
    fallback: bool = False,
    reason: str | None = None,
) -> KellySizing:
    p_use, p_implied = _binary_p_and_implied(signal, odds_b)
    kelly_raw, kelly_adj = _binary_kelly(
        p_use,
        p_implied,
        kelly_fraction=kelly_fraction,
        fee_rate=fee_rate,
    )
    if reason is None:
        reason = (
            "binary: fee-aware Kelly (math_engine kelly_criterion / "
            "adjusted_kelly / size_position net-edge)"
        )
        if kelly_adj <= 0:
            reason = (
                "binary: non-positive fee-aware Kelly "
                "(p_true <= implied net of fees)"
            )
    stake = max(0.0, float(bankroll) * kelly_adj)
    return KellySizing(
        fraction=kelly_adj,
        stake=stake,
        kelly_raw=kelly_raw,
        kelly_adj=kelly_adj,
        mode="binary",
        reason=reason,
        p_true=p_use,
        p_implied=p_implied,
        fallback=fallback,
    )


def _size_skewed(
    signal: Signal,
    bankroll: float,
    *,
    odds_b: float,
    fee_rate: float,
    kelly_fraction: float,
    win_mult: float | None = None,
    loss_frac: float = 1.0,
    **kwargs: Any,
) -> KellySizing:
    fn, err = _load_skewed()
    if fn is None:
        return _size_binary(
            signal,
            bankroll,
            odds_b=odds_b,
            fee_rate=fee_rate,
            kelly_fraction=kelly_fraction,
            fallback=True,
            reason=err,
        )

    meta: Mapping[str, Any] = getattr(signal, "metadata", None) or {}
    if win_mult is None and isinstance(meta, Mapping):
        win_mult = meta.get("win_mult")
    if win_mult is None:
        win_mult = odds_b
    if isinstance(meta, Mapping) and "loss_frac" in meta and loss_frac == 1.0:
        loss_frac = float(meta.get("loss_frac", 1.0))
    max_fraction = float(kwargs.get("max_fraction", 0.20))
    if isinstance(meta, Mapping) and "max_fraction" in meta and "max_fraction" not in kwargs:
        max_fraction = float(meta["max_fraction"])

    b = float(win_mult)
    if fee_rate:
        b = max(b * (1.0 - float(fee_rate)), 0.0)
    if b <= 0:
        return KellySizing(
            fraction=0.0,
            stake=0.0,
            kelly_raw=0.0,
            kelly_adj=0.0,
            mode="skewed",
            reason="skewed: non-positive effective win_mult after fee haircut",
            p_true=float(signal.p_true),
            p_implied=0.0,
            fallback=False,
        )

    result = fn(
        float(signal.p_true),
        b,
        float(loss_frac),
        fraction_of_full=float(kelly_fraction),
        max_fraction=max_fraction,
    )
    if result is None:
        return _size_binary(
            signal,
            bankroll,
            odds_b=odds_b,
            fee_rate=fee_rate,
            kelly_fraction=kelly_fraction,
            fallback=True,
            reason="skewed Kelly: missing inputs; falling back to binary Kelly",
        )

    fraction = max(0.0, min(1.0, float(result.recommended_fraction)))
    kelly_raw = float(result.full_kelly)
    return KellySizing(
        fraction=fraction,
        stake=max(0.0, float(bankroll) * fraction),
        kelly_raw=kelly_raw,
        kelly_adj=fraction,
        mode="skewed",
        reason="skewed: modules.asymmetry.kelly_fraction_skewed",
        p_true=float(signal.p_true),
        p_implied=1.0 / (1.0 + b) if b > 0 else 1.0,
        fallback=False,
    )


def size_paper(
    signal: Signal,
    bankroll: float,
    *,
    mode: str | None = None,
    odds_b: float = 1.0,
    fee_rate: float = 0.0,
    kelly_fraction: float = 0.25,
    win_mult: float | None = None,
    loss_frac: float = 1.0,
    **kwargs: Any,
) -> KellySizing:
    """Size a paper stake. Returns fraction/dollars only; never places orders.

    ``mode`` overrides venue: kalshi/event -> binary; robinhood/coinbase/equity
    -> skewed when ``kelly_fraction_skewed`` imports, else binary fallback.
    """
    resolved = resolve_sizing_mode(signal, mode)
    bankroll = float(bankroll)
    if resolved == "skewed":
        return _size_skewed(
            signal,
            bankroll,
            odds_b=odds_b,
            fee_rate=fee_rate,
            kelly_fraction=kelly_fraction,
            win_mult=win_mult,
            loss_frac=loss_frac,
            **kwargs,
        )
    return _size_binary(
        signal,
        bankroll,
        odds_b=odds_b,
        fee_rate=fee_rate,
        kelly_fraction=kelly_fraction,
    )


def binary_matches_fractional_kelly(
    p: float,
    p_implied: float,
    *,
    fraction: float,
) -> float:
    """Bridge: math_engine Kelly equals ``fractional_kelly`` when fees are 0.

    With net odds ``b = (1 - p_implied) / p_implied``.
    """
    if p_implied <= 0.0 or p_implied >= 1.0:
        return 0.0
    b = (1.0 - p_implied) / p_implied
    return fractional_kelly(p, b, fraction=fraction, fee_rate=0.0)
