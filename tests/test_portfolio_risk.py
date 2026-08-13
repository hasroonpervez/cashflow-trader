from risk.portfolio_risk import advise_portfolio_risk


def test_advisory_heat():
    advice = advise_portfolio_risk(stake=400, bankroll=1000, open_exposure=0, max_heat=0.25)
    assert advice.haircut > 0
    assert advice.ok is False


def test_advisory_ok_small_stake():
    advice = advise_portfolio_risk(stake=50, bankroll=1000, open_exposure=0, max_heat=0.25)
    assert advice.ok is True
    assert advice.haircut == 0.0
