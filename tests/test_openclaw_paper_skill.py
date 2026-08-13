from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "openclaw-skill" / "cashflow-paper" / "SKILL.md"
_SCRIPT = _REPO / "openclaw-skill" / "cashflow-paper" / "scripts" / "paper.sh"


def test_skill_is_paper_loopback_only() -> None:
    text = _SKILL.read_text(encoding="utf-8")
    assert "name: cashflow-paper" in text
    assert "127.0.0.1" in text
    assert "/paper/preview" in text
    assert "/paper/place" in text
    assert "/paper/positions" in text
    assert "/paper/kill" in text
    low = text.lower()
    assert ".pem" in low or "pem" in low
    assert "never" in low
    assert "kalshi-bot" in low
    assert ".env" in low
    assert "robinhood" in low
    assert "0.0.0.0" in text
    assert "live" in low
    for banned in ("KALSHI_PRIVATE_KEY", "BEGIN RSA", "api_key="):
        assert banned not in text


def test_paper_sh_refuses_non_loopback() -> None:
    script = _SCRIPT.read_text(encoding="utf-8")
    assert "127.0.0.1" in script
    assert "refusing non-loopback" in script
    assert "place_paper" in script
