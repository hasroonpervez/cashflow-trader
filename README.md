# 💰 CashFlow Strategic Command Center

**Repository:** [github.com/hasroonpervez/cashflow-trader](https://github.com/hasroonpervez/cashflow-trader)

> A high-density Streamlit trading terminal for options cash-flow execution, with a **HUD-style main column** (Mission Control + ticker tape + in-page watchlist editor), glass UI, persistent state, and decision-first intelligence blocks. The default Streamlit sidebar is hidden; controls live in the main scroll.

---

## What Changed In This Release

### ✅ Execution strip & signal logic (v14.1)
- **Recommended Trade** (Primary Mission Objective): **`_iv_rank_pill_html`** always renders an **IV RANK (PROXY)** pill — numeric rank when `compute_iv_rank_proxy` succeeds, or clear stubs (**chain offline**, **no desk strike yet**, **no reference IV**, **curve too thin**). Desk reference IV is parsed once after the early options fetch and reused for the mission card and the BLUF IV row.
- **“Why this trade?”** (`cf-tip`) uses **`_confluence_why_trade_plain`**, the same **7 headline confluence checklist** as Diamond cards (Supertrend, Ichimoku, ADX, OBV, Divergence, Gold Zone, Structure), including when the chain or strike line is empty.
- **Blue Diamond** now requires **multi-timeframe agreement**: confluence must **cross up to 7+**, **daily market structure must be BULLISH** on that bar, and the **weekly MACD/EMA bias must not be BEARISH** (weekly bias is still evaluated from the current weekly frame; daily structure is evaluated per bar in the scan). Chart legend hovers and the Quick Reference glossary match this definition.
- **Weekly trend label** (`weekly_trend_label`) is **hardened**: requires a **`pandas.DataFrame`**, validates **`Close`**, length, numeric coercion, and try/except so the main desk and **Market Scanner** never throw on thin, malformed, or non-frame weekly inputs.
- **Streamlit widget labels (ASCII):** Mission Control **Turbo** toggle reads **`Turbo mode`** (no emoji in the widget label). Watchlist UI uses **`Edit watchlist symbols`** (expander), **`Open watchlist editor`** (tape shortcut), and plain **Move up / Move down / Remove symbol** buttons — stable explicit `key=` values are unchanged (`sb_mini_mode`, `sb_strat_radio`, etc.) so `config.json` and sessions stay compatible.
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
- Overlay preferences still persist under **`overlay_*`** in `config.json` via a merge onto the latest file-backed config (see **Persisted Keys**).
- The **Technical Chart** section still renders **four charts**: **Price & overlays**, **Volume**, **RSI (14)**, and **MACD** (independent zoom/pan, `hovermode: x unified` per panel).
- **Gold Zone** blends **Volume Profile POC**, **61.8% Fib** (60-bar window), **200-day SMA** when history allows, and **nearest Gann Square of 9** level (mean of available components).

### ✅ Performance & mobile
- **Yahoo access:** OHLC and options use **`@st.cache_data`** with TTLs. The app uses **`_yfinance_ticker()`** (fresh `yf.Ticker` per call) to avoid stale sessions and unbounded cached connections on large watchlists.
- **Cold load:** The five independent Yahoo calls in `main()` (**equity daily, equity weekly, macro, news, earnings**) run in parallel via **`ThreadPoolExecutor`**.
- **Options:** `fetch_options(ticker)` with **`exp=None`** returns **expiration strings only** (no `option_chain` download). Call again with a chosen expiry when you need strikes (saves one redundant chain pull per load).
- **Confluence + Gold Zone:** On the full dataframe, **Gold Zone is computed once** and passed into **`calc_confluence_points(..., gold_zone_price=...)`** so POC/Fib/SMA/Gann are not duplicated for the same bar.
- **`calc_gold_zone`** is **not** wrapped in `st.cache_data`: in the diamond loop every prefix `df.iloc[:i+1]` is a distinct frame, so dataframe-keyed caching did not hit and only added hashing cost.
- **Glance row:** When **`len(df) >= 7`**, the price sparkline reuses **`df["Close"].tail(7)`** instead of a separate `1mo` history fetch.
- **Quant Edge:** ATR is computed **once** per score (single `TA.atr(df)` series) for the volatility pillar.
- **Market Scanner** uses a **thread pool** (up to 8 workers) so watchlist symbols fetch in parallel.
- **`load_config()`** merges **`st.secrets`** (scalar top-level keys only, for Streamlit Cloud) with **`config.json`**.
- **`mini_mode`** (**Turbo mode** toggle in Mission Control) persists in `config.json` and **skips heavy Plotly** (`build_chart` and the four technical panels, volume-profile bar chart, simulator equity chart) while keeping the glance row, execution strip, quant dashboard, and scanner. The **`@st.fragment` technical zone returns immediately** in Turbo mode — it does **not** call `build_chart`. It shows a **Turbo · Technical Summary** card: **price**, **structure**, **confluence score**, **Gold Zone** distance, and **Diamond** status. With Turbo on, the app injects **denser main-column CSS** (tighter padding, smaller section headers and cards) so more fits on one phone screen.
- **CSS:** `touch-action: manipulation`, `min-height: 100dvh` on the app shell, and touch hints on the sticky nav to reduce mobile zoom/jitter.

### ✅ Persistent User State (Watchlist + Scan Ordering)
- `config.json` persistence includes `watchlist`, `scanner_sort_mode`, **Strategy** (`strat_focus`, `strat_horizon`), **Turbo / mini_mode**, and **Chart overlay** toggles (`overlay_*`).
- **Watchlist editor** (main column → **Edit watchlist symbols** expander):
  - **Textarea** for symbols — **commas, newlines, or semicolons**; duplicates removed; uppercase normalization.
  - Auto-saves with the usual **`watch_cfg`** merge; **Save and refresh** forces a disk write + rerun.
  - **Reorder:** **Move up**, **Move down**, **Remove symbol**, **Sort A to Z**, **Quick add** + **Add symbol**.
- **Scanner order** (`Custom watchlist order` vs `Highest confluence first`) is controlled from **Mission Control** (main column).
- **Streamlit-safe session updates:** staging keys **`_sb_scanner_sync`**, **`_sb_watch_selected_sync`**, **`_sb_add_ticker_clear`**, **`_open_watchlist_editor`** are applied **before** widgets that own those values are built, avoiding `StreamlitAPIException` on reorder, add, or tape taps.
- Default bootstrap watchlist (only when config is missing/deleted):
  - `PLTR,BMNR,AAPL,AMZN,NVDA,AMD,TSLA,SPY,QQQ`
- `config.json` stores the keys listed under **Persisted Keys** below (legacy keys from older builds are stripped on load).

### ✅ Institutional Glass UI Infrastructure
- Global CSS architecture moved to a **high-density terminal aesthetic**:
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

### ✅ ADHD-Friendly Tooltip System
- `cf-tip` behavior was redesigned from browser-native title tooltips to a custom readable tooltip panel:
  - high-contrast dark background,
  - `border-left: 4px solid #00E5FF`,
  - readable `14px` font size.
- Streamlit tooltip containers were also styled to match this accessibility pattern.
- Forced minimum tooltip width for readability (`min-width: 350px`) with off-white text (`#f1f5f9`).

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
- **Streamlit ≥ 1.33** recommended (`st.fragment` for chart layers). **`st.segmented_control`** (Streamlit 1.39+ on many installs) maps to a **button group** in the DOM; the app styles both that widget and horizontal radios for Mission Control. Use **≥ 1.39** if you rely on segmented controls; older builds fall back to horizontal `st.radio`.

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

## Configuration & Persistence

All persistent settings are stored in `config.json` via atomic writes.

### Persisted Keys
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
| `mini_mode` | **🚀 Turbo** in Mission Control — lighter UI (skips heavy Plotly blocks; shows **Turbo · Technical Summary** instead of the four-chart stack) |

---

## Migration Notes (Existing Users)

If you are upgrading from an older version, use this safe sequence:

1. Back up your current config:
   ```bash
   cp config.json config.backup.json
   ```
2. Pull/copy the latest `app.py` and `README.md`.
3. Launch once with:
   ```bash
   streamlit run app.py
   ```
4. Expand **Edit watchlist symbols** at the top of the page (or use **Open watchlist editor** under the tape) and confirm your watchlist loaded correctly.

### About missing keys
- Old `config.json` files without newer keys are automatically backfilled by the app’s default config merge.
- New keys are saved automatically the next time the related Mission Control widget, chart-layer toggle, or watchlist flow updates config.
- No manual JSON editing is required unless you want to seed values ahead of first run.

### Optional manual seed example
If you want to prefill watchlist before launch:

```json
{
  "watchlist": "PLTR,BMNR,AAPL,AMZN,NVDA,AMD,TSLA,SPY,QQQ",
  "scanner_sort_mode": "Custom watchlist order",
  "strat_focus": "Hybrid",
  "strat_horizon": "30 DTE",
  "overlay_ema": true,
  "overlay_fib": true,
  "overlay_gann": true,
  "overlay_sr": true,
  "overlay_ichi": false,
  "overlay_super": false,
  "overlay_diamonds": true,
  "overlay_gold": true,
  "mini_mode": false
}
```

---

## QA Verification

Latest QA sweep performed against current `app.py` included:

- Lint diagnostics: no issues reported on `app.py`.
- Python syntax parse: `python3 -c "import ast; ast.parse(open('app.py').read())"` (pass).
- **Plotly 6:** chart layout uses validators-safe patterns (axis `title_text` / `title_font`, `legend.itemwidth` ≥ 30, `hoverlabel.font` as nested `font` dict).
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

## Project Structure

```
cashflow-trader/
├── app.py           # Main app logic + UI/CSS + engines
├── config.json      # Persisted runtime/user settings
├── requirements.txt # Python dependencies
└── README.md        # Project documentation
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
