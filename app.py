"""
╔══════════════════════════════════════════════════════════════════════════╗
║  CASHFLOW COMMAND CENTER v22.0 FREE EDITION · PREDICTIVE ANALYTICS        ║
║  Modular architecture: same UI, same logic, clean separation.           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import os
import sys
import threading

# Streamlit Cloud and some runners leave cwd off sys.path; local imports need the app root.
_app_root = os.path.dirname(os.path.abspath(__file__))
if _app_root not in sys.path:
    sys.path.insert(0, _app_root)

import streamlit as st

st.set_page_config(
    page_title="CashFlow Command Center v22.0",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
/* Production chrome: hide default app menu (hamburger) and footer */
#MainMenu {
  visibility: hidden !important;
  height: 0 !important;
  max-height: 0 !important;
  position: fixed !important;
  top: -9999px !important;
}
footer,
[data-testid="stFooter"],
.stApp footer {
  visibility: hidden !important;
  display: none !important;
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
  pointer-events: none !important;
}
</style>
""",
    unsafe_allow_html=True,
)

import pandas as pd
from datetime import datetime
import warnings, time
warnings.filterwarnings("ignore")

# Process-level cold-boot guard for Streamlit Cloud health checks.
# First script run avoids all network-heavy sections, then flips warm state.
_GLOBAL_COLD_BOOT_PENDING = True

if "edge_log" not in st.session_state:
    st.session_state.edge_log = pd.DataFrame(columns=["Time", "Ticker", "Retail", "Quant", "Delta", "Preview"])
if "bt_thresh" not in st.session_state:
    st.session_state.bt_thresh = 70
if "bt_hold" not in st.session_state:
    st.session_state.bt_hold = 5
if "_cf_ledger" not in st.session_state:
    st.session_state["_cf_ledger"] = []

# ── Module imports: serialize + retry on KeyError (Streamlit watcher vs import race; see streamlit#6404)
_modules_import_lock = threading.Lock()
_IMPORT_KEYERROR_RETRIES = 5
for _import_try in range(_IMPORT_KEYERROR_RETRIES):
    try:
        with _modules_import_lock:
            from modules.config import (
                load_config, save_config, DEFAULT_CONFIG, CONFIG_PATH,
                ConfigTransaction,
                _hydrate_sidebar_prefs, _overlay_prefs_from_session,
                REF_NOTIONAL, RISK_PCT_EXAMPLE, KELLY_DISPLAY_CAP_PCT,
                EMA_EXTENSION_WARN_PCT,
            )
            from modules.utils import safe_html, log_warn
            from modules.desk_locals import build_desk_locals
            from modules.render_pre_tabs import (
                apply_auto_watchlist_to_cfg_tx,
                render_desk_after_context,
                render_mission_control_hud,
                render_tape_open_editor_flush,
                render_watchlist_editor_fragment,
            )
            from modules.renderers import (
                render_setup_tab,
                render_cashflow_tab,
                render_intel_tab,
                render_ledger_tab,
                render_radar_tab,
            )
            from modules.data import (
                retry_fetch, _yfinance_ticker,
                fetch_stock, fetch_intraday_series,
                fetch_info, fetch_options, list_option_expiration_dates,
                fetch_earnings_date, fetch_earnings_calendar_display,
                fetch_global_market_bundle,
                _ticker_daily_ohlcv_from_raw,
                _PLOTLY_UI_CONFIG, _PLOTLY_PAPER_BG, _PLOTLY_PLOT_BG,
                _PLOTLY_CASH_UP, _PLOTLY_CASH_DOWN, _PLOTLY_GRID, _PLOTLY_FONT_MAIN, _PLOTLY_BLUE, _PLOTLY_AXIS_TITLE,
            )
            from modules.options import (
                bs_price, bs_greeks, calc_ev, calc_vol_skew,
                quant_edge_score, weekly_trend_label, calc_gold_zone,
                calc_confluence_points, detect_diamonds, latest_diamond_status,
                diamond_win_rate, scan_single_ticker, Opt, calc_skew_regime, PortfolioRisk,
                build_chain_mc_dataframe,
            )
            from modules.sentiment import Sentiment, Backtest, Alerts, run_cc_sim_cached, QuantBacktest
            from modules.chart import build_chart, _chart_hoverlabel, build_skew_chart
            from modules.ui_helpers import (
                _fragment_technical_zone, _fragment_rolling_edge_capture, _df_price_levels,
                _earnings_calendar_column_config,
                _PRICE_LEVEL_COLUMN_CONFIG, _options_scan_dataframe,
                _options_scan_column_config,
                _persist_overlay_prefs,
                streamlit_df_widget_key,
                streamlit_show_dataframe,
                _theta_gamma_desk_line,
                SCANNER_WHALE_FLOW_BIAS_HELP,
            )

            from modules.css import _CSS, _MINI_MODE_DENSITY_CSS, inject_css_and_navbar
        break
    except KeyError:
        if _import_try >= _IMPORT_KEYERROR_RETRIES - 1:
            raise
        time.sleep(0.08 * (2**_import_try))

# Migrate legacy edge_log sessions (added Preview column for watchlist matrix).
_el = st.session_state.get("edge_log")
if isinstance(_el, pd.DataFrame) and not _el.empty and "Preview" not in _el.columns and "Quant" in _el.columns:
    try:
        from modules.options import quant_edge_status_line as _qesl

        _el2 = _el.copy()
        _el2["Preview"] = _el2["Quant"].apply(
            lambda q: _qesl(float(q)) if pd.notna(q) else "",
        )
        st.session_state.edge_log = _el2
    except Exception as e:
        log_warn("migrating edge_log Preview column", e)

# ── Inject theme + navbar (must happen before any widgets) ──
inject_css_and_navbar()

def main():
    global _GLOBAL_COLD_BOOT_PENDING
    cfg_tx = ConfigTransaction()
    cfg = cfg_tx.current

    if "_sb_scanner_sync" in st.session_state:
        st.session_state["sb_scanner"] = st.session_state.pop("_sb_scanner_sync")
    elif "sb_scanner" not in st.session_state:
        st.session_state["sb_scanner"] = cfg.get("watchlist", DEFAULT_CONFIG["watchlist"])

    # Hydrate HUD + chart overlay keys from config **before** any widget reads them (fixes first-load defaults).
    _hydrate_sidebar_prefs(cfg)

    saved_scanner_mode = cfg.get("scanner_mode", "📈 Options Yield")

    if not st.session_state.get("_cf_pwa_toast_shown"):
        try:
            _hdrs = st.context.headers
            _h = _hdrs.to_dict() if _hdrs is not None else {}
            _ua = str({str(k).lower(): v for k, v in _h.items()}.get("user-agent") or "").lower()
            if any(tok in _ua for tok in ("iphone", "ipad", "ipod", "android", "mobile")):
                st.toast("Tip: install CashFlow from your browser menu (Add to Home Screen).", icon="📲")
        except Exception as e:
            log_warn("pwa install toast hint", e)
        st.session_state["_cf_pwa_toast_shown"] = True

    st.caption("Predictive Pinning, Bayesian News Nuance, & Shadow Liquidity Architecture.")
    render_watchlist_editor_fragment(cfg_tx)
    apply_auto_watchlist_to_cfg_tx(cfg_tx)
    cfg = cfg_tx.current

    hud = render_mission_control_hud(cfg_tx, cfg, saved_scanner_mode)

    if _GLOBAL_COLD_BOOT_PENDING:
        _GLOBAL_COLD_BOOT_PENDING = False
        st.info(
            "Cold boot warm-up complete. Reload once to enter full dashboard mode."
        )
        st.stop()

    cfg, _global_snap = render_tape_open_editor_flush(cfg_tx, hud)

    mini_mode = bool(st.session_state.get("sb_mini_mode", False))
    if mini_mode:
        st.markdown(_MINI_MODE_DENSITY_CSS, unsafe_allow_html=True)

    from modules.pages import build_context
    _defer_meta = bool(cfg.get("defer_headlines_earnings", False))
    _defer_options_first_pass = bool(cfg.get("defer_options_first_pass", DEFAULT_CONFIG["defer_options_first_pass"]))
    _defer_options_fetch = _defer_options_first_pass and not bool(st.session_state.get("_cf_first_pass_done", False))
    ctx = build_context(
        hud.ticker,
        cfg,
        global_snapshot=_global_snap,
        defer_headlines_earnings=_defer_meta,
        defer_options_fetch=_defer_options_fetch,
    )
    st.session_state["_cf_first_pass_done"] = True
    if ctx is None:
        _sym_e = safe_html(hud.ticker)
        st.error(
            f"**Price data unavailable** for `{_sym_e}`. "
            "Yahoo Finance often **rate-limits** shared servers (Streamlit Community Cloud shares IPs), "
            "so liquid names like this can still fail—it is usually throttling, not a bad symbol.\n\n"
            "**Try:** another ticker from the watchlist tape; **⋯ → Reboot app** in Streamlit Cloud for a fresh IP; "
            "or clear the cached fetch below and retry (otherwise a miss can stay cached up to **5 minutes**)."
        )
        if st.button("Clear price cache & retry", key="cf_clear_price_cache_retry", use_container_width=True):
            try:
                fetch_stock.clear()
            except Exception as e:
                log_warn("clearing fetch_stock cache", e, ticker=str(hud.ticker))
            try:
                fetch_global_market_bundle.clear()
            except Exception as e:
                log_warn("clearing fetch_global_market_bundle cache", e, ticker=str(hud.ticker))
            st.rerun()
        st.stop()

    _, _, _risk_closes_df, _simple_corr_mult, _cm_cached = render_desk_after_context(
        ctx, cfg, hud, _global_snap, EMA_EXTENSION_WARN_PCT
    )

    desk = build_desk_locals(
        ctx,
        cfg,
        hud,
        defer_meta=_defer_meta,
        global_snap=_global_snap,
        risk_closes_df=_risk_closes_df,
        simple_corr_mult=_simple_corr_mult,
        cm_cached=_cm_cached,
    )

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1: TECHNICAL CHART (fragment: overlay toggles without refetching Yahoo)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="charts" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    st.session_state["_cf_use_quant_models"] = bool(
        cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"])
    )
    st.session_state["_cf_vix_snapshot"] = float(ctx.vix_v or 0.0)
    try:
        _iv_ch = float(ctx.ref_iv_bluf or 0)
        for _cx in (ctx.bluf_cc, ctx.bluf_csp):
            if _cx:
                try:
                    _vx = float(_cx.get("iv") or 0)
                    if _vx > _iv_ch:
                        _iv_ch = _vx
                except (TypeError, ValueError):
                    pass
        _dte_ch = int(ctx.bluf_dte) if ctx.bluf_dte else 0
        _exp_ch = None
        if ctx.bluf_exp:
            try:
                _exp_ch = datetime.strptime(str(ctx.bluf_exp)[:10], "%Y-%m-%d")
            except Exception as _e:
                log_warn("parsing bluf expiry for chart expected move", _e, ticker=str(ctx.ticker))
                _exp_ch = None
        if _dte_ch > 0 and _iv_ch > 0:
            st.session_state["_cf_chart_em"] = {"iv_pct": _iv_ch, "dte": _dte_ch, "expiry": _exp_ch}
        else:
            st.session_state["_cf_chart_em"] = {}
    except Exception as _e:
        log_warn("computing chart expected move state", _e, ticker=str(ctx.ticker))
        st.session_state["_cf_chart_em"] = {}
    _fragment_technical_zone(
        ctx.df,
        ctx.df_wk,
        ctx.ticker,
        ctx.gold_zone_price,
        ctx.gold_zone_components,
        ctx.price,
        ctx.diamonds,
        ctx.latest_d,
        ctx.cp_breakdown,
        ctx.d_wr,
        ctx.d_n,
        ctx.struct,
        ctx.mini_mode,
        ctx.mobile_chart_layout,
    )

    dash_tab_setup, dash_tab_cashflow, dash_tab_intel, dash_tab_ledger, dash_tab_radar = st.tabs(
        [
            "Setup & quant",
            "Cashflow & strikes",
            "Risk, scanner & intel",
            "📊 Sentinel Ledger",
            "🌎 Market Explosion Radar",
        ]
    )

    with dash_tab_setup:
        render_setup_tab(ctx.chart_mood, desk)
    with dash_tab_cashflow:
        render_cashflow_tab(cfg, desk)
    with dash_tab_intel:
        render_intel_tab(desk)
    with dash_tab_ledger:
        render_ledger_tab(desk)
    with dash_tab_radar:
        render_radar_tab(desk)


if __name__ == "__main__":
    main()
