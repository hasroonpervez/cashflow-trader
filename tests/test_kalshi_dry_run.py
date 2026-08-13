import pytest

from venues.base import Mode, OrderRequest
from venues.kalshi.adapter import KalshiDryRunAdapter


def test_dry_run_fill_deterministic():
    a = KalshiDryRunAdapter(Mode.DRY_RUN)
    order = OrderRequest(market="M", side="yes", size=10.0, signal_id="abc")
    f1 = a.place_order(order)
    f2 = a.place_order(order)
    assert f1.order_id == f2.order_id
    assert f1.price == f2.price
    assert f1.mode is Mode.DRY_RUN


def test_live_mode_refused_on_construct():
    with pytest.raises(ValueError):
        KalshiDryRunAdapter(Mode.LIVE)


def test_base_live_place_refused():
    a = KalshiDryRunAdapter(Mode.PAPER)
    a.mode = Mode.LIVE
    with pytest.raises(PermissionError):
        a.place_order(OrderRequest(market="M", side="yes", size=1.0))
