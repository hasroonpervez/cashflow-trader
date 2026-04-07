"""Black–Scholes Greeks extensions (vanna, charm)."""
from modules.options import bs_greeks


def test_bs_greeks_includes_vanna_charm():
    g = bs_greeks(100.0, 100.0, 30 / 365.0, 0.05, 0.25, "call")
    assert "vanna" in g and "charm" in g
    assert isinstance(g["vanna"], (int, float))
    assert isinstance(g["charm"], (int, float))
    assert all(k in g for k in ("delta", "gamma", "theta", "vega"))


def test_bs_greeks_expired_like_returns_zeros_for_secondaries():
    g = bs_greeks(100.0, 100.0, 0.0, 0.05, 0.25, "call")
    assert g["vanna"] == 0 and g["charm"] == 0
