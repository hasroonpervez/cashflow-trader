from risk.promotion_gate import promotion_gate


def test_gate_holds_on_small_n():
    d = promotion_gate([1.0, 0.0, 1.0], min_n=30)
    assert d.ok is False
    assert any("min_n" in r for r in d.reasons)


def test_gate_promotes_balanced_sample():
    outcomes = [1.0, 0.0] * 20
    labels = ["A", "B"] * 20
    d = promotion_gate(
        outcomes,
        min_n=30,
        split_half_corr=-1.0,
        max_concentration=0.6,
        labels=labels,
    )
    assert d.ok is True
    assert d.reasons == ()


def test_gate_concentration():
    outcomes = [1.0] * 40
    labels = ["ONLY"] * 40
    d = promotion_gate(
        outcomes,
        min_n=30,
        split_half_corr=-1.0,
        max_concentration=0.5,
        labels=labels,
    )
    assert d.ok is False
    assert any("concentration" in r for r in d.reasons)
