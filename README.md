# CashFlow Command Center · v24.0 (Free Edition)

**Predictive analytics options desk**: one screen for watchlist context, consensus, chains, scanner, and a Sentinel ledger. Built with **Streamlit**; data from **Yahoo Finance** (optional **Alpha Vantage** fallback and fundamentals).

---

## ⚠️ Read this first: August 2026 audit

A 13-agent adversarial audit of this codebase confirmed **88 defects**. The full report is in **[`AUDIT_2026-08.md`](AUDIT_2026-08.md)**; the UI findings are in **[`UI_SIMPLIFICATION.md`](UI_SIMPLIFICATION.md)**.

**All confirmed Critical and High defects are now fixed**, each pinned by a regression test, and every fix was re-checked by an independent verifier that re-opened the source rather than trusting the report. The suite went from **127 to 852 tests**, all passing.

The one thing that has *not* changed is the epistemics: **nothing in this app has been validated on live forward returns.** `score_10x_potential` was rebuilt (the double-counted diamond point is gone, the scale is honest) but it remains a heuristic, not a payoff model. Prefer the **🎯 Find 10x** tab, which ranks on payoff shape and labels every row `unvalidated` until an outcome ledger proves otherwise.

The audit's summary was *"the '10x' branding is not currently honest."* It is closer now. It is not done, see **Roadmap Stage 2** in the report for the outcome ledger that would make a validation claim meaningful.

---

## P0 multi-venue (paper)

Shared paper trading scaffold (`signals/`, `risk/`, `execution/`, `venues/`) — **dry-run / paper only**, no live orders. See [`docs/P0_MULTI_VENUE.md`](docs/P0_MULTI_VENUE.md).

## Phase A ingest snapshots

Background ingest writes SQLite WAL bars so Streamlit does not fetch Yahoo on click. Fallback to Yahoo if the DB is empty (Cloud-safe). See [`docs/PHASE_A_INGEST.md`](docs/PHASE_A_INGEST.md).

## At a glance

- **P0 multi-venue (paper)**: Signal schema, Kelly + promotion gate, PaperLedger, Kalshi dry-run adapter — see [`docs/P0_MULTI_VENUE.md`](docs/P0_MULTI_VENUE.md).
- **Phase A ingest snapshots**: Worker writes SQLite WAL bars; Streamlit uses the snapshot when present (no Yahoo on click), else existing fetch. See [`docs/PHASE_A_INGEST.md`](docs/PHASE_A_INGEST.md).
- **🎯 Find 10x**: **New.** Asymmetric-opportunity scanner: ranks on `convexity × confirmation`, fusing payoff shape (bounded downside vs ATR-expansion target) with retail attention and independent creator consensus. Plain-English verdict on every card; the math behind an expander.
- **Options Yield**: Full income workflow: BLUF trade line, GEX / gamma flip, Monte Carlo PoP, spreads, Greeks, multi-ticker scanner.
- **Vol Skew Card**: Cash Flow tab surfaces put IV vs call IV (10% OTM) with color-coded strategy guidance: elevated put skew → sell CSPs; elevated call skew → sell CCs.
- **IV Term Structure**: Mini-table showing ATM IV across the next 3 expirations with contango / backwardation label, so you see event risk priced in at a glance.
- **CSP Payoff Diagram**: Interactive Plotly P&L-at-expiry chart inside each CSP card; shows max profit, breakeven, and max loss with dashed markers for spot/strike/breakeven.
- **Profit Roll Alerts**: Sentinel Ledger fires live alerts at 50% and 80% profit capture (BS-computed current mark vs entry premium); 21-DTE gamma-risk alert also in place.
- **3-state Market Regime**: HMM now distinguishes Calm / Transitional / Stress regimes (previously binary). Regime-conditional Kelly haircut is graduated: Stress applies full 50% size reduction, Transitional applies 35% partial.
- **Equity Radar**: Stock-focused scan: pre-diamond signals, actionable targets, Delta-One setup (same scan payload; options chrome hidden until you switch back).
- **Sentinel Ledger**: Track legs; pin distance, edge realization, portfolio delta/theta/vega + 1d VaR, golden-zone maturity hints, and roll alerts.
- **10x scanner + conviction**: `10x Potential` score, score>=5 screener, and `💎 CONVICTION` when Blue Diamond aligns with 10x. *(See the audit warning above, this score has no payoff term; prefer the 🎯 Find 10x tab.)*
- **Market Explosion Radar**: `🌎 Market Explosion Radar` tab: Tier 1 broad batch filter + Tier 2 deep scan of survivors, ranked by `explosion_score`.
- **Intraday confirmation gate**: IMMINENT pre-diamond calls are now checked against 1h RSI + OBV before final upgrade.
- **Auto scanner refresh**: Scanner can auto-rerun on a timer (`auto_scan_interval`, default 300s) after first manual scan.
- **Watchlist earnings heat map**: Intel tab shows 30-day earnings urgency buckets (`this_week`, `next_week`, `this_month`, `clear`, `reported`, `unknown`).
- **Persistent trade journal**: `trade_journal.json` survives browser restarts with close workflow and realized P&L stats.
- **Walk-forward replay backtest**: Setup tab can replay point-in-time Blue Diamond-style triggers and report forward returns.
- **Radar hit persistence**: Radar and scanner conviction hits are stored in `radar_hits.json` and viewable in-tab.
- **PWA install metadata**: Manifest + mobile meta tags for add-to-home-screen behavior.
- **In-app glossary**: **Intel → Quick Reference Guide**.

---

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

**Tests**

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -q
```

**852 tests, all passing.**

### P0 multi-venue paper scaffold

Paper/dry-run only (no live orders): shared `Signal` schema, fee-aware Kelly + promotion gate, Kalshi dry-run venue stub, and an in-memory/SQLite paper ledger. See [`docs/P0_MULTI_VENUE.md`](docs/P0_MULTI_VENUE.md). Streamlit `app.py` is unchanged.
 Coverage includes utils (`safe_last`, `safe_float`, `safe_html`, `log_warn`), `ConfigTransaction`, correlation / RS vs SPY, signal desk, BS Greeks (vanna/charm, now pinned by a finite-difference test), quant edge, allocation, watchlist helpers, smoke imports, and the v24.0 modules below (no live network in any test).

> **Note on `requirements.txt`:** the pinned `numpy==2.0.2` does not build on Python 3.13+. On a newer interpreter, install unpinned (`pip install streamlit yfinance pandas numpy plotly requests hmmlearn scipy pytrends pytest`).

---

## New in v24.0, the asymmetry stack

Five new modules, each independently unit-tested and importable **without Streamlit** (pure logic is separated from rendering, so the math runs headless):

| Module | Tests | What it does |
|---|---|---|
| [`modules/asymmetry.py`](modules/asymmetry.py) | 73 | The convexity engine. Expected value over a discrete outcome distribution (`Σ pᵢ·payoffᵢ`), convexity ratio, IV rank/percentile, coiled-spring score, catalyst windows, and **Kelly for skewed payoffs**: the exact two-point solution `f* = (p·b − q·a)/(a·b)`, not the symmetric `(pb−q)/b` shortcut that is only valid at `a=1`. `base_rate_report` computes precision/recall/lift at 2x/5x/10x and routes through `promotion_gate`. |
| [`modules/creator_signals.py`](modules/creator_signals.py) | 75 | Free-source creator tracking: YouTube channel RSS, Substack/blog RSS, Reddit DD authors. **No paid APIs.** Requires ≥2 *independent* creators for full marks; a lone voice is capped and flagged `single-source`. |
| [`modules/dossier.py`](modules/dossier.py) | 74 | Ticker deep-dive. Deterministic fundamentals floor (56 sourced facts) + optional narrative from the local `claude` CLI. **Every number comes from the data layer**: `facts` and `narrative` are different types, and any figure the model emits is stripped. |
| [`modules/explain.py`](modules/explain.py) | 45 | Progressive disclosure: **66 jargon terms** registered with a plain sentence, a real explanation, and the formula *this codebase actually uses*. `metric()` is the one canonical way to put a number on screen. |
| [`modules/find10x.py`](modules/find10x.py) | 24 | The 🎯 Find 10x tab. Fuses the four streams above into one ranked list. |

### How Find 10x ranks

```
opportunity = 0.60 × convexity  +  0.40 × confirmation
```

- **convexity**: `(target − entry) / (entry − support)`. Support is the trailing 20-day swing low; target is ATR-expansion based. A pure payoff-shape number with **no attention in it at all**. Saturates at 5:1.
- **confirmation**: retail chatter (Reddit / StockTwits / Google Trends) blended with creator consensus. A **tie-breaker between good payoff shapes; it can never create one.**

Missing evidence lowers `confidence` and is named on the card. It never scores zero silently. A row built on one pillar still ranks, but announces it is half-blind.

### Using the AI dossier

The narrative layer shells out to your local `claude` CLI (no API key, no cost beyond your existing subscription). If the CLI is absent, or you deploy to Streamlit Cloud, it degrades to the deterministic fundamentals dossier automatically. If narratives are missing, authenticate:

```bash
claude
```

---

## Fixed in v24.0

| Fix | File |
|---|---|
| **Vanna sign was inverted**: told a call writer an IV spike *reduces* their delta when it increases it. Now pinned by a finite-difference test and a put-call-parity test | [`options.py:108`](modules/options.py) |
| **Tape pillar operator precedence**: `tape + 6.0 if obv_up else -4.0` binds as `(tape + 6.0) if obv_up else (-4.0)`, so a flat OBV discarded the MACD base and clamped the pillar to 0. Found at **two** sites | [`signal_desk.py:587`](modules/signal_desk.py) |
| **Alpha Vantage served split-unadjusted bars** into an `auto_adjust=True` pipeline, a fake gap at every reverse split. Now prefers `TIME_SERIES_DAILY_ADJUSTED`, back-adjusts the whole OHLC bar, and tags `attrs["price_basis"]`. New `price_basis()` / `bases_comparable()` guards | [`data.py:433`](modules/data.py) |
| **Fabricated macro defaults**: VIX `20.0` and 10Y `4.5%` were displayed as live data and fed the Black-Scholes rate. Now `price=None, unavailable=True`; every consumer already guards with `if vix_val and …`, so absent macro *disables* VIX-conditional scoring instead of inventing calm | [`data.py:634`](modules/data.py) |
| **Corrupt journal was silently wiped**: an unreadable `trade_journal.json` became `[]` and the next append atomically destroyed the history. Now quarantined to `.corrupt-<timestamp>` (bytes preserved), and writes are *refused* if quarantine fails | [`config.py:128`](modules/config.py) |
| **Radar zeroed 35% of its score in silence**: a failed price fetch left volume + earliness unscored with no flag, contradicting the module's own documented rule. Now flags `no-price-data` + `partial-data` | [`sentiment_radar.py:431`](modules/sentiment_radar.py) |
| Test fixture bugs: a 3-arg `np.maximum` (silently dropped its third term) and a read-only `.values` array | [`tests/test_pre_diamond.py`](tests/test_pre_diamond.py) |
| **Kelly could size a position at >100% of bankroll**: the clip landed *before* the haircut and PoP multiplier, and above `f*≥2` the half-Kelly safety margin silently vanished. Now scales first, clips last, hard-capped at 25%. Verified over 1,600 random parameter sweeps | [`options.py:237`](modules/options.py) |
| **Lookahead bias in `detect_diamonds`**: the weekly-trend gate was computed once from the *complete* frame then applied per-bar, contaminating every historical diamond and both win-rate stats. Now sliced causally, label-convention aware (yfinance stamps Monday, `resample("W-FRI")` stamps Friday) | [`options.py:831`](modules/options.py) |
| **Journal realized P&L** assumed expiry intrinsic while the input was labelled "Close price", a CSP closed for \$1.20 recorded −\$2,530 instead of +\$230 | [`config.py`](modules/config.py) |
| **Conviction alerts re-fired on every rerun**, and ~67 duplicate rows silently evicted the entire genuine hit history through the `[-200:]` truncation. Now deduped per ticker per day; `pre_diamond` is derived instead of hardcoded `True` | [`renderers.py`](modules/renderers.py) |
| `find_gamma_flip` searched for the wrong crossing direction; the Pre-Diamond squeeze gate was dead and failed *open*; `compute_explosion_score` triple-counted one diamond and paid +5 for *missing* options data; "PoP" blended long and short win rates into one number | [`options.py`](modules/options.py) |
| Sentiment Radar scored a **crash identically to a rally** (`abs(roc_5d)`); the VIX "macro gate" was a banner that gated nothing; mention velocity was an unstabilised ratio where 1→10 mentions outranked 200→600 | [`sentiment_radar.py`](modules/sentiment_radar.py) |
| Charts: phantom diamond markers drawn when none existed, Fibonacci labels transposed on down-swings, green "S" rails drawn *above* spot, an "IV Crush" annotation plotting *realized* vol | [`chart.py`](modules/chart.py) |
| `st.secrets` scalars were merged into config and persisted into git-tracked `config.json` | [`config.py`](modules/config.py) |
| **Discord webhook alerting removed entirely** at the owner's request, `send_discord_webhook`, the settings UI, and both config keys are gone |, |

---

## Deploy (Streamlit Cloud)

1. Push this repo to GitHub; connect it at [share.streamlit.io](https://share.streamlit.io).
2. Main file: **`app.py`**.
3. Theme comes from **`.streamlit/config.toml`** (dark preset). Local secrets stay in **`.streamlit/secrets.toml`** (gitignored).

**Optional secrets (Settings → Secrets)**

| Secret | Purpose |
|--------|---------|
| `ALPHAVANTAGE_API_KEY` | Daily bars when Yahoo returns empty; fundamentals gap-fill via OVERVIEW / CASH_FLOW / statements |
| `watchlist` | Comma-separated tickers if the host cannot write `config.json` |

**Faster cold starts on Cloud:** set `"defer_headlines_earnings": true` in `config.json` so price/context load first; **Market News** loads from a fragment when you open it.

---

## When data fails (throttling, 503, empty charts)

Community Cloud **shares IPs** with other apps. Yahoo often **throttles** or slow-responds, *“possibly delisted”* in logs is frequently a **rate-limit lie**, not a bad symbol.

**Try this order**

1. **⋯ → Reboot app** (new container / often new IP).
2. Use **Clear price cache & retry** if you see “Price data unavailable” (browser refresh alone may not bust `fetch_stock`’s cache).
3. **Shorten the watchlist** for 24/7 hosting; avoid hammering **Scan Watchlist**.
4. Add **`ALPHAVANTAGE_API_KEY`** if Yahoo stays empty after retries.

**`503 GET /script-health-check`**: the first script run took too long. This repo batches a **single** `yf.download` for the desk (`fetch_global_market_bundle`), evaluates **one** fundamental sieve for the **active** ticker in that bundle (scanner still evaluates per symbol when you run it), and clamps HTTP timeouts. Combine with **`defer_headlines_earnings`** if probes still time out.

---

## Configuration (`config.json`)

Writes are **atomic** (temp file + replace). **Mission Control** fields are batched in a `ConfigTransaction` and flushed once before `build_context`; the **watchlist editor** still saves immediately on edit / reorder (then reruns).

**Common keys**

| Key | Notes |
|-----|--------|
| `watchlist` | Comma-separated symbols |
| `scanner_mode` | `📈 Options Yield` or `🎯 Equity Radar` |
| `equity_capital` | Equity Radar capital base used for suggested-share sizing |
| `intraday_confirmation` | Enables the 1h RSI/OBV confirmation downgrade for IMMINENT pre-diamond states |
| `auto_scan_interval` | Scanner auto-refresh cadence in seconds (`300` default; `0` disables) |
| `scanner_sort_mode`, `strat_focus`, `strat_horizon` | Desk controls |
| `mini_mode` | Turbo / compact layout |
| `use_quant_models` | Institutional quant path (default on) |
| `radar_universe` | Comma-separated universe used by the Market Explosion Radar broad filter |
| `defer_headlines_earnings` | Skip upfront news + earnings in `build_context` |
| `defer_options_first_pass` | Skip options-chain hydration on the first session render (faster Cloud cold boot) |
| `overlay_*` | Chart layers (EMA, Fib, Gann, etc.) |

On Cloud, if the filesystem is **read-only**, use Secrets `watchlist` and expect toasts when disk writes fail, session state still updates.

---

## What the app does

- **Consensus**: Score, trader’s note, bento (setup / momentum / exit), optional heatmap ribbon, unified probability dial, position-size expander (illustrative).
- **Recommended trade**: BLUF line with strikes, EM safety, Θ/Γ, MC PoP, walk-up limit hint.
- **Technical chart**: Overlays, whale volume markers, **shadow move** band, **OpEx pin**, gamma flip, expected-move rails.
- **Gold Zone & confluence**: Blended anchors; **Diamond** blue/pink signals; **pre-diamond** coil hint on scanner (Equity path).
- **Scanner**: Watchlist ranking, GEX regime, flow/bias, optional allocator; results cached in `_cf_scanner_bundle` until the next scan.
- **Rolling Edge log**: Parallel quant vs retail edge across symbols; fragment refresh.
- **Math**: Black-Scholes (+ vanna/charm), Corrado-Su, Kelly-style helpers, FFD-based correlation, HMM path when deps exist; quant edge **blends** pillars + regime track (see below).

---

## Repository layout

```
cashflow-trader/
├── app.py                 # Entry: imports, CSS/nav, main() orchestration
├── config.json            # Defaults for watchlist & UI (optional on Cloud)
├── radar_hits.json        # Persistent Market Explosion Radar / conviction hit history (gitignored)
├── manifest.json          # PWA install manifest
├── requirements.txt
├── requirements-dev.txt
├── .streamlit/config.toml # Theme
└── modules/
    ├── config.py          # load/save config, ConfigTransaction
    ├── data.py            # Yahoo/curl_cffi session, bundle download, fetch_*
    ├── pages.py           # build_context → DashContext
    ├── render_pre_tabs.py # Watchlist fragment, HUD, tape, desk header strip
    ├── renderers.py       # Tab bodies, equity desk, commit_watchlist
    ├── desk_locals.py     # DeskLocals snapshot for tabs
    ├── options.py         # Chains, GEX, scanner row builder, MC PoP
    ├── ta.py              # Indicators, FFD, Hurst, dark-pool proxy, shadow move
    ├── signal_desk.py     # compute_desk_consensus, ribbons, trader note
    ├── chart.py           # Plotly builders
    ├── sentiment.py       # NLP bias, backtests, alerts
    ├── ui_helpers.py      # Fragments, ledger HTML, dataframe helpers
    ├── utils.py           # safe_last, safe_float, safe_html, safe_href, log_warn
    ├── css.py             # Theme CSS + sticky nav JS
    └── streamlit_threading.py  # ScriptRunContext-aware thread pool
```

**Engineering notes**

- Prefer `log_warn` over silent `except` for debugging (stderr / Cloud logs).
- Dynamic HTML: use `safe_html`; links in attributes: `safe_href` (http/https only).
- Thread pool work that touches `@st.cache_data` uses `submit_with_script_ctx` so Streamlit context is restored on workers.

---

## v23.0, headline features

> Full expert-panel audit (Art Director · Copywriter · Quant PhD · Options Expert), all 20 items shipped.

| Area | What shipped |
|------|--------------|
| **Vol Skew Card** | Cash Flow tab now shows 10%-OTM put IV vs call IV with color-coded strategy guidance (amber = heavy put skew → sell CSPs; cyan = heavy call skew → sell CCs) |
| **IV Term Structure** | Collapsible mini-table below the expiry selector: next 3 expirations + ATM IV + contango/backwardation/flat label |
| **CSP Payoff Diagram** | Interactive Plotly P&L-at-expiry chart inside the CSP card with profit / loss shading, spot / strike / breakeven dashed markers, and summary caption |
| **Profit Roll Alerts** | Sentinel Ledger fires `st.warning` at ≥50% profit capture and `st.error` at ≥80%, BS-computed current mark vs entry premium. Combined with the existing 21-DTE gamma-risk alert |
| **3-state HMM** | `n_components=3` (was 2). States sorted ascending by vol: 0=Calm, 1=Transitional, 2=Stress. Diamond gate updated: stress_exposure > 0.25 → filter. A/B diagnostics panel shows all three state probabilities |
| **Graduated Kelly haircut** | Regime-conditional sizing now uses weighted stress: `prob(state2) + 0.35 × prob(state1)`. Smoother position-size reduction instead of binary on/off |
| **Chart overlay groups** | 8 flat toggles reorganised into three labelled groups: 📈 Price (EMAs, S/R, Gold Zone) · 🏗️ Structure (Fib, Gann, Supertrend, Ichimoku) · 💎 Signals (Diamonds) |
| **Terminology** | App-wide: HMM → "Market Regime", FFD → "Stationary Signal", Quant Edge → "Edge Score", dark pool proxy → "Institutional Flow". No model internals in the UI |
| **Tab renames** | "⚙️ Setup & Signals" → "📍 Signals" · "📊 Trade Ledger" → "📋 My Positions" |
| **CSS breathing room** | Card margins increased 8→16 px; section separators 12→16 px; added gold gradient tape separator |
| **Traders' Note** | Plain-English rewrite of the GOD TIER UNICORN note, no FFD / Hurst jargon in user-facing text |
| **CC sim missed upside** | Premium Simulator now shows a 5th metric: "Missed Upside" ($), the gain left on the table when stock is called away above the strike |
| **Scanner leading pillar** | Scanner summary string now names the top active confluence pillar: "Strong bullish confluence (7/9). Led by: Supertrend: Bullish." |
| **IVR warning** | Cash Flow tab warns when IVR < 30 (cheap implied vol, not an ideal premium-selling environment) |
| **Weekly bias gate** | Weekly BEARISH signal suppresses new covered-call suggestions and shows an override note |
| **Kelly → contracts** | Cash Flow tab translates Kelly % into contract count + collateral required for both CC and CSP |
| **Assignment probability** | CSP card shows put delta as assignment risk % with color coding (green < 20%, amber < 35%, red ≥ 35%) |
| **Earnings guard** | st.error fires when earnings are ≤3 days away: "Close or hedge now, do not sell premium into this" |
| **Hurst 252-bar min** | Minimum window for both Hurst methods increased 100→252 bars (1 trading year) for statistical reliability |
| **Backtest disclaimer** | Premium Simulator labels the proxy formula clearly so users don't confuse it with a live-signal backtest |

---

## v22.2, headline features

| Area | What shipped |
|------|----------------|
| Pinning | `predict_opex_pin`: gamma wall blended with Θ/Γ; ledger pin distance / maturity |
| Liquidity vs IV | `get_shadow_move`: whale-volume close band vs expected move; shadow **breakout** flag when price leaves band but stays inside EM |
| News | `analyze_news_bias`: forward-looking phrases weighted vs backward “beat/miss” |
| Desk | Absorption + VWAP-distance Z, RS vs SPY (~90 sessions) from bundle, heatmap ribbon (COIL / ICEBERG / SWEEP / LEADER), Hurst-tilted flow |
| Risk | Portfolio ρ warning; allocator sector + top-3 correlation guards with Sentinel |
| Equity mode | Radar summary, actionable targets, Delta-One tabs; shared scanner cache |
| Options | Vanna & charm on BS row; IV rank proxy; skew chart |
| Scanner upgrades | `score_10x_potential` integrated into scanner rows (`10x Potential`, flags), Intel **10x Screener**, and Blue+10x **CONVICTION** banner |
| Market Explosion Radar | New radar tab: Tier 1 batch squeeze/Hurst/RS/volume pre-filter -> Tier 2 deep `scan_single_ticker` pass; scores with `compute_explosion_score` |
| Alert destination | Scanner conviction logs to radar history (`radar_hits.json`), deduped per ticker per day |
| Intraday gate | Pre-diamond `🔥 IMMINENT BREAKOUT` is conditionally downgraded when 1h RSI is overbought or OBV is declining |
| Auto-monitoring | Intel scanner supports timer-driven reruns via `auto_scan_interval`; cache bundle stores last trigger/time |
| Sentinel risk | Portfolio aggregates now include **total vega** and a simple **1-day 95% VaR** (delta-correlation approximation) |
| Intel earnings | Watchlist earnings heat map expander with urgency buckets and risk callouts for this week / next week |
| Journal persistence | Track Trade now mirrors to disk (`trade_journal.json`), with close-trade workflow + realized P&L and win-rate stats |
| Walk-forward replay | Setup tab includes a point-in-time Blue Diamond replay with configurable lookback/hold/confluence |
| Alerting | In-app only: the Discord webhook path was removed in v24.0 |
| Mobile install | Manifest + theme metadata injection for home-screen install behavior |
| Hardening sweep | Removed remaining bare `except Exception:` and unguarded `.iloc[-1]` tail indexing across core modules |

**Pinning (intuition)**: Dealers hedge gamma; near expiry, GEX can concentrate at strikes (“walls”). Θ/Γ informs how strongly the model weights the wall in `predict_opex_pin`. Heuristic only, not a settlement forecast.

---

## Version lineage (short)

| Era | Focus |
|-----|--------|
| v14-v16 | Scanner, quant edge, MC PoP, Gold Zone, Kelly + correlation haircut |
| v17-v18 | Expected move, GEX, gamma flip on chart and scanner |
| v19 | Volume Z “whale” proxy, NLP bias on desk + scanner |
| v20 | Portfolio heatmap, cluster penalty, Sentinel ledger |
| v21 | FFD correlation, adaptive whale window, HVN-weighted GEX |
| v22 | OpEx pin, shadow band, Bayesian-ish news, Equity Radar, ledger alpha columns |
| v23 | Expert-panel audit: 3-state HMM, vol skew card, term structure, CSP payoff diagram, profit roll alerts, graduated Kelly, chart overlay groups, full terminology cleanup |

---

## 10x “convexity” sieve (strict filter)

Implemented in `scan_single_ticker` / `evaluate_asymmetric_convexity_sieve`. **All** gates must pass, most days should show **no** hits; that is intentional noise control.

| # | Idea | Rule of thumb |
|---|------|----------------|
| 1 | Small float | Under ~30M shares |
| 2 | Vol compression | BBW in bottom ~5% of a year lookback |
| 3 | Volume spike | Volume Z above 4 vs ~90d stats |
| 4 | Skew + squeeze story | High short interest; call IV above put IV (~10% OTM) |

Live code builds BBW from Bollinger on closes; skew from `calc_vol_skew`; float/short from `fetch_info`. **Pre-diamond** logic uses a different squeeze definition. Yahoo `info` is often incomplete, treat hits as hypotheses, not promises.

---

## Indicators & models (reference)

**Indicators**: Trend: EMA, Ichimoku, Supertrend. Momentum: RSI, MACD, stoch, CCI. Volume: OBV, profile, HVN, adaptive volume Z. Vol: Bollinger, ATR, Hurst, expected move. Structure: BOS/CHOCH, S/R, FVG. Gann / Fib as overlays.

**Models**: Corrado-Su; Monte Carlo PoP (seed 42); Kelly-style sizing; FFD for correlation; optional HMM; fundamental sieve (FCF/EV + efficiency YoY via Yahoo + Alpha Vantage when configured).

**Methodology (recent hardening)**

- **Quant Edge (`use_quant_models`)**: Five pillars (trend, momentum, volume, volatility, structure) form a **retail core**. The institutional track (Stationary Signal residual + 3-state Market Regime probability) is **blended** into that core (default 62% / 38%) instead of replacing it, then MC PoP fusion applies. This reduces wild score jumps when the HMM path errors and falls back to retail.
- **3-state Market Regime**: `GaussianHMM(n_components=3)` on [FFD-return, rolling-10-vol] features. States sorted ascending by mean volatility so state 0 = Calm, state 1 = Transitional, state 2 = Stress, deterministic labeling regardless of random init. The regime-conditional Kelly haircut uses a weighted composite `prob(state2) + 0.35 × prob(state1)`, giving a graduated size reduction instead of a binary switch.
- **Gold Zone**: Component prices are a **weighted** mean (POC and HVN highest, then SMA200, Fib, gamma flip, Gann) rather than equal weighting.
- **Scanner Kelly**: Continuous Kelly still uses expected return / variance when variance is positive. The discrete fallback now uses **MC PoP** as win probability and **BS short-put credit vs assignment-gap** style win/loss amounts instead of a flat 55% and daily `chg_pct`.
- **Diamond win rate**: Prefers a **holdout window** (signals only from the first ~75% of bars, forward outcomes on the full series) when history is long enough and the holdout set has enough diamonds; falls back to all signals otherwise. Still not a full walk-forward backtest.
- **CC backtest (`Backtest.cc_sim`)**: Covered-call premium per entry bar uses **`bs_price`** (same BS engine as the desk). Also tracks `missed_upside` (gain left on table when stock is called away above strike) alongside profit.
- **Vol skew (`calc_vol_skew`)**: Compares 10%-OTM put IV vs 10%-OTM call IV. Positive skew = puts are bid (bearish hedging, ideal for selling CSPs). Negative = calls are bid (ideal for selling CCs). Displayed prominently in the Cash Flow tab with color-coded guidance.
- **IV Term Structure**: Loops `opt_exps[:3]`, extracts ATM IV per expiry, labels the shape (Contango / Backwardation / Flat). Near IV > Far IV implies an imminent event risk.

---

## Known limitations

- **Yahoo** is best-effort; shared Cloud IPs worsen throttling. App returns empty/`None` instead of crashing where possible.
- **Cloud filesystem** may be read-only: use Secrets for `watchlist`.
- **Persistent journal on read-only hosts**: `trade_journal.json` writes can fail (UI shows a write error toast; session ledger still works).
- **Options**: Thin names may lack OI or chains; GEX/flip may be blank.
- **Scanner bundle**: Stale until you **Scan Watchlist** again after editing symbols.
- **Auto-rescan behavior**: Timer starts after the first manual scan; very short intervals can increase Yahoo throttling risk.
- **10x / fundamental sieve**: Data gaps yield “-”; not predictive of returns.
- **Diamond win rate / backtests**: Heuristic labels on one price path; holdout scoring is stricter than raw in-sample but still not out-of-sample validation.

Optional `hmmlearn` / `scipy` paths degrade gracefully if missing.

---

## Disclaimer

Educational software only: not financial advice. Confirm prices and suitability with your broker before trading.
