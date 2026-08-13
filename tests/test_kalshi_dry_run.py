"""Unit tests for venues.kalshi dry-run adapter."""
from __future__ import annotations

import pytest

from venues.base import OrderRequest, VenueAdapter
from venues.kalshi.adapter import KalshiDryRunAdapter


def test_deterministic_fill_stable_across_calls():
    adapter = KalshiDryRunAdapter(mode="dry_run")
    req = OrderRequest(
        market_id="KXTEST-1",
        side="yes",
        price=0.42,
        quantity=7,
        client_order_id="cid-1",
    )
    a = adapter.place_order(req)
    b = adapter.place_order(req)
    assert a.ok and b.ok
    assert a.order_id == b.order_id
    assert a.filled_qty == 7
    assert a.avg_fill_price == pytest.approx(0.42)
    assert a.raw["digest"] == b.raw["digest"]


def test_live_mode_refused_on_base_adapter():
    class _Dummy(VenueAdapter):
        name = "dummy"

        def _place_order_impl(self, request):
            raise AssertionError("should not be called")

    live = _Dummy(mode="live")
    req = OrderRequest("M", "yes", 0.5, 1, "c")
    with pytest.raises(RuntimeError, match="refused"):
        live.place_order(req)


def test_kalshi_adapter_rejects_live_construction():
    with pytest.raises(ValueError):
        KalshiDryRunAdapter(mode="live")


def test_invalid_price_rejected():
    adapter = KalshiDryRunAdapter(mode="paper")
    req = OrderRequest("M", "yes", 1.0, 2, "c2")
    res = adapter.place_order(req)
    assert not res.ok
    assert res.status == "rejected"
