"""ConfigTransaction batching."""
import json
from pathlib import Path
from unittest.mock import patch

from modules.config import DEFAULT_CONFIG, ConfigTransaction


def test_no_write_when_clean(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(DEFAULT_CONFIG))
    with patch("modules.config.CONFIG_PATH", cfg_path):
        ct = ConfigTransaction()
        assert ct.flush() is True
        assert not ct.dirty


def test_batches_mutations(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(DEFAULT_CONFIG))
    with patch("modules.config.CONFIG_PATH", cfg_path):
        ct = ConfigTransaction()
        ct.update(watchlist="AAPL,GOOG")
        ct.update(mini_mode=True)
        assert ct.dirty
        assert ct.current["watchlist"] == "AAPL,GOOG"
        assert ct.current["mini_mode"] is True
        assert ct.flush() is True
        saved = json.loads(cfg_path.read_text())
        assert saved["watchlist"] == "AAPL,GOOG"
