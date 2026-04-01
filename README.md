# CashFlow Command Center v20.0 — *Free Edition · Portfolio Intelligence*

**Single-screen options income desk that grew from a basic multi-ticker scanner into a portfolio-aware command center.**

**v20.0** adds **watchlist correlation matrices** (90-day log-returns, Pearson ρ, **inner-joined** dates), a **cluster guard** on Blue Diamonds when ρ **> 0.75** vs another active Blue in the same scan (−2 composite), **`Opt.portfolio_allocation`** for a **$50k** illustrative mix weighted by **Quant Edge × MC PoP %** with **`_simple_corr_haircut`**, a **Sentinel Ledger** tab (session trade log, **Track Trade** on optimal CC/CSP cards, aggregate **Δ**, **Θ/day**, model **unrealized P&L**), a **Portfolio Risk** heatmap (**RdBu_r**, **1h** Streamlit cache on the matrix), and branding **v20.0 · PORTFOLIO INTELLIGENCE**. Earlier pillars remain: **GEX / gamma flip**, **dark-pool volume Z-score**, **NLP headline bias**, **MC PoP**, **EM** rails, **HVN**, Kelly governors, and the full technical stack. **Data: Yahoo Finance only.**

---

## Evolution: v14 Basic Scanner → v20 Portfolio Intelligence

| Era | Theme | You gain |
|-----|--------|-----------|
| **v14.x** | Scanner-first | Multi-ticker reads, confluence, early Diamond logic — “what’s moving” |
| **v15–v16** | Quant & MC | HMM/FFD path, Monte Carlo PoP, chain table, HVN + Gold Zone fusion, Kelly + **correlation haircut** |
| **v17–v18** | Risk & liquidity | Expected Move on chart, Θ/Γ, **GEX** and **gamma flip** in Gold, Diamonds, scanner |
| **v19** | Flow & language | **Volume Z-score** whale scaling, **NLP** bias on desk + scanner **Flow / Bias** |
| **v20.0** | Portfolio | **Correlation heatmap**, **cluster penalty** across Blues, **Kelly-style allocator**, **Sentinel Ledger** |

The Market Scanner still ranks the watchlist, but v20 treats the list as a **portfolio**: overlap and co-movement inform both **signal scores** and **sizing**.

---

## What’s new in v20.0 (Portfolio Intelligence)

- **`TA.get_correlation_matrix`** — Builds a Pearson matrix from a **dict of price histories**; **`pd.concat(..., join="inner")`** on dates; **90** trading days of **log-returns**; `dropna(how="any")` on the return panel so pairwise samples stay aligned.
- **`watchlist_correlation_matrix_cached`** — `@st.cache_data(ttl=3600)` wrapper used by the main **Portfolio Risk** expander and the scanner heatmap path so the matrix is not recomputed on every widget interaction.
- **Cluster penalty** — `detect_diamonds(..., ticker_symbol=, peer_diamond_symbols=, cluster_corr_matrix=)` subtracts **2** from Blue **composite** when ρ **> 0.75** to any peer ticker already showing an active **Blue** earlier in the **same** watchlist scan (sequential scan order).
- **`Opt.portfolio_allocation`** — For scanner **Blue Diamond** rows: weights ∝ **QE × MC PoP %**, notional **× `_simple_corr_haircut`**, outputs **capital ($)** and **contract count** (floor by reference premium).
- **Sentinel Ledger** — `st.session_state["_cf_ledger"]`; **Track Trade** on optimal **Covered Call** / **CSP** lines; tab **📊 Sentinel Ledger** with table + **`sentinel_ledger_metrics`** (BS mark vs entry premium).
- **UI** — Caption *Institutional Portfolio Optimization, Multi-Factor Risk, & Sentinel Ledger Architecture.*; badge **v20.0 · PORTFOLIO INTELLIGENCE**.

---

## What’s new in v19 (Dark Pool Z-Score & NLP Signal Edition) — carried forward

- **Volume Z-Score engine** — `TA.get_dark_pool_proxy(df)` computes **institutional strength** as a continuous **volume Z-score** over a **30-day** rolling mean and standard deviation: **Z = (V − μ) / σ** (vectorized `pandas` rolling). **Std = 0** or invalid division yields **Z = 0**. Columns include **`volume_z_score`**, **`is_whale_alert`** (and **`dark_pool_alert`**, same flag) when **Z > 2.0** (~97.7th percentile under normality).
- **Whale bonus (Blue Diamond)** — Blue **composite** score adds **+1** when **Z > 2.0** and **+2** when **Z > 3.0** on the signal bar (stacked with GEX and liquidity magnet). Missing or short volume history skips the bonus safely.
- **Chart: institutional footprints** — On the **volume** panel, bars with **Z > 2.0** get **cyan (#00FFFF)** markers with hover **Institutional Flow (Z-Score: X.XX)**.
- **News headlines (cached)** — `fetch_news_headlines(symbol)` stays at **`@st.cache_data(ttl=3600)`** (one hour) for Yahoo rate limits; used by the scanner, trade stack, diamond card, and NLP bias.
- **NLP news bias** — `Sentiment.analyze_news_bias(headlines)` scores titles with a **keyword lexicon** into **−1.0 … +1.0** (bearish to bullish). Empty or unclassified headlines return **0.0** (neutral).
- **UI: trade stack** — **News Bias (NLP)** colors the **aggregate score** and **News Sentiment** line: **emerald (#10b981)** if score **> 0.3**, **rose (#ef4444)** if **< −0.3**, else **slate (#94a3b8)**. **Institutional Flow** remains Normal / High Accumulation from the whale flag. **Why This Diamond?** repeats flow and sentiment when a signal is active.
- **Scanner: Flow / Bias** — Column help documents the **Whale Alert (Z-Score)** definition. Rows show **🐋 WHALE** when the latest bar has **Z > 2.0** and **📈 BULLISH NEWS** / **📉 BEARISH NEWS** when bias crosses **±0.15**; otherwise **—** when data is missing.
- **Chart: IV impact** — When **next earnings** is within **14 days**, the price panel annotates **Avg. Post-Earnings IV Crush** using a **realized-volatility proxy** averaged over up to **four prior** earnings cycles from Yahoo `earnings_dates`. If **IV rank proxy ≥ 90** or spot **IV** exceeds the **90th percentile** of **20-day realized vol** over the last year, the chart adds **⚠️ VEGA RISK: IV Crush likely**.
- **Branding (v19)** — Page caption *Institutional Flow Tracking & NLP Sentiment Architecture.*; header badge **v19** (superseded by **v20.0** branding above).

---

## Carried forward from v18.0 (Liquidity & GEX Edition)

- **GEX engine** — `Opt.calc_gamma_exposure(opts_df, spot_price, …)` builds per-strike dealer GEX with **vectorized Black–Scholes gamma** (calls **+**, puts **−**), **`openInterest × gamma × S²/100`**, and strike aggregation. Missing **open interest** or chain columns fail soft (empty series).
- **Gamma flip** — `Opt.find_gamma_flip(gex_by_strike)` cumulates GEX along sorted strikes and locates the **positive→negative** cumulative crossing (linear interpolation between strikes). Used for regime context, Gold Zone fusion, Diamond scoring, chart, and scanner.
- **Chart: zero-gamma floor** — Technical price panel draws **#39FF14** dashed **GAMMA FLIP (Volatility Trigger)** when the chain resolves; if **last close < flip**, a subtle **`rgba(255, 0, 0, 0.05)`** band marks **short-gamma** conditions.
- **Gold Zone + GEX** — `calc_gold_zone(..., gamma_flip_price=…)` adds **Gamma Flip** into the blend when it sits within **5%** of spot.
- **Diamond score (Blue)** — **+2** when **price > flip** and **Gold Zone < flip** (institutional support under the zero-gamma wall); **−3** when **price < flip** (turbulent / short-gamma regime). Pink diamonds unchanged. Display copy uses **composite score** where bonuses apply.
- **Scanner: GEX Regime** — **🛡️ STABLE** if spot **>** gamma flip, **⚠️ TURBULENT** if spot **<** flip (or **—** if GEX cannot be built). Scanner path reuses the same **GEX → Gold → confluence → diamonds** ordering as the main context when options load.
- **Desk & Diamond card: Θ/Γ efficiency** — Recommended CC/CSP rows show **Θ/Γ** with **✅ High Decay Efficiency** if ratio **> 2.0**, **⚠️ Gamma Risk (Squeeze Likely)** if **< 0.5** (from existing desk `theta_gamma_ratio`).
- **UI copy (v18)** — Prior caption **Institutional Risk Oversight & Gamma Exposure Architecture.** and badge **v18.0 · LIQUIDITY & GEX**; chart tip documents **Gamma Flip** (MM hedging accelerates volatility). **v19** uses caption **Institutional Flow Tracking & NLP Sentiment Architecture.** and badge **v19**.

---

## What’s new in v17.0 (Liquidity & Greeks Edition — carried forward)

- **Expected Move (1-σ)** — `Opt.calc_expected_move(price, iv_pct, days_to_expiry)` uses **Spot × (IV/100) × √T** with **numpy** (scalar or array), wrapped in **try/except** at call sites when IV or chain context is missing.
- **Chart: EM rails + cone** — The technical price panel draws **gold (#eab308) dashed** horizontals labeled **Expected Move (1-σ)** and, when expiry is after the last bar, a **filled probability cone** (`rgba(234,179,8,0.1)`) from spot to the EM band at expiration, driven by the **active BLUF expiry** (`bluf_dte`, `ref_iv_bluf` / desk IV).
- **Theta / Gamma** — Prop-desk **Covered Call / CSP** tables and the **full MC chain** table include **Θ/Γ** (per-day theta ÷ gamma). Chain rows compute greeks in **numpy batches** per side (calls/puts); MC PoP remains strike-by-strike for stability.
- **Recommended Trade + Diamond card** — **Safety Status** vs the 1-σ band (**outside** = high safety, **inside** = monitor gamma) plus **Expected Move Range: $X – $Y**, via `expected_move_safety_html` in `ui_helpers.py` (session-backed for the chart fragment).
- **Scanner: EM Safety** — Each row gets **EM Safety**: **SAFE** if the scanner short-put strike is **below spot − EM** (else **MONITOR**), using the same **30D** horizon and **realized-vol → IV%** proxy as the existing scanner MC block, guarded with **try/except**.

---

## What’s new in v16.0 Free Edition (carried forward)

- **Monte Carlo PoP (v16)** — `MonteCarloEngine.calc_pop` uses **fixed RNG seed 42**, **antithetic** standard normals, optional **`dividend_yield`**, optional **`skew`** tilt on shocks (complements **Corrado–Su** closed-form pricing elsewhere), and neutral **50%** fallback when inputs are invalid so the UI stays calm on bad quotes.
- **Full chain table** — Cash Flow Strategies includes an expander with **every strike** and **MC PoP %** plus **Θ/Γ**, wrapped in **try/except** so thin chains never take down the page.
- **HVN on chart** — `TA.get_volume_nodes` returns **price + volume weight** per node; the price panel draws weighted **HVN (Institutional Liquidity)** horizontals (thicker / deeper purple near the **Gold Zone**, try/except guarded).
- **Probability fusion (desk + edge)** — **Gold Zone** blends the nearest **HVN within 2% of spot** with POC, Fib, SMA200, and Gann. **Blue Diamond** rows can gain a **+1 liquidity magnet** when spot sits **between POC and that HVN**. Prop-desk **strike scores** add the same **+1** when the strike lies **between POC and HVN**. **Quant Edge** adds **0.25 × (avg MC PoP of top strikes ÷ 100)** when option chain rows are present (context build after Yahoo chain load).
- **Kelly governors** — Half/full Kelly (discrete and continuous paths) scale by **(max(1, MC PoP) / 85)^0.5** when MC PoP is available. **`Opt._simple_corr_haircut`** blends watchlist correlation into sizing (**max(0.35, 1 − mean ρ)**), wrapped in **try/except** with a **1.0** fallback; the **Market Scanner** multiplies the existing overlap haircut by this factor for **Adj. Kelly**.
- **Scanner PoP** — **PoP** column remains **historical Diamond win rate**; each row also shows a **scanner MC PoP** proxy (30D short-put Monte Carlo), **HVN floor**, **risk multiplier**, **EM Safety**, and **GEX Regime** under Adj. Kelly.
- **Config default** — `use_quant_models` defaults to **`true`** in `modules/config.py` (institutional quant path on fresh installs); override in `config.json` or Secrets as needed.

---

## Quant & desk history (v15.x → v20.0)

- **HMM regimes (FFD)** — Gaussian HMM trains on **fractionally differenced** daily closes for stationarity while preserving memory; `fit` / `predict_proba` stay inside `try/except` so singular covariance cases do not crash the app.
- **Scanner threading** — Rolling Edge Capture and other modules still use a **bounded** pool with `submit_with_script_ctx`. **v20.0** runs the **full watchlist Diamond scan sequentially** so **cluster penalties** see a deterministic **peer-Blue** ordering (correlation context is shared across tickers in one pass).
- **Data layer** — `fetch_stock` is wrapped with `@st.cache_data(ttl=300)`; an **empty** Yahoo history prints a **stderr** warning (visible in Streamlit Cloud logs) instead of failing silently.
- **Diamond detection** — **Hurst exponent** on `Close` adapts **RSI** length (8 if `H < 0.45`, 21 if `H > 0.55`, else 14) and **MACD** fast/slow/signal by the same scale; when `H > 0.55`, **Blue** diamonds also require **MACD line > signal** (when both are defined). **v18** layers **GEX regime** bonuses/penalties on Blue scores when a gamma flip resolves. **v19** adds a **scaled Whale bonus** on Blue from **volume Z-score**: **+1** if **Z > 2.0**, **+2** if **Z > 3.0**. **v20** adds optional **cluster guard** (−2 composite when ρ **> 0.75** vs another **Blue** in the same scanner pass).
- **Skew-aware BLUF** — If **OTM put IV ≥ 120% of OTM call IV** (when call IV is positive) and daily structure is **not BEARISH**, routing prioritizes **SELL CASH SECURED PUTS** even when the tape is only neutral (after covered-call and fear-score rules).
- **Walk-up limit** — The **Recommended Trade** card shows **(bid + mid) / 2** per share for **short premium** as a passive fill anchor (e.g. Robinhood-style limit sells), including the strict-filter **fallback** strike path when present.

---

## What This Does

The dashboard answers one question: **"What should I do right now?"**

- **BLUF Action Card** — plain-English trade recommendation with a specific strike, expiry, broker checklist, optional **walk-up limit** for short premium, **MC PoP %**, **HVN floor**, **correlation risk multiplier**, **Expected Move safety**, and **Θ/Γ efficiency** hints on the headline CC/CSP lines when data exists
- **Traffic Light Indicators** — green/amber/red across Quant Edge Score, Confluence, Market Structure
- **Diamond Signals** — Blue (buy zone) and Pink (take profit) triggered by 7+/9 confluence crossover; diamond scan uses **Hurst-adaptive RSI/MACD** and a MACD confirmation in strong trending regimes; **v18** may adjust Blue **composite** score with **GEX regime** logic; **v19** adds **Z-score Whale** scaling and **headline / NLP** context on the desk and scanner
- **Gold Zone** — dynamic institutional anchor fusing Volume Profile POC, Fib 61.8%, 200-SMA, Gann Sq9, **nearest HVN (within 2% of spot)** when volume nodes resolve, and optionally **Gamma Flip** when within 5% of spot
- **Gamma flip & GEX** — chain-derived **zero-gamma** level on the chart, **GEX Regime** on the scanner, and soft-fail behavior when OI/gamma inputs are missing
- **Feature-Flagged Institutional Mode** — one-click toggle between retail and quant engines (default **on** in v16+)
- **A/B Quant Diagnostics** — institutional vs retail Quant Edge delta shown live
- **Rolling Edge Capture Log** — scans the **entire watchlist in parallel** (thread pool + `ScriptRunContext`), refreshes on a **`@st.fragment` timer (~90s)** so the rest of the page stays responsive, sorts rows by **Quant** score, adds a **Preview** line per symbol (same desk read as the headline Quant gauge: prime / decent / stand down), summary metrics, treemap hover with preview text, and CSV export
- **Market Edge Matrix** — treemap inside the log, sized by Quant score and colored by Quant−Retail delta across all watchlist names
- **De-correlated Quant Edge Score** — retail path uses five orthogonal dimensions (Trend, Momentum, Volume, Volatility, Structure)
- **Institutional Quant Edge Path** — HMM regime detection on **FFD-stationary** features plus fractional-differentiation synthesis in the composite score
- **Volatility Skew Surface** — put vs call IV smile chart with spot marker for fast tail-risk context
- **Skew Regime Tag** — OTM put-IV/call-IV ratio classified as Crash Hedging, Bearish Skew, Balanced Smile, or Upside Mania
- **Time-Machine Backtester** — vectorized 3y historical proxy with win rate, expectancy, Sharpe, max drawdown, and equity curve
- **One-Click Backtest Presets** — Conservative, Balanced, and Aggressive slider snaps for instant scenario switching
- **Options Math Stack** — Black-Scholes Greeks, Corrado-Su skew/kurtosis expansion, Expected Value, discrete/continuous Kelly sizing, Volatility Skew, **Expected Move (1-σ)**, **Θ/Γ**, **GEX / gamma flip**
- **Multi-Ticker Scanner** — ranks the watchlist by confluence and diamond status; **v20** uses a **sequential** pass with **cluster-aware** Blue scores; **PoP** = historical Diamond win rate; **EM Safety**; **GEX Regime**; **Flow / Bias**; optional **$50k allocator** expander for **Blue** rows
- **Premium Simulator** — covered call backtest with honest disclaimers

---

## Architecture

```
cashflow-trader/
├── app.py                    # Thin entrypoint: page config → CSS injection → main()
├── tests/                    # pytest — correlation, allocation, earnings spark, BS/EV
├── config.json               # Watchlist & UI preferences (atomic JSON writes)
├── requirements.txt
├── requirements-dev.txt      # pytest (optional local / CI)
├── .gitignore
└── modules/
    ├── __init__.py
    ├── config.py             # Config persistence, defaults, st.secrets overlay
    ├── data.py               # yfinance fetchers, retry/backoff, fetch_stock cache (300s), macro
    ├── ta.py                 # TA class — indicators, FFD, volume profile, **get_volume_nodes (HVN)**, **get_dark_pool_proxy**, **`get_correlation_matrix` (90D log-ρ, inner join)**
    ├── options.py            # Black-Scholes, Corrado-Su, EV, Kelly, Quant Edge, Hurst-adaptive Diamonds, **GEX / gamma flip**, **cluster-aware Diamonds**, **`Opt.portfolio_allocation`**, **`watchlist_correlation_matrix_cached` (3600s)**, **MC PoP**, **`PortfolioRisk.build_correlation_matrix` → TA**
    ├── sentiment.py          # Sentiment + HMM (FFD features), CC sim, Alerts, QuantBacktest engine
    ├── chart.py              # Four-panel Plotly chart builder + skew surface + **correlation heatmap (RdBu_r)** + **HVN / Z-score / EM / gamma flip**
    ├── ui_helpers.py         # Sparklines, glance cards, fragments, mode badge, DataFrame styling, **`sentinel_ledger_metrics`**, **expected_move_safety_html**, **Θ/Γ desk line**
    ├── pages.py              # Optional page shell + parallel context build (uses threading helper); **options → GEX → fused Gold → confluence → diamonds**
    ├── streamlit_threading.py # Thread pools with ScriptRunContext re-attach per task
    └── css.py                # Full CSS theme + Mini Mode + sidebar toggle JS
```

**Why this split works with Streamlit:**

- `st.set_page_config()` is the first Streamlit call in `app.py` (required)
- CSS/navbar injection happens immediately after via `inject_css_and_navbar()`
- Modules never call `st.*` at import time — only when their functions are invoked
- `@st.cache_data` decorators work correctly because `streamlit` is imported in each module (`quant_edge_score` is intentionally **uncached** so optional chain-based MC fusion stays hash-safe)

**Parallel fetches and Streamlit Cloud:**

- Background `ThreadPoolExecutor` workers that call `@st.cache_data` need Streamlit’s `ScriptRunContext` on that thread. `make_script_ctx_pool()` plus `submit_with_script_ctx()` capture context when work is submitted and re-attach it at the start of each task (initializer-only attachment is not always enough after cache layers).
- The technical chart lives in `@st.fragment`; quant vs retail mode is passed via `st.session_state` (not extra fragment kwargs) so deploys and fragment reruns stay compatible. **Expected Move chart inputs** use the same pattern (`_cf_chart_em`, `_cf_em_safety`). **Gamma flip** uses **`_cf_gamma_flip`**; desk picks use **`_cf_bluf_cc_pick` / `_cf_bluf_csp_pick`** for Θ/Γ on the Diamond card. Stale kwargs from older sessions are ignored safely on the fragment signature.
- The **Rolling Edge Capture Log** uses a separate `@st.fragment(run_every=…)` that recomputes retail vs quant scores for every watchlist ticker; VIX and institutional mode are read from `st.session_state` (`_cf_vix_snapshot`, `_cf_use_quant_models`) so it stays aligned with the active ticker context.

---

## Run Locally

```bash
python3 -m venv venv
source venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
streamlit run app.py
```

### Tests (QA)

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

Covers `TA.get_correlation_matrix`, earnings runway spark series, `Opt.portfolio_allocation` / `_simple_corr_haircut`, and basic Black–Scholes / EV math (no live Yahoo calls).

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

- `use_quant_models: true` (**v16+ default**) enables HMM/FFD-heavy quant scoring, continuous-time Kelly routing in risk sizing, and A/B diagnostics in the UI.
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

The **gamma flip** line and short-gamma tint render when the options chain yields a finite flip price (session-backed); they are not separate toggles.

Layer preferences are saved immediately when each toggle changes.

### Earnings Data Fallback

If the earnings calendar endpoint returns no rows, the app falls back to the primary earnings date feed and still renders a usable "Upcoming Earnings" row (Date / When / Source).

---

## Technical Indicators

| Category | Indicators |
|---|---|
| Trend | EMA 20/50/200, Ichimoku Cloud, Supertrend |
| Momentum | RSI (14), RSI (2), MACD (12,26,9), Stochastic, CCI |
| Volume | OBV, Volume Profile, VWAP, **HVN nodes (volume-at-price)**, **30-day volume Z-score (dark pool proxy)** |
| Volatility | Bollinger Bands, ATR (14), Hurst Exponent, **1-σ Expected Move (IV × √T)** |
| Structure | Market Structure (BOS/CHOCH), Support/Resistance, Fair Value Gaps |
| Gann | Square of 9 levels, Angles, Time Cycles |
| Fibonacci | Retracement levels (0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%) |

## Institutional Math Extensions

| Engine | Purpose |
|---|---|
| Corrado-Su Expansion | Adjust option pricing for skew and fat tails beyond Gaussian Black-Scholes assumptions |
| Monte Carlo PoP | Short-premium probability of profit under GBM; antithetic variates; seed **42**; optional dividend yield and skew tilt on paths |
| Expected Move (1-σ) | `Spot × (IV%/100) × √(DTE/365.25)` for implied range context (chart + desk + scanner) |
| **GEX & Gamma Flip** | **Vectorized gamma × OI** with dealer sign (calls **+**, puts **−**); cumulative strike GEX crosses define **zero-gamma** price for chart, scanner regime, Gold Zone, and Diamond modifiers |
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
- **Scanner EM Safety** uses the same **realized-vol proxy** as the scanner MC block when a full options IV snapshot is not fetched per ticker (fast path); the main dashboard uses **listed IV** for chart and Recommended Trade when the chain loads
- **GEX / gamma flip** depends on **open interest** and option quotes; some symbols return chains without OI — the engine returns empty GEX and the UI shows **—** / omits the flip line

---

## Disclaimer

This tool is for **educational use only** and does not constitute financial advice. Past performance in the Premium Simulator does not predict future results. Always confirm quotes in your broker before placing orders.
