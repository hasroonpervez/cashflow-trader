"""CLI dry-run: --demo and --bars-json, no network."""
from __future__ import annotations

import json
from pathlib import Path

from tools.scanner_dry_run import main


def test_demo_stdout(capsys):
    rc = main(["--demo"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["live"] is False
    assert payload["sig"] == "Sig_orb_rvol_vwap"
    assert payload["mode"] == "dry_run"
    assert "PLAY" in payload["in_play"]
    assert "DEAD" not in payload["in_play"]


def test_demo_paper(capsys):
    rc = main(["--demo", "--paper", "--slippage-bps", "3"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["live"] is False
    assert payload["paper_only"] is True
    assert payload["results"][0]["accepted"] is True
    assert payload["results"][0]["fill"]["slippage_bps"] == 3.0
    assert payload["signals"][0]["source"] == "Sig_orb_rvol_vwap"


def test_bars_json(tmp_path: Path, capsys):
    from signals.scanner_fixtures import demo_payload

    path = tmp_path / "bars.json"
    path.write_text(json.dumps(demo_payload()), encoding="utf-8")
    rc = main(["--bars-json", str(path)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "PLAY" in payload["in_play"]


def test_requires_input():
    with __import__("pytest").raises(SystemExit):
        main([])
