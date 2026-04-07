# CashFlow Command Center v22.0 — *Free Edition · Predictive Analytics*

**Single-screen options income desk that grew from a basic multi-ticker scanner into a portfolio-aware command center.**

**v22.0** adds **predictive** layers on top of v21: **`Opt.predict_opex_pin`** (GEX gamma-wall + **Θ/Γ** magnetic blend), **`TA.get_shadow_move`** (70% whale-volume close band vs IV **Expected Move**, purple chart zone), **Bayesian-style news weighting** (forward **guidance / outlook / forecast** phrases outweigh trailing **beat / miss** in `Sentiment.analyze_news_bias`), **Sentinel Ledger** columns **Dist. to pin %** + **Edge realization %** + **Pin maturity** (✨ **Golden zone**), and **regime calibration**: a **Shadow breakout** callout when spot **exits** the purple whale band but stays **inside** the IV **1σ** rails — an early liquidity-vs-options read. **v22.x “10x executioner” stack** (desk + allocator): **fundamental sieve** (**`evaluate_fundamental_sieve`** / **`GlobalMarketSnapshot.fundamental_sieve_map`** — FCF yield vs EV + EBITDA/asset efficiency via Yahoo with **Alpha Vantage** **OVERVIEW** / **CASH_FLOW** / statements gap-fill); **Hurst R/S** on **100** closes (**`TA.calculate_hurst_exponent`**, **`@st.cache_data(ttl=3600)`** in **`signal_desk`**) tilts consensus flow toward **RSI/Bollinger** when **H < 0.45** (**Options Yield**) vs **MACD/RS vs SPY** when **H > 0.55** (**Equity Radar**); **whale sweep** (price **>** rolling VWAP, volume **Z > 4**, aggressor proxy **> 0.7**) plus **TOTAL INSTITUTIONAL DOMINANCE** when **sweep + absorption** align; **scanner allocator** **sector guard** (**0.5×** when Sentinel book in that **sector > 20%** of capital) and **top-3 ledger ρ** halving (**0.5×** when FFD **|ρ| > 0.80** vs your three largest legs); trader’s note **GOD TIER UNICORN** (FFD stationary proxy + trending Hurst + fundamental FCF gate + sweep) and **Alpha realization** vs **`qs_at_entry`**. The **Market Scanner** is **context-aware by trading mode** (**`scanner_mode`** / session **`_cf_scanner_mode`**): **📈 Options Yield** keeps the full income desk readout (row tiles with **GEX Regime**, **PoP**, **Flow / Bias**, optional **$50k** allocator, and the **Scanner Data Table** expander). **🎯 Equity Radar** swaps that surface for a stock-buying workflow — **📡 Radar Summary** counts, **🎯 Actionable Targets** (signal, price, suggested shares, **ATR-style stop** from `stock_stop_price`, QE, support proximity), then a **Delta-One Equity Setup** desk (**`st.tabs`**: **🚀 Breakout Metrics** / **🛡️ Risk & Support**) fed only from the last scan payload — plus the same desk on **Cashflow & strikes** (options chain, MC PoP, spreads, and Greeks stay **hidden** until you switch back to **Options Yield**). Last-scan rows persist in **`st.session_state["_cf_scanner_bundle"]`** so toggling the Trading Hemisphere or rerunning widgets does not wipe the grid until you **Scan Watchlist** again. Mode-matched copy. **`Opt.detect_pre_diamond`** flags **pre-diamond** coils (confluence **5–6**, squeeze, volume ramp, Gold Zone / **shadow** proximity, weekly not **BEARISH**, **3d RS vs SPY**), with **one cached SPY** fetch per scan for relative strength — suggested **share** sizes reuse **`Opt.portfolio_allocation`** (QE × MC PoP × **correlation haircut** × **sector / top-3 ρ guards** when ledger + matrix exist) against your **capital base** slider. **v21** adaptive stack (FFD correlation, adaptive whale Z, HVN GEX) remains. **Data:** **Yahoo Finance** is primary; if **`fetch_stock`** still returns nothing after retry, the desk can fall back to **Alpha Vantage** **`TIME_SERIES_DAILY`** when **`ALPHAVANTAGE_API_KEY`** is set (**environment** or **`st.secrets`**); **`fetch_info`** can merge the same key for **fundamental** fields (**OVERVIEW**, **CASH_FLOW**, **INCOME_STATEMENT**, **BALANCE_SHEET** as needed for the sieve).

**In-app help:** open **Intel → Quick Reference Guide** for a plain-language glossary (synced with the concepts below).

**Streamlit UX polish (institutional dark + feedback):** repo **`.streamlit/config.toml`** sets a default **dark theme** (deep background, slate secondary surfaces, institutional blue primary). Changing **Trading Hemisphere** shows a **`st.toast`** on successful **`config.json`** write (or a warning toast if the host is read-only). **Scan Watchlist** runs inside **`st.spinner`** (plus the existing per-ticker **`st.progress`**). The **Delta-One Equity Setup** desk uses **`st.container(border=True)`** around metrics (bento-style grouping) and a **Structure visualizer**: last **60** daily closes via **Plotly** (cyan **Whale vol** dashed vline when **volume Z ≥ 4** on that history, same 20-session baseline as the main chart whale marker); falls back to **`st.line_chart`** if Plotly fails (one price fetch per drill-down).

**Yahoo / Streamlit Cloud hardening:** **`modules/data.py`** uses a **`curl_cffi`** session with forced caps, clamps **`yfinance` `YfData`** HTTP timeouts (so **`timed out after 30001 ms`** tar-pits do not block the app for 30s per hop), and exposes fetch helpers that **return empty / `None` instead of raising** so a bad symbol or throttled IP does not take down the page. The main desk run uses a **global market snapshot**: **`fetch_global_market_bundle`** issues **one** **`yf.download`** over **watchlist ∪ macro panel ∪ risk universe ∪ active ticker** (**2y** daily bars), then derives the **sidebar tape**, **macro / VIX glance**, **portfolio-risk closes**, **active-ticker daily** (and **weekly** via Friday resample), a shared **`raw_panel`** for **Scan Watchlist** / **Rolling Edge Matrix** slices, and **`rs_spy_ratio_map`** (**`rs_spy_ratio_map_from_close_matrix`**: **~90 trading-session** RS vs **SPY** on date-aligned closes for **watchlist ∪ risk**)—so Yahoo sees far fewer round trips than a purely pull-per-widget layout. If **`build_context`** cannot load daily bars for the active ticker, **`app.py`** shows a **`st.error`** with throttling / Cloud context and a **Clear price cache & retry** button (clears **`fetch_stock`** and **`fetch_global_market_bundle`** **`@st.cache_data`** entries, then reruns)—useful because a failed fetch can otherwise stay cached for up to **`fetch_stock`**’s **300s** TTL. Details: **Quant & desk history → Data layer** and **Deploy → Yahoo data and shared IPs**.

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
- **Consensus desk — institutional absorption (`institutional_absorption`)** — **Whale trap** when **volume Z ≥ 4** vs the prior **20** sessions (same baseline as the chart whale vline) but the last daily **close-to-close %** sits inside an **ATR-scaled** quiet band (floored **0.35%**, capped **1.0%**, **0.55%** fallback if ATR missing). Surfaces a cyan **INSTITUTIONAL ABSORPTION** strip on the consensus card, **ABSORPTION** in **mini / Turbo** consensus, bento **momentum** copy, and an extended **trader’s note**; **`compute_desk_consensus`** adds a small score lift when active. **OHLCV proxy only** — not lit-book order-flow imbalance.
- **Consensus desk — rolling VWAP distance Z (`vwap_distance_stats`)** — **20-bar** rolling VWAP from **typical price × volume** (daily bars — not cumulative `TA.vwap` from inception, not intraday session VWAP). **Relative deviation** \((C-\text{VWAP})/\text{VWAP}\); **Z** vs **μ/σ** of the **prior 20** deviations (last bar excluded). **`compute_desk_consensus`** blends **volume Z** and **VWAP stretch** in the flow slice (**50/50** on the mapped **0–100** flow score), adds **momentum** copy, exposes **`vwap_z`**, **`vwap_detail`**, and **`vwap_urgency`** (**True** when **volume Z ≥ 2** and **VWAP Z ≥ 2**). **`traders_note_markdown`** adds a **VWAP stretch** paragraph when **|VWAP Z| ≥ 2**. Covered by **`tests/test_signal_desk.py`**.
- **Global snapshot — RS vs SPY (`rs_spy_ratio_map`)** — On the same **`close`** matrix as the tape, **`fetch_global_market_bundle`** fills **`GlobalMarketSnapshot.rs_spy_ratio_map`**: for each **watchlist ∪ risk** symbol (not **SPY**), **inner-aligned** daily closes vs **SPY** yield a **~90-session** growth-factor ratio \((C_t/C_{t-90})/(SPY_t/SPY_{t-90})\); **> 1** means **outperformance** vs the benchmark over that window. **`app.py`** passes the active ticker’s ratio into **`compute_desk_consensus(..., rs_spy_ratio=...)`**. Covered by **`tests/test_data_rs.py`**.
- **Institutional heatmap ribbon + conviction sizer** — **Detailed desk** (non–mini mode): **`institutional_heatmap_ribbon_html`** after the trader’s note — **COIL** (purple, BBW percentile **≤ 5%**), **ICEBERG** (cyan, **`absorption`**), **SWEEP** (gold, **`ribbon_sweep_active`**: **`whale_sweep`** *or* **`vwap_urgency`**), **LEADER** (emerald, **`market_leader`**: **RS > 1** vs SPY **and** **volume Z > 4** on the desk’s 20d volume Z). **REGIME** line: **Hurst** label (**Mean reverting** / **Trending** / neutral) and suggested **Options Yield** vs **Equity Radar** mode; **TOTAL INSTITUTIONAL DOMINANCE** when **sweep + Iceberg** both fire. Subtitle shows **`desk_conviction_multiplier`** (**`whale_sweep`** counts like VWAP urgency for the **1.5× / 2.0×** SWEEP tier). **Calculate position size** expander applies **base risk % × conviction multiplier** to **`suggested_shares_atr_risk`** (illustrative only).
- **Fundamental sieve (cash / EV)** — **`fetch_info`** merges Yahoo **`.info`** with **Alpha Vantage** when **`freeCashflow`**, **`enterpriseValue`**, or **`ebitda`** are missing (**OVERVIEW**, then **CASH_FLOW** for FCF). **`evaluate_fundamental_sieve`** returns **`None`** if yield or YoY efficiency cannot be computed (no fake zeros). **`fetch_global_market_bundle`** fills **`GlobalMarketSnapshot.fundamental_sieve_map`** per **risk** symbol; **`app.py`** passes the active ticker’s dict into **`compute_desk_consensus(..., fundamental_sieve=...)`**. Scanner rows expose **`fundamental_sieve`** / **`fcf_yield_pct`**; **10x Convexity** label can combine technical convexity with **FCF 10x** when gates align.
- **Hurst regime controller** — **`TA.calculate_hurst_exponent`**: rescaled-range Hurst on the last **100** closes. **`signal_desk._cached_hurst_rs`**: **`@st.cache_data(ttl=3600)`**. **`compute_desk_consensus`** adjusts tape + flow blend by regime; exposes **`hurst_exponent`**, **`hurst_regime`**, **`trading_mode_recommendation`**.
- **Whale sweep** — **`detect_whale_sweep`**: last close **>** rolling VWAP, volume **Z > 4**, **`daily_aggressor_proxy` > 0.7**; **`institutional_dominance`** when **absorption** is also true. **Momentum** bento uses **`sweep_gold`** accent + gold **box-shadow** in **`bento_box_html`**. **Turbo / mini** strip: **SWEEP** / **DOMINANCE** / regime chips in **`consensus_compact_html`**.
- **Scanner allocator — sector & correlation guards** — **`Opt.portfolio_allocation(..., sentinel_ledger=, ffd_correlation_matrix=)`** applies **0.5×** when the ticker’s **sector** (from **`fetch_info`**) already exceeds **20%** of **`total_capital`** on tracked **Sentinel** notional proxy (**`premium_100 × contracts`**), and **0.5×** when max **|ρ|** vs **top-3** ledger tickers by that notional exceeds **0.80** on the **FFD** correlation matrix. Output includes **`sector_cluster_penalty`**, **`top3_corr_penalty`**, **`portfolio_guards_product`** (multiplicative with **`_simple_corr_haircut`**).
- **Trader’s note — Alpha realization & GOD TIER** — **`traders_note_markdown(..., alpha_realization_pct=, turbo_desk=)`**: compares live **Quant Edge** to **`qs_at_entry`** (strengthening / rotting / in line). **GOD TIER UNICORN** when **FFD stationary proxy**, **Hurst > 0.55**, **fundamental FCF** gate, and **whale sweep** align. **`turbo_desk=True`** returns one tight paragraph; full **mini / Turbo** layout still skips the long note and ribbon in **`app.py`**.
- **Trader’s note — “Unicorn” perfect storm** — When **COIL + ICEBERG + LEADER** all fire, **`traders_note_markdown`** emits a single **Unicorn alert — high-conviction stack** paragraph (RS, whale volume, absorption detail, coil copy, **20d high** as a tactical “clear **resistance**” proxy) and **skips** the separate **Market leader** and **Whale trap** paragraphs so the note does not double-count. **`tests/test_signal_desk.py`** → **`test_traders_note_unicorn_perfect_storm`**.
- **Unified probability dial** — Non–mini **Mission Control**: **`unified_probability_dial_html`** after the live header blends **42% Quant Edge · 33% confluence % · 25% RS vs SPY tilt** (**`blend_unified_probability`** / **`compute_desk_consensus` → `unified_probability`**). Illustrative composite, not a forecast.
- **Daily aggressor proxy (OFI stand-in)** — **`daily_aggressor_proxy`**: close location inside the **H–L** range over the last few bars, weighted by **volume intensity**; surfaces in bento **momentum** and **`ofi_detail`** on the consensus dict. **Not** lit-book order flow.
- **Heatmap-colored bento** — **`bento_accents_from_consensus`** + **`bento_box_html(..., accent=...)`** tint **Setup / Momentum / Exit** borders (neutral, bullish, bearish, warning, elite) from **COIL**, **LEADER**, **SWEEP**, **band**, etc.
- **Black–Scholes Vanna & Charm** — **`bs_greeks`** returns **`vanna`** (Δδ per **1%** IV) and **`charm`** (Δδ per **day**); the **Greeks, Expected Value & Volatility Skew** block shows them on the top covered-call leg. **`tests/test_bs_greeks.py`**.
- **Alpha Vantage fallback** — After Yahoo + **`retry_fetch`** miss, **`fetch_stock`** tries **`_fetch_stock_alphavantage`** (**daily** bars only; respects **`ALPHAVANTAGE_API_KEY`**). Does not clear the same throttling as Yahoo but helps when the shared IP path is empty.
- **Deferred headlines (`defer_headlines_earnings`)** — Optional **`config.json`** / default **`modules/config.py`** flag: **`build_context`** skips parallel **news** + **next-earnings** fetches so price/context can commit first; **Intel → Market News** uses **`@st.fragment`** to **`fetch_news_headlines`** on demand (earnings fields stay empty on that path until you fetch elsewhere or turn the flag off).
- **Correlated book warning** — After the **Portfolio Risk** heatmap, if max Pearson **ρ** vs another column for the **active ticker** exceeds **0.75**, **`app.py`** shows a **`st.warning`** (90d FFD-return matrix, same cache as the expander).
- **Kelly copy on position sizer** — **Calculate position size** expander adds an illustrative **binary Kelly** line from **`d_wr`** (diamond win rate %) vs **1:1** payoff when **`d_n ≥ 3`**, via **`kelly_criterion`**.
- **Equity Radar & context-aware workspaces** — **MISSION CONTROL → 🎛️ Command Center**: bordered **control deck** with two columns — **Trading Hemisphere** (**📈 Options Yield** vs **🎯 Equity Radar**, `segmented_control` with **radio** fallback) and **Capital Base** slider (Equity mode only). **Trading mode persists** to **`config.json`** as **`scanner_mode`** (restored on the next app launch; same atomic **`save_config`** path as the watchlist). The same **`Scan Watchlist`** run powers both modes; the UI **branches on `scanner_mode`** so **Equity Radar** does not surface options-specific scanner chrome (e.g. **GEX Regime**, Diamond **PoP**, **Scanner Data Table**) on the premium-selling path. **`_cf_scanner_bundle`** stores **`results`**, **`failed`**, **`watchlist_tickers`**, and **`log_returns_df`** after each scan so the Intel scanner block and **Cashflow & strikes** (Equity path) can re-render without a new scan on every rerun. **Delta-One Equity Setup** (below **Actionable Targets** and on **Cashflow & strikes** in Equity mode): focus ticker **`selectbox`**, **Breakout Metrics** (volatility state, confluence, RS vs SPY, QE), **Risk & Support** (entry = scan spot, ATR-style stop from the same `stock_stop_price` rule, distance to support, illustrative **R:R to Gold Zone** using scan **Gold Zone** vs stop). The **📝 Rolling Edge Capture Log** expander uses **mode-aware copy**: **Options Yield** explains premium-selling context (not a simple buy list); **Equity Radar** uses plain **“stocks to BUY”** language (including **IMMINENT BREAKOUT** as a direct buy-list framing). After **Scan Watchlist**, **📡 Radar Summary** HUD uses **`st.metric`** for **🔥 Imminent Breakouts**, **🟡 Accumulating**, and **Total Scanned**. **🎯 Actionable Targets** table uses **string-formatted** currency / percent / thousands separators on **`Styler`**, row highlights unchanged, and **dynamic `st.dataframe` height** (`min(400, (rows+1)×38)`). Core math and **`Opt.portfolio_allocation`** sizing are unchanged. **`scan_single_ticker`** accepts optional **`spy_df`** and **`panel_raw`** (multi-ticker **`yf.download`** frame from the desk snapshot); **SPY** for relative strength is sliced from that panel when present, else **`fetch_stock("SPY", …)`** — if Yahoo times out or returns no rows, **stderr** notes that **RS vs SPY** was skipped for that pass. If the radar UI path errors, a **caption** plus the **Options Yield** **Scanner Data Table** expander is shown.

### Pinning theory (GEX, Θ/Γ, and “magnets”)

Dealers hedge option **gamma** by trading the underlying. Near **expiry**, net **GEX** often concentrates at strikes with heavy **open interest**, creating a **gamma wall**: price can be **pinned** as hedging flow absorbs impulse moves. The **flip** level (zero net GEX) marks where that behavior changes sign. **Theta / gamma** on short-premium structures measures **decay versus convexity** — when **Θ/Γ** is high, daily premium burn dominates localized gamma risk, and the model treats the **wall** as a **stronger attractor** (`predict_opex_pin` raises the weight on the wall strike). This is a **heuristic** desk overlay, not a guarantee of settlement at a strike.

### Regime calibration (Shadow vs IV, pin maturity)

- **Shadow move** — Where **whale bars** (volume **Z > 2**) traded in price: central **70%** of their **volume** defines the purple band. If that band is **narrower** than the IV **1σ** width, the overlay notes that **options may be overpricing** move risk; if **wider**, **break potential** vs implied vol.
- **Shadow breakout** — If **spot** leaves the purple band but remains **between EM− and EM+**, the desk surfaces a **regime calibration** banner: **liquidity** already moved; **IV** has not fully repriced — useful for monitoring **trend continuation or reversal** before the broad tape catches up.
- **Golden zone** (ledger) — As **DTE → 0**, pin estimates get sharper. The ledger flags **✨ Golden zone** when you are **close to expiry**, **distance to the predicted pin** is **shrinking** vs the snapshot at **Track Trade**, and **Θ/day** (desk short-leg income) has **expanded** vs entry — the intended “decay + magnet” window for tracked premium sales.

## Venture-style volatility hunting: **Asymmetric Convexity Sieve**

**v22.0** is optimized for **institutional swing** and **premium harvesting** (confluence, Diamonds, GEX regime, pre-diamond coils). **Venture-style “10x” hunting** looks for **fat-tail** candidates where **liquidity scarcity**, **volatility compression**, **abnormal volume**, and **dealer/short positioning** can align. The sieve below is **implemented** in **`scan_single_ticker`** (`modules/options.py`: **`evaluate_asymmetric_convexity_sieve`**, **`_bbw_series`**, **`_parse_yahoo_float_and_short`**). Each scan row gets **`10x Convexity`** (**`💎 10x Sieve`** only if **all** gates pass, else **—**), a nested **`convexity_sieve`** dict for tooling, the **Scanner Data Table** column **10x Convexity**, **Options Yield** row tiles (**10x Sieve**), **Equity Radar** column **10x Sieve**, and **Delta-One Equity Setup → diagnostics** expander.

**Idea:** Large moves are **rare**; a strict AND-of-filters should usually return **zero** names. That is a feature—noise elimination—not a bug.

### Four simultaneous filters

| Pillar | Role | Example threshold (tunable) |
|--------|------|----------------------------|
| **1. Float rotation (fuel)** | Capital required to move price; micro-float can **turn over** quickly when flow hits. | **Free float under ~30M shares** (scarcity). |
| **2. Volatility coil (spring)** | Cheap vol → more **convexity** per dollar if a break happens. | **BBW** (Bollinger Band Width) in the **bottom ~5th percentile** of a **1y** lookback (or Hurst / range metrics as alternatives). |
| **3. Volume Z-score (footprint)** | Extreme today’s volume vs its own baseline. | **Z-score above 4.0** vs **90-day** volume mean and std on the last bar (tail event under Gaussian noise). |
| **4. Gamma pinch / skew (match)** | Shorts + **call-heavy** dealer hedging can reinforce a squeeze narrative. | **Short interest above ~20%** (of float or shares) **and** **call IV above put IV** at comparable OTM (e.g. skew ratio **call IV / put IV** at least ~**1.1** on your chosen strikes). |

**Caveats:** Yahoo **`info`** fields for **float** and **short interest** are often **missing, stale, or rounded**; options **IV** requires a **liquid chain**. Any live implementation must handle **`None`** gracefully and **never** treat this as a guaranteed “10x” signal.

### Reference sieve (pseudocode)

Below is a compact boolean sieve matching the story above. **`skew_ratio`** means **OTM call IV ÷ OTM put IV** (or your desk’s analogue from `calc_vol_skew` / chain mids)—values **above** 1 mean calls are **richer** than puts.

```python
def detect_10x_convexity(df, float_shares, short_interest, skew_ratio):
    # 1. Scarcity & squeeze potential
    if float_shares is None or float_shares > 30_000_000:
        return False
    if short_interest is None or short_interest < 0.20:
        return False

    # 2. Extreme volatility compression (coil) — requires BBW column on df
    if "BBW" not in df.columns or len(df) < 252:
        return False
    bbw_pct = df["BBW"].tail(252).rank(pct=True).iloc[-1]
    if bbw_pct > 0.05:
        return False

    # 3. Institutional footprint (1-bar volume anomaly)
    tail = df["Volume"].tail(90)
    if len(tail) < 30 or tail.std() == 0:
        return False
    vol_mean, vol_std = tail.mean(), tail.std()
    z_score = (df["Volume"].iloc[-1] - vol_mean) / vol_std
    if z_score < 4.0:
        return False

    # 4. Dealer / skew: calls bid up vs puts
    if skew_ratio is None or skew_ratio < 1.1:
        return False

    return True  # All four gates passed — still not investment advice
```

### Relationship to this repo

- **Live sieve** — **BBW** is built from **`TA.bollinger`** on **Close** (not a pre-existing **`BBW`** column). **Skew** uses **`calc_vol_skew`** (~10% OTM call vs put IV) on the **same** near-term expiry chain used for scanner **GEX**. **Float / short** come from **`fetch_info`** (`floatShares`, `shortPercentOfFloat`, or **`sharesShort` / float** fallback).
- **Pre-diamond** (`Opt.detect_pre_diamond`) uses **BBW/ATR squeeze** on a **shorter** window and **volume ramp** vs a **5-day** mean—not the same as **90d volume Z above 4**.
- **Scanner GEX** and **gamma flip** are independent columns; the sieve does **not** replace them.
- **Dark-pool proxy** (`TA.get_dark_pool_proxy`) uses an **adaptive** window and **Z above 2**—different threshold than the sieve’s **90d / Z at least 4** rule.

### How to use this as a trader

When you run strict versions of this logic, **most** days you should see **no** names. Treat any survivor as a **hypothesis**: size from a defined risk level (e.g. the **low of the high-Z volume session**), assume the feed can be wrong on **float/short**, and treat **convexity** as **asymmetric payoff**, not a promise of **10x**.

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
- **`Opt.portfolio_allocation`** — For scanner **Blue Diamond** rows: weights ∝ **QE × MC PoP %**, then **× `_simple_corr_haircut`** **× sector-cluster penalty** **× top-3 ρ penalty** (when **`sentinel_ledger`** and **`ffd_correlation_matrix`** are passed from **`app.py`**), outputs **capital ($)** and **contract count** (floor by reference premium). **Equity Radar** reuses the same engine for **pre-diamond** names with **reference premium = share price** so the floored **contracts** field maps to **suggested shares**.
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
- **Data layer** — `fetch_stock` uses `@st.cache_data(ttl=300)` (5 minutes). After Yahoo + **`retry_fetch`**, if bars are still missing, **`_fetch_stock_alphavantage`** (**`requests`**, **daily** `TIME_SERIES_DAILY` only) runs when **`ALPHAVANTAGE_API_KEY`** is set (**`os.environ`** or **`st.secrets`**). **`fetch_info`** copies Yahoo **`.info`** and **`_merge_alphavantage_fundamentals_into_info`** fills **freeCashflow / enterpriseValue / ebitda** from **OVERVIEW** and **CASH_FLOW** when missing. **`evaluate_fundamental_sieve`** (`@st.cache_data(ttl=3600)`) combines **FCF/EV** yield with **YoY EBITDA vs total assets** from **INCOME_STATEMENT** + **BALANCE_SHEET**; returns **`None`** if data are insufficient. **`modules/data.py`** routes **yfinance** and direct Yahoo JSON fallbacks through a **single shared `curl_cffi` session** subclass (**`_ForcedTimeoutSession`**) with **`impersonate="safari15_5"`**, which **yfinance 0.2+ requires** (a stdlib `requests.Session` is rejected). **`curl_cffi`** honors an **explicit** per-call **`timeout`** over the session default; **yfinance’s `YfData._make_request`** passes **`timeout=30`** into **`get`**, which produced **`timed out after 30001 ms`** until the data layer was patched. The repo **clamps** timeouts inside **`YfData._make_request`** and **`_get_cookie_and_crumb`**, marks the class with **`_cashflow_trader_yahoo_timeout_v1`** so **reloads cannot double-wrap** the same process, and always runs **`YfData(session=_YAHOO_SESSION)`** (patch success or failure) so import **never aborts** the app. The session subclass still forces **`request(..., timeout=_YAHOO_YF_TIMEOUT)`** (**5.0** s). **`fetch_stock`**, **`fetch_info`**, **`list_option_expiration_dates`**, and **`fetch_intraday_series`** are written to **never raise** (empty / **`None`** on failure). Every **`Ticker.history(...)`** and **`yf.download(...)`** passes **`timeout=_YAHOO_YF_TIMEOUT`**. A **~10s** log line can still appear when **yfinance** retries once after a **4xx** (two **5s** attempts). **`retry_fetch`** does not retry read/timeouts. **Global market snapshot** — **`fetch_global_market_bundle(watch_syms, active_ticker)`** (`@st.cache_data(ttl=120)`) performs **one** **`yf.download`** for **2y** / **1d** over the union of **watchlist**, **macro strip** (**`^VIX`**, **`^TNX`**, **UUP**, **SPY**, **QQQ**), **risk symbols** (up to **20** watchlist names plus the **active** ticker), and returns a **`GlobalMarketSnapshot`**: **`desk`** (**`DeskMarketSnapshot`**: tape %, macro, VIX glance history), **`risk_closes_df`**, pre-sliced **active** daily / weekly / ~1mo frames, **`raw_panel`** for consumers, **`rs_spy_ratio_map`** (**`rs_spy_ratio_map_from_close_matrix`**, **~90** sessions vs **SPY** on aligned dates for **watchlist ∪ risk**), and **`fundamental_sieve_map`** (**`evaluate_fundamental_sieve`** per **risk** symbol). **`app.py`** stores the bundle in **`st.session_state["_cf_global_market_bundle"]`** (and **`_cf_global_market_key`**) so **`build_context`**, the **portfolio correlation** strip, **Scan Watchlist**, and the **Rolling Edge Matrix** can slice the same panel instead of re-downloading. Weekly bars for the desk are **Friday-resampled** from that daily panel when possible; **`build_context`** may still call **`fetch_stock(..., "2y", "1wk")`** if the resample is too short. **`fetch_desk_market_snapshot`** and **`watchlist_tape_pct_changes`** delegate into the global bundle (same cache key family). **`fetch_equity_daily_closes_wide`** remains for ad-hoc multi-symbol closes; the main desk path uses **`risk_closes_df`** from the bundle. **Macro** still batches via the panel (**`fetch_macro`** uses the macro-only slice through **`fetch_desk_market_snapshot(())`**). **Scan Watchlist** prints **stderr** when **SPY** is missing. **`possibly delisted`** on liquid names is usually **throttling**, not delisting.
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
- **Rolling Edge Capture Log** — scans the **entire watchlist in parallel** (thread pool + `ScriptRunContext`), refreshes on a **`@st.fragment` timer (~90s)** so the rest of the page stays responsive, sorts rows by **Quant** score, adds a **Preview** line per symbol (same desk read as the headline Quant gauge: prime / decent / stand down), summary metrics, treemap hover with preview text, and CSV export; instructional blurbs follow **📈 Options Yield** vs **🎯 Equity Radar** (premium-income context vs **buy-list** English)
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
├── app.py                    # Thin orchestrator: watchlist **`@st.fragment`**, Mission Control + tape (**`modules/render_pre_tabs.py`**), **`build_context`**, desk header through execution strip, chart fragment, tab dispatch
├── tests/                    # pytest — correlation, allocation, earnings spark, BS/EV
├── config.json               # Watchlist & UI preferences (atomic JSON writes)
├── requirements.txt
├── requirements-dev.txt      # pytest (optional local / CI)
├── .gitignore
└── modules/
    ├── __init__.py
    ├── config.py             # Config persistence, defaults, st.secrets overlay; **`ConfigTransaction`** batch flush
    ├── desk_locals.py        # **`DeskLocals`** + **`build_desk_locals`** snapshot for tab renderers
    ├── render_pre_tabs.py    # Pre-tab UI: watchlist fragment, HUD, tape, config flush; **`render_desk_after_context`** (consensus → execution strip → alerts)
    ├── renderers.py          # Tab bodies (**`@st.fragment`** on major tabs), equity desk; **`_news_item_markdown_html`** (escaped headlines, http(s)-only links)
    ├── data.py               # Yahoo: `_ForcedTimeoutSession`, `YfData` timeout clamp; **`fetch_stock`** → optional **Alpha Vantage** daily fallback when **`ALPHAVANTAGE_API_KEY`** set; **`fetch_info`** + AV **fundamental** merge; **`evaluate_fundamental_sieve`**; `fetch_global_market_bundle` / `GlobalMarketSnapshot` (**`rs_spy_ratio_map`**, **`fundamental_sieve_map`**); **`rs_spy_ratio_map_from_close_matrix`**; `fetch_*` never-raise; tape + macro via desk slice; swallowed exceptions → **`log_warn`** on stderr for key paths
    ├── ta.py                 # TA class — indicators, **`apply_ffd`**, **`calculate_hurst_exponent`** (R/S, 100-bar), **adaptive `get_dark_pool_proxy`**, **`get_shadow_move` (whale band)**, **`get_correlation_matrix`**, HVN / volume profile
    ├── options.py            # Black-Scholes (**`bs_greeks`**: δ, γ, θ, ν, **vanna**, **charm**), Corrado-Su, EV, Kelly, Quant Edge, **GEX / gamma flip / `predict_opex_pin`**, Diamonds, **`Opt.detect_pre_diamond`**, **`Opt.portfolio_allocation`** (+ **Sentinel sector** / **top-3 ρ** guards), **`scan_single_ticker`** (optional **`spy_df`**, **`panel_raw`**), **`scan_watchlist_edge_rows`** (optional **`panel_raw`**), **`watchlist_correlation_matrix_cached`**, **MC PoP**, **`PortfolioRisk`**
    ├── sentiment.py          # **Bayesian-style `analyze_news_bias`**, HMM (FFD), CC sim, Alerts, QuantBacktest
    ├── chart.py              # Price / volume / RSI / MACD + **Shadow move (purple)** + **OpEx pin** + HVN / EM / gamma flip / correlation heatmap
    ├── ui_helpers.py         # Sparklines, fragments, **`sentinel_ledger_metrics`**, **`sentinel_ledger_table_rows`**, **`ledger_theta_desk_day`**, regime **Shadow breakout** banner, **expected_move_safety_html**, **Θ/Γ desk line**
    ├── signal_desk.py        # **`compute_desk_consensus`** (+ **Hurst regime**, **`whale_sweep`**, **`fundamental_sieve`**, **`unified_probability`**, **`ofi_detail`**, **`daily_aggressor_proxy`**, **`blend_unified_probability`**), **`detect_whale_sweep`**, **`ffd_stationarity_proxy`**, **`_cached_hurst_rs`**, **`unified_probability_dial_html`**, **`traders_note_markdown`** (Unicorn; **GOD TIER**; **Alpha realization**; **`turbo_desk`**), **`vwap_distance_stats`**, **`institutional_absorption`**, **`institutional_heatmap_ribbon_html`**, **`desk_conviction_multiplier`**, **`bento_box_html`**, **`bento_accents_from_consensus`**
    ├── pages.py              # **`build_context`** (optional **`global_snapshot`**, **`defer_headlines_earnings`**): options → GEX → **OpEx pin map** → **shadow move** → **shadow breakout** flag → fused Gold → confluence → diamonds
    ├── utils.py              # **`safe_last`**, **`safe_float`**, **`safe_html`**, **`safe_href`** (http/https only for `href`), **`log_warn`** → stderr
    ├── streamlit_threading.py # Thread pools with ScriptRunContext re-attach per task
    └── css.py                # Full CSS theme + Mini Mode + sidebar toggle JS
```

### Observability & HTML hygiene

- **`modules.utils.log_warn`** — Prefer over bare `except: pass` for non-trivial failures; writes **`[cashflow-trader]`** / **`[cashflow-trader:TICKER]`** lines to **stderr** (visible in local terminals and Streamlit logs). **`data.py`**, **`options.py`**, and **`sentiment.py`** use it on previously silent handlers (e.g. news timestamps, earnings merge paths, quant/HMM fallbacks, scanner sub-blocks).
- **`safe_html` / `safe_href`** — Any string that reaches **`st.markdown(..., unsafe_allow_html=True)`** should be escaped or validated. **`safe_href`** only allows **`http://`** / **`https://`** URLs in attributes (blocks **`javascript:`** etc.). **Intel → Market News** uses **`_news_item_markdown_html`** in **`renderers.py`**; macro row labels are escaped.

**Why this split works with Streamlit:**

- `st.set_page_config()` is the first Streamlit call in `app.py` (required)
- CSS/navbar injection happens immediately after via `inject_css_and_navbar()`
- Modules never call `st.*` at import time — only when their functions are invoked
- `@st.cache_data` decorators work correctly because `streamlit` is imported in each module (`quant_edge_score` is intentionally **uncached** so optional chain-based MC fusion stays hash-safe)

**Parallel fetches and Streamlit Cloud:**

- Background `ThreadPoolExecutor` workers that call `@st.cache_data` need Streamlit’s `ScriptRunContext` on that thread. `make_script_ctx_pool()` plus `submit_with_script_ctx()` capture context when work is submitted and re-attach it at the start of each task (initializer-only attachment is not always enough after cache layers).
- The technical chart lives in `@st.fragment`; quant vs retail mode is passed via `st.session_state` (not extra fragment kwargs) so deploys and fragment reruns stay compatible. **Expected Move chart inputs** use the same pattern (`_cf_chart_em`, `_cf_em_safety`). **Gamma flip** uses **`_cf_gamma_flip`**; desk picks use **`_cf_bluf_cc_pick` / `_cf_bluf_csp_pick`** for Θ/Γ on the Diamond card. Stale kwargs from older sessions are ignored safely on the fragment signature.
- The **Rolling Edge Capture Log** uses a separate `@st.fragment(run_every=…)` that recomputes retail vs quant scores for every watchlist ticker; VIX and institutional mode are read from `st.session_state` (`_cf_vix_snapshot`, `_cf_use_quant_models`) so it stays aligned with the active ticker context. When **`_cf_global_market_bundle`** is present, **`scan_watchlist_edge_rows`** slices **`panel_raw`** instead of calling **`fetch_stock`** per symbol (fallback to **`fetch_stock`** if a column is missing).

### Performance & caching

> **Note:** While the **Global Market Bundle** caches price data to minimize API footprint, secondary metadata (**news**, **earnings**) may still trigger brief background fetches during workspace transitions so the desk stays current; **`build_context`** runs those fetches (with their own **`@st.cache_data`** TTLs) inside **`st.spinner`** on each full script rerun—so you may still see a short “working” state even when the **2y** price panel is a cache hit. **Clear price cache & retry** is scoped to the **price feed** (**`fetch_stock`** + **`fetch_global_market_bundle`**), not every cached helper in the app.

### Future optimization backlog

- **News / earnings spinner** — Default path still loads headlines + next earnings inside **`build_context`**. Set **`defer_headlines_earnings`: `true`** in **`config.json`** to skip those fetches up front; **Market News** then loads via **`@st.fragment`** (earnings glance stays thin until a dedicated fragment or provider exists).
- **Alternative earnings provider** — Optional future path: a dedicated calendar/earnings API with stable auth instead of Yahoo-only scraping, to reduce dependence on **crumb** / quote flows for dates alone (adds vendor choice, keys, and fallback logic).

### UI roadmap: information hierarchy

Desk upgrades from **raw metrics** toward **actionable signals** (ongoing).

1. **Consensus / “traffic light” signal** — **Shipped:** **`modules/signal_desk.py`** + **`compute_desk_consensus`** blends Quant Edge, confluence, fear/greed, daily/weekly structure, MACD/OBV tilt, **volume Z**, and **rolling VWAP distance Z** (combined into the **5% flow** weight; **Hurst regime** reweights RSI/BB vs MACD/RS in that slice) into a **0–100** score with **high risk / neutral / conviction** bands. Optional **RS vs SPY (~90d)** from **`GlobalMarketSnapshot.rs_spy_ratio_map`**; optional **`fundamental_sieve`** from **`fundamental_sieve_map`**; **`market_leader`** when **RS > 1** and **volume Z > 4**. **`app.py`** renders a **ring + bar** banner (compact strip in **Turbo mode**). When **`institutional_absorption`** fires, the banner adds an **INSTITUTIONAL ABSORPTION** callout and the score gets a small bonus. **Also shipped:** **unified probability dial** (separate **0–100** blend for headline scan: QE / confluence / RS tilt).
2. **Context-first “bento” grouping** — **Shipped:** three columns under the note — **The setup** (Bollinger / squeeze language; **COIL** = BBW ≤ **5%** tile), **The momentum** (RSI, MACD, OBV, volume Z, **VWAP distance Z**, **batch RS vs SPY**, optional **absorption / whale trap**, **daily aggressor proxy**), **The exit** (Gold Zone distance + copy) — with **accent-colored** borders from **`bento_accents_from_consensus`**.
3. **Chart storytelling** — **Partially shipped:** price chart adds a **gold vertical** on the **last bar** when **volume Z ≥ 4** vs the prior 20 sessions (**`build_chart(..., mark_whale_volume=True)`**), with overlay key text. Golden Zone / existing overlays unchanged.
4. **Plain-English desk note** — **Shipped:** deterministic **`traders_note_markdown`** (markdown) below the consensus card — **Alpha realization** vs **`qs_at_entry`**, **GOD TIER UNICORN** when FFD/Hurst/fundamental/sweep align, **fundamental sieve** paragraph when FCF gate is hot, ATR-style stop line, squeeze / volume language, **VWAP stretch** when **|VWAP Z| ≥ 2**, **Unicorn alert** when **COIL + ICEBERG + LEADER** (one merged brief; no duplicate leader/absorption lines), else **Market leader** / **whale trap** paragraphs when those gates fire separately (absorption supersedes generic **4σ** footprint when applicable). **`turbo_desk`** single-paragraph mode; full note hidden in **mini / Turbo** layout. LLM swap remains a future option.
5. **Institutional heatmap ribbon** — **Shipped (detailed desk):** **`institutional_heatmap_ribbon_html`** — **COIL** / **ICEBERG** / **SWEEP** / **LEADER** segments plus **REGIME** / **DOMINANCE** lines and **conviction multiplier** subtitle; **SWEEP** when **`whale_sweep`** or **`vwap_urgency`**; **LEADER** when **RS > 1** vs SPY (batch map) **and** **volume Z > 4**.
6. **One-touch workflow** — **Shipped (illustrative):** expander **Calculate position size** — account $, **base risk %** × **`conviction_multiplier`** (**2.0×** when **COIL + ICEBERG + SWEEP** including **`whale_sweep`**; **Unicorn** note can still appear with **LEADER** without **SWEEP**, giving **1.25×**), **~1.5× ATR** stop below spot → **`suggested_shares_atr_risk`**; optional **binary Kelly** caption from **`d_wr`** when diamond stats exist; not broker-connected.

**Still optional later:** exhaustive **`log_warn`** on every inner **`continue`** in hot Yahoo loops, LLM-generated note, **Secrets**-default account size, breakout-candle callouts on chart, mini-mode heatmap strip parity.

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
python3 -m pytest tests/ -q
```

Covers `TA.get_correlation_matrix` (FFD-return path), earnings runway spark series, `Opt.portfolio_allocation` / `_simple_corr_haircut` / sector–ρ guards, **`tests/test_signal_desk.py`** (consensus, absorption, VWAP Z, heatmap, **market leader**, unified blend, OFI proxy, bento accents, **desk conviction + whale_sweep**, **`test_traders_note_unicorn_perfect_storm`**), **`tests/test_data_rs.py`** (**`rs_spy_ratio_map_from_close_matrix`**), **`tests/test_bs_greeks.py`** (**vanna** / **charm**), and basic Black–Scholes / EV math (no live Yahoo calls). Use **`python3 -m pytest`** if the `pytest` script is not on your `PATH`.

## Deploy to Streamlit Cloud

1. Push to GitHub (app and `modules/` must stay in sync on the same branch the app tracks)
2. Connect at [share.streamlit.io](https://share.streamlit.io)
3. Set `app.py` as the main file
4. Theme: **`.streamlit/config.toml`** in the repo is picked up automatically (dark terminal palette); only **`.streamlit/secrets.toml`** stays local/gitignored.
5. (Optional) Add secrets in Streamlit Cloud dashboard under Settings → Secrets — e.g. **`ALPHAVANTAGE_API_KEY`** for **`fetch_stock`** fallback when Yahoo returns no rows
6. (Optional) In **`config.json`**, set **`defer_headlines_earnings`** to **`true`** to lazy-load **Market News** via fragment (see **Future optimization backlog**)

If the app fails to import, check Cloud logs: mismatched commits (e.g. `app.py` importing a symbol removed from `modules/ui_helpers.py`) cause immediate `ImportError` on boot.

### Yahoo data and shared IPs (scanner “goes dark”)

Community Cloud apps often **share egress IPs**. Heavy watchlists plus frequent reruns can cause Yahoo to **throttle**, **block**, or **tar-pit** (hold the connection until a long client timeout). **`yfinance`** then returns **empty** history or raises **curl (28)** timeouts, and may log **`$TICKER: possibly delisted; no price data found`** even for major symbols — that message is a **false flag** when the real issue is **rate limiting**, not delisting.

**What to do:**

- **Reboot the app** in the Streamlit dashboard (**⋯ → Reboot app**) to get a **fresh container** and often a **new IP**.
- In the UI, if you see **Price data unavailable** for the focused symbol, use **Clear price cache & retry** (or switch tickers on the watchlist tape)—a plain browser refresh may **not** refetch Yahoo immediately while **`fetch_stock`** cache is warm (the button also clears **`fetch_global_market_bundle`**, **120s** TTL).
- Rely on **caching** already in the repo (`fetch_stock` **300s**, **global snapshot** **120s**); avoid hammering **Scan Watchlist** unnecessarily.
- Prefer a **shorter watchlist** for 24/7 Cloud use if problems recur; mega-caps and indices add traffic without always helping a focused radar.
- Add **`ALPHAVANTAGE_API_KEY`** (Secrets or env) so **`fetch_stock`** can try **Alpha Vantage** daily bars when Yahoo still returns nothing after retry (**free tier** rate limits apply).
- If logs still show very long **`timed out after … ms`** lines, deploy the latest **`main`**: the app clamps **`YfData._make_request`** / **`_get_cookie_and_crumb`**, forces **`timeout=`** on **`history`** / **`download`**, and subclasses **`Session.request`**. Tune **`_YAHOO_YF_TIMEOUT`** in **`modules/data.py`** (e.g. **8–10**) if **5s** is too aggressive on a slow home network — no Secrets needed, only that float.

If Cloud logs show **`503 GET /script-health-check`** around **60s**, the script was taking too long to become healthy — the data-layer changes above reduce redundant Yahoo work; a reboot still helps after a bad IP day.

---

## Config (`config.json`)

Persisted locally via atomic writes (`.tmp` → `os.replace`). The watchlist **auto-saves** when you edit it (and on each script rerun if the text area differs from disk), so a new browser session reloads from `config.json` on the same machine or container.

On Streamlit Cloud the repo’s `config.json` is read from git; **runtime writes** may be blocked (read-only). If saving fails, set a top-level secret `watchlist = "PLTR,AAPL,..."` (comma-separated, one line) in **Settings → Secrets** so the list survives redeploys.

Keys: `watchlist`, `scanner_sort_mode`, **`scanner_mode`** (**`📈 Options Yield`** or **`🎯 Equity Radar`** — saved when you change **Trading Hemisphere** in **Command Center**), `strat_focus`, `strat_horizon`, `mini_mode`, **`defer_headlines_earnings`** (optional; default **`false`** — lazy **Market News** via **`st.fragment`**), `overlay_ema`, `overlay_fib`, `overlay_gann`, `overlay_sr`, `overlay_ichi`, `overlay_super`, `overlay_diamonds`, `overlay_gold`, `use_quant_models`.

### Trading mode (`scanner_mode`)

The **Trading Hemisphere** control writes **`scanner_mode`** to **`config.json`** on change (via **`modules.config.save_config`**). A successful write triggers a short **`st.toast`**; a failed write (read-only host) still keeps the mode for the session and toasts a warning. On startup, the app hydrates the widget from disk so you do not need to re-toggle after a restart. On Streamlit Cloud, if the filesystem is read-only, the mode still applies for the session (same pattern as other config keys). Each rerun also mirrors the active value into **`st.session_state["_cf_scanner_mode"]`** (used by helpers that need the resolved mode after widget hydration).

**Intel → Risk, scanner & intel → Market Scanner:** toggling **📈 Options Yield** vs **🎯 Equity Radar** switches the **scanner results presentation** (options desk vs equity radar table) using the same cached **`_cf_scanner_bundle`** rows when available. **Cashflow & strikes** follows the same mode: **Options Yield** shows the full chain and prop-desk blocks; **Equity Radar** shows only the **Delta-One workspace** + equity desk until you flip back.

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
| Volume | OBV, Volume Profile, VWAP (**`TA.vwap`** cumulative; desk uses **rolling multi-bar VWAP** in **`vwap_distance_stats`**), **HVN nodes (volume-at-price)**, **adaptive volume Z-score (dark pool proxy)** |
| Volatility | Bollinger Bands, ATR (14), Hurst Exponent (**`TA.hurst`** variance-ratio; **`TA.calculate_hurst_exponent`** R/S on **100** closes for desk regime), **1-σ Expected Move (IV × √T)** |
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
| Fractional Differentiation (FFD) | Improve stationarity while preserving memory in time-series dynamics (see **Elite tier roadmap** below) |
| HMM Regime Detection | Classify latent volatility regimes on **FFD diff + rolling vol** features (subsampled, diagonal covariance, bounded EM iterations); guarded against numerical failures |
| Continuous Kelly (Merton) | Compute variance-aware continuous-time allocation with optional half-Kelly |
| OTM IV Skew Regime Ratio | Classify market-maker fear/greed posture from put-vs-call OTM implied volatility |
| **Vanna & Charm (BS)** | **`bs_greeks`**: **vanna** = ∂Δ/∂σ scaled per **1%** IV move; **charm** = ∂Δ/∂T per **calendar day** — desk CC Greeks panel |
| Vectorized Historical Edge Proxy | Backtest threshold/hold edge signals over daily history without UI lockups |
| **Desk VWAP distance Z** | **`signal_desk.vwap_distance_stats`**: rolling **20**-session VWAP from typical price; Z of **(Close−VWAP)/VWAP** vs prior **20** deviations; **`vwap_urgency`** when aligned with **volume Z** |
| **Hurst R/S (desk)** | **`TA.calculate_hurst_exponent`**: single-window **log(R/S)/log(n)** on **100** closes; **`signal_desk._cached_hurst_rs`** (**1h** Streamlit cache) feeds regime tilt in **`compute_desk_consensus`** |
| **Whale sweep** | **`detect_whale_sweep`**: close **>** rolling VWAP, volume **Z > 4**, aggressor proxy **> 0.7**; **`institutional_dominance`** with **absorption** |
| **Fundamental sieve** | **`evaluate_fundamental_sieve`**: FCF yield vs EV + EBITDA/asset YoY (Yahoo + AV); **`ten_x_candidate`** when yield **> 10%** and efficiency **> 1** |
| **Batch RS vs SPY** | **`data.rs_spy_ratio_map_from_close_matrix`**: **~90**-session growth-factor ratio vs **SPY** on inner-aligned closes; **`GlobalMarketSnapshot.rs_spy_ratio_map`** for **watchlist ∪ risk**; desk **`market_leader`** when **RS > 1** and **volume Z > 4** |
| **Allocator sector / ρ guards** | **`Opt.portfolio_allocation`**: **0.5×** sector cluster when ledger **sector > 20%** of capital; **0.5×** when **|ρ| > 0.8** vs **top-3** ledger names on FFD matrix |

`hmmlearn` and `scipy` are handled with safe fallbacks so the app remains usable if those packages are unavailable.

---

## Elite tier roadmap: market microstructure & data science

This section frames where the desk is headed beyond classic “green arrow” TA: **stationarity with memory**, **volume–price joint tests**, **convex sizing**, **structural liquidity (VPVR/HVN)**, and **portfolio-level correlation hygiene**. **Already shipped** here includes FFD + HMM correlation path, adaptive volume Z, HVN-weighted GEX, Kelly governors with correlation haircut, cluster penalty on scanner Blues, **desk-level institutional absorption**, **rolling VWAP distance Z**, **batch RS vs SPY** on the **global snapshot** (**`rs_spy_ratio_map`**), **institutional heatmap ribbon** (**COIL / ICEBERG / SWEEP / LEADER**) with **REGIME / dominance** callouts and **conviction-scaled** position sizer (**2.0×** = **COIL + ICEBERG + SWEEP** including **`whale_sweep`**), **whale sweep** + **TOTAL INSTITUTIONAL DOMINANCE**, **Hurst R/S** regime tilt (**RSI/BB** vs **MACD/RS**), **`ffd_stationarity_proxy`** in narrative, **fundamental sieve** (**`fetch_info`** + AV, **`evaluate_fundamental_sieve`**, **`fundamental_sieve_map`**), **scanner allocator** **sector** and **top-3 ρ** haircuts vs **Sentinel** + FFD matrix, **GOD TIER / Alpha realization** copy, **market leader** (**RS > 1** + whale volume Z), **unified probability dial**, **daily aggressor proxy**, **heatmap-colored bento** (**sweep_gold**), **Vanna/Charm** on BS Greeks, **portfolio ρ > 0.75** warning under Mission Control, **illustrative Kelly** on the sizer, optional **deferred news** fragment, and **Alpha Vantage** daily + **fundamental** endpoints when the key is set. **Remaining** emphasis: deeper **earnings** lazy-load if desired; optional **FFD-weighted** tape beyond the current regime blend.

### 1. Mathematical stationarity: fractional differentiation (FFD)

Integer differencing (\(d = 1\), e.g. log returns) pushes prices toward stationarity but discards **long-memory** structure that institutions lean on for regime and slow mean reversion. **Fractional differentiation** uses a real order \(d\) (often **0.3–0.7**) so the series is **more stationary** while **retaining persistence**:

\[
\Delta^d X_t = \sum_{k=0}^{\infty} \binom{d}{k} (-1)^k X_{t-k}
\]

**In this repo:** `TA.apply_ffd` (default **`d=0.4`**, bounded weights) and **FFD-based correlation** (`ffd_returns_from_closes` / `get_correlation_matrix`) are **live** in v21+. **Desk:** **`ffd_stationarity_proxy`** and **Hurst-weighted** flow blend in **`compute_desk_consensus`** tie part of the flow score to **memory-aware** dynamics; further **FFD-only** momentum terms remain optional.

### 2. Volume-weighted alpha: VWAP deviation and relative volume

A raw volume spike is noisy; a professional read combines **where** size traded with **how unusual** participation is. A standard construct is the **z-score of distance from session or rolling VWAP** (conceptually \(Z_{\text{VWAP}} = (P_t - \text{VWAP}_t) / \sigma_{\text{VWAP}}\) when a rolling dispersion of VWAP distance is defined), together with **relative volume (RVOL)**. **Narrative:** when price trends, **RVOL / volume Z** is extreme (e.g. **Z > 4**), and **VWAP distance** expands, the desk reads **urgency** (aggressive flow sweeping the book). **In this repo:** VWAP and adaptive volume Z (`get_dark_pool_proxy`) exist on the TA side; **rolling VWAP-distance Z** is **shipped** in **`signal_desk.vwap_distance_stats`** (daily multi-bar VWAP — not intraday tape). **`detect_whale_sweep`** adds a stricter **above-VWAP + Z>4 + aggressor>0.7** gate (OHLCV proxy). **RVOL** as a separate column remains optional future work.

### 3. Convexity engine: Kelly-style allocation

**Kelly** formalizes optimal growth under an edge: \(f^* = (bp - q) / b\) with **odds** \(b\), win probability \(p\), and \(q = 1 - p\). **In this repo:** Kelly governors and **`Opt._simple_corr_haircut`** already scale scanner allocation; **`portfolio_allocation`** adds **Sentinel sector** and **top-3 FFD ρ** multipliers when ledger + matrix are supplied; the **Calculate position size** expander adds an **illustrative binary Kelly** line from **`d_wr`** vs **1:1** payoff when diamond stats exist (**`kelly_criterion`**).

### 4. Structural “gold zone”: volume profile (POC, value area, HVN)

Retail draws arbitrary support; professionals anchor to **high volume nodes (HVN)**, **point of control (POC)**, and **value area (VA)**—where liquidity actually accumulated. **In this repo:** `TA.get_volume_nodes`, Gold Zone fusion, and **HVN-weighted GEX** are **live**. The desk narrative can further stress **“structural floor”** when spot aligns with an HVN and consensus turns constructive (**roadmap copy / scoring tie-in**).

### 5. Visual information architecture (“zero-noise” desk)

**Primary:** a high-resolution **equity curve / projection** for the active setup (backtest path exists; deeper integration is optional). **Secondary:** **correlation matrix** warnings — **shipped:** **`st.warning`** when max peer **ρ > 0.75** vs the active ticker on the same **Portfolio Risk** matrix; scanner **cluster penalty** on Blues remains separate; **shipped:** **`portfolio_allocation`** haircuts vs **Sentinel Ledger** notionals and **top-3** FFD correlations.

### `modules/signal_desk.py` — Elite tier upgrades

1. **FFD / Hurst-aware desk flow** — **Shipped:** **`ffd_stationarity_proxy`** for narrative and **GOD TIER** logic; **Hurst R/S** (**`TA.calculate_hurst_exponent`**, **`_cached_hurst_rs`**) tilts consensus **tape + flow** (mean-reversion vs trending weights on RSI/BB vs MACD/RS).
2. **“Whale trap” / institutional absorption** — **Shipped:** **`institutional_absorption`**: **volume Z ≥ 4** (vs prior **20** sessions, last bar excluded from μ/σ) and **muted** last daily close vs an **ATR-scaled** band; wired into **`compute_desk_consensus`** (`absorption`, `absorption_detail`), **`consensus_banner_html`**, **`consensus_compact_html`**, **`traders_note_markdown`**, and bento **momentum** text. Covered by **`tests/test_signal_desk.py`**.
3. **Whale sweep** — **Shipped:** **`detect_whale_sweep`** (above rolling VWAP, **Z>4**, aggressor **>0.7**); **`institutional_dominance`** with absorption; **SWEEP** ribbon uses **`ribbon_sweep_active`** (**sweep** or **`vwap_urgency`**); **sweep_gold** bento glow.
4. **Rolling VWAP distance Z** — **Shipped:** **`vwap_distance_stats`**: **20-bar** rolling VWAP, **Z** of relative close-vs-VWAP deviation vs **prior 20** bars; consensus **flow** blend, **`vwap_z`**, **`vwap_detail`**, **`vwap_urgency`**; trader’s note when **|Z| ≥ 2**; heatmap **SWEEP** when **`ribbon_sweep_active`**.
5. **Batch RS vs SPY + market leader** — **Shipped:** **`rs_spy_ratio_map_from_close_matrix`** in **`data.py`**; **`compute_desk_consensus(..., rs_spy_ratio=)`**; **`market_leader`** and **LEADER** ribbon when **RS > 1** and **volume Z > 4**.
6. **Portfolio optimizer hook** — **Shipped:** **ρ > 0.75** vs active ticker warning after the heatmap; **`Opt.portfolio_allocation`** **sector** + **top-3 ρ** haircuts vs **Sentinel** when **`app.py`** passes ledger + FFD matrix.

**Disclaimer:** All labels above are **research and education**; they do not guarantee performance. Yahoo-derived OHLCV cannot observe true order flow or lit book imbalance.

---

## Known Limitations

- **Yahoo Finance** may **throttle, block, or tar-pit** requests from **Streamlit Community Cloud** (shared IPs, bot heuristics). Symptoms: **empty** price data, **curl (28)** / **`Operation timed out after … ms`** in logs, scanner rows with **n/a**, and **`possibly delisted`** stderr from **`yfinance`** for symbols that still trade. **Reboot** the app for a new IP; reduce watchlist size and rerun frequency. The data layer is built to **degrade gracefully**: core **`fetch_*`** helpers return **empty / `None`** instead of crashing the UI. Under the hood: **curl_cffi** (**Safari 15.5**), **`_ForcedTimeoutSession`**, **`YfData`** timeout clamp, **`history` / `download`** explicit timeouts, **caching**, **batched tape**, **no retry-on-empty**, **no retry on timeout** — not a paid data feed.
- Config persistence is local-only; Cloud deploys reset the filesystem
- You may still see occasional `missing ScriptRunContext` lines in Cloud logs from threads outside the app’s pool (Streamlit labels many as ignorable in bare mode); parallel cached fetches use `submit_with_script_ctx` to minimize this
- Micro-cap tickers (e.g. BMNR) may lack options chains; the desk falls back gracefully
- **Scanner EM Safety** uses the same **realized-vol proxy** as the scanner MC block when a full options IV snapshot is not fetched per ticker (fast path); the main dashboard uses **listed IV** for chart and Recommended Trade when the chain loads
- **GEX / gamma flip** depends on **open interest** and option quotes; some symbols return chains without OI — the engine returns empty GEX and the UI shows **—** / omits the flip line
- **Market Scanner** results are written to **`_cf_scanner_bundle`** when you click **Scan Watchlist**; reruns reuse them until the next scan (if the bundle is missing, run **Scan Watchlist** once). Editing the watchlist text without rescanning can leave a **stale** bundle versus the new list.
- **10x Convexity sieve** depends on **Yahoo `info`** (float, short %) and a usable **options** snapshot for **skew**; missing fields fail gates and almost always produce **—**. The label is a **research filter**, not a prediction of returns.
- **Fundamental sieve** needs **FCF, EV, and YoY EBITDA/asset growth**; without **`ALPHAVANTAGE_API_KEY`** the efficiency leg often returns **`None`** (by design — no synthetic zeros). **Sector allocator** uses **`fetch_info`** **sector**; missing sector buckets as **Unknown** and may under-trigger the **20%** guard.

---

## Disclaimer

This tool is for **educational use only** and does not constitute financial advice. Past performance in the Premium Simulator does not predict future results. Always confirm quotes in your broker before placing orders.
