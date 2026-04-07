# CashFlow Command Center · v22.2 (Free Edition)

**Predictive analytics options desk** — one screen for watchlist context, consensus, chains, scanner, and a Sentinel ledger. Built with **Streamlit**; data from **Yahoo Finance** (optional **Alpha Vantage** fallback and fundamentals).

---

## At a glance

- **Options Yield** — Full income workflow: BLUF trade line, GEX / gamma flip, Monte Carlo PoP, spreads, Greeks, multi-ticker scanner.
- **Equity Radar** — Stock-focused scan: pre-diamond signals, actionable targets, Delta-One setup (same scan payload; options chrome hidden until you switch back).
- **Sentinel Ledger** — Track legs; pin distance, edge realization, portfolio delta/theta/vega + 1d VaR, and “golden zone” style maturity hints.
- **10x scanner + conviction** — `10x Potential` score, score>=5 screener, and `💎 CONVICTION` when Blue Diamond aligns with 10x.
- **Intraday confirmation gate** — IMMINENT pre-diamond calls are now checked against 1h RSI + OBV before final upgrade.
- **Auto scanner refresh** — Scanner can auto-rerun on a timer (`auto_scan_interval`, default 300s) after first manual scan.
- **Watchlist earnings heat map** — Intel tab shows 30-day earnings urgency buckets (`this_week`, `next_week`, `this_month`, `clear`, `reported`, `unknown`).
- **Persistent trade journal** — `trade_journal.json` survives browser restarts with close workflow and realized P&L stats.
- **Walk-forward replay backtest** — Setup tab can replay point-in-time Blue Diamond-style triggers and report forward returns.
- **Discord conviction alerts** — Optional webhook notifications for `💎 CONVICTION` scanner events.
- **PWA install metadata** — Manifest + mobile meta tags for add-to-home-screen behavior.
- **In-app glossary** — **Intel → Quick Reference Guide**.

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

Coverage includes utils (`safe_last`, `safe_float`, `safe_html`, `log_warn`), `ConfigTransaction`, correlation / RS vs SPY, signal desk, BS Greeks (vanna/charm), quant edge (retail + blended institutional path), allocation, watchlist helpers, and smoke imports (no live Yahoo in most tests).

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

Community Cloud **shares IPs** with other apps. Yahoo often **throttles** or slow-responds — *“possibly delisted”* in logs is frequently a **rate-limit lie**, not a bad symbol.

**Try this order**

1. **⋯ → Reboot app** (new container / often new IP).
2. Use **Clear price cache & retry** if you see “Price data unavailable” (browser refresh alone may not bust `fetch_stock`’s cache).
3. **Shorten the watchlist** for 24/7 hosting; avoid hammering **Scan Watchlist**.
4. Add **`ALPHAVANTAGE_API_KEY`** if Yahoo stays empty after retries.

**`503 GET /script-health-check`** — the first script run took too long. This repo batches a **single** `yf.download` for the desk (`fetch_global_market_bundle`), evaluates **one** fundamental sieve for the **active** ticker in that bundle (scanner still evaluates per symbol when you run it), and clamps HTTP timeouts. Combine with **`defer_headlines_earnings`** if probes still time out.

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
| `discord_webhook_url` | Optional Discord webhook endpoint for conviction alerts |
| `alert_on_conviction` | Toggles webhook dispatch for `💎 CONVICTION` hits |
| `defer_headlines_earnings` | Skip upfront news + earnings in `build_context` |
| `defer_options_first_pass` | Skip options-chain hydration on the first session render (faster Cloud cold boot) |
| `overlay_*` | Chart layers (EMA, Fib, Gann, etc.) |

On Cloud, if the filesystem is **read-only**, use Secrets `watchlist` and expect toasts when disk writes fail — session state still updates.

---

## What the app does

- **Consensus** — Score, trader’s note, bento (setup / momentum / exit), optional heatmap ribbon, unified probability dial, position-size expander (illustrative).
- **Recommended trade** — BLUF line with strikes, EM safety, Θ/Γ, MC PoP, walk-up limit hint.
- **Technical chart** — Overlays, whale volume markers, **shadow move** band, **OpEx pin**, gamma flip, expected-move rails.
- **Gold Zone & confluence** — Blended anchors; **Diamond** blue/pink signals; **pre-diamond** coil hint on scanner (Equity path).
- **Scanner** — Watchlist ranking, GEX regime, flow/bias, optional allocator; results cached in `_cf_scanner_bundle` until the next scan.
- **Rolling Edge log** — Parallel quant vs retail edge across symbols; fragment refresh.
- **Math** — Black–Scholes (+ vanna/charm), Corrado–Su, Kelly-style helpers, FFD-based correlation, HMM path when deps exist; quant edge **blends** pillars + regime track (see below).

---

## Repository layout

```
cashflow-trader/
├── app.py                 # Entry: imports, CSS/nav, main() orchestration
├── config.json            # Defaults for watchlist & UI (optional on Cloud)
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

## v22.2 — headline features

| Area | What shipped |
|------|----------------|
| Pinning | `predict_opex_pin` — gamma wall blended with Θ/Γ; ledger pin distance / maturity |
| Liquidity vs IV | `get_shadow_move` — whale-volume close band vs expected move; shadow **breakout** flag when price leaves band but stays inside EM |
| News | `analyze_news_bias` — forward-looking phrases weighted vs backward “beat/miss” |
| Desk | Absorption + VWAP-distance Z, RS vs SPY (~90 sessions) from bundle, heatmap ribbon (COIL / ICEBERG / SWEEP / LEADER), Hurst-tilted flow |
| Risk | Portfolio ρ warning; allocator sector + top-3 correlation guards with Sentinel |
| Equity mode | Radar summary, actionable targets, Delta-One tabs; shared scanner cache |
| Options | Vanna & charm on BS row; IV rank proxy; skew chart |
| Scanner upgrades | `score_10x_potential` integrated into scanner rows (`10x Potential`, flags), Intel **10x Screener**, and Blue+10x **CONVICTION** banner |
| Intraday gate | Pre-diamond `🔥 IMMINENT BREAKOUT` is conditionally downgraded when 1h RSI is overbought or OBV is declining |
| Auto-monitoring | Intel scanner supports timer-driven reruns via `auto_scan_interval`; cache bundle stores last trigger/time |
| Sentinel risk | Portfolio aggregates now include **total vega** and a simple **1-day 95% VaR** (delta-correlation approximation) |
| Intel earnings | Watchlist earnings heat map expander with urgency buckets and risk callouts for this week / next week |
| Journal persistence | Track Trade now mirrors to disk (`trade_journal.json`), with close-trade workflow + realized P&L and win-rate stats |
| Walk-forward replay | Setup tab includes a point-in-time Blue Diamond replay with configurable lookback/hold/confluence |
| Alerting | Discord webhook utility + Intel alert settings for async conviction notifications |
| Mobile install | Manifest + theme metadata injection for home-screen install behavior |
| Hardening sweep | Removed remaining bare `except Exception:` and unguarded `.iloc[-1]` tail indexing across core modules |

**Pinning (intuition)** — Dealers hedge gamma; near expiry, GEX can concentrate at strikes (“walls”). Θ/Γ informs how strongly the model weights the wall in `predict_opex_pin`. Heuristic only, not a settlement forecast.

---

## Version lineage (short)

| Era | Focus |
|-----|--------|
| v14–v16 | Scanner, quant edge, MC PoP, Gold Zone, Kelly + correlation haircut |
| v17–v18 | Expected move, GEX, gamma flip on chart and scanner |
| v19 | Volume Z “whale” proxy, NLP bias on desk + scanner |
| v20 | Portfolio heatmap, cluster penalty, Sentinel ledger |
| v21 | FFD correlation, adaptive whale window, HVN-weighted GEX |
| v22 | OpEx pin, shadow band, Bayesian-ish news, Equity Radar, ledger alpha columns |

---

## 10x “convexity” sieve (strict filter)

Implemented in `scan_single_ticker` / `evaluate_asymmetric_convexity_sieve`. **All** gates must pass — most days should show **no** hits; that is intentional noise control.

| # | Idea | Rule of thumb |
|---|------|----------------|
| 1 | Small float | Under ~30M shares |
| 2 | Vol compression | BBW in bottom ~5% of a year lookback |
| 3 | Volume spike | Volume Z above 4 vs ~90d stats |
| 4 | Skew + squeeze story | High short interest; call IV above put IV (~10% OTM) |

Live code builds BBW from Bollinger on closes; skew from `calc_vol_skew`; float/short from `fetch_info`. **Pre-diamond** logic uses a different squeeze definition. Yahoo `info` is often incomplete — treat hits as hypotheses, not promises.

---

## Indicators & models (reference)

**Indicators** — Trend: EMA, Ichimoku, Supertrend. Momentum: RSI, MACD, stoch, CCI. Volume: OBV, profile, HVN, adaptive volume Z. Vol: Bollinger, ATR, Hurst, expected move. Structure: BOS/CHOCH, S/R, FVG. Gann / Fib as overlays.

**Models** — Corrado–Su; Monte Carlo PoP (seed 42); Kelly-style sizing; FFD for correlation; optional HMM; fundamental sieve (FCF/EV + efficiency YoY via Yahoo + Alpha Vantage when configured).

**Methodology (recent hardening)**

- **Quant Edge (`use_quant_models`)** — Five pillars (trend, momentum, volume, volatility, structure) form a **retail core**. The institutional track (FFD residual + HMM regime probability) is **blended** into that core (default 62% / 38%) instead of replacing it, then MC PoP fusion applies. This reduces wild score jumps when the HMM path errors and falls back to retail.
- **Gold Zone** — Component prices are a **weighted** mean (POC and HVN highest, then SMA200, Fib, gamma flip, Gann) rather than equal weighting.
- **Scanner Kelly** — Continuous Kelly still uses expected return / variance when variance is positive. The discrete fallback now uses **MC PoP** as win probability and **BS short-put credit vs assignment-gap** style win/loss amounts instead of a flat 55% and daily `chg_pct`.
- **Diamond win rate** — Prefers a **holdout window** (signals only from the first ~75% of bars, forward outcomes on the full series) when history is long enough and the holdout set has enough diamonds; falls back to all signals otherwise. Still not a full walk-forward backtest.
- **CC backtest (`Backtest.cc_sim`)** — Covered-call premium per entry bar uses **`bs_price`** (same BS engine as the desk), not the old hand-tuned premium formula.

---

## Known limitations

- **Yahoo** is best-effort; shared Cloud IPs worsen throttling. App returns empty/`None` instead of crashing where possible.
- **Cloud filesystem** may be read-only — use Secrets for `watchlist`.
- **Persistent journal on read-only hosts** — `trade_journal.json` writes can fail (UI shows a write error toast; session ledger still works).
- **Options** — Thin names may lack OI or chains; GEX/flip may be blank.
- **Scanner bundle** — Stale until you **Scan Watchlist** again after editing symbols.
- **Auto-rescan behavior** — Timer starts after the first manual scan; very short intervals can increase Yahoo throttling risk.
- **10x / fundamental sieve** — Data gaps yield “—”; not predictive of returns.
- **Diamond win rate / backtests** — Heuristic labels on one price path; holdout scoring is stricter than raw in-sample but still not out-of-sample validation.

Optional `hmmlearn` / `scipy` paths degrade gracefully if missing.

---

## Disclaimer

Educational software only — not financial advice. Confirm prices and suitability with your broker before trading.
