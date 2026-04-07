from datetime import datetime, timedelta
from unittest.mock import patch


def test_urgency_bucketing():
    """Verify urgency labels based on days-out."""
    today = datetime.now().date()

    def mock_fetch(sym):
        offsets = {"A": 3, "B": 10, "C": 25, "D": 45, "E": -5}
        days = offsets.get(sym)
        if days is None:
            return None
        return (today + timedelta(days=days)).strftime("%Y-%m-%d")

    with patch("modules.data.fetch_earnings_date", side_effect=mock_fetch):
        from modules.data import fetch_watchlist_earnings_heatmap

        df = fetch_watchlist_earnings_heatmap(("A", "B", "C", "D", "E", "F"))

    assert df[df["Ticker"] == "A"]["Urgency"].iloc[0] == "this_week"
    assert df[df["Ticker"] == "B"]["Urgency"].iloc[0] == "next_week"
    assert df[df["Ticker"] == "C"]["Urgency"].iloc[0] == "this_month"
    assert df[df["Ticker"] == "D"]["Urgency"].iloc[0] == "clear"
    assert df[df["Ticker"] == "E"]["Urgency"].iloc[0] == "reported"
    assert df[df["Ticker"] == "F"]["Urgency"].iloc[0] == "unknown"
    assert df.iloc[0]["Ticker"] == "A"
