# 💰 CashFlow Strategic Command Center

**Repository:** [github.com/hasroonpervez/cashflow-trader](https://github.com/hasroonpervez/cashflow-trader)

> A high-density Streamlit trading terminal for options cash-flow execution, with a **HUD-style main column** (Mission Control + ticker tape), glass UI, persistent state, and decision-first intelligence blocks.

---

## What Changed In This Release

### ✅ HUD / Mission Control layout (v14.1)
- **Main column first:** A bordered **MISSION CONTROL** bar sits directly under the sticky nav (NOC-style: switches above the “monitors”).
- **Target ticker** `selectbox`, **Strategy** (`st.segmented_control` when available, else horizontal `radio`), **Turbo** (`mini_mode`), **option horizon**, and **scanner sort** all live in Mission Control — not buried in the sidebar.
- **Watchlist tape:** one tap per symbol to set the active ticker; **primary** button highlights the selection. Rows show a **cached daily % change** (last vs prior session). Long lists wrap in **chunks of 8** columns so mobile stays usable.
- **Sidebar = paperwork:** **`⚙️ System Config`** with **`Edit Watchlist Symbols`** expander (textarea, reorder, quick add, **Save & refresh main**). The sidebar block runs **first** in `main()` so `sb_scanner` is up to date before Mission Control reads it.
- **Glass sidebar:** translucent panel with blur and cyan border; **`stSidebarNav` hidden** — use the **☰ FAB** to open settings when you need the list editor.
- **App opens with the sidebar collapsed** (`initial_sidebar_state="collapsed"`) so you land on Mission Control without an extra tap.
- **Live Pulse** header after a successful data load: timestamp pill so you can see the feed is fresh at a glance.

### ✅ Technical chart — fragment + four Plotly panels
- **Chart layers** (EMAs, Fib, Gann, S/R, Ichimoku, Supertrend, diamonds, gold zone line) live under **Technical Chart** inside a **`@st.fragment`** region. Toggling layers **reruns the fragment only** — it does **not** re-fetch Yahoo OHLC for the main ticker on every overlay flip.
- Overlay preferences still persist under **`overlay_*`** in `config.json` via a merge onto the latest file-backed config (see **Persisted Keys**).
- The **Technical Chart** section still renders **four charts**: **Price & overlays**, **Volume**, **RSI (14)**, and **MACD** (independent zoom/pan, `hovermode: x unified` per panel).
- **Gold Zone** blends **Volume Profile POC**, **61.8% Fib** (60-bar window), **200-day SMA** when history allows, and **nearest Gann Square of 9** level (mean of available components).

### ✅ Performance & mobile
- **`st.cache_resource`** caches Yahoo **`Ticker`** objects; OHLC still uses **`st.cache_data`** with TTL.
- **Market Scanner** uses a **thread pool** (up to 8 workers) so watchlist symbols fetch in parallel.
- **`load_config()`** merges **`st.secrets`** (scalar top-level keys only, for Streamlit Cloud) with **`config.json`**.
- **`mini_mode`** (**🚀 Turbo** in Mission Control) persists in `config.json` and **skips heavy Plotly** (technical stack, volume-profile bar chart, simulator equity chart) while keeping the glance row, execution strip, quant dashboard, and scanner. With Turbo on, the app injects **denser main-column CSS** (tighter padding, smaller section headers and cards) so more fits on one phone screen.
- **CSS:** `touch-action: manipulation`, `min-height: 100dvh` on the app shell, and touch hints on the sticky nav / FAB to reduce mobile zoom/jitter.

### ✅ Persistent User State (Watchlist + Scan Ordering)
- `config.json` persistence includes `watchlist`, `scanner_sort_mode`, **Strategy** (`strat_focus`, `strat_horizon`), **Turbo / mini_mode**, and **Chart overlay** toggles (`overlay_*`).
- **Watchlist editor** (sidebar → **Edit Watchlist Symbols**):
  - **Textarea** for symbols — **commas, newlines, or semicolons**; duplicates removed; uppercase normalization.
  - Auto-saves with the usual **`watch_cfg`** merge; optional **Save & refresh main** forces a disk write + rerun.
  - **Reorder:** **↑ / ↓**, **✕ Remove**, **Sort A–Z**, **Quick add** + **Add symbol**.
- **Scanner order** (`Custom watchlist order` vs `Highest confluence first`) is controlled from **Mission Control** (main column).
- **Streamlit-safe session updates:** staging keys **`_sb_scanner_sync`**, **`_sb_watch_selected_sync`**, **`_sb_add_ticker_clear`** are applied **before** the textarea / quick-add widgets are built, avoiding `StreamlitAPIException` on reorder/add.
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
- Price/VIX/Earnings/Quant Edge cards include simplified **7-day right-aligned** trend lines (**inline SVG**, not Plotly) so the row stays aligned when the **sidebar is open** or the main column is narrow.
- Layout stays single-row on desktop and wraps cleanly on narrower widths.

### ✅ Mission Card / Execution UX
- “Action Required” presentation was upgraded to a **Primary Mission Objective** card.
- Card now uses a softer pulsating cyan glow (`box-shadow` pulse) for less visual fatigue.
- Robinhood execution instructions use a centered horizontal **1 → 2 → 3 ghost stepper** with cyan focus glow on hover.

### ✅ New PLTR Earnings Intelligence Section
- Added dedicated **Strategic Intelligence earnings drawer** (custom-styled expander) with dual-column catalyst/risk framing.
- Includes high-density “Good vs Bad” bullets tied to Feb 2, 2026 report context and May 4, 2026 projection context.
- Includes upcoming print countdown and projected EPS range (`$0.26-$0.29`).

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
- Market structure + confluence scoring
- Diamond signal state; **Gold Zone** = blend of POC, 61.8% Fib (60 bars), **200-day SMA** (when data allows), and nearest Gann Sq9 level

### 💰 Cash-Flow Strategy Engine
- Covered Call analyzer
- Cash-Secured Put analyzer
- Credit spread scoring
- Single “mission objective” execution recommendation

### 📊 Scanner + Multi-Ticker Workflow
- Batch scan watchlist for:
  - confluence points,
  - diamond status,
  - quant edge,
  - Gold Zone distance.
- **Mission Control** target + **watchlist tape** for fast ticker switching; full list edit in **sidebar → Edit Watchlist Symbols**.
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
- **Streamlit ≥ 1.33** recommended (`st.fragment` for chart layers; `st.segmented_control` when your Streamlit build includes it, with radio fallback otherwise).

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
| `mini_mode` | **🚀 Turbo** in Mission Control — lighter UI (skips heavy Plotly blocks listed in Performance section) |

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
4. Open the sidebar (**☰**), expand **Edit Watchlist Symbols**, and confirm your watchlist loaded correctly.

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
- **Mission Control:** strategy segments, Turbo, horizon, scanner sort, target selectbox sync with **ticker tape**,
- **Sidebar:** **Edit Watchlist Symbols** — textarea, reorder, remove, Sort A–Z, quick add, **Save & refresh main** (no `StreamlitAPIException` from staging keys),
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
