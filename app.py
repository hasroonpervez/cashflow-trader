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

import html as _html_mod
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import math, warnings, json, time, re
import textwrap
from pathlib import Path
warnings.filterwarnings("ignore")

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
                _hydrate_sidebar_prefs, _overlay_prefs_from_session,
                REF_NOTIONAL, RISK_PCT_EXAMPLE, KELLY_DISPLAY_CAP_PCT,
                EMA_EXTENSION_WARN_PCT,
            )
            from modules.data import (
                retry_fetch, _yfinance_ticker, _client_suggests_mobile_chart,
                fetch_stock, _ticker_pct_change_1d, fetch_intraday_series,
                fetch_info, fetch_options, list_option_expiration_dates, compute_iv_rank_proxy, fetch_news_headlines,
                fetch_earnings_date, fetch_earnings_calendar_display, fetch_macro,
                _PLOTLY_UI_CONFIG, _PLOTLY_PAPER_BG, _PLOTLY_PLOT_BG,
                _PLOTLY_CASH_UP, _PLOTLY_CASH_DOWN, _PLOTLY_GRID, _PLOTLY_FONT_MAIN, _PLOTLY_BLUE, _PLOTLY_AXIS_TITLE,
            )
            from modules.ta import TA
            from modules.options import (
                bs_price, bs_greeks, calc_ev, kelly_criterion, calc_vol_skew,
                quant_edge_score, weekly_trend_label, calc_gold_zone,
                calc_confluence_points, detect_diamonds, latest_diamond_status,
                diamond_win_rate, scan_single_ticker, Opt, calc_skew_regime, PortfolioRisk,
                build_chain_mc_dataframe,
                watchlist_correlation_matrix_cached,
            )
            from modules.sentiment import Sentiment, Backtest, Alerts, run_cc_sim_cached, QuantBacktest
            from modules.chart import build_chart, _chart_hoverlabel, build_skew_chart, build_correlation_heatmap
            from modules.ui_helpers import (
                _factor_checklist_labels, _confluence_why_trade_plain,
                _iv_rank_qualitative_words, _iv_rank_pill_html,
                render_mode_badge,
                sentinel_ledger_metrics,
                sentinel_ledger_table_rows,
                ledger_theta_desk_day,
                earnings_runway_spark_series,
                _explain, _section, _mini_sparkline, _glance_sparkline_svg,
                _glance_metric_card, _render_html_block, _parse_watchlist_string,
                walk_up_limit_sell_per_share,
                _fragment_technical_zone, _fragment_rolling_edge_capture, _df_price_levels,
                expected_move_safety_html,
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

def _render_equity_setup_desk(scanner_results, selectbox_key: str, prefer_ticker=None) -> None:
    """Delta-One equity drill-down from cached scanner rows (no extra data fetches)."""
    if not scanner_results:
        st.warning("Run **Scan Watchlist** in **Risk, scanner & intel** (Equity Radar), then pick a symbol below.")
        return
    tickers = [r["ticker"] for r in scanner_results]
    pick = prefer_ticker if prefer_ticker in tickers else tickers[0]
    if selectbox_key not in st.session_state or st.session_state.get(selectbox_key) not in tickers:
        st.session_state[selectbox_key] = pick
    selected_ticker = st.selectbox(
        "Equity desk — focus ticker",
        tickers,
        key=selectbox_key,
        help="Drill into breakout, risk, and support using the last scan payload.",
    )
    ticker_data = next((item for item in scanner_results if item["ticker"] == selected_ticker), None)
    if not ticker_data:
        st.warning("Select a ticker from the Equity Radar scanner above to view the setup.")
        return
    pre_diamond = ticker_data.get("pre_diamond_status") or {}
    signal = pre_diamond.get("signal_strength", "—")
    stop_loss = ticker_data.get("stock_stop_price", "—")
    price = float(ticker_data.get("price") or 0)
    qs_raw = ticker_data.get("qs", "—")
    cp_score = ticker_data.get("cp_score", "—")
    cp_max = ticker_data.get("cp_max", "—")
    confluence_disp = f"{cp_score}/{cp_max}" if isinstance(cp_score, (int, float)) and isinstance(cp_max, (int, float)) else "—"
    st.markdown(f"## 🎯 Equity Setup: {_html_mod.escape(str(selected_ticker))}")
    st.info(f"**Current Signal:** {signal}")
    eq_tab1, eq_tab2 = st.tabs(["🚀 Breakout Metrics", "🛡️ Risk & Support"])
    with eq_tab1:
        st.markdown("### Accumulation Engine")
        st.caption("Pre-diamond logic already folds in a **volume ramp** vs its short baseline; 🔥 / 🟡 rows are the live accumulation pulse.")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "Volatility State",
                pre_diamond.get("volatility_state", "NORMAL"),
                help="SQUEEZED means bottom 25% of 60-day ATR (or BBW) range when pre-diamond fired.",
            )
        with col2:
            st.metric(
                "Confluence Score",
                confluence_disp,
                help="Pre-diamond targets the 5–6 band; 7+ is Blue Diamond territory on the options path.",
            )
        with col3:
            st.metric(
                "Relative Strength",
                "Strong vs SPY" if "🔥" in str(signal) else "Neutral/Weak",
                help="3-day return vs SPY when the pre-diamond stack triggered.",
            )
        qe_disp = f"{float(qs_raw):.0f}/100" if isinstance(qs_raw, (int, float)) else str(qs_raw)
        st.metric("Quant Edge (QE)", qe_disp, help="Same QE score as the scanner row.")
    with eq_tab2:
        st.markdown("### Trade Management")
        r_col1, r_col2, r_col3 = st.columns(3)
        with r_col1:
            st.metric(
                "Suggested Entry",
                f"${price:,.2f}" if price else "—",
                help="Spot from the scan bar.",
            )
        with r_col2:
            sl_txt = f"${float(stop_loss):,.2f}" if isinstance(stop_loss, (int, float)) else stop_loss
            st.metric(
                "ATR Trailing Stop",
                sl_txt,
                help="Scan uses price − 1.5× ATR when ATR is available; else a 5% floor.",
            )
        sup = pre_diamond.get("support_proximity", "—")
        sup_txt = f"{float(sup):.1f}%" if isinstance(sup, (int, float)) else sup
        if sup_txt != "—" and not str(sup_txt).endswith("%"):
            sup_txt = f"{sup_txt}%"
        with r_col3:
            st.metric(
                "Distance to Support",
                sup_txt,
                help="Proximity to Shadow Low or Gold Zone floor when pre-diamond is active.",
            )
        gz = ticker_data.get("gold_zone")
        rr_txt = "—"
        try:
            if (
                isinstance(stop_loss, (int, float))
                and float(stop_loss) > 0
                and price > 0
                and gz is not None
                and float(gz) > 0
            ):
                risk_px = max(price - float(stop_loss), 1e-9)
                reward_px = max(float(gz) - price, 0.0)
                rr_txt = f"{reward_px / risk_px:.2f} : 1" if risk_px else "—"
        except (TypeError, ValueError):
            rr_txt = "—"
        st.metric(
            "Risk / Reward (to Gold Zone)",
            rr_txt,
            help="(Gold Zone − spot) ÷ (spot − stop) per share when all inputs exist; illustrative target only.",
        )


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
    except Exception:
        pass

# ── Inject theme + navbar (must happen before any widgets) ──
inject_css_and_navbar()

def main():
    cfg = load_config()

    if "_sb_scanner_sync" in st.session_state:
        st.session_state["sb_scanner"] = st.session_state.pop("_sb_scanner_sync")
    elif "sb_scanner" not in st.session_state:
        st.session_state["sb_scanner"] = cfg.get("watchlist", DEFAULT_CONFIG["watchlist"])

    # Hydrate HUD + chart overlay keys from config **before** any widget reads them (fixes first-load defaults).
    _hydrate_sidebar_prefs(cfg)

    saved_scanner_mode = cfg.get("scanner_mode", "📈 Options Yield")

    # ── Watchlist editor (must run before Mission Control so sb_scanner is committed same run)
    _wl_expanded = bool(st.session_state.pop("_open_watchlist_editor", False))
    st.caption("Predictive Pinning, Bayesian News Nuance, & Shadow Liquidity Architecture.")
    def _persist_watchlist_text_callback():
        raw = st.session_state.get("sb_scanner", "")
        w = _parse_watchlist_string(raw)
        if not w:
            return
        csv = ",".join(w)
        b = load_config()
        if csv == (b.get("watchlist") or ""):
            return
        save_config(
            {
                **b,
                "watchlist": csv,
                "scanner_sort_mode": b.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"]),
            }
        )

    with st.expander("Edit watchlist symbols", expanded=_wl_expanded):
        st.caption(
            "Drop in tickers separated by commas or line breaks. Shuffle the lineup with the controls. "
            "Your list is saved to **config.json** automatically when it changes (survives closing the browser). "
            "On Streamlit Cloud, if saving fails, add a `watchlist` key in **App settings** under **Secrets**."
        )
        scanner_watchlist_raw = st.text_area(
            "Watchlist symbols",
            height=150,
            help="Paste from a spreadsheet, type commas, or put one ticker per line.",
            key="sb_scanner",
            on_change=_persist_watchlist_text_callback,
            label_visibility="collapsed",
        )
        watch_items_sb = _parse_watchlist_string(scanner_watchlist_raw)
        scanner_watchlist_sb = ",".join(watch_items_sb)

        if watch_items_sb:
            if "_sb_watch_selected_sync" in st.session_state:
                st.session_state["sb_watch_selected"] = st.session_state.pop("_sb_watch_selected_sync")
            if st.session_state.get("sb_watch_selected") not in watch_items_sb:
                st.session_state["sb_watch_selected"] = watch_items_sb[0]
            sel = st.session_state.get("sb_watch_selected")
            st.markdown(
                "<div style='font-size:.68rem;color:#94a3b8;margin:0 0 6px 0'>"
                + " · ".join(f"<span class='mono' style='color:#cbd5e1'>{_html_mod.escape(x)}</span>" for x in watch_items_sb)
                + "</div>",
                unsafe_allow_html=True,
            )
            up_clicked = st.button("Move up", use_container_width=True, key="sb_move_up")
            down_clicked = st.button("Move down", use_container_width=True, key="sb_move_down")
            remove_clicked = st.button("Remove symbol", use_container_width=True, key="sb_remove_ticker")
            sort_az = st.button("Sort A to Z", use_container_width=True, key="sb_sort_az")

            if up_clicked and sel in watch_items_sb:
                idx = watch_items_sb.index(sel)
                if idx > 0:
                    watch_items_sb[idx - 1], watch_items_sb[idx] = watch_items_sb[idx], watch_items_sb[idx - 1]
                    scanner_watchlist_sb = ",".join(watch_items_sb)
                    st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                    st.session_state["_sb_watch_selected_sync"] = sel
                    cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                    save_config(cfg)
                    st.rerun()
            if down_clicked and sel in watch_items_sb:
                idx = watch_items_sb.index(sel)
                if idx < len(watch_items_sb) - 1:
                    watch_items_sb[idx + 1], watch_items_sb[idx] = watch_items_sb[idx], watch_items_sb[idx + 1]
                    scanner_watchlist_sb = ",".join(watch_items_sb)
                    st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                    st.session_state["_sb_watch_selected_sync"] = sel
                    cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                    save_config(cfg)
                    st.rerun()
            if remove_clicked and sel in watch_items_sb:
                watch_items_sb = [t for t in watch_items_sb if t != sel]
                scanner_watchlist_sb = ",".join(watch_items_sb)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                if watch_items_sb:
                    st.session_state["_sb_watch_selected_sync"] = watch_items_sb[0]
                cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                save_config(cfg)
                st.rerun()
            if sort_az and watch_items_sb:
                watch_items_sb = sorted(watch_items_sb)
                scanner_watchlist_sb = ",".join(watch_items_sb)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                sel2 = st.session_state.get("sb_watch_selected")
                if sel2 not in watch_items_sb:
                    st.session_state["_sb_watch_selected_sync"] = watch_items_sb[0]
                cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                save_config(cfg)
                st.rerun()
        else:
            st.session_state.pop("sb_watch_selected", None)
            st.info("Add at least one symbol (e.g. PLTR, NVDA).")

        st.markdown(
            "<div style='font-size:.72rem;color:#94a3b8;margin:10px 0 2px 0;font-weight:600'>Quick add</div>",
            unsafe_allow_html=True,
        )
        if "_sb_add_ticker_clear" in st.session_state:
            st.session_state["sb_add_ticker"] = ""
            st.session_state.pop("_sb_add_ticker_clear", None)
        add_ticker_raw = st.text_input(
            "Symbol",
            placeholder="Try AMD, then tap Add symbol",
            key="sb_add_ticker",
            label_visibility="collapsed",
        )
        add_clicked = st.button("Add symbol", use_container_width=True, key="sb_add_watch")
        add_ticker = (add_ticker_raw or "").strip().upper()
        if add_clicked:
            if add_ticker:
                if add_ticker not in watch_items_sb:
                    watch_items_sb.append(add_ticker)
                scanner_watchlist_sb = ",".join(watch_items_sb)
                st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                st.session_state["_sb_watch_selected_sync"] = add_ticker
                st.session_state["_sb_add_ticker_clear"] = True
                cfg = {**cfg, "watchlist": scanner_watchlist_sb, "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"])}
                save_config(cfg)
                st.rerun()
            else:
                st.toast("Enter a ticker in the box above, then tap Add symbol.")

        if st.button("Save and refresh", use_container_width=True, key="sb_save_refresh_main"):
            w = _parse_watchlist_string(st.session_state.get("sb_scanner", ""))
            if not w:
                st.warning("Add at least one ticker before saving.")
            else:
                _bc = load_config()
                if save_config({**_bc, "watchlist": ",".join(w)}):
                    st.rerun()
                else:
                    st.error(
                        "Could not write **config.json** (read-only filesystem). "
                        "Paste this list into Streamlit **Secrets** as `watchlist = \"...\"` for durable Cloud storage."
                    )

    # Persist watchlist whenever session text differs from disk (survives new browser tabs on the same deployment).
    _auto_wl = _parse_watchlist_string(st.session_state.get("sb_scanner", ""))
    if _auto_wl:
        _auto_csv = ",".join(_auto_wl)
        _disk_cfg = load_config()
        if _auto_csv != (_disk_cfg.get("watchlist") or ""):
            _merged = {
                **_disk_cfg,
                "watchlist": _auto_csv,
                "scanner_sort_mode": _disk_cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"]),
            }
            if save_config(_merged):
                cfg = load_config()
            elif not st.session_state.get("_cf_watchlist_disk_warned"):
                st.session_state["_cf_watchlist_disk_warned"] = True
                st.toast(
                    "Watchlist not written to disk. Use Streamlit Secrets `watchlist` for Cloud, or run the app locally.",
                    icon="⚠️",
                )

    # GLOBAL COMMAND BAR (HUD: first paint in main column, directly under sticky nav)
    scanner_watchlist_raw = st.session_state.get("sb_scanner", cfg.get("watchlist", ""))
    watch_items = _parse_watchlist_string(scanner_watchlist_raw)
    scanner_watchlist = ",".join(watch_items)

    # Must resolve sb_watch_selected before st.selectbox(..., key="sb_watch_selected") (Streamlit 1.33+)
    # forbids assigning session_state for a widget key after that widget is instantiated (e.g. tape buttons).
    if watch_items:
        if "_sb_watch_selected_sync" in st.session_state:
            st.session_state["sb_watch_selected"] = st.session_state.pop("_sb_watch_selected_sync")
        if st.session_state.get("sb_watch_selected") not in watch_items:
            st.session_state["sb_watch_selected"] = watch_items[0]
        ticker = st.session_state.get("sb_watch_selected", watch_items[0])
    else:
        st.session_state.pop("sb_watch_selected", None)
        ticker = "PLTR"

    with st.container(border=True):
        st.markdown(
            "<div style='font-size:.75rem;color:#cbd5e1;font-weight:800;letter-spacing:.12em;margin-bottom:8px;'>MISSION CONTROL</div>",
            unsafe_allow_html=True,
        )
        r1c1, r1c2, r1c3 = st.columns([1.5, 2, 1])
        with r1c1:
            st.markdown('<p class="cf-hud-label">Target ticker</p>', unsafe_allow_html=True)
            if watch_items:
                st.selectbox(
                    "Target Ticker",
                    watch_items,
                    key="sb_watch_selected",
                    help="Main chart, news, options, and scores use this ticker.",
                    label_visibility="collapsed",
                )
            else:
                st.markdown(
                    '<p class="cf-hud-label">No symbols yet</p><p style="color:#cbd5e1;font-size:0.85rem;margin:0">'
                    "Expand <strong>Edit watchlist symbols</strong> up top or use the shortcut under the tape.</p>",
                    unsafe_allow_html=True,
                )
        with r1c2:
            st.markdown('<p class="cf-hud-label">Strategy</p>', unsafe_allow_html=True)
            if hasattr(st, "segmented_control"):
                st.segmented_control(
                    "Strategy",
                    ["Sell premium", "Hybrid", "Growth"],
                    key="sb_strat_radio",
                    label_visibility="collapsed",
                )
            else:
                st.radio(
                    "Strategy",
                    ["Sell premium", "Hybrid", "Growth"],
                    horizontal=True,
                    key="sb_strat_radio",
                    label_visibility="collapsed",
                )
        with r1c3:
            st.markdown('<p class="cf-hud-label">Performance</p>', unsafe_allow_html=True)
            st.toggle(
                "Turbo mode",
                key="sb_mini_mode",
                help="Skips heavy Plotly charts; glance row, execution strip, quant, and scanner stay live. Toggle off for the full chart stack.",
            )
        r2c1, r2c2 = st.columns([1.2, 1.2])
        with r2c1:
            st.markdown('<p class="cf-hud-label">Option horizon</p>', unsafe_allow_html=True)
            if hasattr(st, "segmented_control"):
                st.segmented_control(
                    "Horizon",
                    ["Weekly", "30 DTE", "45 DTE"],
                    key="sb_horizon_radio",
                    label_visibility="collapsed",
                )
            else:
                st.radio(
                    "Horizon",
                    ["Weekly", "30 DTE", "45 DTE"],
                    horizontal=True,
                    key="sb_horizon_radio",
                    label_visibility="collapsed",
                )
        with r2c2:
            st.markdown('<p class="cf-hud-label">Scanner order</p>', unsafe_allow_html=True)
            _scan_seg = st.radio(
                "Scanner order",
                ["Custom order", "Confluence first"],
                horizontal=True,
                key="sb_scan_radio",
                help="Custom follows your lineup. Confluence ranks the strongest tape first.",
            )
            scanner_sort_mode = (
                "Custom watchlist order" if _scan_seg == "Custom order" else "Highest confluence first"
            )

        st.markdown("### 🎛️ Command Center")
        with st.container(border=True):
            if hasattr(st, "segmented_control"):
                if "sb_scanner_mode" not in st.session_state:
                    st.session_state["sb_scanner_mode"] = saved_scanner_mode
            else:
                if "sb_scanner_mode_radio" not in st.session_state:
                    st.session_state["sb_scanner_mode_radio"] = saved_scanner_mode

            col_mode, col_cap = st.columns([1, 1])
            with col_mode:
                if hasattr(st, "segmented_control"):
                    scanner_mode = st.segmented_control(
                        "Trading Hemisphere",
                        ["📈 Options Yield", "🎯 Equity Radar"],
                        key="sb_scanner_mode",
                        default=saved_scanner_mode,
                        help="Switch between premium harvesting (Options) and Delta-One breakout hunting (Equity).",
                    )
                else:
                    scanner_mode = st.radio(
                        "Trading Hemisphere",
                        ["📈 Options Yield", "🎯 Equity Radar"],
                        horizontal=True,
                        key="sb_scanner_mode_radio",
                        help="Switch between premium harvesting (Options) and Delta-One breakout hunting (Equity).",
                    )
            with col_cap:
                equity_capital = 10000
                if scanner_mode == "🎯 Equity Radar":
                    equity_capital = st.select_slider(
                        "Capital Base per Trade ($)",
                        options=[5000, 10000, 25000, 50000, 100000],
                        value=10000,
                        help="Scales Suggested Shares dynamically.",
                    )

            st.session_state["_cf_scanner_mode"] = scanner_mode
            if scanner_mode != saved_scanner_mode:
                b = load_config()
                save_config({**b, "scanner_mode": scanner_mode})

        def _persist_use_quant_models():
            b = load_config()
            q = bool(st.session_state.get("sb_use_quant", False))
            if not save_config({**b, "use_quant_models": q}) and not st.session_state.get("_cf_quant_disk_warned"):
                st.session_state["_cf_quant_disk_warned"] = True
                st.toast(
                    "Quant mode not written to disk (read-only host). It stays on for this session; "
                    "for Streamlit Cloud add `use_quant_models = true` in **Secrets**.",
                    icon="⚠️",
                )

        st.toggle(
            "🔬 Enable Quant/Institutional Models",
            key="sb_use_quant",
            help="Replaces standard Black-Scholes and RSI logic with Corrado-Su pricing, Fractional Differentiation, and HMM Regime Detection.",
            on_change=_persist_use_quant_models,
        )

    # Clickable ticker tape (chunk rows on wide lists so columns stay usable on mobile)
    if watch_items:
        st.markdown('<p class="cf-tape-title">Watchlist tape</p>', unsafe_allow_html=True)
        st.caption("Tap a symbol to promote it to the active ticker. Daily move is versus the prior session close (cached).")
        _TAPE_CHUNK = 8
        tape_i = 0
        for row_start in range(0, len(watch_items), _TAPE_CHUNK):
            row_tickers = watch_items[row_start : row_start + _TAPE_CHUNK]
            # Fixed column count per row avoids Streamlit setIn desync when watchlist length changes.
            tape_cols = st.columns(_TAPE_CHUNK)
            for j in range(_TAPE_CHUNK):
                with tape_cols[j]:
                    if j >= len(row_tickers):
                        st.empty()
                        continue
                    tkr = row_tickers[j]
                    pct = _ticker_pct_change_1d(tkr)
                    pct_str = f"{pct:+.2f}%" if pct is not None else "n/a"
                    c_pct = "#10b981" if (pct is not None and pct >= 0) else ("#ef4444" if pct is not None else "#64748b")
                    is_active = tkr == ticker
                    st.markdown(
                        f"<div class='cf-tape-cell'><span style='color:{c_pct};font-size:.62rem;font-weight:800'>{_html_mod.escape(pct_str)}</span></div>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        tkr,
                        key=f"cf_tape_{tape_i}",
                        use_container_width=True,
                        type="primary" if is_active else "secondary",
                    ):
                        st.session_state["_sb_watch_selected_sync"] = tkr
                        st.rerun()
                tape_i += 1

    b1, b2 = st.columns([1, 2])
    with b1:
        if st.button("Open watchlist editor", use_container_width=True, key="cf_open_watchlist_editor"):
            st.session_state["_open_watchlist_editor"] = True
            st.rerun()
    with b2:
        st.markdown(
            "<div style='color:#94a3b8;font-size:0.7rem;padding-top:10px'>Data: Yahoo Finance · Not advice</div>",
            unsafe_allow_html=True,
        )

    watch_cfg = {**cfg, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
    if watch_cfg != cfg:
        save_config(watch_cfg)
        cfg = watch_cfg

    prefs_cfg = {
        **cfg,
        "strat_focus": st.session_state.get("sb_strat_radio", DEFAULT_CONFIG["strat_focus"]),
        "strat_horizon": st.session_state.get("sb_horizon_radio", DEFAULT_CONFIG["strat_horizon"]),
        "mini_mode": bool(st.session_state.get("sb_mini_mode", cfg.get("mini_mode", False))),
        "use_quant_models": bool(
            st.session_state.get("sb_use_quant", cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))
        ),
    }
    if prefs_cfg != cfg:
        save_config(prefs_cfg)
        cfg = prefs_cfg

    mini_mode = bool(st.session_state.get("sb_mini_mode", False))
    mobile_chart_layout = _client_suggests_mobile_chart()
    if mini_mode:
        st.markdown(_MINI_MODE_DENSITY_CSS, unsafe_allow_html=True)

    # ── BUILD CONTEXT (all fetches + computations in one shot) ──
    from modules.pages import build_context
    ctx = build_context(ticker, cfg)
    if ctx is None:
        st.error(
            f"Data feed unavailable for {ticker}. Yahoo Finance may be throttling or the tape may be quiet. "
            "We will try again the moment you refresh."
        )
        st.stop()

    # Unpack context into locals; rendering code below uses these directly.
    # This keeps the entire rendering layer untouched from the original monolith.
    df = ctx.df; df_wk = ctx.df_wk; df_1mo_spark = ctx.df_1mo_spark
    vix_1mo_df = ctx.vix_1mo_df; macro = ctx.macro; news = ctx.news
    earnings_date_raw = ctx.earnings_date_raw
    price = ctx.price; prev = ctx.prev; chg = ctx.chg; chg_pct = ctx.chg_pct
    hi52 = ctx.hi52; lo52 = ctx.lo52; vix_v = ctx.vix_v
    qs = ctx.qs; qb = ctx.qb
    use_quant_models = bool(cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))
    earnings_near = ctx.earnings_near; earnings_dt = ctx.earnings_dt
    days_to_earnings = ctx.days_to_earnings; earnings_parse_failed = ctx.earnings_parse_failed
    st.session_state["_cf_earnings_days"] = days_to_earnings
    earn_glance = ctx.earn_glance
    wk_label = ctx.wk_label; wk_color = ctx.wk_color
    struct = ctx.struct; fg = ctx.fg; fg_label = ctx.fg_label
    fg_emoji = ctx.fg_emoji; fg_advice = ctx.fg_advice
    macd_bull = ctx.macd_bull; obv_up = ctx.obv_up; rsi_v = ctx.rsi_v
    h_v = ctx.h_v
    al = ctx.al
    gold_zone_price = ctx.gold_zone_price; gold_zone_components = ctx.gold_zone_components
    cp_score = ctx.cp_score; cp_max = ctx.cp_max; cp_breakdown = ctx.cp_breakdown
    cp_bearish = ctx.cp_bearish; cp_color = ctx.cp_color; cp_label = ctx.cp_label
    diamonds = ctx.diamonds; latest_d = ctx.latest_d
    d_wr = ctx.d_wr; d_avg = ctx.d_avg; d_n = ctx.d_n
    daily_struct = ctx.daily_struct; weekly_struct = ctx.weekly_struct

    render_mode_badge(use_quant_models)
    st.markdown(
        "<div style='margin:2px 0 10px 0'>"
        "<span style='font-size:0.72rem;color:#c4b5fd;padding:3px 10px;border-radius:6px;"
        "border:1px solid rgba(139,92,246,0.45);background:rgba(76,29,149,0.22);font-weight:600;letter-spacing:0.04em'>"
        "v22.0 · PREDICTIVE ANALYTICS</span></div>",
        unsafe_allow_html=True,
    )
    qs_color = ctx.qs_color; qs_status = ctx.qs_status
    rfr = ctx.rfr; bluf_cc = ctx.bluf_cc; bluf_csp = ctx.bluf_csp
    bluf_exp = ctx.bluf_exp; bluf_dte = ctx.bluf_dte
    bluf_calls = ctx.bluf_calls; bluf_puts = ctx.bluf_puts
    opt_exps = ctx.opt_exps; ref_iv_bluf = ctx.ref_iv_bluf
    st.session_state["_cf_bluf_cc_pick"] = bluf_cc
    st.session_state["_cf_bluf_csp_pick"] = bluf_csp
    st.session_state["_cf_gamma_flip"] = None
    try:
        _gf_ctx = getattr(ctx, "gamma_flip", None)
        if _gf_ctx is not None and np.isfinite(float(_gf_ctx)):
            st.session_state["_cf_gamma_flip"] = float(_gf_ctx)
    except (TypeError, ValueError):
        st.session_state["_cf_gamma_flip"] = None
    nc = ctx.nc; action_strat = ctx.action_strat; action_plain = ctx.action_plain
    mini_mode = ctx.mini_mode; mobile_chart_layout = ctx.mobile_chart_layout

    _risk_closes_df = pd.DataFrame()
    _portfolio_lr_df = pd.DataFrame()
    _simple_corr_mult = 1.0
    try:
        _risk_syms = list(dict.fromkeys([str(t).strip().upper() for t in watch_items if t]))[:20]
        _tku = str(ticker).strip().upper()
        if _tku not in _risk_syms:
            _risk_syms.append(_tku)
        _cm = {}
        for _rt in _risk_syms:
            _rdf = fetch_stock(_rt, "1y", "1d")
            if _rdf is not None and not _rdf.empty and "Close" in _rdf.columns:
                _cm[_rt] = pd.to_numeric(_rdf["Close"], errors="coerce")
        _risk_closes_df = pd.DataFrame(_cm).dropna(how="all")
        if len(_risk_closes_df.columns) >= 2 and len(_risk_closes_df) >= 5:
            _portfolio_lr_df = TA.ffd_returns_from_closes(_risk_closes_df, d=0.4)
            if _portfolio_lr_df.empty:
                _portfolio_lr_df = np.log(_risk_closes_df / _risk_closes_df.shift(1)).dropna()
            _simple_corr_mult = Opt._simple_corr_haircut(_risk_syms, _tku, _portfolio_lr_df)
    except Exception:
        _risk_closes_df = pd.DataFrame()
        _portfolio_lr_df = pd.DataFrame()
        _simple_corr_mult = 1.0

    try:
        if len(_risk_closes_df.columns) >= 2:
            _cm_cached = watchlist_correlation_matrix_cached(_risk_closes_df)
            if _cm_cached is not None and not _cm_cached.empty:
                with st.expander("Portfolio Risk", expanded=False):
                    st.caption(
                        "90-day Pearson correlation on **FFD return** innovations (inner-joined dates). "
                        "Matrix refreshes at most once per hour while you interact with the desk."
                    )
                    _heat_main = build_correlation_heatmap(_cm_cached)
                    if _heat_main is not None:
                        st.plotly_chart(_heat_main, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    except Exception:
        pass

    # HEADER: Live Pulse
    last_update = datetime.now().strftime("%H:%M:%S")
    tk_hdr = _html_mod.escape(ticker)
    st.markdown(
        f"""<div class="cf-page-header" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
    <h1 style="margin:0;font-size:1.8rem;background:linear-gradient(135deg,#10b981,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">
        {tk_hdr} COMMAND CENTER
    </h1>
    <div style="display:flex;align-items:center;gap:8px;background:rgba(16,185,129,0.1);padding:4px 12px;border-radius:20px;border:1px solid rgba(16,185,129,0.2);">
        <div style="width:8px;height:8px;background:#10b981;border-radius:50%;box-shadow:0 0 8px #10b981;animation:cf_live_dot_pulse 2s ease-in-out infinite;"></div>
        <span style="font-size:.7rem;color:#10b981;font-family:JetBrains Mono,monospace;font-weight:700;">LIVE FEED: {last_update}</span>
    </div>
</div>
<style>
@keyframes cf_live_dot_pulse {{
  0%,100% {{ opacity: 1; }}
  50% {{ opacity: 0.3; }}
}}
</style>""",
        unsafe_allow_html=True,
    )

    # ── EARNINGS AMBUSH CHECK ──
    if earnings_near and earnings_dt:
        st.markdown(f"""<div style='background:linear-gradient(135deg,rgba(245,158,11,.15),rgba(217,119,6,.1));
            border:2px solid #f59e0b;border-radius:12px;padding:16px 20px;margin:0 0 16px 0'>
            <span style='font-size:1.1rem;color:#f59e0b;font-weight:700'>⚠️ EARNINGS IN {days_to_earnings} DAYS</span>
            <span style='color:#94a3b8;font-size:.9rem;display:block;margin-top:4px'>
            Implied volatility is rich because the print is close. Picture a retailer marking up tags before a holiday rush.
            Assignment risk on short calls jumps with that backdrop. We pause auto alerts until after {earnings_dt.strftime('%b %d, %Y')}.</span></div>""", unsafe_allow_html=True)

    # ── GLANCE ROW ──
    vix_disp = f"{vix_v:.1f}" if vix_v else "N/A"
    if vix_v and vix_v > 25:
        vix_mood = "Fear is up. Premiums pay better."
    elif vix_v and vix_v > 18:
        vix_mood = "Balanced mood. Normal premiums."
    elif vix_v:
        vix_mood = "Calm tape. Premiums run thin."
    else:
        vix_mood = "VIX not loaded"
    if len(df) >= 7:
        price_spark = df["Close"].tail(7)
    else:
        price_spark = (
            df_1mo_spark["Close"].tail(7)
            if df_1mo_spark is not None and not df_1mo_spark.empty
            else df["Close"].tail(min(7, len(df)))
        )
    vix_spark = (
        vix_1mo_df["Close"].tail(7)
        if vix_1mo_df is not None and not vix_1mo_df.empty
        else pd.Series([vix_v, vix_v, vix_v, vix_v, vix_v, vix_v, vix_v])
    )
    earnings_spark = earnings_runway_spark_series(days_to_earnings)
    qe_spark = pd.Series(np.linspace(max(0, qs - 10), min(100, qs + 4), 7))

    g1, g2, g3, g4 = st.columns(4)
    with g1:
        st.markdown(
            _glance_metric_card(
                f"{_html_mod.escape(ticker)} PRICE",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:#e2e8f0'>${price:.2f}</div>",
                f"<div class='glance-caption'>{chg_pct:+.2f}% vs prior close</div>",
                price_spark,
                "#00E5FF",
            ),
            unsafe_allow_html=True,
        )
    with g2:
        st.markdown(
            _glance_metric_card(
                "MARKET MOOD (VIX)",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:#00E5FF'>{_html_mod.escape(vix_disp)}</div>",
                f"<div class='glance-caption'>{_html_mod.escape(vix_mood)}</div>",
                vix_spark,
                "#FF005C" if vix_v and vix_v > 20 else "#00FFA3",
            ),
            unsafe_allow_html=True,
        )
    with g3:
        if earn_glance == "Date unavailable from feed":
            earnings_caption = "Confirm the next print in your broker or calendar feed"
        elif days_to_earnings is not None:
            de = int(days_to_earnings)
            if de < 0:
                earnings_caption = "Print is behind you — size for the next cycle once the date is fresh"
            elif de == 0:
                earnings_caption = "Earnings today — gaps and IV swings; size to what you can hold through"
            elif de <= 5:
                earnings_caption = "Under a week — IV often richest here; ease naked upside risk if you run tight"
            elif de <= 14:
                earnings_caption = "Inside two weeks — decide strikes and contracts before the event"
            else:
                earnings_caption = "Outside two weeks — set risk budget and strikes before IV heats up (hover the gold line for what it shows)"
        else:
            earnings_caption = "Plan size before the print"
        _earn_spark_hint = (
            "Illustrative: days-to-earnings stepping down toward the print — not stock price or IV."
        )
        st.markdown(
            _glance_metric_card(
                "EARNINGS COUNTDOWN",
                f"<div class='glance-value' style='font-size:1.0rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(earn_glance)}</div>",
                f"<div class='glance-caption'>{_html_mod.escape(earnings_caption)}</div>",
                earnings_spark,
                "#FFD700",
                spark_title=_earn_spark_hint,
            ),
            unsafe_allow_html=True,
        )
    with g4:
        qe_color = "#00FFA3" if qs > 70 else ("#FFD700" if qs > 50 else "#FF005C")
        st.markdown(
            _glance_metric_card(
                "QUANT EDGE",
                f"<div class='glance-value' style='font-size:1.28rem;font-weight:700;color:{qe_color}'>{qs:.0f}/100</div>",
                "<div class='glance-caption'>24h directional momentum context</div>",
                qe_spark,
                qe_color,
            ),
            unsafe_allow_html=True,
        )

    why_trade_tip = _html_mod.escape(
        _confluence_why_trade_plain(cp_breakdown, options_chain_available=bool(opt_exps))
    )
    trade_hdr_html = (
        "<div style='display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px'>"
        "<div style='font-size:.72rem;font-weight:800;color:#00e5ff;letter-spacing:.18em'>RECOMMENDED TRADE</div>"
        "<span class='cf-tip cf-tip-ico' tabindex='0' aria-label='Why this trade'>"
        "<span class='cf-tip-ico-mark'>ⓘ</span>"
        f"<span class='cf-tiptext'>{why_trade_tip}</span></span>"
        "<span style='font-size:.62rem;color:#94a3b8'>Why this trade?</span></div>"
    )
    _headlines_v19 = []
    _news_bias_v19 = None
    try:
        _headlines_v19 = fetch_news_headlines(ticker)
        _news_bias_v19 = (
            float(Sentiment.analyze_news_bias(_headlines_v19)) if _headlines_v19 else 0.0
        )
    except Exception:
        _headlines_v19 = []
        _news_bias_v19 = None
    _inst_flow_lbl = "—"
    try:
        _dp_tr = TA.get_dark_pool_proxy(df)
        if _dp_tr is not None and len(_dp_tr) and "dark_pool_alert" in _dp_tr.columns:
            _inst_flow_lbl = (
                "High Accumulation" if bool(_dp_tr["dark_pool_alert"].iloc[-1]) else "Normal"
            )
    except Exception:
        pass
    _news_sent_lbl = "—"
    if _news_bias_v19 is not None and _headlines_v19:
        if _news_bias_v19 > 0.15:
            _news_sent_lbl = "Positive"
        elif _news_bias_v19 < -0.15:
            _news_sent_lbl = "Negative"
        else:
            _news_sent_lbl = "Neutral"
    _score_disp = f"{_news_bias_v19:+.2f}" if _news_bias_v19 is not None else "—"
    _nb_col = "#94a3b8"
    if _news_bias_v19 is not None:
        if _news_bias_v19 > 0.3:
            _nb_col = "#10b981"
        elif _news_bias_v19 < -0.3:
            _nb_col = "#ef4444"
        else:
            _nb_col = "#94a3b8"
    _lines_v19 = []
    for _it in (_headlines_v19[:3] if _headlines_v19 else []):
        _tit = (_it.get("title") or "")[:200]
        _lines_v19.append(f"• {_html_mod.escape(_tit)}")
    _news_why_block = (
        f"<div style='margin:0 0 10px 0;padding:10px 12px;border-radius:8px;border:1px solid rgba(56,189,248,.35);background:rgba(8,47,73,.22)'>"
        f"<div style='font-size:.62rem;font-weight:800;color:#38bdf8;letter-spacing:.12em;margin-bottom:6px'>NEWS BIAS (NLP)</div>"
        f"<div style='font-size:.85rem;font-weight:700;color:#e2e8f0;margin-bottom:6px'>Aggregate score: "
        f"<span class='mono' style='color:{_nb_col};font-weight:800'>{_html_mod.escape(str(_score_disp))}</span> "
        f"<span style='color:#64748b;font-weight:500'>(−1 bearish … +1 bullish)</span></div>"
        + (
            "<div style='font-size:.74rem;color:#94a3b8;line-height:1.45'>" + "<br>".join(_lines_v19) + "</div>"
            if _lines_v19
            else "<div style='font-size:.72rem;color:#64748b'>No headlines available.</div>"
        )
        + "</div>"
    )
    _trade_hdr_stack = f"{trade_hdr_html}{_news_why_block}<div style='margin:0 0 10px 0;padding:8px 12px;border-radius:8px;border:1px solid rgba(148,163,184,.28);font-size:.78rem;color:#cbd5e1;line-height:1.5'>"
    _trade_hdr_stack += (
        f"<strong style='color:#93c5fd'>Institutional Flow:</strong> {_html_mod.escape(str(_inst_flow_lbl))}<br>"
        f"<strong style='color:#93c5fd'>News Sentiment:</strong> "
        f"<span style='color:{_nb_col};font-weight:700'>{_html_mod.escape(str(_news_sent_lbl))}</span></div>"
    )

    # ── RECOMMENDED TRADE (optimal strike from options engine) ──
    _cf_em_safety = {"price": float(price), "strike": None, "iv_pct": None, "dte": None}
    master_kind, master_b = None, None
    if opt_exps and bluf_exp:
        br = struct in ("BULLISH", "RANGING")
        if br and bluf_cc:
            master_kind, master_b = "cc", bluf_cc
        elif br and bluf_csp:
            master_kind, master_b = "csp", bluf_csp
        elif bluf_csp:
            master_kind, master_b = "csp", bluf_csp
        elif bluf_cc:
            master_kind, master_b = "cc", bluf_cc

    master_html = ""
    if master_kind and master_b and bluf_exp:
        try:
            exp_dt = datetime.strptime(str(bluf_exp)[:10], "%Y-%m-%d")
            exp_disp = exp_dt.strftime("%B %d").upper()
            dte_m = max(1, (exp_dt - datetime.now()).days)
        except Exception:
            exp_disp = str(bluf_exp).upper()[:18]
            dte_m = max(1, int(bluf_dte or 30))
        _mstrike = float(master_b.get("strike") or 0)
        _mdelta = float(master_b.get("delta") or 0)
        _mprem = float(master_b.get("prem_100") or 0)
        _miv = float(master_b.get("iv") or 0)
        pop_pct = int(min(92, max(55, round((1.0 - abs(_mdelta)) * 100))))
        tk_esc = _html_mod.escape(ticker)
        _ref_rank_iv = _miv if _miv > 0 else ref_iv_bluf
        iv_badge_html = _iv_rank_pill_html(ticker, price, _ref_rank_iv)
        _mc_hdr = "—"
        try:
            _mpv = master_b.get("mc_pop")
            if _mpv is not None and math.isfinite(float(_mpv)):
                _mc_hdr = f"{float(_mpv):.1f}%"
        except (TypeError, ValueError):
            pass
        _hvn_hdr = "—"
        try:
            _hv = gold_zone_components.get("HVN") if isinstance(gold_zone_components, dict) else None
            if _hv is not None and math.isfinite(float(_hv)):
                _hvn_hdr = f"${float(_hv):,.2f}"
        except (TypeError, ValueError):
            pass
        _prob_subhdr = (
            f"<div style='font-size:.78rem;color:#c4b5fd;font-weight:600;margin:0 0 10px 0;letter-spacing:.02em'>"
            f"MC PoP: {_mc_hdr} | HVN Floor: {_hvn_hdr} | Risk Multiplier: {_simple_corr_mult:.2f}x</div>"
        )
        _iv_for_safe = float(_miv) if _miv > 0 else float(ref_iv_bluf or 0)
        _safe_trade_html = expected_move_safety_html(price, _mstrike, _iv_for_safe, dte_m)
        _cf_em_safety = {
            "price": float(price),
            "strike": float(_mstrike),
            "iv_pct": _iv_for_safe,
            "dte": int(dte_m),
        }
        if master_kind == "cc":
            n_c = nc
            prem_tot = _mprem * n_c
            headline = (
                f"SELL {n_c}x {tk_esc} ${_mstrike:.0f} CALLS EXP {exp_disp}. "
                f"COLLECT ${prem_tot:,.0f} CASH TODAY. {pop_pct} PERCENT PROBABILITY OF KEEPING SHARES."
            )
            rh_steps = [
                f"In your broker app, open {ticker} and go to options.",
                f"Choose expiration {bluf_exp} ({dte_m} days out).",
                f"Sell {n_c}x ${_mstrike:.0f} call(s) near mid, then confirm the order.",
            ]
        else:
            prem_tot = _mprem
            headline = (
                f"SELL 1x {tk_esc} ${_mstrike:.0f} PUTS EXP {exp_disp}. "
                f"COLLECT ${prem_tot:,.0f} CASH TODAY. {pop_pct} PERCENT ODDS OPTION EXPIRES WORTHLESS IF PRICE STAYS ABOVE THE STRIKE."
            )
            rh_steps = [
                f"In your broker app, open {ticker} and go to options.",
                f"Choose expiration {bluf_exp} ({dte_m} days out).",
                f"Sell 1x ${_mstrike:.0f} put near mid, then confirm the order.",
            ]
        stepper = "".join(
            f"<div class='rh-step'><div class='num'>{i}.</div><div class='txt'>{_html_mod.escape(s)}</div></div>"
            for i, s in enumerate(rh_steps, start=1)
        )
        strike_s = f"{_mstrike:.0f}"
        iv_line = f"IV {_miv:.1f}% · " if _miv > 0 else ""
        _mc_pop_seg = ""
        _mc_pop_raw = master_b.get("mc_pop", None)
        if _mc_pop_raw is not None:
            try:
                _mc_pop_v = float(_mc_pop_raw)
                if math.isfinite(_mc_pop_v):
                    _mc_pop_seg = f" · MC PoP: {_mc_pop_v:.1f}%"
            except (TypeError, ValueError):
                pass
        _mb_bid = master_b.get("bid", 0)
        _mb_mid = master_b.get("mid", 0)
        _walk = walk_up_limit_sell_per_share(_mb_bid, _mb_mid)
        _walk_seg = ""
        if _walk is not None:
            _walk_seg = (
                f"<div style='color:#a5f3fc;font-size:.86rem;margin-bottom:10px;font-weight:600'>"
                f"Walk-up limit (sell credit): <span class='mono'>${_walk:.2f}</span> / sh "
                f"<span style='color:#64748b;font-weight:500'>(bid + mid) / 2</span></div>"
            )
        master_html = (
            f"<div class='trade-master'>"
            f"{_trade_hdr_stack}"
            f"{iv_badge_html}"
            f"{_prob_subhdr}"
            f"{_safe_trade_html}"
            f"<p style='color:#e2e8f0;font-size:1.05rem;line-height:1.55;margin:0 0 14px 0;font-weight:600'>{headline}</p>"
            f"<div class='strike-big' style='margin:8px 0 6px 0'>${_html_mod.escape(strike_s)}</div>"
            f"{_walk_seg}"
            f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px'>Desk optimal strike · {iv_line}DTE {dte_m}{_mc_pop_seg}</div>"
            f"<div style='font-size:.75rem;font-weight:700;color:#a5f3fc;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px'>Broker checklist</div>"
            f"<div class='rh-stepper'>{stepper}</div>"
            f"<p style='color:#64748b;font-size:.78rem;margin:14px 0 0 0'>Quotes can lag. Confirm credit in the app before you send the order.</p>"
            f"</div>"
        )
    elif not opt_exps:
        _iv_off = _iv_rank_pill_html(ticker, price, None, stub="offline")
        master_html = (
            f"<div class='trade-master'>"
            f"{_trade_hdr_stack}"
            f"{_iv_off}"
            f"<p style='color:#e2e8f0;font-size:1rem;line-height:1.5;margin:0'>"
            f"No option expirations from Yahoo for <span class='mono'>{_html_mod.escape(ticker)}</span> after retries. "
            f"Use <a href='#strategies' style='color:#22d3ee'>Cash Flow</a>, then <strong>Refresh options data</strong>, "
            f"or pick strikes in your broker. Micro-caps may have no Yahoo chain even if options trade elsewhere."
            f"</p>"
            f"<p style='color:#64748b;font-size:.78rem;margin:10px 0 0 0'>Quant Edge and Confluence above still describe the tape.</p>"
            f"</div>"
        )
    else:
        # Fallback when strict OI/volume filters remove every strike.
        # Prefer 3-7% OTM candidates on the strategy side, then nearest to 5% OTM.
        def _fallback_pick(df_opt, side):
            if not isinstance(df_opt, pd.DataFrame) or df_opt.empty:
                return None
            w = df_opt.copy()
            w["strike"] = pd.to_numeric(w.get("strike"), errors="coerce")
            w["bid"] = pd.to_numeric(w.get("bid"), errors="coerce").fillna(0.0)
            w["ask"] = pd.to_numeric(w.get("ask"), errors="coerce").fillna(0.0)
            w["lastPrice"] = pd.to_numeric(w.get("lastPrice"), errors="coerce").fillna(0.0)
            w["mid"] = (w["bid"] + w["ask"]) / 2.0
            # After-hours feeds often carry zero bid/ask; use last trade as backup quote.
            w["est_px"] = np.where(w["mid"] > 0.0, w["mid"], w["lastPrice"])
            if side == "call":
                w = w[w["strike"] > price].copy()
                w["otm"] = (w["strike"] / price - 1.0) * 100.0
                strike_sort = ["target_gap", "strike"]
                asc = [True, True]
            else:
                w = w[w["strike"] < price].copy()
                w["otm"] = (1.0 - w["strike"] / price) * 100.0
                strike_sort = ["target_gap", "strike"]
                asc = [True, False]
            w = w[w["otm"].notna()].copy()
            if w.empty:
                return None
            preferred = w[(w["otm"] >= 3.0) & (w["otm"] <= 7.0)].copy()
            if preferred.empty:
                preferred = w
            preferred["target_gap"] = (preferred["otm"] - 5.0).abs()
            return preferred.sort_values(strike_sort, ascending=asc).iloc[0]

        fallback_kind = None
        fallback_row = None
        prefer_put_side = action_strat in ("SELL CASH SECURED PUTS", "BULL PUT SPREAD")
        side_order = [("csp", "put"), ("cc", "call")] if prefer_put_side else [("cc", "call"), ("csp", "put")]
        for kind, side in side_order:
            row = _fallback_pick(bluf_puts if side == "put" else bluf_calls, side)
            if row is not None:
                fallback_kind, fallback_row = kind, row
                break

        if fallback_row is not None and bluf_exp:
            _f_strike = float(fallback_row["strike"])
            try:
                _f_dte_safe = max(1, (datetime.strptime(str(bluf_exp)[:10], "%Y-%m-%d") - datetime.now()).days)
            except Exception:
                _f_dte_safe = max(1, int(bluf_dte or 30))
            _f_px = float(pd.to_numeric(fallback_row.get("est_px"), errors="coerce") or 0.0)
            _f_prem = _f_px * 100.0
            _f_bid = float(pd.to_numeric(fallback_row.get("bid"), errors="coerce") or 0.0)
            _f_mid = float(pd.to_numeric(fallback_row.get("mid"), errors="coerce") or 0.0)
            if _f_mid <= 0 and _f_px > 0:
                _f_mid = _f_px
            _f_walk = walk_up_limit_sell_per_share(_f_bid, _f_mid if _f_mid > 0 else None)
            _f_walk_html = ""
            if _f_walk is not None:
                _f_walk_html = (
                    f"<div style='color:#a5f3fc;font-size:.85rem;margin:6px 0 8px 0;font-weight:600'>"
                    f"Walk-up limit (sell credit): <span class='mono'>${_f_walk:.2f}</span> / sh "
                    f"<span style='color:#64748b;font-weight:500'>(bid + mid) / 2</span></div>"
                )
            _f_iv_raw = float(pd.to_numeric(fallback_row.get("impliedVolatility"), errors="coerce") or 0.0)
            _f_iv_pct = _f_iv_raw * 100.0 if _f_iv_raw > 0 else ref_iv_bluf
            _iv_fb = _iv_rank_pill_html(ticker, price, _f_iv_pct, stub=None if _f_iv_pct else "no_strike")
            _safe_fb_html = expected_move_safety_html(price, _f_strike, float(_f_iv_pct or 0), _f_dte_safe)
            _cf_em_safety = {
                "price": float(price),
                "strike": float(_f_strike),
                "iv_pct": float(_f_iv_pct or 0),
                "dte": int(_f_dte_safe),
            }
            if fallback_kind == "cc":
                _f_headline = (
                    f"FALLBACK LINE: SELL {nc}x {_html_mod.escape(ticker)} ${_f_strike:.0f} CALLS EXP {bluf_exp}. "
                    f"EST CREDIT ${_f_prem * nc:,.0f}."
                )
                _f_note = "Strict desk liquidity filters blocked every strike; this is the nearest 3-7% OTM call line."
            else:
                _f_headline = (
                    f"FALLBACK LINE: SELL 1x {_html_mod.escape(ticker)} ${_f_strike:.0f} PUTS EXP {bluf_exp}. "
                    f"EST CREDIT ${_f_prem:,.0f}."
                )
                _f_note = "Strict desk liquidity filters blocked every strike; this is the nearest 3-7% OTM put line."
            master_html = (
                f"<div class='trade-master'>"
                f"{_trade_hdr_stack}"
                f"{_iv_fb}"
                f"{_safe_fb_html}"
                f"<p style='color:#e2e8f0;font-size:1rem;line-height:1.5;margin:0 0 10px 0;font-weight:600'>{_f_headline}</p>"
                f"<div class='strike-big' style='margin:6px 0 4px 0'>${_f_strike:.0f}</div>"
                f"{_f_walk_html}"
                f"<div style='color:#94a3b8;font-size:.85rem'>{_f_note}</div>"
                f"</div>"
            )
        else:
            _iv_ns = _iv_rank_pill_html(ticker, price, ref_iv_bluf, stub="no_strike" if not ref_iv_bluf else None)
            _fallback_action = _html_mod.escape(action_strat.title())
            master_html = (
                f"<div class='trade-master'>"
                f"{_trade_hdr_stack}"
                f"{_iv_ns}"
                f"<p style='color:#e2e8f0;font-size:1rem;line-height:1.5;margin:0 0 8px 0'>"
                f"Desk filters are too strict for this snapshot. Use a manual {_fallback_action} line around 3-7% OTM on the nearest monthly expiry."
                f"</p>"
                f"<p style='color:#94a3b8;font-size:.85rem;margin:0'>"
                f"Reference spot: ${price:,.2f}. Open Cash Flow Strategies for full chain selection."
                f"</p>"
                f"</div>"
            )

    st.session_state["_cf_em_safety"] = _cf_em_safety

    ema_dist_pct = None
    if len(df) >= 20:
        _e20 = TA.ema(df["Close"], 20).iloc[-1]
        if not pd.isna(_e20) and float(_e20) > 0:
            ema_dist_pct = abs(price / float(_e20) - 1.0) * 100.0

    # Build diamond status badge HTML
    d_badge_html = ""
    if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
        if latest_d["type"] == "blue":
            d_badge_html = f"<span class='diamond-badge badge-blue'>🔷 BLUE DIAMOND ACTIVE</span>"
        else:
            d_badge_html = f"<span class='diamond-badge badge-pink'>💎 PINK DIAMOND: TAKE PROFIT</span>"
    else:
        d_badge_html = "<span class='diamond-badge badge-none'>◇ No Active Diamond</span>"

    iv_rank_info = compute_iv_rank_proxy(ticker, price, ref_iv_bluf) if ref_iv_bluf else None
    ext_warn_html = ""
    if ema_dist_pct is not None and ema_dist_pct > EMA_EXTENSION_WARN_PCT:
        ext_warn_html = (
            f"<div style='margin-top:10px;padding:8px 12px;border-radius:8px;border:1px solid rgba(245,158,11,.45);"
            f"background:rgba(245,158,11,.12);font-size:.76rem;color:#fde68a;line-height:1.45'>"
            f"<strong>Caution: Extended.</strong> Price sits <strong>{ema_dist_pct:.1f}%</strong> away from the 20 day EMA. "
            f"After violent gaps, Gold Zone and Fib anchors can lag even while confluence still reflects the old range.</div>"
        )
    iv_row_html = ""
    if iv_rank_info is not None and ref_iv_bluf:
        rnk = iv_rank_info["rank"]
        lo, hi = iv_rank_info["lo"], iv_rank_info["hi"]
        rk_color = "#f59e0b" if rnk > 70 else ("#34d399" if rnk < 25 else "#94a3b8")
        iv_row_html = (
            f"<div style='margin-top:8px;padding:8px 12px;border-radius:8px;border:1px solid rgba(34,211,238,.35);"
            f"background:rgba(6,182,212,.1);font-size:.74rem;color:#cbd5e1;line-height:1.45'>"
            f"<span style='color:{rk_color};font-weight:800;font-family:JetBrains Mono,monospace'>{rnk:.0f}</span> "
            f"<span style='color:#94a3b8'>IV rank (term-structure proxy)</span> · "
            f"ref <strong>{ref_iv_bluf:.1f}%</strong> vs ATM curve from <span class='mono'>{lo:.1f}%</span> to <span class='mono'>{hi:.1f}%</span> "
            f"across listed expiries. <span style='color:#64748b'>This is a term structure proxy, not a full 52 week IV history.</span></div>"
        )
    elif ref_iv_bluf:
        iv_row_html = (
            "<div style='margin-top:8px;font-size:.72rem;color:#64748b'>IV rank proxy unavailable (need 2+ expiries with IV).</div>"
        )
    bluf_context_strip = ext_warn_html + iv_row_html

    # Confluence bar segments HTML
    cp_bar_html = ""
    for i in range(cp_max):
        filled = i < cp_score
        color = "#10b981" if filled and cp_score >= 7 else ("#f59e0b" if filled and cp_score >= 4 else ("#ef4444" if filled else "#1e293b"))
        cp_bar_html += f"<div style='flex:1;height:10px;background:{color};border-radius:5px;margin:0 1px'></div>"

    gz_gap_pct = ((price / gold_zone_price - 1) * 100) if gold_zone_price else 0.0
    show_gold_glance = bool(st.session_state.get("sb_gold_zone", True))
    bluf_html = f"""<div class='bluf'>
        <div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px'>
            <div>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{qs_color}'>{qs:.0f}</span>
                <span style='color:{qs_color};font-size:.9rem;margin-left:8px'>{qs_status}</span>
            </div>
            <div style='text-align:center'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>CONFLUENCE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{cp_color}'>{cp_score}/{cp_max}</span>
                <span style='color:{cp_color};font-size:.9rem;display:block'>{cp_label}</span>
                <div style='display:flex;gap:2px;margin-top:6px;width:160px'>{cp_bar_html}</div>
            </div>
            <div style='text-align:right'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>WEEKLY TREND</div>
                <span style='font-size:1.2rem;font-weight:700;color:{wk_color}'>{wk_label}</span>
                <div style='margin-top:8px'>{d_badge_html}</div>
            </div>
        </div>
        {bluf_context_strip}
        <div style='display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;border-top:1px solid rgba(255,255,255,.06);padding-top:12px'>
            <div style='flex:1;min-width:250px'>
                <div style='font-size:.7rem;color:{"#eab308" if show_gold_glance else "#64748b"};text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px'>⬥ GOLD ZONE</div>
                <span class='mono' style='font-size:1.3rem;font-weight:700;color:#fbbf24'>${gold_zone_price:.2f}</span>
                <span style='color:#94a3b8;font-size:.8rem;margin-left:8px'>({gz_gap_pct:+.1f}% away)</span>
            </div>
            <div style='flex:1;min-width:250px'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px'>MULTI-TF BIAS</div>
                <span style='font-size:.85rem;color:{"#10b981" if daily_struct=="BULLISH" else ("#ef4444" if daily_struct=="BEARISH" else "#f59e0b")}'>Daily: {daily_struct}</span>
                <span style='margin:0 8px;color:#334155'>|</span>
                <span style='font-size:.85rem;color:{"#10b981" if weekly_struct=="BULLISH" else ("#ef4444" if weekly_struct=="BEARISH" else "#f59e0b")}'>Weekly: {weekly_struct}</span>
                <div style='margin-top:8px;font-size:.78rem;color:#64748b'>52 week: <span class='mono' style='color:#94a3b8'>${hi52:.2f}</span> high · <span class='mono' style='color:#94a3b8'>${lo52:.2f}</span> low</div>
            </div>
        </div>
        <div style='display:flex;gap:24px;flex-wrap:wrap;margin-top:14px;border-top:1px solid rgba(255,255,255,.06);padding-top:12px'>
            <div><span class='tl' style='background:{"#10b981" if macd_bull else "#ef4444"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Momentum: <strong style="color:#e2e8f0">{"Buyers are in control" if macd_bull else "Sellers are gaining ground"}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if obv_up else "#ef4444"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Volume: <strong style="color:#e2e8f0">{"Big money is buying" if obv_up else "Big money is selling"}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if vix_v and vix_v > 20 else "#f59e0b"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>Premiums: <strong style="color:#e2e8f0">{"Huge. Fear is high." if vix_v and vix_v > 25 else ("Normal range" if vix_v and vix_v > 18 else "Thin. Market is too calm.")}</strong></span></div>
            <div><span class='tl' style='background:{"#10b981" if 35 < rsi_v < 65 else "#f59e0b"}'></span>
                <span style='color:#94a3b8;font-size:.85rem'>RSI: <strong style="color:#e2e8f0">{rsi_v:.0f}. {"Perfect zone for selling" if 35 < rsi_v < 65 else ("Stock ran too fast" if rsi_v > 65 else "Stock dropped too fast")}</strong></span></div>
        </div>
    </div>"""

    # ══════════════════════════════════════════════════════════════════
    #  EXECUTION STRIP (aligned mission + context)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="execution" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _ex_left, _ex_right = st.columns([1.25, 1])
    with _ex_left:
        st.markdown(_render_html_block(master_html), unsafe_allow_html=True)
    with _ex_right:
        st.markdown(_render_html_block(bluf_html), unsafe_allow_html=True)

    # ── ALERTS BAR ──
    hi_al = [a for a in al if a["p"] == "HIGH"]
    if hi_al:
        _lead = hi_al[0]["m"]
        _more = f" +{len(al) - 1} more" if len(al) > 1 else ""
        with st.expander(
            f"🔔 {len(al)} Alert{'s' if len(al) > 1 else ''}: {_lead}{_more}",
            expanded=False,
        ):
            for _a in al:
                _ic = "🟢" if _a["t"] == "bullish" else ("🔴" if _a["t"] == "bearish" else "🟡")
                st.markdown(
                    f"<div class='ac'>{_ic} [{_html_mod.escape(_a['p'])}] {_html_mod.escape(_a['m'])}</div>",
                    unsafe_allow_html=True,
                )

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1: TECHNICAL CHART (fragment: overlay toggles without refetching Yahoo)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="charts" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    # Fragment reruns must not rely on extra kwargs (Streamlit's @st.fragment can omit them).
    st.session_state["_cf_use_quant_models"] = use_quant_models
    st.session_state["_cf_vix_snapshot"] = float(vix_v or 0.0)
    try:
        _iv_ch = float(ref_iv_bluf or 0)
        for _cx in (bluf_cc, bluf_csp):
            if _cx:
                try:
                    _vx = float(_cx.get("iv") or 0)
                    if _vx > _iv_ch:
                        _iv_ch = _vx
                except (TypeError, ValueError):
                    pass
        _dte_ch = int(bluf_dte) if bluf_dte else 0
        _exp_ch = None
        if bluf_exp:
            try:
                _exp_ch = datetime.strptime(str(bluf_exp)[:10], "%Y-%m-%d")
            except Exception:
                _exp_ch = None
        if _dte_ch > 0 and _iv_ch > 0:
            st.session_state["_cf_chart_em"] = {"iv_pct": _iv_ch, "dte": _dte_ch, "expiry": _exp_ch}
        else:
            st.session_state["_cf_chart_em"] = {}
    except Exception:
        st.session_state["_cf_chart_em"] = {}
    _fragment_technical_zone(
        df,
        df_wk,
        ticker,
        gold_zone_price,
        gold_zone_components,
        price,
        diamonds,
        latest_d,
        cp_breakdown,
        d_wr,
        d_n,
        struct,
        mini_mode,
        mobile_chart_layout,
    )
    chart_mood = "bull" if struct == "BULLISH" else ("bear" if struct == "BEARISH" else "neutral")

    dash_tab_setup, dash_tab_cashflow, dash_tab_intel, dash_tab_ledger = st.tabs(
        [
            "Setup & quant",
            "Cashflow & strikes",
            "Risk, scanner & intel",
            "📊 Sentinel Ledger",
        ]
    )

    with dash_tab_setup:
            # ══════════════════════════════════════════════════════════════════
            #  SECTION 2 \u2014 SETUP ANALYSIS
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="setup" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Setup Analysis", "Trend, range, or fade: here is the read and how to play it without guessing.",
                     tip_plain="This block is your bias clock. Uptrends reward measured premium sales with air above price. Ranges invite two sided discipline. Downtrends demand smaller size and wider buffers.")

            if ticker == "PLTR":
                next_print = datetime(2026, 5, 4)
                d_to_print = (next_print.date() - datetime.now().date()).days
                if d_to_print > 0:
                    countdown_txt = f"{d_to_print} days to earnings ({next_print.strftime('%b %d, %Y')})"
                elif d_to_print == 0:
                    countdown_txt = "Earnings expected today (May 04, 2026)"
                else:
                    countdown_txt = f"Last projected print date passed by {abs(d_to_print)} days (May 04, 2026)"
                with st.expander("STRATEGIC INTELLIGENCE: PLTR · Q4 2025 / 2026 OUTLOOK", expanded=True):
                    gc, bc = st.columns(2)
                    with gc:
                        st.markdown(
                            """
                            <div class='earn-col earn-good'>
                                <h4>THE GOOD (THE CATALYST)</h4>
                                <ul>
                                    <li><strong>Hyper Growth:</strong> Q4 2025 revenue grew 70% Y/Y to $1.41B. U.S. Commercial surged 137%.</li>
                                    <li><strong>Rule of 40:</strong> Palantir is operating at an elite Rule of 40 score of 127%.</li>
                                    <li><strong>2026 Guidance:</strong> Management guided to roughly 61% Y/Y growth with a $7.2B target.</li>
                                    <li><strong>Profitability:</strong> GAAP Net Income reached $609M (43% margin); FCF hit $791M.</li>
                                </ul>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with bc:
                        st.markdown(
                            f"""
                            <div class='earn-col earn-bad'>
                                <h4>THE BAD (THE RISK)</h4>
                                <ul>
                                    <li><strong>Valuation:</strong> Trading near 125x to 248x P/E, priced for near perfection.</li>
                                    <li><strong>International Lag:</strong> U.S. commercial +137% vs international commercial +2%.</li>
                                    <li><strong>SBC &amp; Dilution:</strong> Heavy stock based compensation remains a key bear argument.</li>
                                    <li><strong>Upcoming Print:</strong> {countdown_txt}. Street EPS projection is $0.26 to $0.29.</li>
                                </ul>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    st.markdown(
                        """
                        <div class='earn-meta'>
                            <span class='earn-pill'>Q4 2025 Revenue: $1.41B</span>
                            <span class='earn-pill'>U.S. Commercial: +137% Y/Y</span>
                            <span class='earn-pill'>2026 Guide: $7.2B</span>
                            <span class='earn-pill'>Projected EPS: $0.26-$0.29</span>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

            sa_left, sa_right = st.columns(2)
            with sa_left:
                cls = "sb" if struct == "BULLISH" else ("sr" if struct == "BEARISH" else "sn")
                st.markdown(f"<div class='{cls}'><strong>Market Structure: {struct}</strong></div>", unsafe_allow_html=True)
                struct_explain = {
                    "BULLISH": "The stock is making higher highs and higher lows. Think of a store where sales grow every single quarter. The trend is your friend. Sell covered calls at the highs to collect rent on your shares.",
                    "BEARISH": "The stock is making lower highs and lower lows. Think of a store where foot traffic drops every month. Be careful. Widen your safety buffers or wait for the bottom before selling options.",
                    "RANGING": "The stock is bouncing between a ceiling and a floor. Think of a business in a steady market. This is actually great for selling options on both sides and collecting cash."}
                _explain("Why this matters for your trade", struct_explain[struct], chart_mood)

                # Hurst Exponent: market regime filter
                hurst_val = TA.hurst(df["Close"])
                if hurst_val > 0.55:
                    h_label, h_color = "TRENDING", "#10b981"
                elif hurst_val < 0.45:
                    h_label, h_color = "MEAN REVERTING", "#8b5cf6"
                else:
                    h_label, h_color = "RANDOM WALK", "#f59e0b"
                st.markdown(f"<div class='tc' style='text-align:center;margin-bottom:12px'>"
                    f"<div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Hurst Exponent (R/S)</div>"
                    f"<div class='mono' style='font-size:1.3rem;color:{h_color}'>{hurst_val:.3f} = {h_label}</div></div>", unsafe_allow_html=True)
                if 0.45 <= hurst_val <= 0.55:
                    _explain("\u26a0\ufe0f Random Walk Warning",
                        f"Hurst is {hurst_val:.3f}. That means the price is moving randomly right now. Like flipping a coin. "
                        "Trend tools like Supertrend, ADX, and MACD are not reliable when this happens. "
                        "Your best move is to wait for a clear direction or use strategies that profit from sideways movement.", "bear")
                elif hurst_val > 0.55:
                    _explain("Hurst says: Trending Market",
                        f"Hurst is {hurst_val:.3f}. The stock has strong trending behavior. Whatever direction it is going, it is likely to keep going. "
                        "Think of a business with sales growing every quarter. You can trust the trend. "
                        "Trend tools like Supertrend and MACD are working correctly right now.", "bull")
                else:
                    _explain("Hurst says: Prices Snap Back",
                        f"Hurst is {hurst_val:.3f}. Prices are snapping back to the average faster than normal. "
                        "Big moves tend to reverse quickly. This is perfect for selling options at extremes. "
                        "You collect the premium and the stock comes back to you. Time decay works in your favor.", "bull")

                _qe_blurb = (
                    "Institutional mode: headline score blends <strong>FFD</strong> and <strong>HMM regime</strong> "
                    "(open A/B diagnostics for the retail five pillars)."
                    if use_quant_models and isinstance(qb, dict) and qb.get("model") == "institutional"
                    else "Composite from five checks: trend, momentum, volume, volatility, structure."
                )
                st.markdown(
                    f"""<div class='qe'>
                    <div style='font-size:.75rem;color:#8b5cf6;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE SCORE</div>
                    <div style='font-size:3rem;font-weight:800;color:{qs_color};font-family:JetBrains Mono,monospace'>{qs:.0f}</div>
                    <div style='font-size:.85rem;color:#94a3b8'>{_qe_blurb}</div></div>""",
                    unsafe_allow_html=True,
                )
                with st.expander("📝 Rolling Edge Capture Log (live matrix edge market)", expanded=False):
                    _fragment_rolling_edge_capture()
                if use_quant_models:
                    retail_score, retail_breakdown = quant_edge_score(df, vix_val=vix_v, use_quant=False)
                    inst_score, inst_breakdown = qs, qb
                    delta_q = inst_score - retail_score
                    st.metric(
                        label="Quant Edge (Institutional)",
                        value=f"{inst_score:.0f}/100",
                        delta=f"{delta_q:+.0f} vs Retail",
                        delta_color="normal" if delta_q >= 0 else "inverse",
                    )
                    with st.expander("🔬 A/B Engine Diagnostics"):
                        st.caption("Comparing standard RSI/MA logic against FFD/HMM models.")
                        col1, col2 = st.columns(2)
                        col1.metric("Retail Engine", f"{retail_score:.0f}")
                        col2.metric("Quant Engine", f"{inst_score:.0f}", delta=f"{delta_q:+.0f} vs retail")
                        _is_inst = isinstance(inst_breakdown, dict) and inst_breakdown.get("model") == "institutional"
                        if _is_inst:
                            st.success(
                                "Institutional path active: headline **Quant** score blends **FFD momentum** and **HMM regime** "
                                "(not the simple average of the five retail pillars)."
                            )
                            i1, i2, i3 = st.columns(3)
                            _rp = float(inst_breakdown.get("regime_prob_high_vol") or 0.0)
                            _ffd = float(inst_breakdown.get("ffd_last") or 0.0)
                            i1.metric("High-vol regime (HMM)", f"{_rp * 100:.1f}%", help="Probability mass in the high-volatility state.")
                            i2.metric("FFD residual", f"{_ffd:.4f}", help="Fractional differentiation signal (stationary momentum memory).")
                            i3.metric("Composite", f"{inst_score:.1f}", help="Capped blend used for the main Quant Edge gauge.")
                            st.markdown("##### Retail: five pillars (20% each)")
                            _pillars = {k: retail_breakdown.get(k) for k in ("trend", "momentum", "volume", "volatility", "structure") if k in retail_breakdown}
                            streamlit_show_dataframe(
                                pd.DataFrame([{"Dimension": k.title(), "Score": round(float(v), 1)} for k, v in _pillars.items()]),
                                use_container_width=True,
                                hide_index=True,
                                key=f"qe_pillars_inst_{ticker}_{len(_pillars)}",
                                on_select="ignore",
                                selection_mode=[],
                                column_config={"Score": st.column_config.NumberColumn("Score", format="%.1f")},
                            )
                        else:
                            st.warning(
                                "**Quant engine matched Retail.** The FFD/HMM institutional branch did not run "
                                "(missing `hmmlearn`, insufficient history, or an internal error). "
                                "Both numbers use the same five-factor model below."
                            )
                            pc1, pc2 = st.columns(2)
                            _dims = ("trend", "momentum", "volume", "volatility", "structure")

                            def _pillar_df(bd):
                                rows = [
                                    {"Dimension": k.title(), "Score": round(float(bd[k]), 1)}
                                    for k in _dims
                                    if isinstance(bd, dict) and k in bd and isinstance(bd[k], (int, float))
                                ]
                                return pd.DataFrame(rows)

                            with pc1:
                                st.markdown("**Retail**")
                                streamlit_show_dataframe(
                                    _pillar_df(retail_breakdown),
                                    use_container_width=True,
                                    hide_index=True,
                                    key=f"qe_pillars_retail_{ticker}",
                                    on_select="ignore",
                                    selection_mode=[],
                                    column_config={"Score": st.column_config.NumberColumn(format="%.1f")},
                                )
                            with pc2:
                                st.markdown("**Quant (fallback)**")
                                streamlit_show_dataframe(
                                    _pillar_df(inst_breakdown),
                                    use_container_width=True,
                                    hide_index=True,
                                    key=f"qe_pillars_qfb_{ticker}",
                                    on_select="ignore",
                                    selection_mode=[],
                                    column_config={"Score": st.column_config.NumberColumn(format="%.1f")},
                                )
                    with st.expander("⏳ Time-Machine Backtester (Historical Edge)", expanded=False):
                        st.caption("Simulates buying this asset every time the Quant Edge flashes, holding for N days.")

                        p1, p2, p3 = st.columns(3)
                        if p1.button("🛡️ Conservative (80 / 5d)", use_container_width=True, help="High conviction entry, quick exit. Optimizes for Win Rate."):
                            st.session_state.bt_thresh = 80
                            st.session_state.bt_hold = 5
                        if p2.button("⚖️ Balanced (70 / 10d)", use_container_width=True, help="Standard swing trade parameters."):
                            st.session_state.bt_thresh = 70
                            st.session_state.bt_hold = 10
                        if p3.button("🔥 Aggressive (60 / 20d)", use_container_width=True, help="Lower conviction entry, longer trend capture. Optimizes for Max Profit."):
                            st.session_state.bt_thresh = 60
                            st.session_state.bt_hold = 20

                        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

                        bt_col1, bt_col2 = st.columns([1, 1])
                        with bt_col1:
                            bt_thresh = st.slider("Entry Edge Score Threshold", min_value=50, max_value=90, key="bt_thresh", step=5)
                        with bt_col2:
                            bt_hold = st.slider("Holding Period (Days)", min_value=1, max_value=30, key="bt_hold", step=1)

                        try:
                            bt_results = QuantBacktest.run_edge_backtest(df, threshold=bt_thresh, hold_days=bt_hold)

                            if bt_results and bt_results["Total_Trades"] > 0:
                                st.markdown("<br>", unsafe_allow_html=True)
                                m1, m2, m3, m4, m5 = st.columns(5)
                                m1.metric("Total Trades", f"{bt_results['Total_Trades']}")
                                m2.metric("Win Rate", f"{bt_results['Win_Rate']:.1f}%")
                                m3.metric("Expectancy per Trade", f"{bt_results['Expectancy']:+.2f}%")
                                m4.metric("Sharpe Ratio", f"{bt_results['Sharpe']:.2f}")
                                m5.metric("Max Drawdown", f"{bt_results['Max_DD']:.1f}%")

                                st.markdown("<br>", unsafe_allow_html=True)
                                eq_df = bt_results["Equity_Curve"]
                                fig_eq = go.Figure()
                                fig_eq.add_trace(
                                    go.Scatter(
                                        x=eq_df.index,
                                        y=eq_df["Equity_Curve"],
                                        mode="lines",
                                        name="Strategy Equity",
                                        line=dict(color="#3b82f6", width=2),
                                        fill="tozeroy",
                                        fillcolor="rgba(59, 130, 246, 0.1)",
                                    )
                                )
                                fig_eq.update_layout(
                                    title=dict(text="Strategy Equity Curve ($10k Start)", font=dict(color="#e2e8f0", size=14)),
                                    template="plotly_dark",
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(0,0,0,0)",
                                    margin=dict(l=10, r=10, t=40, b=10),
                                    height=250,
                                    xaxis_title="Date",
                                    yaxis_title="Account Value ($)",
                                )
                                st.plotly_chart(fig_eq, use_container_width=True)
                            else:
                                st.warning("Not enough historical data or no trades triggered at this threshold.")
                        except Exception:
                            st.error("Backtest simulation failed. Adjust parameters.")
                    if isinstance(retail_breakdown, dict):
                        for k, v in retail_breakdown.items():
                            if not isinstance(v, (int, float, np.integer, np.floating)):
                                continue
                            clr = "#10b981" if v > 70 else ("#f59e0b" if v > 50 else "#ef4444")
                            st.markdown(f"<div style='display:flex;align-items:center;margin:3px 0'><span style='width:85px;color:#94a3b8;font-size:.8rem;text-transform:capitalize'>{k}</span><div style='flex:1;background:#1e293b;border-radius:4px;height:7px;margin:0 8px'><div style='width:{v}%;background:{clr};border-radius:4px;height:7px'></div></div><span class='mono' style='color:#e2e8f0;font-size:.8rem'>{v:.0f}</span></div>", unsafe_allow_html=True)
                else:
                    for k, v in qb.items():
                        if not isinstance(v, (int, float, np.integer, np.floating)):
                            continue
                        clr = "#10b981" if v > 70 else ("#f59e0b" if v > 50 else "#ef4444")
                        st.markdown(f"<div style='display:flex;align-items:center;margin:3px 0'><span style='width:85px;color:#94a3b8;font-size:.8rem;text-transform:capitalize'>{k}</span><div style='flex:1;background:#1e293b;border-radius:4px;height:7px;margin:0 8px'><div style='width:{v}%;background:{clr};border-radius:4px;height:7px'></div></div><span class='mono' style='color:#e2e8f0;font-size:.8rem'>{v:.0f}</span></div>", unsafe_allow_html=True)

                # ── CONFLUENCE POINTS (0-9 visual meter) ──
                st.markdown(f"""<div class='confluence-meter' style='margin-top:16px'>
                    <div style='font-size:.75rem;color:{cp_color};text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px'>💎 CONFLUENCE POINTS</div>
                    <div style='font-size:2.2rem;font-weight:800;color:{cp_color};font-family:JetBrains Mono,monospace'>{cp_score}/{cp_max} {cp_label}</div>
                    <div style='font-size:.8rem;color:#94a3b8;margin-top:2px'>{"🔷 Blue Diamond territory: strong buy signal active" if cp_score >= 7 else ("Approaching diamond zone: watch closely" if cp_score >= 5 else "Not enough confluence for a diamond signal")}</div>
                </div>""", unsafe_allow_html=True)
                for comp_name, comp_data in cp_breakdown.items():
                    pts = comp_data["pts"]
                    mx = comp_data["max"]
                    detail = comp_data["detail"]
                    bar_pct = (pts / mx * 100) if mx > 0 else 0
                    clr = "#10b981" if pts == mx else ("#f59e0b" if pts > 0 else "#334155")
                    st.markdown(f"<div style='display:flex;align-items:center;margin:3px 0'>"
                        f"<span style='width:95px;color:#94a3b8;font-size:.78rem'>{comp_name}</span>"
                        f"<div style='flex:1;background:#1e293b;border-radius:4px;height:7px;margin:0 8px'>"
                        f"<div style='width:{bar_pct}%;background:{clr};border-radius:4px;height:7px'></div></div>"
                        f"<span class='mono' style='color:#e2e8f0;font-size:.78rem;width:30px;text-align:right'>{pts}/{mx}</span>"
                        f"<span style='color:#64748b;font-size:.72rem;margin-left:8px;width:120px'>{detail}</span></div>",
                        unsafe_allow_html=True)

            with sa_right:
                st.markdown("**Key Price Levels**")
                if len(df) >= 50:
                    rec = df.iloc[-60:]
                    fl = TA.fib_retracement(rec["High"].max(), rec["Low"].min())
                    _fib_df = _df_price_levels(fl, price)
                    streamlit_show_dataframe(
                        _fib_df,
                        column_config=_PRICE_LEVEL_COLUMN_CONFIG,
                        use_container_width=True,
                        hide_index=True,
                        key=streamlit_df_widget_key(f"cf_fib_{ticker}", _fib_df),
                        on_select="ignore",
                        selection_mode=[],
                    )
                _explain("What are Fibonacci levels?",
                    "After a big move, stocks tend to pull back to specific levels before continuing. The key levels are 38.2%, 50%, and 61.8%. "
                    "The 61.8% level is called the golden ratio. It is the most watched level by professional traders. "
                    "Why you care: set your put strikes near Fibonacci support. You collect cash AND you buy at a natural price floor.", "neutral")
                if st.checkbox("Gann Square of 9", key="exp_1"):
                    gl = TA.gann_sq9(price)
                    _gann_df = _df_price_levels(gl, price)
                    streamlit_show_dataframe(
                        _gann_df,
                        column_config=_PRICE_LEVEL_COLUMN_CONFIG,
                        use_container_width=True,
                        hide_index=True,
                        key=streamlit_df_widget_key(f"cf_gann_{ticker}", _gann_df),
                        on_select="ignore",
                        selection_mode=[],
                    )
                if st.checkbox("Gann Angles", key="exp_2"):
                    ang, sp = TA.gann_angles(df)
                    st.markdown(f"**Swing Low:** ${sp:.2f}")
                    for n_g, p_v in ang.items():
                        st.markdown(f"* **{n_g}** maps to ${p_v:.2f} ({(p_v / price - 1) * 100:+.1f}%)")
                if st.checkbox("Gann Time Cycles", key="exp_3"):
                    for cyc in TA.gann_time_cycles(df):
                        st.markdown(
                            f"* **{cyc['cycle']} bar cycle** lands {cyc['date'].strftime('%Y-%m-%d')} ({cyc['status']})"
                        )

            # ══════════════════════════════════════════════════════════════════
            #  SECTION 3 \u2014 QUANT DASHBOARD (two-column: metric + explanation)
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="quant-dashboard" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Quant Dashboard", "Every dial translated into English. Meaning first. Action second.",
                     tip_plain="Treat this like an aircraft panel. Strong green bars confirm edge. Thin readings mean throttle back. Confluence and Gold Zone still own the headline.")
            rv2 = TA.rsi2(df["Close"]).iloc[-1] if len(df) > 5 else 50
            adx_v, dip, din = TA.adx(df)
            cci_v = TA.cci(df).iloc[-1]
            st_l, st_d = TA.supertrend(df)
            _, kj, sa_ich, sb_ich, _ = TA.ichimoku(df)
            an = adx_v.iloc[-1] if not pd.isna(adx_v.iloc[-1]) else 0

            # RSI
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>RSI (14)</div><div class='mono' style='font-size:1.5rem;color:{'#ef4444' if rsi_v > 70 else ('#10b981' if rsi_v < 30 else '#e2e8f0')}'>{rsi_v:.1f}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>RSI 2 bar: {rv2:.1f}</div></div>", unsafe_allow_html=True)
            with ir:
                if rsi_v > 70:
                    _explain("RSI: Stock is Overheated", f"RSI is {rsi_v:.0f}. The stock ran up too fast. Think of a product flying off shelves after a viral review. Buyers are overpaying right now. This is the ideal time to sell Covered Calls and collect cash at peak excitement.", "bear")
                elif rsi_v < 30:
                    _explain("RSI: Stock is On Sale", f"RSI is {rsi_v:.0f}. Sellers have panicked. Think of a clearance sale that went too deep. This is your signal to sell Cash Secured Puts. You get paid cash today and you might buy shares at a bargain price.", "bull")
                else:
                    _explain("RSI: Stock is Resting", f"RSI is {rsi_v:.0f}. The stock is calm. Buyers are not panicking. Sellers are not panicking. This is the perfect zone to collect cash from selling options.", "neutral")

            # MACD
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>MACD</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if macd_bull else '#ef4444'}'>{'BULLISH' if macd_bull else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Hist: {h_v.iloc[-1]:.3f}</div></div>", unsafe_allow_html=True)
            with ir:
                if macd_bull:
                    _explain("MACD: Buyers Are Winning", "Recent momentum is stronger than the longer term average. Think of a store where this month's sales beat the quarterly average. Buyers are in charge. You can sell Covered Calls at higher strikes with more confidence.", "bull")
                else:
                    _explain("MACD: Sellers Are Winning", "Recent momentum dropped below the longer term average. Think of a store where this month's sales fell below the quarterly trend. Be more careful when picking your strike prices.", "bear")

            # ADX
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>ADX</div><div class='mono' style='font-size:1.5rem;color:{'#10b981' if an > 25 else '#f59e0b'}'>{an:.1f}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Plus DI {dip.iloc[-1]:.1f} · Minus DI {din.iloc[-1]:.1f}</div></div>", unsafe_allow_html=True)
            with ir:
                di_w = "Buyers via plus DI" if dip.iloc[-1] > din.iloc[-1] else "Sellers via minus DI"
                if an > 25:
                    _explain("ADX: Strong Trend Detected", f"ADX is {an:.0f}. That is above 25 which means a strong trend is happening. The winner right now is: {di_w}. Think of a business with a clear growth direction. Sell your options in the direction of the trend for the safest play.", "bull" if dip.iloc[-1] > din.iloc[-1] else "bear")
                else:
                    _explain("ADX: No Clear Trend", f"ADX is {an:.0f}. That is below 25 which means the market has no clear direction right now. Think of a business in a holding pattern. This is a good time for strategies that profit from sideways movement.", "neutral")

            # CCI + Supertrend row
            il, ir = st.columns([1, 2])
            stb = st_d.iloc[-1] == 1
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>CCI (20)</div><div class='mono' style='font-size:1.5rem;color:{'#ef4444' if not pd.isna(cci_v) and cci_v > 100 else ('#10b981' if not pd.isna(cci_v) and cci_v < -100 else '#e2e8f0')}'>{cci_v:.0f}</div></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='tc' style='text-align:center;margin-top:8px'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Supertrend</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if stb else '#ef4444'}'>{'BULLISH' if stb else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>${st_l.iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
            with ir:
                cci_txt = f"CCI is {cci_v:.0f}. " + (
                    "That is above positive 100. The stock is stretched versus its average. Great moment to lean on call sales. "
                    if not pd.isna(cci_v) and cci_v > 100
                    else (
                        "That is below negative 100. The stock washed out under its average. Sellers overdid it. Look at put sales for income. "
                        if not pd.isna(cci_v) and cci_v < -100
                        else "That is in the neutral pocket. No extreme edge to harvest yet. "
                    )
                )
                st_price = st_l.iloc[-1]
                st_txt = f"The Supertrend is your price floor. It is BULLISH at ${st_price:.2f}. As long as the stock stays above this green line, your shares are safe." if stb else f"The Supertrend is BEARISH at ${st_price:.2f}. It is acting as a falling ceiling above the price. The trend is down. Be defensive and protect your shares."
                _explain("CCI and Supertrend", cci_txt + st_txt, "bull" if stb else "bear")

            # Ichimoku + OBV row
            above_cloud = not pd.isna(sa_ich.iloc[-1]) and not pd.isna(sb_ich.iloc[-1]) and price > max(sa_ich.iloc[-1], sb_ich.iloc[-1])
            ou = obv_up
            il, ir = st.columns([1, 2])
            with il:
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Ichimoku</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if above_cloud else '#ef4444'}'>{'ABOVE CLOUD' if above_cloud else 'IN/BELOW'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Kijun: ${kj.iloc[-1]:.2f}</div></div>", unsafe_allow_html=True)
                st.markdown(f"<div class='tc' style='text-align:center;margin-top:8px'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>OBV</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if ou else '#ef4444'}'>{'RISING' if ou else 'FALLING'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>{'Accumulation' if ou else 'Distribution'}</div></div>", unsafe_allow_html=True)
            with ir:
                ich_txt = "The price is above the Ichimoku Cloud. The cloud acts as a thick safety net below the stock. When the price floats above it, the trend is strongly in your favor. Your shares are protected. " if above_cloud else "The price is inside or below the cloud. The trend is unclear right now. Think of it like driving through fog. Wait for visibility before you sell options aggressively. "
                obv_txt = "OBV is rising. Big institutional players are quietly buying up shares. Think of your biggest wholesale customers stocking up before a price increase. That is a bullish sign. " if ou else "OBV is falling. Big money is selling into rallies. Think of your best customers reducing their orders. The price may follow them down. Be careful. "
                _explain("Ichimoku Cloud and Volume Flow", ich_txt + obv_txt, "bull" if above_cloud and ou else ("bear" if not above_cloud and not ou else "neutral"))

            # Divergence Scanner
            st.markdown("#### Divergence Scanner")
            rsi_s = TA.rsi(df["Close"])
            divs_rsi = TA.detect_divergences(df["Close"], rsi_s)
            obv_divs = TA.detect_divergences(df["Close"], TA.obv(df))
            all_divs = [(d, "RSI") for d in divs_rsi] + [(d, "OBV") for d in obv_divs]
            if all_divs:
                _div_html = []
                for d, src in all_divs[-5:]:
                    _div_html.append(
                        f"<div class='ac'>{'🟢' if d['type'] == 'bullish' else '🔴'} <strong>{d['type'].title()} {src} divergence</strong> near ${d['price']:.2f} on {d['idx'].strftime('%Y-%m-%d')}</div>"
                    )
                st.markdown("\n".join(_div_html), unsafe_allow_html=True)
                _explain("What is a divergence?", "The price makes a new high or low but the indicator does not agree. Think of a company reporting record revenue but declining profits. The numbers do not match. That is an early warning that the trend might reverse soon.", "neutral")
            else:
                st.info("No divergences found. All indicators agree with the current trend.")

            # Volume Profile
            vp = TA.volume_profile(df)
            if not vp.empty:
                poc = vp.loc[vp["volume"].idxmax()]
                if not mini_mode:
                    vmax = vp["volume"].max()
                    fig_vp = go.Figure(
                        go.Bar(
                            x=vp["volume"],
                            y=vp["mid"],
                            orientation="h",
                            marker_color=[_PLOTLY_CASH_UP if v == vmax else _PLOTLY_BLUE for v in vp["volume"]],
                            opacity=0.72,
                            hovertemplate=(
                                "<b>Volume profile</b><br>"
                                "Price <b>$%{y:,.2f}</b><br>"
                                "Volume <b>%{x:,.0f}</b><extra></extra>"
                            ),
                        )
                    )
                    fig_vp.add_hline(
                        y=poc["mid"],
                        line_dash="solid",
                        line_color="rgba(245, 158, 11, 0.85)",
                        line_width=1.5,
                        annotation_text=f"POC ${poc['mid']:,.2f}",
                        annotation_font=dict(size=11, color="#fbbf24"),
                    )
                    fig_vp.update_layout(
                        template="plotly_dark",
                        paper_bgcolor=_PLOTLY_PAPER_BG,
                        plot_bgcolor=_PLOTLY_PLOT_BG,
                        font=_PLOTLY_FONT_MAIN,
                        height=300,
                        margin=dict(l=60, r=20, t=28, b=40),
                        hoverlabel=_chart_hoverlabel(),
                        title=dict(
                            text="Volume by price (horizontal)",
                            x=0,
                            xanchor="left",
                            font=dict(size=13, color="#e2e8f0", family="Inter, system-ui, sans-serif"),
                        ),
                    )
                    fig_vp.update_xaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=False,
                        title_text="Volume (shares)",
                        tickformat=",.0f",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    fig_vp.update_yaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=False,
                        title_text="Price",
                        tickprefix="$",
                        tickformat=",.2f",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    st.plotly_chart(fig_vp, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                else:
                    st.caption(f"Volume POC (mini mode): **${poc['mid']:.2f}**. Full profile chart stays parked while Turbo is on.")
                _explain("\U0001f9e0 Volume Profile", f"The Point of Control (POC) is ${poc['mid']:.2f}. This is the most traded price. Think of it as the price point where your store sees the most customers. The stock is pulled toward this price like a magnet. Use it to pick your option strike prices.", "neutral")

            # ══════════════════════════════════════════════════════════════════

    with dash_tab_cashflow:
            _cf_trading_mode_cf = st.session_state.get("_cf_scanner_mode", cfg.get("scanner_mode", "📈 Options Yield"))
            if _cf_trading_mode_cf != "📈 Options Yield":
                st.markdown('<div id="strategies" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                _section(
                    "Delta-One workspace",
                    f"Equity Radar hides premium-selling strikes for {_html_mod.escape(ticker)}. Use the desk below with your last **Scan Watchlist** run.",
                    tip_plain="Open **Risk, scanner & intel → Market Scanner** to refresh rows. Metrics reuse scanner output only.",
                )
                _bundle_cf = st.session_state.get("_cf_scanner_bundle")
                _rows_cf = _bundle_cf.get("results") if isinstance(_bundle_cf, dict) else None
                _render_equity_setup_desk(_rows_cf or [], "cf_equity_desk_cashflow", prefer_ticker=ticker)
            if _cf_trading_mode_cf == "📈 Options Yield":
                #  SECTION 4 \u2014 CASH-FLOW STRATEGIES
                # ══════════════════════════════════════════════════════════════════
                st.markdown('<div id="strategies" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                _cfs_subtitle = (
                    f"Concrete strikes for {ticker} at ${price:.2f}. Lift them straight into your ticket."
                    if opt_exps
                    else (
                        f"Spot ${price:.2f}. The options feed returned no expirations yet. Use Refresh during market hours, "
                        f"or mirror the desk rules in your broker (about 3% to 7% OTM, standard monthly cycle)."
                    )
                )
                _section(
                    "Cash Flow Strategies",
                    _cfs_subtitle,
                    tip_plain="Start with the optimal line the desk highlights. Covered calls need stock on hand. Cash secured puts monetize patience. Spreads are for when you want a hard loss ceiling.",
                )
                if opt_exps:
                    st.markdown(
                        f"<div class='tc'><div style='text-align:center'><span style='color:#64748b;font-size:.8rem'>ANALYZING</span><br>"
                        f"<span style='font-size:1.4rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(ticker)} @ ${price:.2f}</span></div></div>",
                        unsafe_allow_html=True,
                    )
                    sel_exp = st.selectbox("Expiration", opt_exps[:10], index=min(2, len(opt_exps) - 1), key="sel_exp")
                    dte = max(1, (datetime.strptime(sel_exp, "%Y-%m-%d") - datetime.now()).days)
                    try:
                        result_sel, _ = fetch_options(ticker, sel_exp)
                    except Exception as e:
                        st.warning(f"Could not load the option chain for expiration {sel_exp}. ({type(e).__name__})")
                        result_sel = (pd.DataFrame(), pd.DataFrame())
                    calls, puts = result_sel if isinstance(result_sel, (tuple, list)) and len(result_sel) == 2 else (pd.DataFrame(), pd.DataFrame())
                    calls = calls if isinstance(calls, pd.DataFrame) else pd.DataFrame()
                    puts = puts if isinstance(puts, pd.DataFrame) else pd.DataFrame()
                    opts_df = pd.DataFrame()
                    try:
                        _calls_t = calls.copy()
                        _puts_t = puts.copy()
                        if not _calls_t.empty:
                            _calls_t["type"] = "call"
                        if not _puts_t.empty:
                            _puts_t["type"] = "put"
                        opts_df = pd.concat([_calls_t, _puts_t], ignore_index=True)
                    except Exception:
                        opts_df = pd.DataFrame()
                    if not calls.empty or not puts.empty:
                        with st.expander("Full option chain — MC PoP % (every strike)", expanded=False):
                            try:
                                _chain_mc = build_chain_mc_dataframe(price, calls, puts, dte, rfr)
                                if _chain_mc is not None and not _chain_mc.empty:
                                    streamlit_show_dataframe(
                                        _chain_mc,
                                        use_container_width=True,
                                        hide_index=True,
                                        height=min(520, 36 + min(len(_chain_mc), 100) * 28),
                                        key=streamlit_df_widget_key(f"cf_opt_mc_{sel_exp}", _chain_mc),
                                        on_select="ignore",
                                        selection_mode=[],
                                        column_config={
                                            "Type": st.column_config.TextColumn("Type", width="small"),
                                            "Strike": st.column_config.NumberColumn("Strike", format="$%.2f"),
                                            "Bid": st.column_config.NumberColumn("Bid", format="$%.2f"),
                                            "Ask": st.column_config.NumberColumn("Ask", format="$%.2f"),
                                            "Mid": st.column_config.NumberColumn("Mid", format="$%.4f"),
                                            "IV %": st.column_config.NumberColumn("IV", format="%.2f%%"),
                                            "\u0398/\u0393": st.column_config.NumberColumn(
                                                "\u0398/\u0393",
                                                format="%.4f",
                                                help="Theta / Gamma (vectorized chain greeks).",
                                            ),
                                            "MC PoP %": st.column_config.NumberColumn(
                                                "MC PoP %",
                                                format="%.1f%%",
                                                help="10k antithetic simulations — v22.0 Predictive Analytics",
                                            ),
                                        },
                                    )
                                else:
                                    st.caption("No strikes with usable bid/ask for MC PoP in this snapshot.")
                            except Exception:
                                st.caption("MC PoP chain table unavailable for this expiration.")
                        _desk_poc = gold_zone_components.get("POC") if isinstance(gold_zone_components, dict) else None
                        _desk_hvn = gold_zone_components.get("HVN") if isinstance(gold_zone_components, dict) else None
                        s1, s2 = st.columns(2)
                        with s1:
                            st.markdown("#### Covered Calls")
                            cc = Opt.covered_calls(price, calls, dte, rfr, poc=_desk_poc, hvn_anchor=_desk_hvn)
                            if cc:
                                opt_cc = next((c for c in cc if c.get("optimal")), cc[0])
                                b = opt_cc; nc_s = 1
                                opt_html = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                                in_zone = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                                delta_color = "#10b981" if in_zone else "#f59e0b"
                                cc_mc_pop = b.get("mc_pop", None)
                                cc_mc_pop_txt = ""
                                if cc_mc_pop is not None:
                                    try:
                                        _v = float(cc_mc_pop)
                                        if math.isfinite(_v):
                                            cc_mc_pop_txt = f" | MC PoP: {_v:.1f}%"
                                    except (TypeError, ValueError):
                                        pass
                                st.markdown(f"<div class='sb'>{opt_html}<strong>SELL {nc_s}x ${b['strike']:.0f}C @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color}'>\u0394 {b['delta']:.2f}</strong>{cc_mc_pop_txt}<br>Premium: <strong style='color:#10b981'>${b['prem_100'] * nc_s:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Ann: {b['ann_yield']:.1f}% | OI: {b['oi']:,}</span>{_theta_gamma_desk_line(b.get('theta_gamma_ratio'))}</div>", unsafe_allow_html=True)
                                _cc_track_key = re.sub(
                                    r"[^a-zA-Z0-9_]",
                                    "_",
                                    f"cf_track_cc_{ticker}_{sel_exp}_{b['strike']}",
                                )[:110]
                                if st.button("Track Trade", key=_cc_track_key, help="Append this optimal covered-call line to the Sentinel Ledger (session only)."):
                                    _pin_e = st.session_state.get("_cf_opex_pin")
                                    _dist_pin_e = None
                                    try:
                                        if _pin_e is not None:
                                            _pf = float(_pin_e)
                                            if np.isfinite(_pf) and _pf > 0:
                                                _dist_pin_e = round((float(price) / _pf - 1.0) * 100.0, 2)
                                    except (TypeError, ValueError):
                                        pass
                                    _th_day_e = None
                                    try:
                                        _th_day_e = round(
                                            ledger_theta_desk_day(
                                                float(price),
                                                float(b["strike"]),
                                                int(dte),
                                                float(rfr),
                                                float(b.get("iv") or 30),
                                                "call",
                                                int(nc_s),
                                            ),
                                            4,
                                        )
                                    except Exception:
                                        pass
                                    st.session_state.setdefault("_cf_ledger", []).append(
                                        {
                                            "ticker": str(ticker).upper(),
                                            "strike": float(b["strike"]),
                                            "premium_100": float(b["prem_100"]),
                                            "entry_date": datetime.now().strftime("%Y-%m-%d"),
                                            "leg": "CC",
                                            "option_type": "call",
                                            "iv": float(b.get("iv") or 0),
                                            "expiry": str(sel_exp)[:10],
                                            "dte_at_entry": int(dte),
                                            "contracts": int(nc_s),
                                            "qs_at_entry": float(qs),
                                            "dist_pin_pct_at_entry": _dist_pin_e,
                                            "theta_desk_day_entry": _th_day_e,
                                        }
                                    )
                                    st.rerun()
                                if st.checkbox("All CC strikes", key="exp_5"):
                                    _cc_df = _options_scan_dataframe(cc, put_table=False)
                                    streamlit_show_dataframe(
                                        _cc_df,
                                        column_config=_options_scan_column_config(put_table=False),
                                        use_container_width=True,
                                        hide_index=True,
                                        key=streamlit_df_widget_key(f"cf_cc_{sel_exp}", _cc_df),
                                        on_select="ignore",
                                        selection_mode=[],
                                    )
                            else:
                                st.info("No covered call strikes met pricing/liquidity checks in this snapshot. Try a nearby expiry or refresh.")
                        with s2:
                            st.markdown("#### Cash Secured Puts")
                            csp = Opt.cash_secured_puts(price, puts, dte, rfr, poc=_desk_poc, hvn_anchor=_desk_hvn)
                            if csp:
                                opt_csp = next((c for c in csp if c.get("optimal")), csp[0])
                                b = opt_csp
                                opt_html_p = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                                in_zone_p = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                                delta_color_p = "#10b981" if in_zone_p else "#f59e0b"
                                csp_mc_pop = b.get("mc_pop", None)
                                csp_mc_pop_txt = ""
                                if csp_mc_pop is not None:
                                    try:
                                        _v = float(csp_mc_pop)
                                        if math.isfinite(_v):
                                            csp_mc_pop_txt = f" | MC PoP: {_v:.1f}%"
                                    except (TypeError, ValueError):
                                        pass
                                st.markdown(f"<div class='sb'>{opt_html_p}<strong>SELL 1x ${b['strike']:.0f}P @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color_p}'>\u0394 {b['delta']:.2f}</strong>{csp_mc_pop_txt}<br>Premium: <strong style='color:#10b981'>${b['prem_100']:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Eff buy: ${b['eff_buy']:.2f} | OI: {b['oi']:,}</span>{_theta_gamma_desk_line(b.get('theta_gamma_ratio'))}</div>", unsafe_allow_html=True)
                                _csp_track_key = re.sub(
                                    r"[^a-zA-Z0-9_]",
                                    "_",
                                    f"cf_track_csp_{ticker}_{sel_exp}_{b['strike']}",
                                )[:110]
                                if st.button("Track Trade", key=_csp_track_key, help="Append this optimal cash-secured put to the Sentinel Ledger (session only)."):
                                    _pin_e2 = st.session_state.get("_cf_opex_pin")
                                    _dist_pin_e2 = None
                                    try:
                                        if _pin_e2 is not None:
                                            _pf2 = float(_pin_e2)
                                            if np.isfinite(_pf2) and _pf2 > 0:
                                                _dist_pin_e2 = round((float(price) / _pf2 - 1.0) * 100.0, 2)
                                    except (TypeError, ValueError):
                                        pass
                                    _th_day_e2 = None
                                    try:
                                        _th_day_e2 = round(
                                            ledger_theta_desk_day(
                                                float(price),
                                                float(b["strike"]),
                                                int(dte),
                                                float(rfr),
                                                float(b.get("iv") or 30),
                                                "put",
                                                1,
                                            ),
                                            4,
                                        )
                                    except Exception:
                                        pass
                                    st.session_state.setdefault("_cf_ledger", []).append(
                                        {
                                            "ticker": str(ticker).upper(),
                                            "strike": float(b["strike"]),
                                            "premium_100": float(b["prem_100"]),
                                            "entry_date": datetime.now().strftime("%Y-%m-%d"),
                                            "leg": "CSP",
                                            "option_type": "put",
                                            "iv": float(b.get("iv") or 0),
                                            "expiry": str(sel_exp)[:10],
                                            "dte_at_entry": int(dte),
                                            "contracts": 1,
                                            "qs_at_entry": float(qs),
                                            "dist_pin_pct_at_entry": _dist_pin_e2,
                                            "theta_desk_day_entry": _th_day_e2,
                                        }
                                    )
                                    st.rerun()
                                if st.checkbox("All CSP strikes", key="exp_6"):
                                    _csp_df = _options_scan_dataframe(csp, put_table=True)
                                    streamlit_show_dataframe(
                                        _csp_df,
                                        column_config=_options_scan_column_config(put_table=True),
                                        use_container_width=True,
                                        hide_index=True,
                                        key=streamlit_df_widget_key(f"cf_csp_{sel_exp}", _csp_df),
                                        on_select="ignore",
                                        selection_mode=[],
                                    )
                            else:
                                st.info("No put strikes met pricing/liquidity checks in this snapshot. Try a nearby expiry or refresh.")

                        _explain("\U0001f9e0 What are Delta and Theta?",
                            "<strong>Delta is your win probability.</strong> A Delta of 0.16 means you have an 84 percent chance to keep all the cash and keep your shares. Lower Delta means safer. "
                            "<strong>Theta is your daily paycheck.</strong> Every day that passes, the option loses value. That lost value goes straight into your pocket. Time is literally paying you. "
                            "<strong>OI is how busy the market is.</strong> Higher OI means more traders are active. That means you get better prices when you sell. We filter out anything below 100 OI to protect you.", "neutral")

                        with st.expander("📈 Volatility Skew Surface (Tail Risk)", expanded=False):
                            st.caption("Visualizing the 'Smile': Higher IV on puts indicates the market is pricing in heavy downside fear.")
                            try:
                                regime_label, regime_color, regime_desc = calc_skew_regime(opts_df, price)
                                st.markdown(
                                    f"""
                                    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px; padding: 10px; background: rgba(15, 23, 42, 0.6); border: 1px solid #334155; border-radius: 8px;">
                                        <span style="background: {regime_color}; color: #ffffff; padding: 4px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.05em;">
                                            {regime_label}
                                        </span>
                                        <span style="color: #cbd5e1; font-size: 0.85rem;">{regime_desc}</span>
                                    </div>
                                    """,
                                    unsafe_allow_html=True,
                                )
                                skew_fig = build_skew_chart(opts_df, price)
                                if skew_fig:
                                    st.plotly_chart(skew_fig, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                                else:
                                    st.warning("Insufficient liquidity to plot the volatility skew.")
                            except Exception:
                                pass

                        st.divider()
                        sp1, sp2 = st.columns(2)
                        with sp1:
                            st.markdown("#### Bull Put Spread")
                            ps = Opt.credit_spreads(price, puts, "put_credit")
                            if ps:
                                b = ps[0]
                                st.markdown(f"<div class='sb'><strong>${b['short']:.0f}P/${b['long']:.0f}P</strong> | Cr: ${b['credit_100']:.0f} | ML: ${b['max_loss']:.0f} | POP: {b['pop']:.0f}%</div>", unsafe_allow_html=True)
                        with sp2:
                            st.markdown("#### Bear Call Spread")
                            cs = Opt.credit_spreads(price, calls, "call_credit")
                            if cs:
                                b = cs[0]
                                st.markdown(f"<div class='sr'><strong>${b['short']:.0f}C/${b['long']:.0f}C</strong> | Cr: ${b['credit_100']:.0f} | ML: ${b['max_loss']:.0f} | POP: {b['pop']:.0f}%</div>", unsafe_allow_html=True)

                        _explain("\U0001f9e0 What is a credit spread?",
                            "A credit spread is like selling insurance with a cap on your worst case. You sell one option and collect cash. Then you buy a cheaper one further away to limit your risk. "
                            "<strong>POP</strong> is your Probability of Profit. <strong>ML</strong> is your Max Loss, the absolute worst case. <strong>Cr</strong> is the cash you receive today. "
                            "A 75% POP means you win roughly 3 out of every 4 times you make this trade.", "neutral")

                        if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
                            st.divider()
                            if latest_d["type"] == "blue":
                                st.markdown(f"""<div class='diamond-blue'>
                                    <div style='font-size:1rem;font-weight:700;margin-bottom:8px'>🔷 BLUE DIAMOND AUTO SUGGESTIONS</div>
                                    <div style='color:#94a3b8;font-size:.85rem;margin-bottom:10px'>
                                        A Blue Diamond fired {(df.index[-1] - latest_d['date']).days} day(s) ago at ${latest_d['price']:.2f} with composite score {latest_d['score']}.
                                        Historical probability of profit: <strong style='color:#10b981'>{d_wr:.0f}%</strong> ({d_n} signals backtested).
                                    </div>
                                    <div style='color:#e2e8f0;font-size:.9rem;line-height:1.8'>""", unsafe_allow_html=True)
                                suggestions = []
                                if cc:
                                    b = cc[0]
                                    suggestions.append(f"<strong>Covered Call:</strong> Sell {nc}x ${b['strike']:.0f}C exp {sel_exp} @ ${b['mid']:.2f} (collect ${b['prem_100']*nc:,.0f})")
                                if csp:
                                    b = csp[0]
                                    suggestions.append(f"<strong>Cash Secured Put:</strong> Sell 1x ${b['strike']:.0f}P exp {sel_exp} @ ${b['mid']:.2f} (collect ${b['prem_100']:,.0f})")
                                if ps:
                                    b = ps[0]
                                    suggestions.append(f"<strong>Bull Put Spread:</strong> ${b['short']:.0f}/${b['long']:.0f}P exp {sel_exp} credit ${b['credit_100']:,.0f} POP {b['pop']:.0f}%")
                                for sug in suggestions:
                                    st.markdown(f"<div style='margin:4px 0'>• {sug}</div>", unsafe_allow_html=True)
                                st.markdown("</div></div>", unsafe_allow_html=True)
                                _explain("Why these trades on a Blue Diamond?",
                                    f"The Blue Diamond means {latest_d['score']} out of 9 confluence factors aligned bullish. "
                                    "Historically, similar setups have a strong track record. "
                                    "Covered Calls collect premium while riding the trend. "
                                    "Cash Secured Puts let you buy the dip if it comes. "
                                    "Bull Put Spreads give you bullish exposure with capped risk. "
                                    "Pick the strategy that matches your capital and conviction.", "bull")
                            else:
                                st.markdown(f"""<div class='diamond-pink'>
                                    <div style='font-size:1rem;font-weight:700;margin-bottom:8px'>💎 PINK DIAMOND: DEFENSIVE POSTURE</div>
                                    <div style='color:#94a3b8;font-size:.85rem;margin-bottom:10px'>
                                        A Pink Diamond fired {(df.index[-1] - latest_d['date']).days} day(s) ago at ${latest_d['price']:.2f}.
                                        Confluence composite dropped to {latest_d['score']}. Momentum is exhausting.
                                    </div>
                                    <div style='color:#e2e8f0;font-size:.9rem;line-height:1.8'>""", unsafe_allow_html=True)
                                if cs:
                                    b = cs[0]
                                    st.markdown(f"<div style='margin:4px 0'>• <strong>Bear Call Spread:</strong> ${b['short']:.0f}/${b['long']:.0f}C credit ${b['credit_100']:,.0f} POP {b['pop']:.0f}%</div>", unsafe_allow_html=True)
                                if cc:
                                    b = cc[0]
                                    st.markdown(f"<div style='margin:4px 0'>• <strong>Aggressive Covered Call:</strong> Sell ATM or near-ATM ${b['strike']:.0f}C to maximize premium capture</div>", unsafe_allow_html=True)
                                st.markdown(f"<div style='margin:4px 0'>• <strong>Tighten Stops:</strong> If below Gold Zone ${gold_zone_price:.2f}, consider reducing exposure</div>", unsafe_allow_html=True)
                                st.markdown("</div></div>", unsafe_allow_html=True)
                                _explain("Why go defensive on a Pink Diamond?",
                                    "The Pink Diamond means bullish momentum has exhausted or confluence collapsed. "
                                    "This does not mean crash. It means the easy money in the current leg is done. "
                                    "Bear Call Spreads profit from a pullback. Aggressive CCs lock in premium at the top. "
                                    "Wait for the next Blue Diamond before entering again aggressively.", "bear")

                        # Greeks, EV & Vol Skew
                        st.divider()
                        st.markdown("#### Greeks, Expected Value & Volatility Skew")
                        gk1, gk2, gk3 = st.columns(3)
                        with gk1:
                            if cc:
                                b0 = cc[0]; iv_d = b0["iv"] / 100 if b0["iv"] > 0 else 0.5; T_y = dte / 365
                                gr = bs_greeks(price, b0["strike"], T_y, rfr, iv_d, "call")
                                fv = bs_price(price, b0["strike"], T_y, rfr, iv_d, "call")
                                edge = b0["mid"] - fv
                                edge_c = "#10b981" if edge > 0 else "#ef4444"
                                st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>TOP CC GREEKS (r={rfr * 100:.2f}%)</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>Delta: <strong style='color:#e2e8f0'>{gr['delta']:.3f}</strong><br>Theta: <strong style='color:#10b981'>${gr['theta']:.3f}/day</strong><br>Vega: <strong style='color:#e2e8f0'>${gr['vega']:.3f}/1%IV</strong><br>Fair: <strong style='color:#e2e8f0'>${fv:.2f}</strong> | Edge: <strong style='color:{edge_c}'>${edge:+.2f}</strong></div></div>", unsafe_allow_html=True)
                            else:
                                st.markdown("<div class='tc'><span style='color:#64748b'>No CC data for Greeks</span></div>", unsafe_allow_html=True)
                        with gk2:
                            ev_lines = []
                            if cc:
                                b0 = cc[0]; pop_cc = min(85, max(50, 100 - b0["otm_pct"] * 5))
                                ev_cc = calc_ev(b0["prem_100"], b0["prem_100"] * 3, pop_cc)
                                ec = "#10b981" if ev_cc > 0 else "#ef4444"
                                ev_lines.append(f"CC ${b0['strike']:.0f}: <strong style='color:{ec}'>${ev_cc:+.0f}</strong> (POP ~{pop_cc:.0f}%)")
                            if ps:
                                b0 = ps[0]; ev_ps = calc_ev(b0["credit_100"], b0["max_loss"], b0["pop"])
                                ec = "#10b981" if ev_ps > 0 else "#ef4444"
                                ev_lines.append(f"Put Spread: <strong style='color:{ec}'>${ev_ps:+.0f}</strong> (POP {b0['pop']:.0f}%)")
                            joined = "<br>".join(ev_lines) if ev_lines else "N/A"
                            st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>EXPECTED VALUE</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>{joined}</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>Positive means edge. Negative means walk away.</div></div>", unsafe_allow_html=True)
                        with gk3:
                            skew, p_iv, c_iv = calc_vol_skew(price, calls, puts)
                            if skew is not None:
                                sc = "#ef4444" if skew > 10 else ("#f59e0b" if skew > 5 else "#10b981")
                                sm = "Institutions hedging heavily" if skew > 10 else ("Mild put skew" if skew > 5 else "Balanced")
                                st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>VOL SKEW</div><div class='mono' style='font-size:1.3rem;color:{sc};margin-top:8px'>{skew:+.1f}%</div><div style='color:#94a3b8;font-size:.85rem;margin-top:4px'>Put IV: {p_iv:.1f}% | Call IV: {c_iv:.1f}%</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>{sm}</div></div>", unsafe_allow_html=True)
                            else:
                                st.markdown("<div class='tc'><div style='font-size:.7rem;color:#64748b'>VOL SKEW</div><div style='color:#94a3b8;margin-top:8px'>Insufficient IV data</div></div>", unsafe_allow_html=True)

                        _explain("\U0001f9e0 What do these numbers mean for me?",
                            "<strong>Expected Value (EV)</strong> is your long term profit margin. Think of it like calculating net profit per product after returns. Positive EV means you have a real edge. Negative means avoid the trade. "
                            "<strong>Volatility Skew</strong> tells you if big institutions are buying crash insurance. When put prices are much higher than call prices, fear is elevated. You get fatter premiums but the risk is also higher. "
                            "<strong>Edge</strong> is the difference between the market price and the mathematically fair price. Positive Edge means the market is overpaying you. That is exactly what you want.", "neutral")
                    else:
                        st.warning(
                            "This expiration returned an empty chain from the feed after walking nearby dates. "
                            "Pick another expiry or retry when the options pit is live."
                        )
                else:
                    st.markdown(
                        f"<div class='tc'><div style='text-align:center'><span style='color:#f59e0b;font-size:.75rem;font-weight:700;letter-spacing:.12em'>OPTIONS FEED</span><br>"
                        f"<span style='font-size:1.25rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(ticker)} @ ${price:.2f}</span>"
                        f"<br><span style='color:#94a3b8;font-size:.82rem'>No expirations returned. Not necessarily illiquid; often a data gap.</span></div></div>",
                        unsafe_allow_html=True,
                    )
                    st.info(
                        "Yahoo Finance sometimes omits option chains off-hours, under load, or on Streamlit Cloud. "
                        "Use **Refresh** to bust the cache and pull again. If it persists, open your broker’s chain for the same symbol."
                    )
                    if st.button("Refresh options data", key="retry_opts_chain", help="Clears cached option expirations and reloads"):
                        list_option_expiration_dates.clear()
                        fetch_options.clear()
                        st.rerun()

                # ══════════════════════════════════════════════════════════════════

    with dash_tab_intel:
            #  SECTION 5 \u2014 PSYCHOLOGY & RISK MANAGEMENT
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="risk" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Psychology and Risk Management", "Sentiment, sizing, guardrails. The stuff that keeps pros solvent.",
                     tip_plain="Fear and Greed shows how the crowd is priced. Kelly and ATR frame responsible size. When stories disagree, shrink the bet and wait for a cleaner tape.")
            p1, p2 = st.columns(2)
            with p1:
                gc = "#10b981" if fg < 30 else ("#f59e0b" if fg < 60 else "#ef4444")
                st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>FEAR & GREED</div><div style='font-size:3.5rem;font-weight:800;color:{gc};margin:12px 0;font-family:JetBrains Mono,monospace'>{fg:.0f}</div><div style='font-size:1.1rem;color:{gc}'>{fg_emoji} {fg_label}</div><div style='color:#94a3b8;margin-top:8px;font-size:.85rem'>{fg_advice}</div></div>", unsafe_allow_html=True)
                _explain("Why sentiment matters",
                    "Fear and Greed is like reading the room before you set your prices. "
                    "<strong style='color:#10b981'>High fear (low score)</strong>: Customers are panicking. They will pay you extra for protection. Sell options aggressively and collect fat premiums. "
                    "<strong style='color:#ef4444'>High greed (high score)</strong>: Everyone is euphoric. Premiums get thinner and the risk of losing your shares goes up. Be very selective.",
                    "bull" if fg < 40 else ("bear" if fg > 60 else "neutral"))
                st.markdown("#### Macro Environment")
                for k, v in macro.items():
                    dc = "#10b981" if v["chg"] >= 0 else "#ef4444"
                    st.markdown(f"<div style='display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1e293b'><span style='color:#94a3b8'>{k}</span><span class='mono' style='color:#e2e8f0'>{v['price']:.2f} <span style='color:{dc}'>{v['chg']:+.2f}%</span></span></div>", unsafe_allow_html=True)
            with p2:
                mrt = REF_NOTIONAL * RISK_PCT_EXAMPLE / 100
                st.markdown(
                    f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>EXAMPLE MAX RISK/TRADE</div>"
                    f"<div class='mono' style='font-size:1.3rem;color:#e2e8f0'>${mrt:,.0f}</div>"
                    f"<div style='font-size:.65rem;color:#64748b;margin-top:6px'>{RISK_PCT_EXAMPLE:.0f}% of ${REF_NOTIONAL:,.0f} reference (illustrative)</div></div>",
                    unsafe_allow_html=True,
                )
                atr_v = TA.atr(df).iloc[-1]
                if pd.isna(atr_v) or atr_v <= 0:
                    atr_v = price * .03
                sh_atr = int(mrt / (atr_v * 2)) if atr_v > 0 else 0
                st.markdown(f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>ATR SIZING</div><div style='color:#94a3b8;font-size:.85rem;margin-top:8px'>ATR: ${atr_v:.2f} | Max shares: {sh_atr} | Contracts: {sh_atr // 100}</div></div>", unsafe_allow_html=True)
                _explain("Position sizing in plain English",
                    f"ATR is ${atr_v:.2f}. That is how much this stock moves on an average day. Think of it as the normal daily price swing. "
                    f"Using an illustrative {RISK_PCT_EXAMPLE:.0f}% risk budget on a ${REF_NOTIONAL:,.0f} reference account (${mrt:,.0f} max loss per trade), "
                    f"you could size up to about {sh_atr} shares or {max(0, sh_atr // 100)} option contracts. Scale to your own account and rules.", "neutral")

                # Kelly Criterion: mathematically optimal allocation
                k_full, k_half = 0.0, 0.0
                k_source = ""
                daily_ret = df["Close"].pct_change().dropna()
                exp_ret = float(daily_ret.mean() * 252) if len(daily_ret) > 0 else 0.0
                ret_var = float(daily_ret.var() * 252) if len(daily_ret) > 1 else 0.0
                kelly_overlap = 0.0
                kelly_corr_haircut = 1.0
                try:
                    if not _risk_closes_df.empty and len(_risk_closes_df.columns) >= 2:
                        risk_corr = PortfolioRisk.build_correlation_matrix(_risk_closes_df)
                        kelly_overlap = PortfolioRisk.get_overlap_score(risk_corr, ticker)
                        kelly_corr_haircut = PortfolioRisk.calc_kelly_haircut(kelly_overlap)
                except Exception:
                    kelly_overlap = 0.0
                    kelly_corr_haircut = 1.0
                kelly_effective_haircut = float(kelly_corr_haircut) * float(_simple_corr_mult)
                _k_mc = None
                if bluf_cc:
                    try:
                        _k_mc = float(bluf_cc["mc_pop"]) if bluf_cc.get("mc_pop") is not None else None
                    except (TypeError, ValueError):
                        _k_mc = None
                elif bluf_csp:
                    try:
                        _k_mc = float(bluf_csp["mc_pop"]) if bluf_csp.get("mc_pop") is not None else None
                    except (TypeError, ValueError):
                        _k_mc = None
                if bluf_cc:
                    k_pop = min(85, max(50, 100 - bluf_cc["otm_pct"] * 5))
                    k_win = bluf_cc["prem_100"]
                    k_loss = k_win * 3
                    k_full, k_half = kelly_criterion(
                        k_pop, k_win, k_loss,
                        use_quant=use_quant_models,
                        expected_return=exp_ret,
                        variance=ret_var,
                        correlation_haircut=kelly_effective_haircut,
                        avg_mc_pop=_k_mc,
                    )
                    k_source = f"CC ${bluf_cc['strike']:.0f}"
                elif bluf_csp:
                    k_pop = min(85, max(50, 100 - bluf_csp["otm_pct"] * 5))
                    k_win = bluf_csp["prem_100"]
                    k_loss = bluf_csp["strike"] * 100 - k_win
                    k_full, k_half = kelly_criterion(
                        k_pop, k_win, k_loss,
                        use_quant=use_quant_models,
                        expected_return=exp_ret,
                        variance=ret_var,
                        correlation_haircut=kelly_effective_haircut,
                        avg_mc_pop=_k_mc,
                    )
                    k_source = f"CSP ${bluf_csp['strike']:.0f}"
                if k_half > 0:
                    k_cap = KELLY_DISPLAY_CAP_PCT
                    k_show = min(k_half, k_cap)
                    k_dollars = REF_NOTIONAL * k_show / 100
                    capped_note = (
                        f" Half Kelly math landed at {k_half:.1f}%; <strong>we cap the headline at {k_cap:.0f}%</strong> for portfolio heat. Never treat Kelly as a target allocation."
                        if k_half > k_cap
                        else ""
                    )
                    kc = "#10b981" if k_show <= RISK_PCT_EXAMPLE * 2 else "#f59e0b"
                    st.markdown(
                        f"<div class='tc'><div style='font-size:.75rem;color:#64748b'>KELLY HALF MODE · UI CAP</div>"
                        f"<div class='mono' style='font-size:1.3rem;color:{kc}'>{k_show:.1f}% = ${k_dollars:,.0f}</div>"
                        f"<div style='font-size:.7rem;color:#64748b;margin-top:4px'>Raw half Kelly {k_half:.1f}% · full Kelly {k_full:.1f}% · {k_source}. "
                        f"Corr overlap {kelly_overlap:.2f} · overlap haircut x{kelly_corr_haircut:.2f} · simple corr x{_simple_corr_mult:.2f}. Display max {k_cap:.0f}% for risk hygiene.{capped_note}</div></div>",
                        unsafe_allow_html=True)
                    _explain("Kelly Criterion in plain English",
                        f"The Kelly formula can suggest large fractions; here we show <strong>Half Kelly</strong> then <strong>cap the headline at {k_cap:.0f}%</strong> "
                        f"so the desk view stays conservative (raw half-Kelly was {k_half:.1f}%). "
                        f"On a <strong>${REF_NOTIONAL:,.0f}</strong> illustrative reference, the capped line is <strong>${k_dollars:,.0f}</strong>. "
                        "Scale to your own capital; Kelly is a theoretical optimum, not an order size.", "neutral")
                else:
                    st.markdown("<div class='tc'><div style='font-size:.75rem;color:#64748b'>KELLY CRITERION</div>"
                        "<div style='color:#94a3b8;font-size:.85rem;margin-top:6px'>Not enough data yet. No liquid option strikes available to calculate your optimal bet size.</div></div>",
                        unsafe_allow_html=True)

                st.markdown("#### Active Alerts")
                if al:
                    for a in al:
                        ic = "\U0001f7e2" if a["t"] == "bullish" else ("\U0001f534" if a["t"] == "bearish" else "\U0001f7e1")
                        st.markdown(f"<div class='ac'>{ic} [{a['p']}] {a['m']}</div>", unsafe_allow_html=True)
                else:
                    st.info("No alerts.")

            # ══════════════════════════════════════════════════════════════════
            #  SECTION 6 \u2014 PREMIUM SIMULATOR
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="simulator" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Premium Simulator", "Replay a year of covered calls with your assumptions before you commit capital.",
                     tip_plain="Dial OTM, hold time, and IV multiplier. Hunt for settings that still look sane in both calm and chaotic tapes.")
            st.warning(
                "Premiums here are modeled from historical volatility. They are illustrative, not a promise. Treat the run as a dress rehearsal; live fills will differ."
            )
            bc1, bc2, bc3, bc4 = st.columns(4)
            bt_otm = bc1.slider("OTM%", 2, 15, 5, key="sim_otm") / 100
            bt_hold = bc2.slider("Hold (d)", 7, 45, 30, key="sim_hold")
            bt_per = bc3.selectbox("Period", ["6mo", "1y"], index=1, key="sim_period")
            bt_iv = bc4.slider("IV Mult", .5, 2.0, 1.0, .1, key="sim_iv")
            br = run_cc_sim_cached(ticker, bt_per, bt_otm, bt_hold, bt_iv)
            if not br.empty:
                tp = br["premium"].sum() * 1
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Trades", len(br))
                m2.metric("Win Rate", f"{(br['profit'] > 0).mean() * 100:.0f}%")
                m3.metric("Avg Ret", f"{br['ret_pct'].mean():.1f}%")
                m4.metric("Est Premium", f"${tp:,.0f}")
                _cum = br["ret_pct"].cumsum().astype(float)
                if not mini_mode:
                    fig_b = go.Figure()
                    _colors = [_PLOTLY_CASH_UP if (i == 0 or _cum.iloc[i] >= _cum.iloc[i - 1]) else _PLOTLY_CASH_DOWN for i in range(len(_cum))]
                    fig_b.add_trace(
                        go.Scatter(
                            x=br["entry_date"],
                            y=_cum,
                            mode="lines+markers",
                            line=dict(color=_PLOTLY_CASH_UP, width=2.2),
                            marker=dict(size=6, color=_colors, line=dict(width=0)),
                            fill="tozeroy",
                            fillcolor="rgba(52, 211, 153, 0.12)",
                            name="Cumulative return",
                            hovertemplate=(
                                "<b>Covered-call sim</b><br>"
                                "Entry %{x|%Y-%m-%d}<br>"
                                "Cumulative <b>%{y:+.2f}%</b><extra></extra>"
                            ),
                        )
                    )
                    fig_b.update_layout(
                        template="plotly_dark",
                        paper_bgcolor=_PLOTLY_PAPER_BG,
                        plot_bgcolor=_PLOTLY_PLOT_BG,
                        font=_PLOTLY_FONT_MAIN,
                        height=300,
                        margin=dict(l=48, r=20, t=36, b=44),
                        hoverlabel=_chart_hoverlabel(),
                        title=dict(
                            text="Modeled cumulative return (% of premium stack)",
                            x=0,
                            xanchor="left",
                            font=dict(size=13, color="#e2e8f0", family="Inter, system-ui, sans-serif"),
                        ),
                        showlegend=False,
                    )
                    fig_b.update_xaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=False,
                        title_text="Trade entry",
                        tickformat="%Y-%m-%d",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    fig_b.update_yaxes(
                        showgrid=True,
                        gridcolor=_PLOTLY_GRID,
                        gridwidth=1,
                        zeroline=True,
                        zerolinecolor="rgba(128,128,128,0.25)",
                        title_text="Cumulative return (%)",
                        ticksuffix="%",
                        tickformat=".1f",
                        **_PLOTLY_AXIS_TITLE,
                    )
                    st.plotly_chart(fig_b, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                else:
                    st.caption(
                        f"Mini mode parks the cumulative return chart. Modeled cumulative return landed at **{_cum.iloc[-1]:.1f}%** across {len(br)} trades."
                    )
                wr = (br["profit"] > 0).mean() * 100
                _explain("\U0001f9e0 What does this backtest tell me?",
                    f"Over {len(br)} simulated trades, selling {bt_otm * 100:.0f}% out of the money covered calls every {bt_hold} days would have made roughly <strong>${tp:,.0f}</strong> in premium cash. "
                    f"The win rate was {wr:.0f}%. That means most of your options expired worthless and you kept all the cash. "
                    "Think of this as reviewing last year's sales numbers before planning this year's budget. It is your proof of concept.",
                    "bull" if wr > 60 else "neutral")
            else:
                st.info(
                    "Not enough daily history for this symbol and settings to run the covered-call sweep. "
                    "Try a longer period, a shorter hold window, or confirm the ticker has a full options tape."
                )

            # ══════════════════════════════════════════════════════════════════
            # SECTION 7: MARKET SCANNER (multi-ticker diamond and confluence scan)
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="scanner" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("🔎 Market Scanner", "One pass across the list for Diamonds, confluence stacks, and Gold Zone distance.",
                     tip_plain="Sort mentally by confluence, then hunt for a live Blue Diamond. If nothing clears the bar, flat is a position.")

            watchlist_tickers = [t.strip().upper() for t in scanner_watchlist.split(",") if t.strip()]
            if watchlist_tickers:
                if st.button("Scan Watchlist", key="run_scanner"):
                    closes_map = {}
                    for tkr in watchlist_tickers:
                        try:
                            cdf = fetch_stock(tkr, "1y", "1d")
                            if cdf is not None and not cdf.empty and "Close" in cdf.columns:
                                closes_map[tkr] = pd.to_numeric(cdf["Close"], errors="coerce")
                        except Exception:
                            pass
                    closes_df = pd.DataFrame(closes_map).dropna(how="all")
                    log_returns_df = TA.ffd_returns_from_closes(closes_df, d=0.4)
                    if log_returns_df.empty:
                        log_returns_df = np.log(closes_df / closes_df.shift(1)).dropna()
                    corr_matrix = watchlist_correlation_matrix_cached(closes_df)
                    if corr_matrix is None:
                        corr_matrix = PortfolioRisk.build_correlation_matrix(closes_df)
                    overlap_map = {tkr: PortfolioRisk.get_overlap_score(corr_matrix, tkr) for tkr in watchlist_tickers}
                    haircut_map = {tkr: PortfolioRisk.calc_kelly_haircut(overlap_map.get(tkr, 0.0)) for tkr in watchlist_tickers}
                    corr_fig = build_correlation_heatmap(corr_matrix)
                    if corr_fig is not None:
                        with st.expander("🕸️ Dynamic Correlation Matrix", expanded=False):
                            st.plotly_chart(corr_fig, use_container_width=True, config=_PLOTLY_UI_CONFIG)

                    spy_df = None
                    try:
                        spy_df = fetch_stock("SPY", "1y", "1d")
                    except Exception:
                        pass

                    scanner_results = []
                    n_scan = len(watchlist_tickers)
                    scan_progress = st.progress(0)
                    scan_failed = []
                    peer_blues = set()
                    for idx, tkr in enumerate(watchlist_tickers):
                        scan_progress.progress((idx + 1) / n_scan, text=f"Scanning {tkr}… ({idx + 1}/{n_scan})")
                        _simp = Opt._simple_corr_haircut(watchlist_tickers, tkr, log_returns_df)
                        _comb = float(haircut_map.get(tkr, 1.0)) * float(_simp)
                        try:
                            overlap = overlap_map.get(tkr, 0.0)
                            haircut = haircut_map.get(tkr, 1.0)
                            result = scan_single_ticker(
                                tkr,
                                _comb,
                                cluster_peers=frozenset(peer_blues),
                                corr_matrix=corr_matrix,
                                spy_df=spy_df,
                            )
                            if result:
                                result["overlap"] = overlap
                                result["haircut"] = haircut
                                result["risk_multiplier"] = float(
                                    Opt._simple_corr_haircut(watchlist_tickers, tkr, log_returns_df)
                                )
                                result["Adj. Kelly %"] = float(result.get("kelly_half", 0.0))
                                scanner_results.append(result)
                                if "BLUE" in str(result.get("d_status", "")):
                                    peer_blues.add(tkr)
                        except Exception as e:
                            scan_failed.append((tkr, type(e).__name__))
                    scan_progress.empty()
                    st.session_state["_cf_scanner_bundle"] = {
                        "results": list(scanner_results),
                        "failed": list(scan_failed),
                        "watchlist_tickers": list(watchlist_tickers),
                        "log_returns_df": log_returns_df,
                    }

                _scan_bundle = st.session_state.get("_cf_scanner_bundle")
                if _scan_bundle:
                    _scan_failed = _scan_bundle.get("failed") or []
                    if _scan_failed:
                        failed_line = ", ".join(f"{_html_mod.escape(t)} ({err})" for t, err in _scan_failed[:12])
                        more = f" (+{len(_scan_failed) - 12} more)" if len(_scan_failed) > 12 else ""
                        st.warning(f"Some symbols could not be scanned: {failed_line}{more}")

                    scanner_results = list(_scan_bundle.get("results") or [])
                    watchlist_tickers_scn = _scan_bundle.get("watchlist_tickers") or watchlist_tickers
                    log_returns_df = _scan_bundle.get("log_returns_df")
                    if log_returns_df is None:
                        log_returns_df = pd.DataFrame()

                    if scanner_results:
                        if scanner_sort_mode == "Highest confluence first":
                            scanner_results.sort(key=lambda x: x["cp_score"], reverse=True)
                        else:
                            order = {t: i for i, t in enumerate(watchlist_tickers_scn)}
                            scanner_results.sort(key=lambda x: order.get(x["ticker"], 10_000))

                        def _render_scanner_options_data_table():
                            scanner_df = pd.DataFrame(
                                [
                                    {
                                        "Ticker": r["ticker"],
                                        "Price": float(r["price"]),
                                        "Change %": float(r["chg_pct"]),
                                        "QE Score": float(r["qs"]),
                                        "Adj. Kelly %": float(r.get("Adj. Kelly %", 0.0)),
                                        "Confluence": int(r["cp_score"]),
                                        "Diamond": r["d_status"],
                                        "PoP": (
                                            f"{float(r.get('diamond_pop', 0)):.0f}%"
                                            if int(r.get("diamond_n") or 0) > 0
                                            else "—"
                                        ),
                                        "EM Safety": r.get("EM Safety", "—"),
                                        "GEX Regime": r.get("GEX Regime", "—"),
                                        "Flow / Bias": r.get("Flow / Bias", "—"),
                                        "Gold Zone Dist %": float(r["dist_gz"]),
                                        "Daily": r["struct"],
                                        "Summary": r["summary"],
                                    }
                                    for r in scanner_results
                                ]
                            )
                            with st.expander("Scanner Data Table", expanded=False):
                                streamlit_show_dataframe(
                                    scanner_df,
                                    use_container_width=True,
                                    hide_index=True,
                                    key="cf_scanner_tbl_df",
                                    on_select="ignore",
                                    selection_mode=[],
                                    column_config={
                                        "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                                        "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
                                        "Change %": st.column_config.NumberColumn("Change", format="%+.1f%%"),
                                        "QE Score": st.column_config.NumberColumn("QE Score", format="%.0f"),
                                        "Adj. Kelly %": st.column_config.NumberColumn(
                                            "Adj. Kelly",
                                            format="%.1f%%",
                                            help="Kelly Criterion sizing after applying the Portfolio Correlation Haircut.",
                                        ),
                                        "Confluence": st.column_config.NumberColumn("Confluence", format="%d"),
                                        "Diamond": st.column_config.TextColumn("Diamond"),
                                        "PoP": st.column_config.TextColumn(
                                            "PoP",
                                            help="Historical win rate for Diamond signals (same methodology as the main dashboard backtest).",
                                        ),
                                        "EM Safety": st.column_config.TextColumn(
                                            "EM Safety",
                                            help="1-σ implied move vs scanner short-put strike: SAFE if strike < spot − EM (else MONITOR).",
                                        ),
                                        "GEX Regime": st.column_config.TextColumn(
                                            "GEX Regime",
                                            help="Gamma Flip: the price level where market maker hedging accelerates volatility. 🛡️ STABLE = spot above flip; ⚠️ TURBULENT = spot below flip.",
                                        ),
                                        "Flow / Bias": st.column_config.TextColumn(
                                            "Flow / Bias",
                                            help=SCANNER_WHALE_FLOW_BIAS_HELP,
                                        ),
                                        "Gold Zone Dist %": st.column_config.NumberColumn("Gold Zone Dist", format="%+.1f%%"),
                                        "Daily": st.column_config.TextColumn("Daily"),
                                        "Summary": st.column_config.TextColumn("Summary", width="large"),
                                    },
                                )

                        if scanner_mode == "📈 Options Yield":
                            _blues_alloc = [r for r in scanner_results if "BLUE" in str(r.get("d_status", ""))]
                            if _blues_alloc:
                                _alloc_rows = Opt.portfolio_allocation(
                                    [
                                        {
                                            "ticker": r["ticker"],
                                            "quant_edge": float(r["qs"]),
                                            "mc_pop_pct": float(r.get("scanner_mc_pop") or 0),
                                            "premium_per_contract": float(r.get("reference_prem_100") or 1),
                                        }
                                        for r in _blues_alloc
                                    ],
                                    total_capital=50000,
                                    watchlist_tickers=watchlist_tickers_scn,
                                    log_returns_df=log_returns_df,
                                )
                                if _alloc_rows:
                                    with st.expander("$50k Kelly-style mix (Blue Diamonds only)", expanded=False):
                                        st.caption(
                                            "Weights scale with Quant Edge × MC PoP %; each name’s notional is scaled by `_simple_corr_haircut` vs the watchlist (FFD-return correlations when history is sufficient)."
                                        )
                                        _adf = pd.DataFrame(_alloc_rows)
                                        streamlit_show_dataframe(
                                            _adf,
                                            use_container_width=True,
                                            hide_index=True,
                                            key="cf_portfolio_alloc_df",
                                            on_select="ignore",
                                            selection_mode=[],
                                        )

                            # Single markdown block: one st.markdown per row desyncs Streamlit's element tree
                            # (setIn index errors) when the watchlist length changes between reruns.
                            _scan_chunks = []
                            for r in scanner_results:
                                pc = "#10b981" if r["chg_pct"] >= 0 else "#ef4444"
                                cpc = "#10b981" if r["cp_score"] >= 7 else ("#f59e0b" if r["cp_score"] >= 4 else "#ef4444")
                                qec = "#10b981" if r["qs"] > 70 else ("#f59e0b" if r["qs"] > 50 else "#ef4444")
                                gz_c = "#10b981" if r["dist_gz"] > 0 else "#ef4444"
                                cp_mini_bar = ""
                                for bi in range(r["cp_max"]):
                                    filled = bi < r["cp_score"]
                                    bc = "#10b981" if filled and r["cp_score"] >= 7 else ("#f59e0b" if filled and r["cp_score"] >= 4 else ("#ef4444" if filled else "#1e293b"))
                                    cp_mini_bar += f"<div style='flex:1;height:6px;background:{bc};border-radius:3px;margin:0 1px'></div>"
                                _tk = _html_mod.escape(str(r["ticker"]))
                                _sum = _html_mod.escape(str(r.get("summary") or ""))
                                _st = _html_mod.escape(str(r.get("struct") or ""))
                                _ds = _html_mod.escape(str(r.get("d_status") or ""))
                                _ov = (
                                    f"<div style='font-size:.72rem;color:#f59e0b;font-weight:600'>⚠️ High Portfolio Overlap ({float(r.get('overlap', 0.0)):.2f})</div>"
                                    if r.get("overlap", 0.0) >= 0.7
                                    else ""
                                )
                                _scan_chunks.append(
                                    f"""<div class='scanner-row'>
                                <div class='scanner-grid'>
                                    <div style='min-width:80px'>
                                        <div style='font-size:1.1rem;font-weight:700;color:#e2e8f0'>{_tk}</div>
                                        {_ov}
                                        <div class='mono' style='font-size:.9rem;color:{pc}'>${r['price']:.2f} ({r['chg_pct']:+.1f}%)</div>
                                    </div>
                                    <div style='text-align:center;min-width:70px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>QE Score</div>
                                        <div class='mono' style='color:{qec};font-weight:700'>{r['qs']:.0f}/100</div>
                                    </div>
                                    <div style='text-align:center;min-width:90px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Adj. Kelly</div>
                                        <div class='mono' style='font-size:.82rem;color:#93c5fd;font-weight:700'>{r.get('Adj. Kelly %', 0.0):.1f}%</div>
                                        <div style='font-size:.58rem;color:#64748b;margin-top:3px;line-height:1.25'>MC PoP {float(r.get('scanner_mc_pop') or 0):.1f}% · HVN {('—' if r.get('hvn_floor') is None else f"${float(r['hvn_floor']):,.0f}")} · R×{float(r.get('risk_multiplier') or 1):.2f}</div>
                                    </div>
                                    <div style='text-align:center;min-width:100px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Confluence</div>
                                        <div class='mono' style='color:{cpc};font-weight:700'>{r['cp_score']}/{r['cp_max']}</div>
                                        <div style='display:flex;gap:1px;margin-top:3px;width:80px'>{cp_mini_bar}</div>
                                    </div>
                                    <div style='text-align:center;min-width:100px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Diamond</div>
                                        <span class='diamond-badge {r["d_class"]}'>{_ds}</span>
                                    </div>
                                    <div style='text-align:center;min-width:100px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>GEX Regime</div>
                                        <div class='mono' style='font-size:.72rem;color:#e2e8f0;font-weight:700;line-height:1.25'>{_html_mod.escape(str(r.get("GEX Regime") or "—"))}</div>
                                    </div>
                                    <div style='text-align:center;min-width:120px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Flow / Bias</div>
                                        <div class='mono' style='font-size:.7rem;color:#e2e8f0;font-weight:700;line-height:1.25'>{_html_mod.escape(str(r.get("Flow / Bias") or "—"))}</div>
                                    </div>
                                    <div style='text-align:center;min-width:72px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>PoP</div>
                                        <div class='mono' style='font-size:.82rem;color:#c4b5fd;font-weight:700'>{(f"{float(r.get('diamond_pop', 0)):.0f}%" if int(r.get("diamond_n") or 0) > 0 else "—")}</div>
                                        <div style='font-size:.62rem;color:#64748b;margin-top:2px'>Diamond win</div>
                                    </div>
                                    <div style='text-align:center;min-width:90px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Gold Zone</div>
                                        <div class='mono' style='font-size:.8rem;color:#fbbf24'>${r['gold_zone']:.2f}</div>
                                        <div style='font-size:.7rem;color:{gz_c}'>{r['dist_gz']:+.1f}%</div>
                                    </div>
                                    <div style='text-align:center;min-width:60px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Daily</div>
                                        <div style='font-size:.8rem;color:{"#10b981" if r["struct"]=="BULLISH" else ("#ef4444" if r["struct"]=="BEARISH" else "#f59e0b")}'>{_st}</div>
                                    </div>
                                    <div style='flex:1;min-width:180px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Summary</div>
                                        <div class='scan-summary' style='font-size:.82rem;color:#e2e8f0;line-height:1.4'>{_sum}</div>
                                    </div>
                                </div>
                            </div>"""
                                )
                            if _scan_chunks:
                                st.markdown("\n".join(_scan_chunks), unsafe_allow_html=True)

                            _render_scanner_options_data_table()

                            _explain("🔎 How to use the Scanner",
                                "Look for tickers with <strong>7+ confluence points</strong> and an active <strong>Blue Diamond</strong>. "
                                "Those are your highest-probability setups across the entire watchlist. "
                                "Tickers near their Gold Zone with rising confluence are about to trigger. "
                                "Pink Diamonds mean take profits or avoid new entries on that ticker. "
                                "Sort mentally by confluence score. The higher the number, the stronger the setup.", "neutral")
                        else:
                            try:
                                _pre_signal = [
                                    r for r in scanner_results
                                    if r.get("pre_diamond_status", {}).get("is_pre_diamond")
                                ]
                                _alloc_by_tkr = {}
                                if _pre_signal:
                                    _eq_alloc = Opt.portfolio_allocation(
                                        [
                                            {
                                                "ticker": r["ticker"],
                                                "quant_edge": float(r["qs"]),
                                                "mc_pop_pct": float(r.get("scanner_mc_pop") or 0),
                                                "premium_per_contract": max(float(r["price"]), 1e-9),
                                            }
                                            for r in _pre_signal
                                        ],
                                        total_capital=float(equity_capital),
                                        watchlist_tickers=watchlist_tickers_scn,
                                        log_returns_df=log_returns_df,
                                    )
                                    for row in _eq_alloc:
                                        _alloc_by_tkr[row["ticker"]] = int(row.get("contracts") or 0)

                                equity_rows = []
                                for r in scanner_results:
                                    pre = r.get("pre_diamond_status", {"is_pre_diamond": False})
                                    signal = pre.get("signal_strength", "—") if pre.get("is_pre_diamond") else "—"
                                    price = float(r.get("price") or 0)
                                    shares = (
                                        _alloc_by_tkr.get(r["ticker"], 0)
                                        if pre.get("is_pre_diamond")
                                        else 0
                                    )
                                    equity_rows.append({
                                        "Ticker": r.get("ticker", "—"),
                                        "Signal": signal,
                                        "Price": round(price, 2) if price else "—",
                                        "Suggested Shares": shares,
                                        "Stop Loss": r.get("stock_stop_price", "—"),
                                        "QE Score": r.get("qs", 0),
                                        "Support Proximity (%)": pre.get("support_proximity", "—"),
                                    })

                                breakout_count = sum(1 for row in equity_rows if "🔥" in str(row.get("Signal", "")))
                                accum_count = sum(1 for row in equity_rows if "🟡" in str(row.get("Signal", "")))

                                st.markdown("### 📡 Radar Summary")
                                hud_col1, hud_col2, hud_col3 = st.columns(3)
                                with hud_col1:
                                    st.metric(
                                        "🔥 Imminent Breakouts",
                                        breakout_count,
                                        help="Volatility coil + relative strength.",
                                    )
                                with hud_col2:
                                    st.metric(
                                        "🟡 Accumulating",
                                        accum_count,
                                        help="Pre-breakout conditions met; awaiting broader strength.",
                                    )
                                with hud_col3:
                                    st.metric(
                                        "Total Scanned",
                                        len(scanner_results),
                                        help="Tickers evaluated in this run.",
                                    )

                                st.divider()

                                if equity_rows:
                                    equity_df = pd.DataFrame(equity_rows)

                                    formatted_df = equity_df.copy()
                                    formatted_df["Price"] = formatted_df["Price"].apply(
                                        lambda x: f"${x:,.2f}" if isinstance(x, (int, float)) else x
                                    )
                                    formatted_df["Stop Loss"] = formatted_df["Stop Loss"].apply(
                                        lambda x: f"${x:,.2f}" if isinstance(x, (int, float)) else x
                                    )
                                    formatted_df["Support Proximity (%)"] = formatted_df[
                                        "Support Proximity (%)"
                                    ].apply(
                                        lambda x: f"{x:.1f}%" if isinstance(x, (int, float)) else x
                                    )
                                    formatted_df["Suggested Shares"] = formatted_df["Suggested Shares"].apply(
                                        lambda x: f"{int(x):,}" if isinstance(x, (int, float)) and not isinstance(x, bool) else x
                                    )

                                    def style_equity_row(row):
                                        if "🔥" in str(row.get("Signal", "")):
                                            return [
                                                "background-color: #fefce8; color: #854d0e; font-weight: bold"
                                            ] * len(row)
                                        if "🟡" in str(row.get("Signal", "")):
                                            return [
                                                "background-color: #f8fafc; color: #334155"
                                            ] * len(row)
                                        return [""] * len(row)

                                    styled_df = formatted_df.style.apply(style_equity_row, axis=1)

                                    st.markdown("### 🎯 Actionable Targets")
                                    st.dataframe(
                                        styled_df,
                                        use_container_width=True,
                                        hide_index=True,
                                        height=min(400, (len(equity_rows) + 1) * 38),
                                    )
                                else:
                                    st.info("Radar scan complete. No tickers met the criteria.")

                                st.caption(
                                    "🔥 **IMMINENT BREAKOUT** = Volatility coil + RS vs SPY + accumulation near Gold/Shadow floor. "
                                    "Suggested shares respect full Kelly + correlation haircut."
                                )
                                st.divider()
                                _render_equity_setup_desk(
                                    scanner_results, "cf_equity_desk_scanner", prefer_ticker=ticker
                                )
                            except Exception:
                                st.caption(
                                    "Equity Radar temporarily unavailable — showing Options Yield table instead."
                                )
                                _render_scanner_options_data_table()
                    else:
                        st.info("No scanner results. Check your ticker symbols.")
            else:
                st.info("Add tickers under **Edit watchlist symbols** (top of page) to use the scanner.")

            # ══════════════════════════════════════════════════════════════════
            #  SECTION 8 \u2014 NEWS & MACRO
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="news" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("News and Market Conditions", f"Headlines, macro, and earnings calendar for {ticker} while the tape is open.",
                     tip_plain="Stories explain gaps and IV pops. Always read news through price. When headline risk stacks near earnings, favor safer strikes and lighter size.")
            n_tab, m_tab, e_tab = st.tabs(["🗞️ Market News", "🌍 Macro & Yields", "📅 Upcoming Earnings"])
            with n_tab:
                st.markdown(f"#### {ticker} News")
                if news:
                    for item in news:
                        lnk = f"<a href='{item['link']}' target='_blank' style='color:#06b6d4'>Read</a>" if item["link"] else ""
                        st.markdown(f"<div class='ni'><strong style='color:#e2e8f0'>{item['title']}</strong><br><span style='color:#64748b;font-size:.8rem'>{item['pub']} {item['time']}</span>{' | ' + lnk if lnk else ''}</div>", unsafe_allow_html=True)
                else:
                    st.info("No news found.")
            with m_tab:
                st.markdown("#### Macro Dashboard")
                for k, v in macro.items():
                    dc = "#10b981" if v["chg"] >= 0 else "#ef4444"
                    st.markdown(f"<div class='tc' style='padding:10px 14px;margin-bottom:6px'><div style='display:flex;justify-content:space-between'><span style='color:#94a3b8'>{k}</span><span class='mono' style='color:#e2e8f0'>{v['price']:.2f} <span style='color:{dc}'>{v['chg']:+.2f}%</span></span></div></div>", unsafe_allow_html=True)
            with e_tab:
                st.markdown('<div id="earnings" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                st.markdown(f"#### {_html_mod.escape(ticker)} earnings calendar")
                earn_cal_df, earn_highlight_idx = fetch_earnings_calendar_display(ticker)
                if earn_cal_df.empty:
                    if earnings_dt is not None and days_to_earnings is not None:
                        # Fallback when calendar rows are empty but we still have a valid next earnings date.
                        _status = (
                            f"In {days_to_earnings} day(s)"
                            if days_to_earnings > 0
                            else ("Today" if days_to_earnings == 0 else f"Reported {abs(days_to_earnings)} day(s) ago")
                        )
                        st.caption("Calendar rows unavailable from feed; showing single-date fallback.")
                        streamlit_show_dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Date": earnings_dt.strftime("%Y-%m-%d"),
                                        "When": _status,
                                        "Source": "Primary earnings date feed",
                                    }
                                ]
                            ),
                            use_container_width=True,
                            hide_index=True,
                            key=f"cf_earn_fallback_{ticker}_{earnings_dt.strftime('%Y%m%d')}",
                            on_select="ignore",
                            selection_mode=[],
                        )
                    else:
                        _earn_empty = (
                            "We could not load earnings dates from the feed for this symbol. "
                            "That can happen with API gaps, very new listings, or certain ADRs. "
                            "Confirm the next print in your broker or any public earnings calendar."
                        )
                        if earnings_parse_failed:
                            _earn_empty += " A raw value came back but could not be parsed into a calendar date."
                        st.info(_earn_empty)
                        if st.button("Refresh earnings", key="retry_earnings_tab", help="Clears cached earnings and quote info"):
                            fetch_earnings_date.clear()
                            fetch_earnings_calendar_display.clear()
                            fetch_info.clear()
                            st.rerun()
                else:
                    st.caption("Rows are newest-first. Cross-check **Status** and dates with your broker.")
                    streamlit_show_dataframe(
                        earn_cal_df.reset_index(drop=True),
                        column_config=_earnings_calendar_column_config(),
                        use_container_width=True,
                        hide_index=True,
                        key=streamlit_df_widget_key(f"cf_earn_cal_{ticker}", earn_cal_df),
                        on_select="ignore",
                        selection_mode=[],
                    )

            with st.expander("Quick Reference Guide", expanded=False):
                st.markdown('<div id="guide" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                _section(
                    "Quick Reference Guide",
                    "Plain language glossary for every signal on this desk — including v22 **Shadow move**, **OpEx pin**, **Sentinel Ledger**, and **regime calibration**. Keep it open during live markets.",
                    tip_plain="Mirrors the high-level story in **README.md** (repo root). Reach for this when a label feels fuzzy; clarity beats impulse every session.",
                )
                edu = [
                    ("Blue Diamond Signal", "A Blue Diamond appears when confluence crosses up to 7+ out of 9, <strong>daily market structure is BULLISH</strong>, the <strong>weekly MACD/EMA bias is not BEARISH</strong>, and <strong>volume is at least 90% of the 20-day volume SMA</strong> (participation). An ATR blow-off guard still filters manic prints. Buy on Blue Diamonds."),
                    ("Pink Diamond Signal", "A Pink Diamond appears when bullish confluence collapses or momentum exhausts (RSI > 75 with weak confluence). Think of it as your dashboard warning lights all turning on. It means the easy money in this move is done. Take profits, sell aggressive covered calls, or tighten your stops. Sell on Pink Diamonds."),
                    ("Gold Zone", "The Gold Zone is a single dynamic price level calculated from Volume Profile POC, the 61.8% Fibonacci golden ratio, the 200-day simple moving average, and the nearest Gann Square of 9 level. When the stock is above the Gold Zone, bulls are in control. Below it, bears have the edge. Use the Gold Zone as your anchor for all strike selection."),
                    ("Confluence Points (0 to 9)", "The Confluence score checks nine independent bullish factors: Supertrend direction (2pts), Ichimoku cloud position (2pts), ADX trend strength (1pt), OBV accumulation (1pt), bullish divergences (1pt), position versus Gold Zone (1pt), and market structure (1pt). Scores of 7 or higher trigger Blue Diamonds. Scores below 4 signal caution."),
                    ("Covered Call", "You own 100 shares. You sell 1 call above the current price. You collect cash today. If the stock stays below that price, you keep the cash AND you keep your shares. Target: 1 to 3 percent per month in pure cash income."),
                    ("Cash Secured Put and The Wheel", "You sell a put and hold cash to buy shares if needed. If you get assigned, you sell Covered Calls on those new shares. When shares get called away, you sell puts again. This is the cash flow loop. Repeat forever."),
                    ("Credit Spreads", "You sell one option and collect cash. Then you buy a cheaper one further away to cap your worst case loss. Bull Put Spread means you are bullish. Bear Call Spread means you are bearish. Uses less money than Cash Secured Puts."),
                    ("RSI (Relative Strength Index)", "RSI is a 0 to 100 energy meter for the stock. Above 70 means buyers are exhausted. Great time to sell calls. Below 30 means sellers panicked. Great time to sell puts. The sweet spot for collecting cash is 40 to 60."),
                    ("MACD", "MACD shows who is winning: buyers or sellers. When the blue line crosses above the orange line, buyers are taking over. When it crosses below, sellers are winning. Think of it as comparing this month's sales to the quarterly average."),
                    ("ADX (Trend Strength)", "ADX is a 0 to 100 gauge for how strong the trend is. Above 25 means a strong trend is happening. Below 20 means the market is going nowhere. ADX does not tell you the direction. It only tells you the strength."),
                    ("Ichimoku Cloud", "The cloud is a safety net for the stock price. When the price floats above the cloud, the trend is bullish. When it falls into or below the cloud, the trend is weak. When all 5 parts agree, that is the strongest signal you can get."),
                    ("Supertrend", "The Supertrend is your price floor or ceiling. Green line below the price means bullish. Your shares are safe. Red line above the price means bearish. When it flips color, that is your signal to act."),
                    ("OBV (On Balance Volume)", "OBV tracks what the big money is doing. Rising OBV means institutions are quietly buying. Think of wholesale customers stocking up. Falling OBV means they are selling. If OBV disagrees with the price, a reversal may be coming."),
                    ("Fibonacci Retracement", "After a big move, stocks pull back to key levels before continuing: 38.2%, 50%, and 61.8%. The 61.8% level is the golden ratio. It is the most watched level on Wall Street. Set your put strikes near these levels for the safest entries."),
                    ("Volatility Skew", "When put options cost much more than call options, big institutions are buying crash insurance. That means premiums are fat for you to sell. But it also means the smart money is nervous. Collect the cash but stay aware."),
                    ("Expected Value", "EV is your long run profit per trade. Multiply win rate by gain, then subtract loss rate times loss. Positive EV means a real edge. Negative EV means pass."),
                    ("Gann Square of 9", "These are natural support and resistance levels calculated from mathematical spirals. Stocks tend to stop or bounce at these prices. Use them to pick smarter strike prices for your options."),
                    ("Quant Edge Score", "Your overall score from 0 to 100. It checks five things: Trend, Momentum, Volume, Volatility, and Structure. Above 70 means prime conditions to sell options. Below 40 means wait for a better setup."),
                    ("Shadow Move (purple band)", "The <strong>Shadow</strong> is built from days when volume Z-score says <strong>whale</strong> activity (Z &gt; 2). We sort those closes by price and capture the middle <strong>70% of whale volume</strong> — that price range is shaded <strong>purple</strong> on the chart. Compare it to the gold <strong>Expected Move (1σ)</strong> rails: if the shadow is <strong>narrower</strong> than IV implies, vol may be rich; if <strong>wider</strong>, a larger move than options price may be brewing."),
                    ("Shadow breakout (regime calibration)", "When <strong>spot steps outside</strong> the purple Shadow band but <strong>still sits inside</strong> the IV <strong>1σ Expected Move</strong>, the chart tab shows a <strong>purple calibration banner</strong>. Whale prints already led price <strong>past</strong> the liquidity cluster while options vol has <strong>not</strong> fully caught up — watch for institutional-led <strong>trend continuation or reversal</strong> before retail reprices risk."),
                    ("Predicted OpEx pin", "A <strong>pink dotted</strong> line estimates where price may <strong>pin</strong> into expiry: we find the strongest dealer <strong>gamma wall</strong> (|GEX| near spot when it matters), then blend toward spot using your desk <strong>Θ/Γ</strong> — high decay efficiency makes the wall more <strong>magnetic</strong>. It is a positioning heuristic, not a settlement promise."),
                    ("News bias (Bayesian-style)", "Headlines are scored with a <strong>weighted lexicon</strong>: <strong>forward</strong> phrases (guidance, outlook, forecast) count more than <strong>trailing</strong> words (beat, miss). A line like <em>missed earnings but raised guidance</em> tilts <strong>bullish</strong> because forward guidance outweighs the backward print. Empty or neutral text scores zero."),
                    ("Sentinel Ledger & Edge realization", "Use <strong>Track Trade</strong> on the optimal CC or CSP row to log a leg for this session. The ledger shows model <strong>Δ</strong>, <strong>Θ/day</strong>, and unrealized P&amp;L vs entry premium. <strong>Edge realization %</strong> compares today’s <strong>Quant Edge</strong> to the score stored at track time for the <strong>active ticker</strong> (capped at 150%)."),
                    ("Pin maturity — Golden zone", "For rows tracked with v22+ snapshots: inside <strong>14 DTE</strong>, if <strong>|Dist. to pin %|</strong> has <strong>shrunk</strong> versus entry and your desk <strong>Θ/day</strong> has <strong>grown</strong> versus entry, the ledger shows <strong>✨ Golden zone</strong> — the window where pin gravity and daily decay often peak together. Older rows without snapshots show a dash."),
                    ("Market Scanner", "The Scanner checks your entire watchlist in seconds. It calculates Confluence Points, Diamond Status, Gold Zone distance, and Quant Edge for every ticker. Sort by confluence to find the strongest setups across all your stocks. Tickers with 7+ confluence and a Blue Diamond are your best opportunities."),
                ]
                for i in range(0, len(edu), 2):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i][1]}</div></div>", unsafe_allow_html=True)
                    with ec2:
                        if i + 1 < len(edu):
                            st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i + 1][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i + 1][1]}</div></div>", unsafe_allow_html=True)

    with dash_tab_ledger:
            st.markdown('<div id="sentinel-ledger" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section(
                "📊 Sentinel Ledger",
                "Session-based simulated trade log: track desk strikes, then read portfolio-level Greeks and mark-to-model P&L.",
                tip_plain="**Pin maturity ✨ Golden zone** (≤14 DTE): |Dist. to pin %| shrinking vs entry while desk Θ/day rises vs entry — pin magnet strengthens into expiry. "
                "New **Track Trade** rows snapshot dist-to-pin and Θ/day at entry. On the chart tab, **Shadow breakout** flags spot outside the purple whale band but inside IV 1σ — early regime read.",
            )
            _led = st.session_state.get("_cf_ledger") or []
            if not _led:
                st.caption(
                    "No tracked trades yet. Use **Track Trade** on the optimal Covered Call or Cash Secured Put "
                    "card in **Cashflow & strikes**."
                )
            _pin_m = st.session_state.get("_cf_opex_pin_map") or {}
            _rows, _v22 = sentinel_ledger_table_rows(
                _led,
                active_ticker=str(ticker),
                active_qs=float(qs),
                pin_map=_pin_m,
                rfr=float(rfr),
            )
            _hide_ledger_internal = ("dist_pin_pct_at_entry", "theta_desk_day_entry")
            _ldf = pd.DataFrame(
                [{k: v for k, v in row.items() if k not in _hide_ledger_internal} for row in _rows]
            )
            streamlit_show_dataframe(
                _ldf,
                use_container_width=True,
                hide_index=True,
                key="cf_sentinel_ledger_df",
                on_select="ignore",
                selection_mode=[],
            )
            _m = sentinel_ledger_metrics(_led, rfr=float(rfr))
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Total portfolio Δ (equiv. shares)", f"{_m['total_delta']:,.2f}")
            with m2:
                st.metric("Total Θ / day (desk income)", f"${_m['total_theta_day']:,.2f}")
            with m3:
                st.metric("Unrealized P&L (model)", f"${_m['unrealized_pnl']:,.2f}")
            with m4:
                _er = _v22.get("avg_edge_realization")
                st.metric(
                    "Edge realization (avg, active tickers)",
                    f"{_er:.1f}%" if _er is not None else "—",
                    help="Current Quant Edge vs **qs_at_entry** for ledger rows on the active symbol (capped at 150%).",
                )
            if st.button("Clear Sentinel Ledger", key="cf_ledger_clear"):
                st.session_state["_cf_ledger"] = []
                st.rerun()


if __name__ == "__main__":
    main()
