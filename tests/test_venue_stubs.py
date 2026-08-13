import pytest

from venues.base import Mode, OrderRequest
from venues.coinbase.adapter import CoinbasePaperAdapter
from venues.robinhood.adapter import RobinhoodReadAdapter


def test_coinbase_live_refused():
    with pytest.raises(ValueError):
        CoinbasePaperAdapter(Mode.LIVE)


def test_robinhood_live_refused():
    with pytest.raises(ValueError):
        RobinhoodReadAdapter(Mode.LIVE)


def test_stubs_paper_fill():
    cb = CoinbasePaperAdapter()
    rh = RobinhoodReadAdapter()
    order = OrderRequest(market="X", side="yes", size=1.0, price=0.5, signal_id="s")
    assert cb.place_order(order).mode is Mode.PAPER
    assert rh.place_order(order).mode is Mode.PAPER
