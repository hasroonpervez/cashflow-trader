# OpenClaw paper skill (repo stub)

**Status:** in-repo skill only. Not installed on the OpenClaw box.
Paper / dry-run. No live `place_order`. No LaunchAgent, Tailscale, or secrets.

OpenClaw should run the desk (agent loop) against the Phase B API on
`127.0.0.1:8000`. Streamlit Cloud is not the trader.

## Layout

| Path | Role |
|---|---|
| `openclaw-skill/cashflow-paper/SKILL.md` | OpenClaw skill (AgentSkills frontmatter) |
| `openclaw-skill/cashflow-paper/scripts/paper.sh` | curl helper, loopback-only |
| `api/app.py` | `/paper/preview`, `/paper/place`, `/paper/positions`, `/paper/kill` |

## Tools

| Skill tool | HTTP |
|---|---|
| preview | `POST http://127.0.0.1:8000/paper/preview` |
| place_paper | `POST http://127.0.0.1:8000/paper/place` |
| positions | `GET http://127.0.0.1:8000/paper/positions` |
| kill | `POST http://127.0.0.1:8000/paper/kill` |

MODE is `dry_run` or `paper`. `mode=live` returns **403**.

Positions/kill use an **in-memory** ledger in the API process (lost on restart).
That is enough for a paper agent loop. It is not a durable book.

## Hard rules

- Bind remains `127.0.0.1`. Do not expose `0.0.0.0` from this stub.
- Do **not** copy `~/kalshi-bot` `.env` or `*.pem`.
- Do **not** unofficially scrape Robinhood.
- Do **not** install this skill, a LaunchAgent, or Tailscale in this PR.
  Copying `openclaw-skill/cashflow-paper` into an OpenClaw workspace
  (`skills/` or `skills.load.extraDirs`) is a later CEO-gated step.

## Tests

`tests/test_phase_b_api.py` covers positions/kill + live 403.
`tests/test_openclaw_paper_skill.py` gates the skill text (loopback, no secrets).
