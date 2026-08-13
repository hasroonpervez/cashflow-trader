from risk.kelly import fee_aware_kelly, fractional_kelly


def test_fractional_kelly_positive_edge():
    f = fractional_kelly(0.6, 1.0, fraction=0.5, fee_rate=0.0)
    assert 0 < f <= 0.5


def test_fractional_kelly_no_edge():
    assert fractional_kelly(0.4, 1.0, fraction=0.25) == 0.0


def test_fee_aware_reduces_size():
    raw = fractional_kelly(0.62, 1.0, fraction=0.25, fee_rate=0.0)
    fee = fee_aware_kelly(0.62, 1.0, fraction=0.25, fee_rate=0.07)
    assert fee <= raw
