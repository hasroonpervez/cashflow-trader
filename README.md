# CashFlow Command Center v16.0 — *Free Edition · Probability Mode*

**Single-screen options income desk and multi-ticker watchlists.**

Glanceable execution guidance, Diamond buy/sell signals, Gold Zone confluence, Black-Scholes + Corrado-Su options math, **institutional-style Monte Carlo PoP** (seeded GBM with antithetic variates), **volume-profile HVN rails** on the main chart, a live Market Edge Matrix, a volatility skew surface with regime tagging, and a vectorized Time-Machine backtester — all in a Streamlit dashboard built for mobile-first traders who sell covered calls and cash-secured puts for weekly income. **Data: Yahoo Finance only; no paid market-data APIs.**

---

## What’s new in v16.0 Free Edition

- **Monte Carlo PoP (v16)** — `MonteCarloEngine.calc_pop` uses **fixed RNG seed 42**, **antithetic** standard normals, optional **`dividend_yield`**, optional **`skew`** tilt on shocks (complements **Corrado–Su** closed-form pricing elsewhere), and neutral **50%** fallback when inputs are invalid so the UI stays calm on bad quotes.
- **Full chain table** — Cash Flow Strategies includes an expander with **every strike** and a **MC PoP %** column (short-premium framing), wrapped in **try/except** so thin chains never take down the page.
- **HVN on chart** — `TA.get_volume_nodes` builds **high-volume nodes** from recent volume-at-price; the main price panel draws **semi-transparent dashed “HVN”** horizontals (try/except guarded).
- **Scanner PoP** — Market Scanner adds a **PoP** column: **historical Diamond win rate** (same `diamond_win_rate` methodology as the main dashboard).
- **Config default** — `use_quant_models` defaults to **`true`** in `modules/config.py` (institutional quant path on fresh installs); override in `config.json` or Secrets as needed.

---

## Quant & desk history (v15.x → v16.0)

- **HMM regimes (FFD)** — Gaussian HMM trains on **fractionally differenced** daily closes for stationarity while preserving memory; `fit` / `predict_proba` stay inside `try/except` so singular covariance cases do not crash the app.
- **Scanner threading** — Market Scanner uses a **bounded** pool (`min(8, watchlist length)`) and queues one future per ticker so workers drain the queue instead of spawning one thread per symbol on small Cloud CPUs.
- **Data layer** — `fetch_stock` is wrapped with `@st.cache_data(ttl=300)`; an **empty** Yahoo history prints a **stderr** warning (visible in Streamlit Cloud logs) instead of failing silently.
- **Diamond detection** — **Hurst exponent** on `Close` adapts **RSI** length (8 if `H < 0.45`, 21 if `H > 0.55`, else 14) and **MACD** fast/slow/signal by the same scale; when `H > 0.55`, **Blue** diamonds also require **MACD line > signal** (when both are defined).
- **Skew-aware BLUF** — If **OTM put IV ≥ 120% of OTM call IV** (when call IV is positive) and daily structure is **not BEARISH**, routing prioritizes **SELL CASH SECURED PUTS** even when the tape is only neutral (after covered-call and fear-score rules).
- **Walk-up limit** — The **Recommended Trade** card shows **(bid + mid) / 2** per share for **short premium** as a passive fill anchor (e.g. Robinhood-style limit sells), including the strict-filter **fallback** strike path when present.

---

## What This Does

The dashboard answers one question: **"What should I do right now?"**

- **BLUF Action Card** — plain-English trade recommendation with a specific strike, expiry, broker checklist, optional **walk-up limit** for short premium, and **MC PoP %** from the Monte Carlo engine
- **Traffic Light Indicators** — green/amber/red across Quant Edge Score, Confluence, Market Structure
- **Diamond Signals** — Blue (buy zone) and Pink (take profit) triggered by 7+/9 confluence crossover; diamond scan uses **Hurst-adaptive RSI/MACD** and a MACD confirmation in strong trending regimes
- **Gold Zone** — dynamic institutional anchor fusing Volume Profile POC, Fib 61.8%, 200-SMA, Gann Sq9
- **Feature-Flagged Institutional Mode** — one-click toggle between retail and quant engines (default **on** in v16)
- **A/B Quant Diagnostics** — institutional vs retail Quant Edge delta shown live
- **Rolling Edge Capture Log** — scans the **entire watchlist in parallel** (thread pool + `ScriptRunContext`), refreshes on a **`@st.fragment` timer (~90s)** so the rest of the page stays responsive, sorts rows by **Quant** score, adds a **Preview** line per symbol (same desk read as the headline Quant gauge: prime / decent / stand down), summary metrics, treemap hover with preview text, and CSV export
- **Market Edge Matrix** — treemap inside the log, sized by Quant score and colored by Quant−Retail delta across all watchlist names
- **De-correlated Quant Edge Score** — retail path uses five orthogonal dimensions (Trend, Momentum, Volume, Volatility, Structure)
- **Institutional Quant Edge Path** — HMM regime detection on **FFD-stationary** features plus fractional-differentiation synthesis in the composite score
- **Volatility Skew Surface** — put vs call IV smile chart with spot marker for fast tail-risk context
- **Skew Regime Tag** — OTM put-IV/call-IV ratio classified as Crash Hedging, Bearish Skew, Balanced Smile, or Upside Mania
- **Time-Machine Backtester** — vectorized 3y historical proxy with win rate, expectancy, Sharpe, max drawdown, and equity curve
- **One-Click Backtest Presets** — Conservative, Balanced, and Aggressive slider snaps for instant scenario switching
- **Options Math Stack** — Black-Scholes Greeks, Corrado-Su skew/kurtosis expansion, Expected Value, discrete/continuous Kelly sizing, Volatility Skew
- **Multi-Ticker Scanner** — ranks your full watchlist by confluence and diamond status using a **capped** parallel pool and queued work per ticker; **PoP** = historical Diamond win rate
- **Premium Simulator** — covered call backtest with honest disclaimers

---

## Architecture

```
cashflow-trader/
├── app.py                    # Thin entrypoint: page config → CSS injection → main()
├── config.json               # Watchlist & UI preferences (atomic JSON writes)
├── requirements.txt
├── .gitignore
└── modules/
    ├── __init__.py
    ├── config.py             # Config persistence, defaults, st.secrets overlay
    ├── data.py               # yfinance fetchers, retry/backoff, fetch_stock cache (300s), macro
    ├── ta.py                 # TA class — indicators, FFD, volume profile, **get_volume_nodes (HVN)**
    ├── options.py            # Black-Scholes, Corrado-Su, EV, Kelly, Quant Edge, Hurst-adaptive Diamonds, **MC PoP**, **build_chain_mc_dataframe**
    ├── sentiment.py          # Sentiment + HMM (FFD features), CC sim, Alerts, QuantBacktest engine
    ├── chart.py              # Four-panel Plotly chart builder + skew surface + **HVN hlines**
    ├── ui_helpers.py         # Sparklines, glance cards, fragments, mode badge, DataFrame styling
    ├── pages.py              # Optional page shell + parallel context build (uses threading helper)
    ├── streamlit_threading.py # Thread pools with ScriptRunContext re-attach per task
    └── css.py                # Full CSS theme + Mini Mode + sidebar toggle JS
```

**Why this split works with Streamlit:**

- `st.set_page_config()` is the first Streamlit call in `app.py` (required)
- CSS/navbar injection happens immediately after via `inject_css_and_navbar()`
- Modules never call `st.*` at import time — only when their functions are invoked
- `@st.cache_data` decorators work correctly because `streamlit` is imported in each module

**Parallel fetches and Streamlit Cloud:**

- Background `ThreadPoolExecutor` workers that call `@st.cache_data` need Streamlit’s `ScriptRunContext` on that thread. `make_script_ctx_pool()` plus `submit_with_script_ctx()` capture context when work is submitted and re-attach it at the start of each task (initializer-only attachment is not always enough after cache layers).
- The technical chart lives in `@st.fragment`; quant vs retail mode is passed via `st.session_state` (not extra fragment kwargs) so deploys and fragment reruns stay compatible. Stale kwargs from older sessions are ignored safely on the fragment signature.
- The **Rolling Edge Capture Log** uses a separate `@st.fragment(run_every=…)` that recomputes retail vs quant scores for every watchlist ticker; VIX and institutional mode are read from `st.session_state` (`_cf_vix_snapshot`, `_cf_use_quant_models`) so it stays aligned with the active ticker context.

---

## Run Locally

```bash
python3 -m venv venv
source venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Cloud

1. Push to GitHub (app and `modules/` must stay in sync on the same branch the app tracks)
2. Connect at [share.streamlit.io](https://share.streamlit.io)
3. Set `app.py` as the main file
4. (Optional) Add secrets in Streamlit Cloud dashboard under Settings → Secrets

If the app fails to import, check Cloud logs: mismatched commits (e.g. `app.py` importing a symbol removed from `modules/ui_helpers.py`) cause immediate `ImportError` on boot.

---

## Config (`config.json`)

Persisted locally via atomic writes (`.tmp` → `os.replace`). The watchlist **auto-saves** when you edit it (and on each script rerun if the text area differs from disk), so a new browser session reloads from `config.json` on the same machine or container.

On Streamlit Cloud the repo’s `config.json` is read from git; **runtime writes** may be blocked (read-only). If saving fails, set a top-level secret `watchlist = "PLTR,AAPL,..."` (comma-separated, one line) in **Settings → Secrets** so the list survives redeploys.

Keys: `watchlist`, `scanner_sort_mode`, `strat_focus`, `strat_horizon`, `mini_mode`, `overlay_ema`, `overlay_fib`, `overlay_gann`, `overlay_sr`, `overlay_ichi`, `overlay_super`, `overlay_diamonds`, `overlay_gold`, `use_quant_models`.

### Institutional Mode Toggle

- `use_quant_models: true` (**v16 default**) enables HMM/FFD-heavy quant scoring, continuous-time Kelly routing in risk sizing, and A/B diagnostics in the UI.
- `use_quant_models: false` keeps the original retail scoring/sizing path.

### Chart Layer Persistence

Technical Chart layer toggles persist to `config.json` and are restored on the next app run:

- EMAs & Bollinger
- Fibonacci
- Gann Sq9
- S/R levels
- Ichimoku
- Supertrend
- Diamonds
- Gold zone

Layer preferences are saved immediately when each toggle changes.

### Earnings Data Fallback

If the earnings calendar endpoint returns no rows, the app falls back to the primary earnings date feed and still renders a usable "Upcoming Earnings" row (Date / When / Source).

---

## Technical Indicators

| Category | Indicators |
|---|---|
| Trend | EMA 20/50/200, Ichimoku Cloud, Supertrend |
| Momentum | RSI (14), RSI (2), MACD (12,26,9), Stochastic, CCI |
| Volume | OBV, Volume Profile, VWAP, **HVN nodes (volume-at-price)** |
| Volatility | Bollinger Bands, ATR (14), Hurst Exponent |
| Structure | Market Structure (BOS/CHOCH), Support/Resistance, Fair Value Gaps |
| Gann | Square of 9 levels, Angles, Time Cycles |
| Fibonacci | Retracement levels (0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%) |

## Institutional Math Extensions

| Engine | Purpose |
|---|---|
| Corrado-Su Expansion | Adjust option pricing for skew and fat tails beyond Gaussian Black-Scholes assumptions |
| Monte Carlo PoP | Short-premium probability of profit under GBM; antithetic variates; seed **42**; optional dividend yield and skew tilt on paths |
| Fractional Differentiation (FFD) | Improve stationarity while preserving memory in time-series dynamics |
| HMM Regime Detection | Classify latent volatility regimes on **FFD log-return + vol** features (subsampled, diagonal covariance, bounded EM iterations); guarded against numerical failures |
| Continuous Kelly (Merton) | Compute variance-aware continuous-time allocation with optional half-Kelly |
| OTM IV Skew Regime Ratio | Classify market-maker fear/greed posture from put-vs-call OTM implied volatility |
| Vectorized Historical Edge Proxy | Backtest threshold/hold edge signals over daily history without UI lockups |

`hmmlearn` and `scipy` are handled with safe fallbacks so the app remains usable if those packages are unavailable.

---

## Known Limitations

- Yahoo Finance may throttle or block symbols on Streamlit Cloud (more liberal locally)
- Config persistence is local-only; Cloud deploys reset the filesystem
- You may still see occasional `missing ScriptRunContext` lines in Cloud logs from threads outside the app’s pool (Streamlit labels many as ignorable in bare mode); parallel cached fetches use `submit_with_script_ctx` to minimize this
- Micro-cap tickers (e.g. BMNR) may lack options chains; the desk falls back gracefully

---

## Disclaimer

This tool is for **educational use only** and does not constitute financial advice. Past performance in the Premium Simulator does not predict future results. Always confirm quotes in your broker before placing orders.
