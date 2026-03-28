# 💰 CashFlow Strategic Command Center

**Repository:** [github.com/hasroonpervez/cashflow-trader](https://github.com/hasroonpervez/cashflow-trader)

> A high-density Streamlit trading terminal for options cash-flow execution, with a **HUD-style main column** (Mission Control + ticker tape + in-page watchlist editor), glass UI, persistent state, and decision-first intelligence blocks. The default Streamlit sidebar is hidden; controls live in the main scroll.

---

## Architecture (modular layout)

| Area | Location |
|------|----------|
| Streamlit UI + technical / options / scanner logic | `app.py` |
| Yahoo Finance access (thread-local `requests` session, retries, defensive empty frames) | `data/yf_engine.py` |
| Global theme CSS + sticky-nav / settings FAB boot script | `assets/styles.css`, `assets/routing.js` → `inject_assets()` in `app.py` |
| Desk preferences (watchlist, strategy, overlays, Turbo, scanner order) | `st.session_state` only (`_cf_app_config`); **the app does not write `config.json`** |
| Optional legacy seed | If `config.json` is present at startup, it is **read once per browser session** to hydrate session state (migration / local convenience) |

Quant engines (Black–Scholes, Hurst exponent, Kelly criterion, and related desk math) live in `app.py` and were **not** refactored for this modular split.

---

## What Changed In This Release

### ✅ Execution strip & signal logic (v14.1)
- **Recommended Trade** (Primary Mission Objective): **`_iv_rank_pill_html`** always renders an **IV RANK (PROXY)** pill — numeric rank when `compute_iv_rank_proxy` succeeds, or clear stubs (**chain offline**, **no desk strike yet**, **no reference IV**, **curve too thin**). Desk reference IV is parsed once after the early options fetch and reused for the mission card and the BLUF IV row.
- **“Why this trade?”** (`cf-tip`) uses **`_confluence_why_trade_plain`**, the same **7 headline confluence checklist** as Diamond cards (Supertrend, Ichimoku, ADX, OBV, Divergence, Gold Zone, Structure), including when the chain or strike line is empty.
- **Blue Diamond** now requires **multi-timeframe agreement**: confluence must **cross up to 7+**, **daily market structure must be BULLISH** on that bar, and the **weekly MACD/EMA bias must not be BEARISH** (weekly bias is still evaluated from the current weekly frame; daily structure is evaluated per bar in the scan). Chart legend hovers and the Quick Reference glossary match this definition.
- **Weekly trend label** (`weekly_trend_label`) is **hardened**: requires a **`pandas.DataFrame`**, validates **`Close`**, length, numeric coercion, and try/except so the main desk and **Market Scanner** never throw on thin, malformed, or non-frame weekly inputs.
- **Streamlit widget labels (ASCII):** Mission Control **Turbo** toggle reads **`Turbo mode`** (no emoji in the widget label). Watchlist UI uses **`Edit watchlist symbols`** (expander), **`Open watchlist editor`** (tape shortcut), and plain **Move up / Move down / Remove symbol** buttons — stable explicit `key=` values are unchanged (`sb_mini_mode`, `sb_strat_radio`, etc.) so session state and optional legacy `config.json` stay aligned.
- **Early options / BLUF path** is wrapped in defensive parsing: safe expiry strings, tuple unpacking, and fallbacks so missing or quiet option chains do not crash the page.
- **Mission Control segments:** Streamlit’s `st.segmented_control` renders as **`data-testid="stButtonGroup"`** on current builds; HUD CSS styles **`stButtonGroup` and legacy `stSegmentedControl`** so unselected pills stay **dark with readable text** (not default light fills).

### ✅ HUD / Mission Control layout (v14.0+)
- **Main column first:** A bordered **MISSION CONTROL** bar sits directly under the sticky nav (NOC-style: switches above the “monitors”).
- **Target ticker** `selectbox`, **Strategy** (`st.segmented_control` when available, else horizontal `radio`), **Turbo** (`mini_mode`), **option horizon**, and **scanner sort** all live in Mission Control.
- **Watchlist tape:** one tap per symbol to set the active ticker; **primary** button highlights the selection. Rows show a **cached daily % change** (last vs prior session). Long lists wrap in **chunks of 8** columns so mobile stays usable. Tape taps use a **staging key** (`_sb_watch_selected_sync`) so `session_state` stays compatible with Streamlit 1.33+ (no mutating the selectbox key after the widget exists).
- **No sidebar workflow:** The Streamlit sidebar is **hidden in CSS**; all list editing is in the **main column**. **`Edit watchlist symbols`** is a **`st.expander` at the top of main** (it runs **before** Mission Control so `sb_scanner` is current on the same run). **`Open watchlist editor`** under the tape sets `_open_watchlist_editor` and reruns once to expand the editor. Footer line: **Data: Yahoo Finance · Not advice**.
- **High-contrast HUD labels:** Mission Control row titles use a dedicated **`cf-hud-label`** style so **Strategy**, **Option horizon**, and similar fields stay readable on dark backgrounds (including segmented controls).
- **Sticky nav** still jumps to Execution, Charts, Setup, Quant, Strategies, Risk, Scanner, News, Guide (`initial_sidebar_state="collapsed"` remains for hosts that still mount an empty sidebar region).
- **Live Pulse** header after a successful data load: timestamp pill so you can see the feed is fresh at a glance.

### ✅ Technical chart — fragment + four Plotly panels
- **Chart layers** (EMAs, Fib, Gann, S/R, Ichimoku, Supertrend, diamonds, gold zone line) live under **Technical Chart** inside a **`@st.fragment`** region. Toggling layers **reruns the fragment only** — it does **not** re-fetch Yahoo OHLC for the main ticker on every overlay flip.
- Overlay preferences persist in **session state** (merged via `save_config` into `_cf_app_config`); see **Configuration & persistence**.
- The **Technical Chart** section still renders **four charts**: **Price & overlays**, **Volume**, **RSI (14)**, and **MACD** (independent zoom/pan, `hovermode: x unified` per panel).
- **Gold Zone** blends **Volume Profile POC**, **61.8% Fib** (60-bar window), **200-day SMA** when history allows, and **nearest Gann Square of 9** level (mean of available components).

### ✅ Performance & mobile
- **Yahoo access:** OHLC and options use **`@st.cache_data`** in `app.py` with TTLs; implementations call **`data/yf_engine.py`**, which uses a **thread-local `requests.Session`** (custom User-Agent) and **exponential backoff** on failures. Each call still uses a fresh `yf.Ticker(..., session=...)` to avoid stale state on large watchlists.
- **Cold load:** The five independent Yahoo calls in `main()` (**equity daily, equity weekly, macro, news, earnings**) run in parallel via **`ThreadPoolExecutor`**.
- **Options:** `fetch_options(ticker)` with **`exp=None`** returns **expiration strings only** (no `option_chain` download). Call again with a chosen expiry when you need strikes (saves one redundant chain pull per load).
- **Confluence + Gold Zone:** On the full dataframe, **Gold Zone is computed once** and passed into **`calc_confluence_points(..., gold_zone_price=...)`** so POC/Fib/SMA/Gann are not duplicated for the same bar.
- **`calc_gold_zone`** is **not** wrapped in `st.cache_data`: in the diamond loop every prefix `df.iloc[:i+1]` is a distinct frame, so dataframe-keyed caching did not hit and only added hashing cost.
- **Glance row:** When **`len(df) >= 7`**, the price sparkline reuses **`df["Close"].tail(7)`** instead of a separate `1mo` history fetch.
- **Quant Edge:** ATR is computed **once** per score (single `TA.atr(df)` series) for the volatility pillar.
- **Market Scanner** uses a **thread pool** (up to 8 workers) so watchlist symbols fetch in parallel.
- **`load_config()`** returns settings from **`st.session_state`**, seeded from **defaults**, **scalar `st.secrets`** (Streamlit Cloud), and an **optional one-time read** of `config.json` if the file exists.
- **`mini_mode`** (**Turbo mode** toggle in Mission Control) persists in **session state** and **skips heavy Plotly** (`build_chart` and the four technical panels, volume-profile bar chart, simulator equity chart) while keeping the glance row, execution strip, quant dashboard, and scanner. The **`@st.fragment` technical zone returns immediately** in Turbo mode — it does **not** call `build_chart`. It shows a **Turbo · Technical Summary** card: **price**, **structure**, **confluence score**, **Gold Zone** distance, and **Diamond** status. With Turbo on, the app injects **denser main-column CSS** from `assets/styles.css` (mini-density block) so more fits on one phone screen.
- **CSS:** Theme lives in **`assets/styles.css`** (imported at runtime). The shell uses `touch-action: manipulation`, `min-height: 100dvh`, and touch hints on the sticky nav to reduce mobile zoom/jitter.

### ✅ Persistent user state (watchlist + scan ordering)
- **Session-only persistence:** `watchlist`, `scanner_sort_mode`, **Strategy** (`strat_focus`, `strat_horizon`), **Turbo / `mini_mode`**, and **chart overlay** toggles (`overlay_*`) are stored under **`st.session_state[_cf_app_config]`** via `save_config()`. **Nothing is written back to `config.json`.**
- **Watchlist editor** (main column → **Edit watchlist symbols** expander):
  - **Textarea** for symbols — **commas, newlines, or semicolons**; duplicates removed; uppercase normalization.
  - Auto-saves merge into session config; **Save and refresh** commits the textarea to session state and reruns (no disk write).
  - **Reorder:** **Move up**, **Move down**, **Remove symbol**, **Sort A to Z**, **Quick add** + **Add symbol**.
- **Scanner order** (`Custom watchlist order` vs `Highest confluence first`) is controlled from **Mission Control** (main column).
- **Streamlit-safe session updates:** staging keys **`_sb_scanner_sync`**, **`_sb_watch_selected_sync`**, **`_sb_add_ticker_clear`**, **`_open_watchlist_editor`** are applied **before** widgets that own those values are built, avoiding `StreamlitAPIException` on reorder, add, or tape taps.
- **Default watchlist** (when no legacy file and no secrets override): `PLTR,BMNR,AAPL,AMZN,NVDA,AMD,TSLA,SPY,QQQ`
- **Optional `config.json`:** if present, read **once per session** on first load to seed state; legacy keys from older builds are stripped. Use the sample in-repo `config.json` only as a **template** or migration aid — the live app does not update it.

### ✅ Institutional glass UI infrastructure
- Global CSS lives in **`assets/styles.css`** and is injected through **`inject_assets()`** (plus optional mini-density CSS when Turbo is on). The aesthetic is a **high-density terminal** look:
  - glass cards with blur/backdrop filtering,
  - tight spacing between widgets and sections,
  - reduced visual noise and less default Streamlit chrome.
- **Mission Control** uses the bordered main `st.container` shell with extra cyan border / depth so the HUD reads as one integrated panel above the scroll.
- Main content width is now constrained to `max-width: 1400px` for consistent desktop scanning.
- Card system now uses a unified treatment:
  - `background: rgba(15, 23, 42, 0.65)`
  - `backdrop-filter: blur(12px)`
  - `border: 1px solid rgba(255, 255, 255, 0.1)`
  - cyan inner glow + soft drop shadow.

### ✅ Typography + Palette Upgrade
- Font system:
  - **Inter** for prose and interface copy,
  - **JetBrains Mono** for prices, tickers, and numerical data.
- Numeric stability:
  - `font-variant-numeric: tabular-nums` used for price-heavy surfaces to reduce jitter during live updates.
- Color system now includes explicit semantic roles:
  - Primary: `#00E5FF`
  - Success: `#00FFA3`
  - Danger: `#FF005C`
  - Gold: `#FFD700`

### ✅ 4-Column “Glance” Header (with Sparklines)
- Header was refactored from static metric cards into a responsive 4-column glance strip:
  1. Price
  2. VIX
  3. Earnings countdown
  4. Quant Edge
- Price/VIX/Earnings/Quant Edge cards include simplified **7-day right-aligned** trend lines (**inline SVG**, not Plotly) so the row stays aligned on narrow viewports.
- Layout stays single-row on desktop and wraps cleanly on narrower widths.

### ✅ Mission Card / Execution UX
- “Action Required” presentation was upgraded to a **Primary Mission Objective** card (left column of the **execution shell**), paired with the **BLUF** context column (quant edge, confluence bar, weekly trend, Gold Zone, IV rank strip).
- Card now uses a softer pulsating cyan glow (`box-shadow` pulse) for less visual fatigue.
- Broker-style steps use a centered horizontal **1 → 2 → 3 ghost stepper** with cyan focus glow on hover.
- v14.1 adds an **always-on IV rank pill** on the mission card and **Why this trade?** (`cf-tip`) tied to the **7-factor** checklist; offline, empty-chain, or no-strike states still show both pill stubs and the tip.

### ✅ New PLTR Earnings Intelligence Section
- Added dedicated **Strategic Intelligence earnings drawer** (custom-styled expander) with dual-column catalyst/risk framing.
- Includes high-density “Good vs Bad” bullets tied to Feb 2, 2026 report context and May 4, 2026 projection context.
- Includes upcoming print countdown and projected EPS range (`$0.26` to `$0.29`).

### ✅ Dense Data Tracking Enhancements
- Added hover transitions and highlight color on table rows to help track lines across wide data grids.
- Global spacing across vertical/horizontal blocks was tightened for faster dashboard navigation.
- Scanner rows remain hover-highlighted for easier watchlist tracking.
- Scanner rows are constrained for single-line dense readability (reduced wrapping, overflow-safe summary handling).
- Quick Reference Guide was compressed into a denser 2-column “reference manual” style with smaller typography.

### ✅ Strategic Intelligence Drawer
- Earnings intelligence now renders in a custom-styled expander drawer:
  - `📊 STRATEGIC INTELLIGENCE: Q4 2025 / 2026 OUTLOOK`
  - glassmorphism container styling aligned with the terminal theme
  - dual-column Good vs Bad intelligence layout with tighter list density.

---

## Current Feature Set

### 📈 Advanced Chart & Signal Engine
- **Four charts:** price (+ overlays), volume bars, RSI, MACD — see **Technical chart — fragment + four Plotly panels** above.
- **Chart layers** toggles live under **Technical Chart** (fragment-isolated); overlays include EMAs, Bollinger, Ichimoku, Supertrend, Fibonacci, Gann, S/R, diamond markers, and Gold Zone line.
- Market structure + confluence scoring (0–9) with per-factor breakdown
- **Blue / Pink Diamond** signals; **Blue** requires a **7+ confluence cross**, **BULLISH daily structure** on that bar, **weekly bias ≠ BEARISH**, plus volume/ATR institutional filters. **Gold Zone** = blend of POC, 61.8% Fib (60 bars), **200-day SMA** (when data allows), and nearest Gann Sq9 level

### 💰 Cash-Flow Strategy Engine
- Covered Call analyzer
- Cash-Secured Put analyzer
- Credit spread scoring
- Single **Primary Mission Objective** execution recommendation with **always-visible IV rank (proxy) pill** and **Why this trade?** tooltip (confluence checklist)

### 📊 Scanner + Multi-Ticker Workflow
- Batch scan watchlist for:
  - confluence points,
  - diamond status,
  - quant edge,
  - Gold Zone distance.
- **Mission Control** target + **watchlist tape** for fast ticker switching; full list edit in **✏️ Edit Watchlist Symbols** (top expander or button under the tape).
- Scanner output order is set in **Mission Control** (`Custom watchlist order` vs confluence-first).

### 🧠 Risk, Sentiment, and Backtesting
- Composite fear/greed framework with VIX context
- Position sizing and risk controls
- Covered call simulation module with performance stats

### 📚 Embedded Education Layer
- Plain-language explainers and actionable tooltips
- Quick-reference guide for indicators and strategy components

---

## Installation & Setup

### Prerequisites
- Python 3.9+
- `pip`
- **Streamlit** is **pinned** in `requirements.txt` (strict `==`) to reduce breakage from Streamlit/React DOM changes around custom CSS and `components.v1.html`. The app targets **`st.fragment`** (chart layers), **`st.segmented_control`** when available (falls back to horizontal `st.radio`), and styles both **`stButtonGroup`** and legacy segmented-control test IDs in CSS.

### Install
```bash
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### Run
```bash
streamlit run app.py
```

App URL: `http://localhost:8501`

---

## Configuration & persistence

Desk settings live in **`st.session_state`** (`_cf_app_config`). They are merged from, in order:

1. Built-in **defaults** (see `DEFAULT_CONFIG` in `app.py`)
2. **Scalar top-level keys** from **`st.secrets`** (Streamlit Cloud), when names match persisted keys
3. **Optional one-time import** from **`config.json`** in the project root, if the file exists when the session first initializes

The app **never writes** `config.json`. Failed saves to session state surface a **toast** (`Failed to save settings`); failed legacy file reads toast once (`Could not read legacy config.json`).

### Persisted keys (session + optional legacy file)
| Key | Purpose |
|-----|---------|
| `watchlist` | Comma-separated scanner tickers |
| `scanner_sort_mode` | Scanner output order preference |
| `strat_focus` | Mission Control **Strategy**: `Sell premium`, `Hybrid`, or `Growth` |
| `strat_horizon` | Mission Control **Horizon**: `Weekly`, `30 DTE`, or `45 DTE` |
| `overlay_ema` | EMA overlay on (Technical Chart → Chart layers) |
| `overlay_fib` | Fibonacci overlay on |
| `overlay_gann` | Gann overlay on |
| `overlay_sr` | Support/resistance overlay on |
| `overlay_ichi` | Ichimoku overlay on |
| `overlay_super` | Supertrend overlay on |
| `overlay_diamonds` | Diamond signals overlay on |
| `overlay_gold` | Gold zone line on price chart |
| `mini_mode` | **Turbo mode** in Mission Control — lighter UI (skips heavy Plotly blocks; shows **Turbo · Technical Summary** instead of the four-chart stack) |

---

## Migration notes (existing users)

1. **Pull** the latest repo (includes `app.py`, `data/`, `assets/`, `requirements.txt`, `README.md`).
2. **Reinstall deps** (pinned versions): `pip install -r requirements.txt`
3. **Optional:** Keep a **`config.json`** next to `app.py` if you want the **first session** to import your old watchlist / preferences. After that, changes live only in the browser session (and Cloud secrets where configured).
4. Run `streamlit run app.py` and confirm **Edit watchlist symbols** / Mission Control match what you expect.

### About missing keys in `config.json`
- Partial JSON files are merged with **defaults** on first load; unknown legacy keys are dropped.
- The in-repo **`config.json`** is a **reference template** — you can delete it, shrink it to only the keys you care about, or omit it entirely.

### Optional legacy seed file
See the root **`config.json`** in this repository for a full example of keys the importer understands. Edit copy/paste as needed; the running app **does not update this file**.

---

## QA Verification

Latest QA sweep performed against current `app.py` included:

- Lint diagnostics: no issues reported on `app.py`.
- Python syntax parse: `python3 -c "import ast; ast.parse(open('app.py').read())"` (pass).
- **Plotly 5.x** (pinned in `requirements.txt`): chart layout uses validators-safe patterns (axis `title_text` / `title_font`, `legend.itemwidth` ≥ 30, `hoverlabel.font` as nested `font` dict).
- Runtime boot smoke check (headless Streamlit):
  - app starts successfully and serves local URL
  - no startup exceptions observed.

Residual manual QA recommended:
- viewport pass at 1400/1200/992/768 widths,
- live market/open-hours data behavior (yfinance variability),
- **Mission Control:** Strategy / Option horizon segments readable on dark HUD (unselected pills not white-on-white), Turbo, horizon, scanner sort, target selectbox sync with **ticker tape** (no `StreamlitAPIException` when tapping tape symbols),
- **Execution strip:** IV rank pill always visible (number or stub); **Why this trade?** tooltip matches confluence checklist copy,
- **Turbo mode:** Technical **fragment** shows summary card only — confirm **`build_chart` is not invoked** (no four-chart Plotly stack),
- **Watchlist editor:** textarea, reorder, remove, Sort A to Z, quick add, **Save and refresh**; bottom button opens the expander on rerun,
- **Technical Chart:** flip overlay toggles and confirm charts update without a full refetch feeling (fragment rerun).

---

## Project structure

```
cashflow-trader/
├── app.py              # Streamlit app, UI flow, TA / options / scanner logic, quant engines
├── assets/
│   ├── styles.css      # Global theme + mini-mode density (injected via inject_assets)
│   └── routing.js      # Sticky-nav hash routing + sidebar FAB bootstrap (components.v1.html)
├── data/
│   ├── __init__.py
│   └── yf_engine.py    # Yahoo Finance: session, retries, fetch_* implementations
├── config.json         # Optional: one-time per-session import template (not written by the app)
├── requirements.txt    # Pinned Python dependencies
└── README.md           # This file
```

---

## Important Disclaimer

⚠️ Educational/informational tool only. Not financial advice.

- Options involve substantial risk.
- Past performance does not guarantee future results.
- Verify all broker-side order details before execution.
- Backtests and model outputs are approximations, not guarantees.

---

## License

Personal use only. Not for redistribution.
