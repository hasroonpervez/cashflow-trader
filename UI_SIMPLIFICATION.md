# UI / UX Simplification Plan

> **The requirement, verbatim:** *"make the ui and ux super simple and easy and fast and
> extremely easy to understand and explain if you want to know"*

Four goals, decoded:

| Goal | Test it passes |
|---|---|
| **SIMPLE** | One obvious next action per view. Fewer things on screen. |
| **FAST** | No fetch on the render path, no work repeated per rerun, visible loading states. |
| **EASY TO UNDERSTAND** | Every number has a plain-English label. No unexplained acronym, ever. |
| **EXPLAIN IF YOU WANT TO KNOW** | Plain answer always visible; the math one click away. Never forced, never hidden. |

This document is the audit and the migration plan. The toolkit it plans around already
exists: **`modules/explain.py`** (new, tested by `tests/test_explain.py`, 45 tests, imports
without Streamlit). Nothing else was modified.

---

## 1. What I measured

| Measure | Count |
|---|---|
| Top-level tabs | **6** (`app.py:328-337`) |
| Nested tab bars | **2** — `renderers.py:142` (2 tabs), `renderers.py:2893` (3 tabs) |
| Total tab surfaces a user can land on | **11** |
| Sticky-nav jump links (a second, parallel navigation) | **10** (`css.py:1086-1095`) |
| Always-on controls above the first tab | **~14** (watchlist editor, Mission Control's 8, tape, overlay toggles) |
| Formatted numbers rendered across the desk | **308** |
| `st.expander` blocks | **28** |
| `unsafe_allow_html=True` sites | **124** |
| Native `help=` tooltips | **72** |
| Distinct hard-coded hex colours | **27** renderers + **36** ui_helpers + **25** pre_tabs + **45** css = **133** |
| Distinct numeric format specs in use | **8** (`:.0f :.1f :.2f :.3f :.4f :.5f :,.0f :,.2f`) |
| `st.rerun()` calls | **14** |
| Glossary entries, hidden 3 clicks deep | **27** (`renderers.py:2981-3009`) |

### Numbers per screen — the density ranking

| Screen | Formatted numbers | Lines of render code |
|---|---:|---:|
| `renderers.py::render_cashflow_tab` (916-1801) | **85** | 885 |
| `renderers.py::render_intel_tab` (1801-3021) | **70** | 1220 |
| `renderers.py::render_setup_tab` (321-916) | **51** | 595 |
| `render_pre_tabs.py::render_desk_after_context` (542-1402) | **47** | 860 |
| `renderers.py::render_ledger_tab` (3225-3559) | **22** | 334 |
| `ui_helpers.py::_fragment_technical_zone` (1008-1376) | 16 | 368 |
| `renderers.py::render_radar_tab` (3021-3225) | 4 | 204 |

Reference point: a well-designed dashboard screen carries **5-9** numbers. Cash Flow carries
**85**. That is not a styling problem; it is an editing problem.

---

## 2. The five worst-complexity screens

### 1. Cash Flow tab — `renderers.py:916-1801` (885 lines, 85 numbers)

The single densest screen. In one scroll it shows: weekly-bias warning, an expiration
selectbox, an IV term-structure table (Expiry / DTE / ATM strike / ATM IV × 3 rows), a
full option chain with **Θ/Γ** and **MC PoP %** columns, a vol-skew card, covered-call and
cash-secured-put tables (strike, bid, ask, mid, IV, volume, OI, OTM %, premium yield,
annualised yield, premium/100, breakeven, delta, Θ/Γ, MC PoP — **16 columns each**),
Kelly sizing, and EV.

To act on this screen you must already know what delta 0.16 means, what Θ/Γ 2.0 implies,
and why annualised yield is a ranking device rather than a return. `renderers.py:1199-1203`
literally renders a column header of `Θ/Γ` with the help text *"Theta / Gamma (vectorized
chain greeks)"* — which explains the jargon using more jargon.

**Worst single offence:** `renderers.py:1204-1208`, the MC PoP column, whose help text is
*"10k antithetic simulations — v22.0 Predictive Analytics"*. That sentence tells a normal
person nothing. The number it labels is the single most decision-relevant figure on the
screen: *the chance this trade makes money*.

### 2. Scanner & Intel tab — `renderers.py:1801-3021` (1220 lines, 70 numbers)

Four unrelated jobs in one tab: the watchlist scanner, the quant diagnostics panel, a
backtest, and a news/macro/earnings section with **its own 3-tab bar** (`renderers.py:2893`).
The Quick Reference glossary is also buried here (`renderers.py:2974`), inside an expander,
inside the third sub-tab, inside the third top-level tab. A user who does not know what
"GEX" means will not find the answer.

The scanner emits per-row: confluence, diamond status, Gold Zone distance, Edge Score,
GEX regime, 10x potential, MC PoP, HVN floor, risk multiplier — nine figures per ticker,
before you have chosen anything.

### 3. Everything above the tabs — `render_pre_tabs.py:207-1402` (47 numbers)

The user meets, in order, before any tab: a watchlist editor, **Mission Control** with
8 controls (`render_pre_tabs.py:228-368`: ticker, strategy segmented control, turbo toggle,
option horizon, scanner order, trading hemisphere, capital slider, quant toggle), a ticker
tape, a consensus banner, an institutional heatmap ribbon, three bento cells, a position-size
expander, a 4-column glance row, a two-column execution strip, and the technical chart.

Mission Control asks eight configuration questions before answering one user question. Most
users will change the ticker and nothing else. **"Trading Hemisphere"** (`render_pre_tabs.py:313`)
is a mode switch whose name explains nothing; its help text — *"premium harvesting (Options)
and Delta-One breakout hunting (Equity)"* — introduces "Delta-One", a term defined nowhere
in the app.

### 4. Signals tab — `renderers.py:321-916` (595 lines, 51 numbers)

Opens with **Hurst Exponent (R/S)** rendered as `0.487 = RANDOM WALK` in a raw metric card
(`renderers.py:428-430`). This is the first analytical number a user sees after the chart,
and "Hurst Exponent (R/S)" is arguably the most obscure label in the entire app. The
`_explain()` card immediately below it does a genuinely good job of translating it — which
proves the content exists and is merely in the wrong order: **jargon first, plain English
second**. Invert that and this screen improves without deleting anything.

Also here: the quant diagnostics with `regime_prob_calm / medium / stress`, `ffd_last`,
`inst_signal`, `retail_core` — raw dict keys surfaced to the UI.

### 5. My Positions / ledger — `renderers.py:3225-3559` (9 `st.metric`, 22 numbers)

Row-level metrics are Δ, Θ/day, unrealized P&L, "Dist. to pin %", "Pin maturity", "Edge
realization %", and a **1-day 95% VaR**. Three of those are inventions of this app
(`Pin maturity`, `Edge realization`, `Golden zone`), so no outside knowledge can rescue the
user — and their only definitions live in the glossary in a different tab
(`renderers.py:3004-3005`).

---

## 3. Jargon audit — what appears on screen with no translation attached

Counted across `renderers.py`, `render_pre_tabs.py`, `ui_helpers.py`:

| Term | On-screen occurrences | Has a native tooltip? |
|---|---:|---|
| skew | 69 | partial |
| delta / Δ | 61 | no |
| theta / Θ | 57 | partial (Θ/Γ column only) |
| Kelly | 31 | partial |
| gamma / Γ | 35 | no |
| DTE | 25 | no |
| RSI | 21 | no |
| Supertrend | 14 | no |
| OBV | 13 | no |
| GEX | 13 | no |
| ATR | 13 | no |
| ADX | 13 | no |
| vega | 12 | no |
| Gann | 11 | no |
| Hurst | 10 | no |
| Ichimoku | 9 | no |
| HMM | 7 | no |
| POC | 6 | no |
| σ (sigma) | 6 | no |
| VaR | 3 | no |
| OpEx | 3 | no |
| vanna, charm | 2 | no |

**`modules/explain.py` registers 66 terms**, covering all of the above plus this app's own
inventions (Gold Zone, Blue/Pink Diamond, Pre-Diamond Coil, Edge Score, Confluence Points,
Explosion Score, 10x Potential, Shadow Move, Attention Stage, Edge Realization, Crowd
Conviction). Every definition was read out of the implementation, not a textbook, and each
`formula` field cites the exact function — `tests/test_explain.py` asserts that citation
exists and that the quoted constants (`0.62/0.38` Edge blend, `1.35` Gold Zone POC weight,
`0.16` delta target, `10000` MC paths, `1.96` Wilson z, FFD `d=0.4`) still match the source.

---

## 4. The four parallel explanation systems (pick one)

The app already tries hard to explain itself. The problem is that it does so **four
different ways**, so the user never learns where to look:

| # | Mechanism | Where | Uses | Trigger |
|---|---|---|---|---|
| 1 | Native `help=` tooltip | widgets, `st.column_config` | 72 | hover the `?` |
| 2 | `_explain(title, body, mood)` — coloured HTML card, always visible | `ui_helpers.py:554-565` | 26 | none, always on |
| 3 | `_section(..., tip_plain=...)` — custom `.cf-tip` HTML span | `ui_helpers.py:567-574`, CSS `css.py:442-461` | 10 | hover a custom `i` |
| 4 | Quick Reference Guide — 27 HTML `edu-card`s in an expander | `renderers.py:2974-3016` | 1 | Intel → scroll → expand |

**Recommendation: keep #1 and #4, retire #2 and #3 into `explain.py`.**

- #1 is native, accessible, keyboard-reachable, and carries zero HTML-injection risk. It is
  what `explain.metric(term=...)` uses.
- #4 is the right *idea* (one canonical glossary) with the wrong *plumbing*: it is a
  hand-maintained list of HTML strings that can silently drift from the code. `explain.glossary()`
  is a drop-in replacement rendering the same content from `TERMS`, so a tooltip and the
  glossary can never disagree. The existing auto-open hook (`css.py:950-961`, matches the
  literal text `"Quick Reference"`) keeps working if the expander title is preserved.
- #2 (`_explain`) is genuinely good writing wrapped in the wrong container: it is *always
  expanded*, which is exactly the "forcing the detail on the user" the requirement rules out.
  Its content is the best raw material in the codebase and much of it was lifted directly
  into `TERMS[...].detail`.
- #3 (`.cf-tip`) is a hand-rolled tooltip that duplicates `help=` with worse accessibility
  and a mobile media query to patch (`css.py:618`).

---

## 5. Speed audit

| # | Problem | Location | Cost |
|---|---|---|---|
| S1 | **3 sequential `fetch_options` calls on the render path** to build the IV term-structure table — the tab cannot paint until Yahoo answers three times | `renderers.py:1071-1099` | 3 network round-trips per cold Cash Flow render |
| S2 | **Serial per-ticker loop** building the scanner's close-price map, while `options.py:450 scan_watchlist_edge_rows` does the same job with an 8-worker thread pool | `renderers.py:2332-2345` | O(n) round-trips; a 20-name watchlist is 20 sequential fetches |
| S3 | **`TA.hurst(df["Close"])` recomputed on every rerun**, uncached, on the render path — and `TA.hurst` is the slower variance-ratio estimator, not the cached one | `renderers.py:421` | full recompute on every widget interaction in the Signals fragment |
| S4 | **`fetch_options` on the main render path** for the selected expiry | `renderers.py:1160` | blocking; cached 300 s, so only cold, but it blocks paint |
| S5 | **`fetch_earnings_calendar_display` on the render path** | `renderers.py:2922` | blocking |
| S6 | **Ledger metrics fetch per symbol inside an aggregation function** — `_spot()` and `_realized_vol_20()` each call `fetch_stock` per ticker, twice (3mo and 6mo windows) | `ui_helpers.py:136-170` | 2 fetches × positions, on the render path |
| S7 | **14 `st.rerun()` calls**, several immediately after a config write; a rerun discards in-flight widget state and re-executes the whole script including the 1119-line CSS injection | `renderers.py:317, 1391, 1515, 1794, 2961, 3199, 3216, 3500, 3552, 3557`; `render_pre_tabs.py:186, 490, 497`; `app.py:260` | full page rebuild per click |
| S8 | **Two forever-running `setInterval` loops** injected into the page: one at 400 ms (re-asserting the hamburger + sidebar observer) and one at 1500 ms (re-hiding the Streamlit header) | `css.py:1076-1077` | continuous main-thread work for the life of the tab |
| S9 | **Sticky-nav tab switching is a retry loop of DOM clicks** — up to 30 retries at 120 ms, then a fixed 620 ms wait, then up to 50 scroll retries at 110 ms | `css.py:932-1001` | a nav click can take >1 s and can silently fail |
| S10 | **CSS + navbar re-injected before every widget on every rerun** | `app.py:190` → `css.py:1078` | ~40 KB of markdown per rerun |

**The good news:** the caching discipline is otherwise strong — 17 `@st.cache_data`
decorators in `data.py` with sensible TTLs, `@st.fragment` on all five tab renderers plus
the chart and watchlist editor, a deferred-first-pass options flag
(`config.py`, `defer_options_first_pass`), and a health-probe short-circuit before expensive
imports (`app.py:62-91`). `sentiment_radar.py:620-629` is the model to copy: one
`@st.cache_data(ttl=300)` wrapper around a `ThreadPoolExecutor` that fans out four
independent fetches. S1 and S2 should both become that pattern.

---

## 6. Inconsistency audit

| Concept | Names in use | Where |
|---|---|---|
| The 0-100 composite score | **"Edge Score"**, **"Quant Edge"**, **"Quant Edge Score"**, **"QE"**, `qs`, `Retail`/`Quant` columns | `renderers.py:170` vs `:560` vs `:2104` vs `:3496`; `ui_helpers.py:418`; `options.py:354` |
| Probability of profit | **"MC PoP %"**, **"MC PoP"**, **"PoP"**, `mc_pop`, `pop_pct` | `ui_helpers.py:1476,1500`; `renderers.py:1204,1324,1420`; `options.py:134` |
| Theta/gamma | **`Θ/Γ`** (raw glyph as a column header), **"Theta / Gamma"**, **"Θ/Γ Ratio"**, `theta_gamma_ratio` | `renderers.py:1199`; `ui_helpers.py:373-398` |
| Yield | **"Ann. Yield"**, `ann_yield`, "annualized", `prem_yield` with no display name | `options.py:2161`; `ui_helpers.py:1456` |
| Confluence | **"Confluence Points"**, **"Confluence"**, **"7/9"**, **"cp"** | `renderers.py:2985`; `ui_helpers.py:413-442` |
| A third 0-100 dial | **"unified probability"** — blends Edge + confluence + RS into *another* 0-100 number | `signal_desk.py:350-367` |

Formatting is equally scattered: **8 distinct numeric format specs** across the three UI
files, 287 sites in total (99×`:.0f`, 73×`:.2f`, 48×`:.1f`, 39×`:,.0f`, 17×`:,.2f`, plus `:.3f/.4f/.5f`), so the
same dollar amount appears as `$1235`, `$1,235`, and `$1234.50` on different screens.

Colour semantics are defined **inline, per screen**: `cp_color`, `qs_color`, `h_color`,
`wk_color`, the IV-rank pill (`ui_helpers.py:537`), the Θ/Γ line (`ui_helpers.py:383-397`),
and `_BENTO_ACCENTS` (`signal_desk.py:370-380`) each pick their own greens, ambers and reds
from **133 distinct hex literals**. Green does not reliably mean the same thing twice.

`explain.py` fixes the last two directly: `money() / pct() / ratio() / score() / compact() /
signed()` are the one implementation each, and `TONE_GLYPH` gives four tones with
*distinguishable glyphs* (🟢🟡🔴⚪) so the read survives colour-blindness and does not
require a new hex literal.

---

## 7. Dead weight

`modules/creator_signals.py` (1000 lines), `modules/asymmetry.py` (1356), and
`modules/dossier.py` (1416) are **untracked and referenced by no UI path** — 3,772 lines
that cannot be reached from `app.py`. They cost nothing at runtime but they make the
codebase look twice as complicated as the shipped app actually is. Decide: wire them in or
delete them.

---

## 8. Proposed information architecture

**From 11 tab surfaces + 10 nav links → 4 tabs, no nested tabs, no parallel nav.**

| # | Tab | What it is FOR (one sentence) | Absorbs |
|---|---|---|---|
| 1 | **Today** | *What should I do with this stock right now?* | Signals tab, the execution strip, the glance row, the chart |
| 2 | **Income** | *If I sell an option here, which one and what do I earn?* | Cash Flow tab (trimmed to the recommended trade + one table) |
| 3 | **Find** | *Which of my tickers, or the wider market, is worth looking at?* | Scanner, Market Radar, Sentiment Radar — three scanners that answer one question |
| 4 | **Mine** | *What am I holding and how is it doing?* | My Positions / ledger |

Everything else becomes progressive disclosure rather than a destination:

- **Quant diagnostics, backtest, correlation matrix, full option chain, IV term structure,
  GEX by strike** → expanders inside the tab that owns them. They are already expanders in
  several cases; the change is that they stop being *tabs*.
- **News / Macro / Earnings** (`renderers.py:2893`, currently 3 nested tabs) → one collapsed
  "Context" expander on **Today**. It is background, never the next action.
- **Quick Reference Guide** → promoted out of Intel to a persistent **"?" in the header**,
  rendering `explain.glossary()`. A glossary that is three clicks deep is a glossary nobody
  reads.
- **Sticky nav (10 links)** → delete. It exists only because the tabs are too long to scroll,
  and it needs 100+ lines of retry-loop JavaScript (`css.py:905-1033`) to work around the
  fact that anchors inside inactive Streamlit tabs are not mounted. Four short tabs need no
  jump links, and deleting it removes S9 entirely.
- **Mission Control's 8 controls** → **1 visible** (ticker picker) plus a **"Settings"**
  expander for the other seven. Strategy, horizon, scanner order, hemisphere, capital, turbo
  and quant mode are all set-once preferences that already persist to `config.json`; they do
  not need to occupy the top of every page view.
- **Rename "Trading Hemisphere"** → *"What are you looking for?"* with options *"Income from
  options"* / *"Stocks that might run"*. Same switch, no new vocabulary.

Target density: **no screen shows more than 9 numbers without an expander.** Cash Flow's 85
becomes ~7 visible (recommended strike, credit, chance of profit, buffer, expiry, breakeven,
income per day) with the remaining 78 behind *"Show every strike"* and *"Show the maths"*.

---

## 9. The house rule: one verdict line per card

**Every card, panel, and table on the desk opens with a single plain-English sentence saying
what to do or what it means. No card ships without one.**

```python
from modules import explain

explain.verdict_line(
    "Sell the $185 call expiring Feb 21 — you collect $210 and keep the shares "
    "unless the stock rises 6%.",
    tone="good",
)
explain.metric("You collect", explain.money(210), term="prem_yield",
               hint="That is 1.4% of the stock's value, this month.")
explain.metric("Chance it works", explain.pct(84), term="mc_pop", tone="good",
               hint="Out of 10,000 simulated futures, 8,400 end profitably.")
explain.explain("mc_pop")   # collapsed: "What does 'Monte Carlo PoP' mean?"
```

Three enforceable sub-rules:

1. **The verdict comes before the numbers, not after.** Today the Signals tab renders the
   Hurst *number* at `renderers.py:428` and the plain-English explanation at `:432`. Swap them.
2. **If you cannot write the sentence, the card does not know what it is telling the user** —
   that is a signal to cut the card, not to write vaguer copy.
3. **Jargon may appear in the tooltip and the expander; never in the label alone.** Label the
   metric *"Chance it works"* and attach `term="mc_pop"`. `Θ/Γ` as a bare column header
   (`renderers.py:1199`) is the anti-pattern.

`explain.verdict_line()` renders via native `st.success/warning/error/info` — no HTML, and
the tone glyph means the state is readable without relying on colour.

---

## 10. Migration order

Ranked by **legibility gained per unit of risk**. Every step is independently shippable;
`explain.metric()` can replace a single number without touching anything else on the screen.

| # | Change | Files / functions | Blast radius | Why first |
|---|---|---|---|---|
| **1** | Add `term=` tooltips to the 12 worst bare numbers: MC PoP, Θ/Γ, delta, IV rank, Edge Score, confluence, Gold Zone, GEX, DTE, annualised yield, Hurst, VaR | `renderers.py:170, 428-430, 1199-1208, 3490-3500`; `ui_helpers.py:1486-1517` | **Tiny.** Additive `help=` on existing widgets; no layout change, no logic touched. | Biggest legibility win available, near-zero risk. Roughly 20 call sites. |
| **2** | Replace the Quick Reference `edu` list with `explain.glossary()` | `renderers.py:2974-3016` (delete 43 lines) | **Small, isolated.** One expander. Keep the title string `"Quick Reference Guide"` so the `css.py:950-961` auto-open hook still matches. | Kills the drift risk between tooltips and glossary permanently; 27 hand-written HTML entries become 66 generated ones. |
| **3** | Add `verdict_line()` to the top of the 6 primary cards: Recommended Trade, Diamond status, Setup Analysis, Scanner summary, Ledger summary, Radar summary | `renderers.py:321-450` (Setup), `:916-1060` (Cash Flow header), `:3225-3300` (ledger); `render_pre_tabs.py:1380-1400` (execution strip) | **Small.** Additive; one `st.success/info` per card above existing content. | This is the requirement's core deliverable. Nothing is removed, so it cannot regress. |
| **4** | Invert jargon-first ordering on the Signals tab: `_explain()` copy above the raw metric card | `renderers.py:421-446` (Hurst), and the 25 other `_explain()` sites | **Small.** Statement reordering within one function. | The plain English already exists and is well-written — it is just in second place. |
| **5** | Swap all `${x:,.2f}` / `${x:.0f}` hand-formatting for `explain.money/pct/ratio/compact` | `renderers.py`, `ui_helpers.py`, `render_pre_tabs.py` — 287 format-spec sites | **Medium.** Wide but mechanical; a wrong call site produces a visibly wrong string, not a crash. | Collapses 8 formatting conventions into 1. Do it file-by-file, verifying visually. |
| **6** | Convert `Opt.covered_calls` / `cash_secured_puts` result tables from 16 columns to 6, with the rest behind *"Show every column"* | `ui_helpers.py:1456-1517` (`_options_scan_dataframe`, `_options_scan_column_config`); `renderers.py:1300-1500` | **Medium.** Column config is centralised in `ui_helpers`, so the change lands in two functions, but every table that consumes them shifts. | Cash Flow's 85 numbers drop to roughly 25 in one edit. |
| **7** | Fix S1 + S2: wrap the IV term-structure fetch and the scanner close-map loop in one `@st.cache_data(ttl=300)` + `ThreadPoolExecutor`, copying `sentiment_radar.py:620-629` | `renderers.py:1071-1099`, `renderers.py:2332-2345` | **Medium.** Touches the fetch path; needs care that cached functions are never called *from* worker threads (the comment at `sentiment_radar.py:617-619` documents why). | Turns 3 + N sequential round-trips into 1 parallel batch. The single largest perceived-speed win. |
| **8** | Cache `TA.hurst` on the render path (or switch to the already-cached estimator) | `renderers.py:421` | **Tiny.** One line, wrap in a `@st.cache_data(ttl=300)` helper. | Cheap; removes a full recompute from every Signals-fragment interaction. |
| **9** | Collapse Mission Control to 1 visible control + a Settings expander | `render_pre_tabs.py:207-376` | **Medium-high.** Seven widget keys are read across `desk_locals.py`, `pages.py` and every tab; the keys must not change, only their container. | Recovers the top third of every page view. Do after 1-8 so the tabs are already legible. |
| **10** | Merge 6 tabs → 4 and delete the sticky nav | `app.py:328-353`; `css.py:566-620, 905-1033, 1086-1095` | **High.** Restructures `app.py`'s tab block, deletes ~180 lines of JS/CSS, and invalidates the `css.py:1019` tab-index map and every `<div id="...">` anchor. | The right destination, but it should be last: it is the only step that can break navigation, and steps 1-9 make each tab short enough that the nav is no longer needed. |
| **11** | Delete or wire up `creator_signals.py`, `asymmetry.py`, `dossier.py` | 3,772 untracked lines | **Zero at runtime** (nothing imports them). | Housekeeping; do it whenever. |

**Suggested first PR:** steps 1-3. About 30 call sites, entirely additive, no layout risk, and
it delivers the literal requirement — plain answer visible, math one click away — on the
screens where confusion is worst.

---

## 11. Honest counterpoint: what is *not* over-complicated

A simplification plan that calls everything bad is not an audit. These are genuinely good and
should be left alone:

- **The writing.** The `_explain()` bodies and the 27 glossary entries are some of the
  clearest plain-English finance copy I have read in a codebase — *"Think of a store where
  sales grow every single quarter"* (`renderers.py:415`). The problem is packaging, not prose.
  Most of `TERMS[...].detail` is derived from it.
- **Sentiment Radar** (`modules/sentiment_radar.py`) is already the model for the rest of the
  app: a "How to read this (30 seconds)" table, plain-English verdicts
  (`verdict_for_row`, `:532-554`), zero-buzz semantics that refuse to invent data, parallel
  cached fetching, and a no-fail outer shell (`:557-566`). Build the other tabs to look like
  this one.
- **The failure copy.** `app.py:244-250` explains a Yahoo rate-limit in terms a user can act
  on, including *why* it happens on shared IPs. Most apps print "Error fetching data".
- **The caching architecture.** 17 TTL-tuned `@st.cache_data` decorators, fragments on every
  tab, deferred first-pass options loading, and a health-probe short-circuit. The speed
  problems listed in §5 are ten specific leaks in an otherwise well-built system.
- **The maths.** `bs_greeks`, `MonteCarloEngine.calc_pop` (antithetic + fixed seed, so numbers
  do not jitter across reruns), the Wilson lower bound as an anti-hype guard, and the adaptive
  whale z-score window are correct and thoughtfully done. **None of this should be simplified.
  It should be explained.** That distinction is the whole point of `modules/explain.py`: the
  sophistication stays, the *obligation to already understand it* goes away.

---

## Appendix — `modules/explain.py` API

```python
from modules import explain

# ── Pure, importable without Streamlit ────────────────────────────────
explain.TERMS                    # 66 × Term(short, plain, detail, formula, label, aliases)
explain.lookup("Θ/Γ")            # resolves keys, labels and aliases → Term
explain.tooltip("mc_pop")        # text for a native help= parameter (None if unknown)
explain.missing_terms([...])     # migration aid: which jargon still lacks a definition
explain.check_registry()         # [] when healthy — asserted in tests
explain.money/pct/ratio/score/compact/signed        # the one formatter each
explain.tone_label / verdict_text / TONE_GLYPH      # 🟢🟡🔴⚪

# ── Rendering (imports streamlit internally, house pattern) ───────────
explain.verdict_line(text, tone)                    # the "so what", tops every card
explain.metric(label, value, term=, tone=, hint=)   # st.metric + native help= tooltip
explain.explain("gex")                              # "What does this mean?" expander
explain.term_badge("gex")                           # one-line caption for dense rows
explain.glossary()                                  # the whole registry, searchable
```

Tests: `tests/test_explain.py` — 45 tests, including one that imports the module in a
subprocess with `import streamlit` monkey-patched to raise, proving the registry and every
pure helper work with no Streamlit runtime.
