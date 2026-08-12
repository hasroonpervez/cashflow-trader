# Implementation brief for OpenCode

Paste the block below into OpenCode. Everything it needs is either in the prompt or in the
repo it will be pointed at.

---

## THE PROMPT

You are implementing **CashFlow Trader v2**, a self-hosted stock scanner, on the machine it
will run on. The complete specification is in `ARCHITECTURE.md` in the repository root. **Read
that file in full before writing any code.** It states every technology choice, the reason for
it, and the alternative that was rejected. Supporting evidence lives in `AUDIT_2026-08.md` (88
confirmed defects in v1 and how they were fixed) and `STACK_SURVEY_2026-08.md` (benchmarks
proving why the stack is what it is).

### What this app is

A scanner that finds asymmetric stock opportunities, meaning setups where the possible gain is
much larger than the risk taken. One user, on phone and desktop. Roughly 100 to 500 tickers,
daily bars, updated on a schedule. It is a research tool: it suggests what to look at. It never
places a trade.

### The one idea the whole design rests on

> **Nothing is computed during a read.** Background workers precompute everything into
> PostgreSQL. The API only does indexed reads from materialised views.

v1 was slow because it fetched from Yahoo, Reddit and StockTwits *inside the request*, while
the user waited. If you ever find yourself calling an external API from inside an HTTP handler,
you have reintroduced the original bug. There are no exceptions to this rule.

### Non-negotiables

These are not preferences. Breaking any of them fails the work.

1. **The 852 existing tests must keep passing.** They encode the fixes for 88 audited defects,
   including an inverted vanna sign, a Kelly clip that could size a position above 100 percent
   of bankroll, and lookahead bias contaminating every historical win rate. Run
   `pytest tests/ -q` before you start and after every step. If a test fails, you broke
   something. Do not edit a test to make it pass unless you can show in writing that the test
   was asserting buggy behaviour.
2. **`core/` has zero framework dependencies.** No Litestar, no asyncpg, no SQLAlchemy, no
   Streamlit, no Valkey. It is pure functions over dataframes and plain types. Add a CI check
   that fails the build if any of those appear in a `core/` import. This single rule is what
   makes every other layer replaceable.
3. **Never invent data.** A failed source writes a row to `data_quality_events` and leaves the
   field NULL. It does not substitute a plausible default. v1 displayed a hardcoded VIX of 20.0
   as though it were live; that class of bug must be unrepresentable now.
4. **Append only.** Never UPDATE a signal. Insert a new row. History is the product.
5. **Every fact is bitemporal:** `as_of` (when it was true in the market) and `ingested_at`
   (when we learned it). This is what makes point-in-time correctness a WHERE clause instead of
   a hope, and it is how lookahead bias stays dead.
6. **Everything must be free and open source.** The licence audit is section 3.6 of
   `ARCHITECTURE.md`. Use Valkey, not Redis. Do not add a dependency without checking its
   licence and recording it in that table.
7. **No em dashes or en dashes** in any code, comment, docstring, commit message or UI string.
   Use commas, colons or full stops. The repository is currently clean of them; keep it that way.

### Build in this order. Each step ends with something that works.

1. **`db/`** Alembic migrations for the schema in section 5 of `ARCHITECTURE.md`. Seed
   `instruments` from the current `watchlist` and `radar_universe` in `config.json`.
2. **`core/`** Move `modules/` to `core/`, strip every Streamlit import, add the import ban
   check. **All 852 tests green on Python 3.13 as well as 3.12** before you go further. They
   were validated on 3.12.13; if something fails on 3.13, fix it there rather than downgrading.
3. **`workers/ingest_bars.py`** plus `job_runs` logging. Backfill two years for the universe.
   Verify `price_basis` is set correctly for both Yahoo and Alpha Vantage.
4. **`workers/compute_signals.py`** writing `scan_runs` and `signals`, using `core/`.
5. **`workers/resolve_outcomes.py`** and the materialised views. Backfill outcomes over the
   bars you just loaded, so `/validation` has real sample size on day one rather than in a year.
6. **`api/`** health, dashboard, ticker, signals, validation. Contract-test every endpoint.
7. **`web/`** `/` and `/ticker/[symbol]` first, with lightweight-charts and the plain-English
   glosses from `core/explain.py` wired in.
8. **The snapshot pattern from section 3.5.** This is worth more perceived speed than every
   other optimisation combined: one immutable versioned JSON, a service worker, and all
   sorting, filtering and tab switching served from memory with zero network.
9. **`ops/`** launchd plists, cloudflared, Cloudflare Access, uptime-kuma checks.
10. **`/positions` and `/validation`**, then retire Streamlit.

Do not skip ahead. Step 2 is the safety net for everything after it.

### Traps that have already bitten this project

Read these. Each one cost real time.

- **Do not add `run_every=` to a Streamlit or SvelteKit component that does network work.**
  A previous fix added `@st.fragment(run_every=90.0)` to a watchlist scanner. It reran in every
  open session forever and the hosting platform killed the app. On-demand plus an explicit
  refresh button is correct.
- **Test on the deployment's exact versions.** The same incident was missed because testing
  happened on pandas 3.0.5 / numpy 2.5.2 / Python 3.14 while production ran pandas 2.3.3 /
  numpy 2.0.2 / Python 3.12.13. Pin a replica environment and use it.
- **Run long enough to hit the timers.** That bug fired at 90 seconds; every smoke test ran for
  35. Soak for several minutes with a real browser session open before declaring success.
- **`scipy.stats.norm.cdf` on scalars is 400x slower than `math.erf`.** It was costing 12.6 ms
  per option chain in pure dispatch overhead. Already fixed in `core/options.py`; do not
  reintroduce the pattern anywhere else. Vectorise or use `math`.
- **Do not mix adjusted and unadjusted prices.** `price_basis` is part of the bars primary key
  for exactly this reason. A reverse split silently injected a fake gap in v1.

### Definition of done, per step

- The tests pass.
- The job appears in `/ops` with its run history.
- The failure mode is **visible**, not silent. If a source is down, a human can see that in the
  UI, not just infer it from a number that looks a bit odd.

### How to communicate

When you finish a step, report: what you built, what you measured, what you could not do and
why, and any place where you disagreed with `ARCHITECTURE.md`. If you do disagree, say so and
change the document deliberately with your reason. Do not change a decision silently.

If something in the spec is ambiguous or looks wrong, stop and ask rather than guessing. The
spec was written knowing it would be handed over, so ambiguity is a bug in the spec.

---

## Notes for the human, not for OpenCode

**Before OpenCode starts, install the dependencies on `box`:**

```bash
brew install postgresql@17 valkey cloudflared
brew services start postgresql@17
brew services start valkey
```

Python 3.13.14, Node 26 and Bun tooling are needed too; 3.13 and Node are already installed,
Bun is not:

```bash
brew install oven-sh/bun/bun
```

**What still needs you, not the agent:**

1. **Cloudflare login.** `cloudflared tunnel login` opens a browser and only you can authorise
   it. Same for turning on Cloudflare Access.
2. **Domain DNS.** Cloudflare Tunnel needs the domain's nameservers pointed at Cloudflare.
   Suggested: `sprucespark.com`, with the app at `trade.sprucespark.com`. Registration stays at
   GoDaddy, only DNS moves, and it is free.
3. **A decision on vendor independence.** Cloudflare is free but proprietary. Section 3.6 of
   `ARCHITECTURE.md` lists fully open self-hosted alternatives, all of which need a cheap VPS.

**One unrelated thing found while auditing the box:** Home Assistant (`~/.ha-venv/bin/hass`,
PID 335) has been pegging a full CPU core at 100 percent for nearly six days. It is not related
to this project, but it is burning power and heat continuously and is worth a look.
