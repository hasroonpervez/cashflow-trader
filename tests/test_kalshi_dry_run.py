"""Unit tests for venues.kalshi dry-run adapter."""
from __future__ import annotations

import pytest

from venues.base import Mode, OrderRequest
from venues.kalshi import KalshiDryRunAdapter


def test_live_construction_rejected() -> None:
    with pytest.raises(ValueError):
        KalshiDryRunAdapter(mode=Mode.LIVE)


def test_place_order_live_refused_on_base_mode() -> None:
    adapter = KalshiDryRunAdapter(mode=Mode.PAPER)
    adapter.mode = Mode.LIVE
    with pytest.raises(PermissionError):
        adapter.place_order(
            OrderRequest(market="M", side="yes", size=1.0, signal_id="sig")
        )


def test_deterministic_fills_from_signal_id() -> None:
    adapter = KalshiDryRunAdapter(mode=Mode.DRY_RUN)
    order = OrderRequest(
        market="DEMO-MARKET",
        side="yes",
        size=25.0,
        signal_id="abc123",
    )
    f1 = adapter.place_order(order)
    f2 = adapter.place_order(order)
    assert f1.order_id == f2.order_id
    assert f1.price == f2.price
    assert f1.mode is Mode.DRY_RUN
    assert 0.0 < f1.price <= 1.0


def test_different_signal_ids_differ() -> None:
    adapter = KalshiDryRunAdapter()
    a = adapter.place_order(
        OrderRequest(market="M", side="yes", size=1.0, signal_id="a")
    )
    b = adapter.place_order(
        OrderRequest(market="M", side="yes", size=1.0, signal_id="b")
    )
    assert a.order_id != b.order_id


def test_fetch_markets_no_network() -> None:
    markets = KalshiDryRunAdapter().fetch_markets()
    assert markets and markets[0]["market"] == "DEMO-MARKET"
