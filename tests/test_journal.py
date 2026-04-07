from unittest.mock import patch


def test_journal_roundtrip(tmp_path):
    jp = tmp_path / "trade_journal.json"
    with patch("modules.config.JOURNAL_PATH", jp):
        from modules.config import (
            journal_add_entry,
            journal_clear,
            journal_close_trade,
            load_journal,
        )

        assert load_journal() == []
        assert journal_add_entry(
            {
                "ticker": "PLTR",
                "strike": 100,
                "premium_100": 350,
                "option_type": "put",
                "contracts": 1,
                "status": "open",
            }
        )
        j = load_journal()
        assert len(j) == 1
        assert j[0]["ticker"] == "PLTR"
        assert journal_close_trade(0, 95.0)
        j2 = load_journal()
        assert j2[0]["status"] == "closed"
        assert j2[0]["realized_pnl"] is not None
        assert journal_clear()
        assert load_journal() == []
