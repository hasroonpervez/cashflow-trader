# CashFlow Command Center v14.1

Single-file Streamlit command desk for options income and technical context.

## What This Version Uses

- `app.py` as the primary app file (single-file architecture)
- `config.json` for watchlist and UI preferences
- `requirements.txt` for dependencies
- `yfinance` for market data (no API key required)

## Run Locally

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
streamlit run app.py
```

## Config Model (`config.json`)

This v14.1 build expects these keys:

- `watchlist`
- `scanner_sort_mode`
- `strat_focus`
- `strat_horizon`
- `mini_mode`
- `overlay_ema`
- `overlay_fib`
- `overlay_gann`
- `overlay_sr`
- `overlay_ichi`
- `overlay_super`
- `overlay_diamonds`
- `overlay_gold`

Legacy portfolio keys are ignored and removed by the app on load.

## Notes

- If Yahoo throttles/blocks a symbol, data may be temporarily unavailable.
- Streamlit Cloud can be more rate-limited than local runs.
- This tool is for educational use, not financial advice.
