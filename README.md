# CashFlow Command Center v22.0 — *Free Edition · Predictive Analytics*

**Single-screen options income desk that grew from a basic multi-ticker scanner into a portfolio-aware command center.**

**v22.0** adds **predictive** layers on top of v21: **`Opt.predict_opex_pin`** (GEX gamma-wall + **Θ/Γ** magnetic blend), **`TA.get_shadow_move`** (70% whale-volume close band vs IV **Expected Move**, purple chart zone), **Bayesian-style news weighting** (forward **guidance / outlook / forecast** phrases outweigh trailing **beat / miss** in `Sentiment.analyze_news_bias`), **Sentinel Ledger** columns **Dist. to pin %** + **Edge realization %** + **Pin maturity** (✨ **Golden zone**), and **regime calibration**: a **Shadow breakout** callout when spot **exits** the purple whale band but stays **inside** the IV **1σ** rails — an early liquidity-vs-options read. The **Market Scanner** also offers **🎯 Equity Radar** mode: **`Opt.detect_pre_diamond`** flags **pre-diamond** coils (confluence **5–6**, squeeze, volume ramp, Gold Zone / **shadow** proximity, weekly not **BEARISH**, **3d RS vs SPY**), with **one cached SPY** fetch per scan for relative strength — suggested **share** sizes reuse **`Opt.portfolio_allocation`** (QE × MC PoP weights × **correlation haircut**) against your **capital base** slider. **v21** adaptive stack (FFD correlation, adaptive whale Z, HVN GEX) remains. **Data: Yahoo Finance only.**

**In-app help:** open **Intel → Quick Reference Guide** for a plain-language glossary (synced with the concepts below).

---

## Evolution: v14 Basic Scanner → v22 Predictive Analytics

| Era | Theme | You gain |
|-----|--------|-----------|
| **v14.x** | Scanner-first | Multi-ticker reads, confluence, early Diamond logic — “what’s moving” |
| **v15–v16** | Quant & MC | HMM/FFD path, Monte Carlo PoP, chain table, HVN + Gold Zone fusion, Kelly + **correlation haircut** |
| **v17–v18** | Risk & liquidity | Expected Move on chart, Θ/Γ, **GEX** and **gamma flip** in Gold, Diamonds, scanner |
| **v19** | Flow & language | **Volume Z-score** whale scaling, **NLP** bias on desk + scanner **Flow / Bias** |
| **v20.0** | Portfolio | **Correlation heatmap**, **cluster penalty** across Blues, **Kelly-style allocator**, **Sentinel Ledger** |
| **v21.0** | Adaptive quant | **Adaptive whale radar**, **FFD correlation + HMM**, **HVN-weighted GEX**, **ADAPTIVE INTELLIGENCE** branding |
| **v22.0** | Predictive | **OpEx pin**, **Shadow EM**, **Bayesian NLP nuance**, **Sentinel alpha columns**, **Equity Radar** (pre-diamond + **SPY RS** + allocator-sized shares), **v22.0 · PREDICTIVE ANALYTICS** |

The Market Scanner still ranks the watchlist, but v20+ treats the list as a **portfolio**: overlap and co-movement inform both **signal scores** and **sizing**. **v21** sharpens correlations and flow baselines; **v22** projects **pin risk**, **liquidity-implied range**, and **edge retention** on tracked legs.

---

## What’s new in v22.0 (Predictive Analytics)

- **`Opt.predict_opex_pin(gex_series, theta_gamma_ratio, spot_price)`** — Locates the **gamma wall** (max **|GEX|** near spot when strong enough vs global), blends toward spot with weight **`clip(Θ/Γ / 2, 0.42, 0.97)`** so high decay-efficiency pins **stick**. Session: **`_cf_opex_pin`**, map **`_cf_opex_pin_map`** per ticker for the ledger.
- **`TA.get_shadow_move(df, volume_z_score=None, lookback=30, whale_mass=0.70)`** — Sorts whale bars (**Z > 2**) by close; **central 70%** of whale **volume** defines **`low` / `high`**. Chart compares band width to IV **1σ** rails (overlay copy: narrow → vol rich; wide → break risk).
- **`Sentiment.analyze_news_bias`** — Sorted **phrase lexicon** (longest first), **forward** weight **1.45×** vs **trailing** **0.82×**, neutral **prior**, headline-level evidence then **`tanh`** aggregate (mixed “miss + raised guidance” tilts bullish when forward hits).
- **Chart** — Purple **`hrect`** shadow band; pink dotted **OpEx pin** line; legend rows in overlay key.
- **Sentinel Ledger** — **`qs_at_entry`** on **Track Trade**; snapshots **`dist_pin_pct_at_entry`** and **`theta_desk_day_entry`** (hidden columns) for calibration; table shows **Dist. to pin %**, **Edge realization %**, **Pin maturity**; metric **Edge realization (avg)** for active-ticker rows.
- **Regime calibration** — **`_cf_regime_shadow_breakout`**: purple banner on the **Technical Chart** when spot is outside **`get_shadow_move`** but inside **`calc_expected_move`** (BLUF IV/DTE). **Pin maturity ✨ Golden zone** when **≤14 DTE**, **|Dist. to pin %|** shrinks vs entry, and desk **Θ/day** is **≥ ~102%** of entry (pin magnet + rising decay into expiry).
- **UI** — Caption *Predictive Pinning, Bayesian News Nuance, & Shadow Liquidity Architecture.*; badge **v22.0 · PREDICTIVE ANALYTICS**.
- **Equity Radar (scanner)** — **MISSION CONTROL → Trading Mode**: toggle **📈 Options Yield** (unchanged: full diamond/confluence scanner + optional **$50k** Blue allocator) vs **🎯 Equity Radar**. Radar table shows **Signal** (**🔥 IMMINENT BREAKOUT** / **🟡 ACCUMULATING** / **—**), **Suggested Shares** from **`Opt.portfolio_allocation`** on pre-diamond rows only ( **`premium_per_contract` = spot** so **contracts** ≈ shares), **`stock_stop_price`** (ATR trail when **`ATR`** exists on history, else **~5%** cushion). **`scan_single_ticker`** accepts optional **`spy_df`**; the app fetches **SPY** once per **Scan Watchlist** and passes it into every ticker (no per-row Yahoo spam). If the radar UI path errors, a **caption** notes the fallback and the same **Scanner Data Table** expander used in **Options Yield** (identical columns and `streamlit_show_dataframe` wiring) is shown.

### Pinning theory (GEX, Θ/Γ, and “magnets”)

Dealers hedge option **gamma** by trading the underlying. Near **expiry**, net **GEX** often concentrates at strikes with heavy **open interest**, creating a **gamma wall**: price can be **pinned** as hedging flow absorbs impulse moves. The **flip** level (zero net GEX) marks where that behavior changes sign. **Theta / gamma** on short-premium structures measures **decay versus convexity** — when **Θ/Γ** is high, daily premium burn dominates localized gamma risk, and the model treats the **wall** as a **stronger attractor** (`predict_opex_pin` raises the weight on the wall strike). This is a **heuristic** desk overlay, not a guarantee of settlement at a strike.

### Regime calibration (Shadow vs IV, pin maturity)

- **Shadow move** — Where **whale bars** (volume **Z > 2**) traded in price: central **70%** of their **volume** defines the purple band. If that band is **narrower** than the IV **1σ** width, the overlay notes that **options may be overpricing** move risk; if **wider**, **break potential** vs implied vol.
- **Shadow breakout** — If **spot** leaves the purple band but remains **between EM− and EM+**, the desk surfaces a **regime calibration** banner: **liquidity** already moved; **IV** has not fully repriced — useful for monitoring **trend continuation or reversal** before the broad tape catches up.
- **Golden zone** (ledger) — As **DTE → 0**, pin estimates get sharper. The ledger flags **✨ Golden zone** when you are **close to expiry**, **distance to the predicted pin** is **shrinking** vs the snapshot at **Track Trade**, and **Θ/day** (desk short-leg income) has **expanded** vs entry — the intended “decay + magnet” window for tracked premium sales.

---

## What’s new in v21.0 (Adaptive Intelligence)

- **`TA.get_dark_pool_proxy`** — **Adaptive rolling window**: **10** sessions when short-horizon volatility dominates (**RVI**), **40** when the tape is calm / efficient, else **30**. Still **Z = (V − μ) / σ**, whale flags **Z > 2.0**. Outputs **`whale_lookback`**, **`vol_mean_roll` / `vol_std_roll`** (legacy **`vol_mean_30` / `vol_std_30`** aliases preserved).
- **`TA.apply_ffd`** — Fixed-width fractional differentiation (**default `d=0.4`**, **≤50** weight lags, threshold trim, **`sliding_window_view`** dot-product). **`frac_diff_ffd`** delegates here for a bounded, UI-safe path.
- **`TA.get_correlation_matrix` / `ffd_returns_from_closes`** — Pearson ρ on **first differences of FFD levels** per ticker (inner-joined dates, same **`lookback_days`** tail). Watchlist **haircut** and **Portfolio Risk** expander use this panel (with **log-return** fallback only if FFD alignment is too thin).
- **`Opt.calc_gamma_exposure(..., hvn_prices=)`** — Strikes within a **liquidity band** of any **HVN** price get **1.2×** weight on **gamma × OI** before strike aggregation (desk **`pages.py`** path + **scanner** both pass **`TA.get_volume_nodes`**).
- **UI** — Caption *(historical v21)* *Adaptive Risk Oversight, FFD Memory, & Synthetic GEX Architecture.*; badge superseded by **v22.0** above.

### Stationarity vs. memory (why FFD over plain returns)

Integer differentiation (**d = 1**, e.g. simple log-returns) pushes series toward **stationarity** but throws away **long-horizon dependence** that drives regime structure and slow mean reversion. **Fractional differentiation** with **0 < d < 1** trades off the two: you remove enough persistence to satisfy linear / Gaussian tooling (correlation matrices, HMM Gaussian emissions) while **retaining more memory** than first differences. **v21** uses **FFD innovations** (diff of the FFD level) for **cross-sectional correlation** and **FFD diff + vol** features for **HMM**, with a **hard cap of 50 lags** on the weight expansion so the desk stays snappy.

---

## What’s new in v20.0 (Portfolio Intelligence) — carried forward

- **`TA.get_correlation_matrix`** — *(v21)* Now Pearson on **FFD return** innovations; still **`pd.concat(..., join="inner")`** on dates and `dropna(how="any")` on the return panel.
- **`watchlist_correlation_matrix_cached`** — `@st.cache_data(ttl=3600)` wrapper used by the main **Portfolio Risk** expander and the scanner heatmap path so the matrix is not recomputed on every widget interaction.
- **Cluster penalty** — `detect_diamonds(..., ticker_symbol=, peer_diamond_symbols=, cluster_corr_matrix=)` subtracts **2** from Blue **composite** when ρ **> 0.75** to any peer ticker already showing an active **Blue** earlier in the **same** watchlist scan (sequential scan order).
- **`Opt.portfolio_allocation`** — For scanner **Blue Diamond** rows: weights ∝ **QE × MC PoP %**, notional **× `_simple_corr_haircut`**, outputs **capital ($)** and **contract count** (floor by reference premium). **Equity Radar** reuses the same engine for **pre-diamond** names with **reference premium = share price** so the floored **contracts** field maps to **suggested shares**.
- **Sentinel Ledger** — `st.session_state["_cf_ledger"]`; **Track Trade** on optimal **Covered Call** / **CSP** lines; tab **📊 Sentinel Ledger** with table + **`sentinel_ledger_metrics`** (BS mark vs entry premium).

---

## What’s new in v19 (Dark Pool Z-Score & NLP Signal Edition) — carried forward

- **Volume Z-Score engine** — `TA.get_dark_pool_proxy(df)` computes **institutional strength** as **Z = (V − μ) / σ** over an **adaptive** rolling window (**10 / 30 / 40** sessions from **RVI** and **20-day efficiency ratio**). *(v19 used a fixed 30-day window.)* **Std = 0** or invalid division yields **Z = 0**. Columns include **`volume_z_score`**, **`whale_lookback`**, **`is_whale_alert`** / **`dark_pool_alert`** when **Z > 2.0**.
- **Whale bonus (Blue Diamond)** — Blue **composite** score adds **+1** when **Z > 2.0** and **+2** when **Z > 3.0** on the signal bar (stacked with GEX and liquidity magnet). Missing or short volume history skips the bonus safely.
- **Chart: institutional footprints** — On the **volume** panel, bars with **Z > 2.0** get **cyan (#00FFFF)** markers with hover **Institutional Flow (Z-Score: X.XX)**.
- **News headlines (cached)** — `fetch_news_headlines(symbol)` stays at **`@st.cache_data(ttl=3600)`** (one hour) for Yahoo rate limits; used by the scanner, trade stack, diamond card, and NLP bias.
- **NLP news bias** — `Sentiment.analyze_news_bias(headlines)` uses a **weighted lexicon** (v22: forward vs trailing tiers) into **−1.0 … +1.0**. Empty or unclassified headlines return **0.0** (neutral).
- **UI: trade stack** — **News Bias (NLP)** colors the **aggregate score** and **News Sentiment** line: **emerald (#10b981)** if score **> 0.3**, **rose (#ef4444)** if **< −0.3**, else **slate (#94a3b8)**. **Institutional Flow** remains Normal / High Accumulation from the whale flag. **Why This Diamond?** repeats flow and sentiment when a signal is active.
- **Scanner: Flow / Bias** — Column help documents the **Whale Alert (Z-Score)** definition. Rows show **🐋 WHALE** when the latest bar has **Z > 2.0** and **📈 BULLISH NEWS** / **📉 BEARISH NEWS** when bias crosses **±0.15**; otherwise **—** when data is missing.
- **Chart: IV impact** — When **next earnings** is within **14 days**, the price panel annotates **Avg. Post-Earnings IV Crush** using a **realized-volatility proxy** averaged over up to **four prior** earnings cycles from Yahoo `earnings_dates`. If **IV rank proxy ≥ 90** or spot **IV** exceeds the **90th percentile** of **20-day realized vol** over the last year, the chart adds **⚠️ VEGA RISK: IV Crush likely**.
- **Branding (v19)** — Page caption *Institutional Flow Tracking & NLP Sentiment Architecture.*; header badge **v19** (superseded by **v22.0** branding above).

---

## Carried forward from v18.0 (Liquidity & GEX Edition)

- **GEX engine** — `Opt.calc_gamma_exposure(opts_df, spot_price, …, hvn_prices=…)` builds per-strike dealer GEX with **vectorized Black–Scholes gamma** (calls **+**, puts **−**), **`openInterest × gamma × S²/100`**, optional **1.2×** liquidity weight when strike aligns with an **HVN** node, then strike aggregation. Missing **open interest** or chain columns fail soft (empty series).
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

## Quant & desk history (v15.x → v22.0)

- **HMM regimes (FFD)** — Gaussian HMM trains on **FFD-level differences** plus short rolling volatility (stationary features with memory); `fit` / `predict_proba` stay inside `try/except` so singular covariance cases do not crash the app.
- **Scanner threading** — Rolling Edge Capture and other modules still use a **bounded** pool with `submit_with_script_ctx`. **v20.0** runs the **full watchlist Diamond scan sequentially** so **cluster penalties** see a deterministic **peer-Blue** ordering (correlation context is shared across tickers in one pass).
- **Data layer** — `fetch_stock` is wrapped with `@st.cache_data(ttl=300)`; an **empty** Yahoo history prints a **stderr** warning (visible in Streamlit Cloud logs) instead of failing silently.
- **Diamond detection** — **Hurst exponent** on `Close` adapts **RSI** length (8 if `H < 0.45`, 21 if `H > 0.55`, else 14) and **MACD** fast/slow/signal by the same scale; when `H > 0.55`, **Blue** diamonds also require **MACD line > signal** (when both are defined). **v18** layers **GEX regime** bonuses/penalties on Blue scores when a gamma flip resolves. **v19** adds a **scaled Whale bonus** on Blue from **volume Z-score**: **+1** if **Z > 2.0**, **+2** if **Z > 3.0**. **v20** adds optional **cluster guard** (−2 composite when ρ **> 0.75** vs another **Blue** in the same scanner pass). **v22** adds **`Opt.detect_pre_diamond`** on the scanner path (three-bar **Hurst-aligned** confluence slice, **shadow** low from **`TA.get_shadow_move`**, optional **SPY** dataframe for **3d** relative strength).
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
- **Options Math Stack** — Black-Scholes Greeks, Corrado-Su skew/kurtosis expansion, Expected Value, discrete/continuous Kelly sizing, Volatility Skew, **Expected Move (1-σ)**, **Θ/Γ**, **GEX / gamma flip**, **predicted OpEx pin**, **shadow move** vs EM
- **Sentinel Ledger (v22+)** — **Track Trade** snapshots; **Dist. to pin %**, **Edge realization %**, **Pin maturity**; portfolio **Δ**, **Θ/day**, model **P&L**; **Shadow breakout** alert on the chart when conditions align
- **Multi-Ticker Scanner** — ranks the watchlist by confluence and diamond status; **v20** uses a **sequential** pass with **cluster-aware** Blue scores; **PoP** = historical Diamond win rate; **EM Safety**; **GEX Regime**; **Flow / Bias**; optional **$50k allocator** expander for **Blue** rows; **v22** adds **Equity Radar** mode (**`Opt.detect_pre_diamond`**, **SPY** RS, **`portfolio_allocation`** share sizing, styled radar table)
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
    ├── ta.py                 # TA class — indicators, **`apply_ffd`**, **adaptive `get_dark_pool_proxy`**, **`get_shadow_move` (whale band)**, **`get_correlation_matrix`**, HVN / volume profile
    ├── options.py            # Black-Scholes, Corrado-Su, EV, Kelly, Quant Edge, **GEX / gamma flip / `predict_opex_pin`**, Diamonds, **`Opt.detect_pre_diamond`**, **`Opt.portfolio_allocation`**, **`scan_single_ticker`** (optional **`spy_df`**), **`watchlist_correlation_matrix_cached`**, **MC PoP**, **`PortfolioRisk`**
    ├── sentiment.py          # **Bayesian-style `analyze_news_bias`**, HMM (FFD), CC sim, Alerts, QuantBacktest
    ├── chart.py              # Price / volume / RSI / MACD + **Shadow move (purple)** + **OpEx pin** + HVN / EM / gamma flip / correlation heatmap
    ├── ui_helpers.py         # Sparklines, fragments, **`sentinel_ledger_metrics`**, **`sentinel_ledger_table_rows`**, **`ledger_theta_desk_day`**, regime **Shadow breakout** banner, **expected_move_safety_html**, **Θ/Γ desk line**
    ├── pages.py              # **`build_context`**: options → GEX → **OpEx pin map** → **shadow move** → **shadow breakout** flag → fused Gold → confluence → diamonds
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

Covers `TA.get_correlation_matrix` (FFD-return path), earnings runway spark series, `Opt.portfolio_allocation` / `_simple_corr_haircut`, and basic Black–Scholes / EV math (no live Yahoo calls).

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
| Volume | OBV, Volume Profile, VWAP, **HVN nodes (volume-at-price)**, **adaptive volume Z-score (dark pool proxy)** |
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
| **GEX & Gamma Flip** | **Vectorized gamma × OI** with dealer sign (calls **+**, puts **−**); optional **HVN liquidity weight (1.2×)**; cumulative strike GEX crosses define **zero-gamma**; **`predict_opex_pin`** blends **gamma wall** with **Θ/Γ** magnet |
| **Shadow Expected Move** | **`TA.get_shadow_move`**: central **70%** of whale-volume closes vs IV **1σ** band — chart insight when liquidity range diverges from options-implied width |
| Fractional Differentiation (FFD) | Improve stationarity while preserving memory in time-series dynamics |
| HMM Regime Detection | Classify latent volatility regimes on **FFD diff + rolling vol** features (subsampled, diagonal covariance, bounded EM iterations); guarded against numerical failures |
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
