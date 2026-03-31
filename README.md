# CashFlow Command Center v14.1

**Single-screen options income desk for PLTR and multi-ticker watchlists.**

Glanceable execution guidance, Diamond buy/sell signals, Gold Zone confluence, Black-Scholes Greeks, and a full technical chart stack — all in a Streamlit dashboard built for mobile-first traders who sell covered calls and cash-secured puts for weekly income.

---

## What This Does

The dashboard answers one question: **"What should I do right now?"**

- **BLUF Action Card** — plain-English trade recommendation with a specific strike, expiry, and broker checklist
- **Traffic Light Indicators** — green/amber/red across Quant Edge Score, Confluence, Market Structure
- **Diamond Signals** — Blue (buy zone) and Pink (take profit) triggered by 7+/9 confluence crossover
- **Gold Zone** — dynamic institutional anchor fusing Volume Profile POC, Fib 61.8%, 200-SMA, Gann Sq9
- **De-correlated Quant Edge Score** — five orthogonal dimensions (Trend, Momentum, Volume, Volatility, Structure)
- **Black-Scholes Greeks** — live 10Y yield as risk-free rate, Expected Value, Kelly sizing, Volatility Skew
- **Multi-Ticker Scanner** — ranks your full watchlist by confluence and diamond status
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
    ├── data.py               # yfinance fetchers, retry/backoff, caching, macro
    ├── ta.py                 # TA class — 25+ indicators (RSI, MACD, Ichimoku, etc.)
    ├── options.py            # Black-Scholes, Greeks, EV, Kelly, Quant Edge, Diamonds
    ├── sentiment.py          # Sentiment, Backtest simulator, Alerts scanner
    ├── chart.py              # Four-panel Plotly chart builder
    ├── ui_helpers.py         # Sparklines, glance cards, sections, DataFrame styling
    └── css.py                # Full CSS theme + Mini Mode + sidebar toggle JS
```

**Why this split works with Streamlit:**

- `st.set_page_config()` is the first Streamlit call in `app.py` (required)
- CSS/navbar injection happens immediately after via `inject_css_and_navbar()`
- Modules never call `st.*` at import time — only when their functions are invoked
- `@st.cache_data` decorators work correctly because `streamlit` is imported in each module

---

## Run Locally

```bash
python3 -m venv venv
source venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Cloud

1. Push to GitHub
2. Connect at [share.streamlit.io](https://share.streamlit.io)
3. Set `app.py` as the main file
4. (Optional) Add secrets in Streamlit Cloud dashboard under Settings → Secrets

---

## Config (`config.json`)

Persisted locally via atomic writes (`.tmp` → `os.replace`). On Streamlit Cloud the filesystem resets on deploy, so preferences are ephemeral unless backed by `st.secrets`.

Keys: `watchlist`, `scanner_sort_mode`, `strat_focus`, `strat_horizon`, `mini_mode`, `overlay_ema`, `overlay_fib`, `overlay_gann`, `overlay_sr`, `overlay_ichi`, `overlay_super`, `overlay_diamonds`, `overlay_gold`.

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
| Volume | OBV, Volume Profile, VWAP |
| Volatility | Bollinger Bands, ATR (14), Hurst Exponent |
| Structure | Market Structure (BOS/CHOCH), Support/Resistance, Fair Value Gaps |
| Gann | Square of 9 levels, Angles, Time Cycles |
| Fibonacci | Retracement levels (0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%) |

---

## Known Limitations

- Yahoo Finance may throttle or block symbols on Streamlit Cloud (more liberal locally)
- Config persistence is local-only; Cloud deploys reset the filesystem
- Streamlit Cloud cold starts and rapid reruns can surface transient `missing ScriptRunContext` warnings in logs; these are typically non-fatal
- Micro-cap tickers (e.g. BMNR) may lack options chains; the desk falls back gracefully

---

## Disclaimer

This tool is for **educational use only** and does not constitute financial advice. Past performance in the Premium Simulator does not predict future results. Always confirm quotes in your broker before placing orders.
