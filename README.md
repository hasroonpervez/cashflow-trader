# 💰 CashFlow Strategic Command Center

**Repository:** [github.com/hasroonpervez/cashflow-trader](https://github.com/hasroonpervez/cashflow-trader)

> A high-density Streamlit trading terminal for options cash-flow execution, upgraded with persistent state, institutional glass UI, and decision-first intelligence blocks.

---

## What Changed In This Release

### ✅ Persistent User State (Watchlist + Scan Ordering)
- `config.json` persistence includes `watchlist` and `scanner_sort_mode`.
- Sidebar **Scanner Watchlist** uses a compact **textarea** (not a single-line field):
  - paste or type symbols separated by **commas, newlines, or semicolons**,
  - duplicates are removed; symbols are normalized to uppercase,
  - auto-saves on change,
  - remains persistent across refreshes/restarts.
- Watchlist controls:
  - **Reorder / remove** dropdown + full-width **↑ Move up**, **↓ Move down**, **✕ Remove**, **Sort A–Z** (avoids cramped 3-column buttons in the narrow sidebar),
  - **Quick add** + **Add symbol** for a single ticker without editing the whole list,
  - scan result order: `Custom watchlist order` vs `Highest confluence first` (horizontal radio).
- **Streamlit-safe session updates:** programmatic list/selection changes use staging keys (`_sb_scanner_sync`, `_sb_watch_selected_sync`, `_sb_add_ticker_clear`) applied **before** the `text_area` / `selectbox` / quick-add input are created, so Streamlit does not throw `StreamlitAPIException` when reordering or adding symbols.
- Default bootstrap watchlist (only when config is missing/deleted):
  - `PLTR,BMNR,AAPL,AMZN,NVDA,AMD,TSLA,SPY,QQQ`
- `config.json` only stores **watchlist** and **scanner_sort_mode** (legacy keys from older builds are ignored on load).

### ✅ Institutional Glass UI Infrastructure
- Global CSS architecture moved to a **high-density terminal aesthetic**:
  - glass cards with blur/backdrop filtering,
  - tight spacing between widgets and sections,
  - reduced visual noise and less default Streamlit chrome.
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
- Candlesticks + overlays (EMAs, Bollinger, Ichimoku, Supertrend)
- Fibonacci + Gann + support/resistance scaffolding
- Market structure + confluence scoring
- Diamond signal state and Gold Zone logic
- RSI, MACD, volume/flow context

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
- Watchlist is persistent, user-controlled, and reorderable.
- Scanner output can follow custom list order or confluence rank.

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
4. Open sidebar and verify Scanner Watchlist loads your saved list.

### About missing keys
- Old `config.json` files without newer keys (such as `watchlist` and `scanner_sort_mode`) are automatically backfilled by the app’s default config merge.
- New keys are saved automatically the next time the related sidebar input changes.
- No manual JSON editing is required unless you want to seed values ahead of first run.

### Optional manual seed example
If you want to prefill watchlist before launch:

```json
{
  "watchlist": "PLTR,BMNR,AAPL,AMZN,NVDA,AMD,TSLA,SPY,QQQ",
  "scanner_sort_mode": "Custom watchlist order"
}
```

---

## QA Verification

Latest QA sweep performed against current `app.py` included:

- Lint diagnostics: no issues reported on `app.py`.
- Python compile smoke check:
  - `python3 -m compileall -b app.py` (pass)
- Runtime boot smoke check (headless Streamlit):
  - app starts successfully and serves local URL
  - no startup exceptions observed.

Residual manual QA recommended:
- viewport pass at 1400/1200/992/768 widths,
- live market/open-hours data behavior (yfinance variability),
- sidebar watchlist: edit textarea, reorder, remove, Sort A–Z, quick add after rapid edits (confirm no `StreamlitAPIException` on session state).

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
