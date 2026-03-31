"""
╔══════════════════════════════════════════════════════════════════════════╗
║  CASHFLOW COMMAND CENTER v14.1 · INSTITUTIONAL EDITION                   ║
║  Modular architecture — same UI, same logic, clean separation.           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import streamlit as st

st.set_page_config(
    page_title="CashFlow Command Center v14.1",
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import plotly.graph_objects as go
import math, warnings, json, time, os
import textwrap
from pathlib import Path
warnings.filterwarnings("ignore")

# ── Module imports ──
from modules.config import (
    load_config, save_config, DEFAULT_CONFIG, CONFIG_PATH,
    _hydrate_sidebar_prefs, _overlay_prefs_from_session,
    REF_NOTIONAL, RISK_PCT_EXAMPLE, KELLY_DISPLAY_CAP_PCT,
    EMA_EXTENSION_WARN_PCT,
)
from modules.data import (
    retry_fetch, _yfinance_ticker, _client_suggests_mobile_chart,
    fetch_stock, _ticker_pct_change_1d, fetch_intraday_series,
    fetch_info, fetch_options, compute_iv_rank_proxy, fetch_news,
    fetch_earnings_date, fetch_earnings_calendar_display, fetch_macro,
    _PLOTLY_UI_CONFIG, _PLOTLY_PAPER_BG, _PLOTLY_PLOT_BG,
    _PLOTLY_CASH_UP, _PLOTLY_CASH_DOWN, _PLOTLY_GRID, _PLOTLY_FONT_MAIN,
)
from modules.ta import TA
from modules.options import (
    bs_price, bs_greeks, calc_ev, kelly_criterion, calc_vol_skew,
    quant_edge_score, weekly_trend_label, calc_gold_zone,
    calc_confluence_points, detect_diamonds, latest_diamond_status,
    diamond_win_rate, scan_single_ticker, Opt,
)
from modules.sentiment import Sentiment, Backtest, Alerts, run_cc_sim_cached
from modules.chart import build_chart
from modules.ui_helpers import (
    _factor_checklist_labels, _confluence_why_trade_plain,
    _iv_rank_qualitative_words, _iv_rank_pill_html,
    _explain, _section, _mini_sparkline, _glance_sparkline_svg,
    _glance_metric_card, _render_html_block, _parse_watchlist_string,
    _fragment_technical_zone, _df_price_levels, _style_price_levels_table,
    _earnings_calendar_column_config, _style_earnings_next_highlight,
    _PRICE_LEVEL_COLUMN_CONFIG, _options_scan_dataframe,
    _options_scan_column_config, _style_propdesk_highlight,
    _persist_overlay_prefs,
)
from modules.css import _CSS, _MINI_MODE_DENSITY_CSS, inject_css_and_navbar

# ── Inject theme + navbar (must happen before any widgets) ──
inject_css_and_navbar()

def main():
    cfg = load_config()

    if "_sb_scanner_sync" in st.session_state:
        st.session_state["sb_scanner"] = st.session_state.pop("_sb_scanner_sync")
    elif "sb_scanner" not in st.session_state:
        st.session_state["sb_scanner"] = cfg.get("watchlist", DEFAULT_CONFIG["watchlist"])

    # ── Watchlist editor (must run before Mission Control so sb_scanner is committed same run)
    _wl_expanded = bool(st.session_state.pop("_open_watchlist_editor", False))
    st.caption("CashFlow Command Center · v14.1")
    with st.expander("Edit watchlist symbols", expanded=_wl_expanded):
        st.caption(
            "Drop in tickers separated by commas or line breaks. Shuffle the lineup with the controls. "
            "Everything commits when the app saves your config."
        )
        scanner_watchlist_raw = st.text_area(
            "Watchlist symbols",
            height=150,
            help="Paste from a spreadsheet, type commas, or put one ticker per line.",
            key="sb_scanner",
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
            save_config({**load_config(), "watchlist": ",".join(w)})
            st.rerun()

    # ── GLOBAL COMMAND BAR (HUD — first paint in main column, directly under sticky nav)
    scanner_watchlist_raw = st.session_state.get("sb_scanner", cfg.get("watchlist", ""))
    watch_items = _parse_watchlist_string(scanner_watchlist_raw)
    scanner_watchlist = ",".join(watch_items)

    _scan_idx = (
        0 if cfg.get("scanner_sort_mode", "Custom watchlist order") == "Custom watchlist order" else 1
    )

    # Must resolve sb_watch_selected before st.selectbox(..., key="sb_watch_selected") — Streamlit 1.33+
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
                index=_scan_idx,
                horizontal=True,
                key="sb_scan_radio",
                help="Custom follows your lineup. Confluence ranks the strongest tape first.",
            )
            scanner_sort_mode = (
                "Custom watchlist order" if _scan_seg == "Custom order" else "Highest confluence first"
            )

    # Clickable ticker tape (chunk rows on wide lists so columns stay usable on mobile)
    if watch_items:
        st.markdown('<p class="cf-tape-title">Watchlist tape</p>', unsafe_allow_html=True)
        st.caption("Tap a symbol to promote it to the active ticker. Daily move is versus the prior session close (cached).")
        _TAPE_CHUNK = 8
        tape_i = 0
        for row_start in range(0, len(watch_items), _TAPE_CHUNK):
            row_tickers = watch_items[row_start : row_start + _TAPE_CHUNK]
            tape_cols = st.columns(len(row_tickers))
            for j, tkr in enumerate(row_tickers):
                pct = _ticker_pct_change_1d(tkr)
                pct_str = f"{pct:+.2f}%" if pct is not None else "n/a"
                c_pct = "#10b981" if (pct is not None and pct >= 0) else ("#ef4444" if pct is not None else "#64748b")
                is_active = tkr == ticker
                with tape_cols[j]:
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

    _hydrate_sidebar_prefs(cfg)

    prefs_cfg = {
        **cfg,
        "strat_focus": st.session_state.get("sb_strat_radio", DEFAULT_CONFIG["strat_focus"]),
        "strat_horizon": st.session_state.get("sb_horizon_radio", DEFAULT_CONFIG["strat_horizon"]),
        "mini_mode": bool(st.session_state.get("sb_mini_mode", cfg.get("mini_mode", False))),
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

    # Unpack context into locals — rendering code below uses these directly.
    # This keeps the entire rendering layer untouched from the original monolith.
    df = ctx.df; df_wk = ctx.df_wk; df_1mo_spark = ctx.df_1mo_spark
    vix_1mo_df = ctx.vix_1mo_df; macro = ctx.macro; news = ctx.news
    earnings_date_raw = ctx.earnings_date_raw
    price = ctx.price; prev = ctx.prev; chg = ctx.chg; chg_pct = ctx.chg_pct
    hi52 = ctx.hi52; lo52 = ctx.lo52; vix_v = ctx.vix_v
    qs = ctx.qs; qb = ctx.qb
    earnings_near = ctx.earnings_near; earnings_dt = ctx.earnings_dt
    days_to_earnings = ctx.days_to_earnings; earnings_parse_failed = ctx.earnings_parse_failed
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
    qs_color = ctx.qs_color; qs_status = ctx.qs_status
    rfr = ctx.rfr; bluf_cc = ctx.bluf_cc; bluf_csp = ctx.bluf_csp
    bluf_exp = ctx.bluf_exp; bluf_dte = ctx.bluf_dte
    bluf_calls = ctx.bluf_calls; bluf_puts = ctx.bluf_puts
    opt_exps = ctx.opt_exps; ref_iv_bluf = ctx.ref_iv_bluf
    nc = ctx.nc; action_strat = ctx.action_strat; action_plain = ctx.action_plain
    mini_mode = ctx.mini_mode; mobile_chart_layout = ctx.mobile_chart_layout

    # ── HEADER — Live Pulse ──
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
    if days_to_earnings is not None:
        earn_anchor = max(1, min(30, days_to_earnings if days_to_earnings >= 0 else 1))
        earnings_spark = pd.Series(np.linspace(earn_anchor + 1, max(0, earn_anchor - 1), 7))
    else:
        earnings_spark = pd.Series(np.linspace(24, 1, 7))
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
        earnings_caption = (
            "Plan size before the print"
            if earn_glance != "Date unavailable from feed"
            else "Keep base size until date is confirmed"
        )
        st.markdown(
            _glance_metric_card(
                "EARNINGS COUNTDOWN",
                f"<div class='glance-value' style='font-size:1.0rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(earn_glance)}</div>",
                f"<div class='glance-caption'>{_html_mod.escape(earnings_caption)}</div>",
                earnings_spark,
                "#FFD700",
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

    why_trade_tip = _html_mod.escape(_confluence_why_trade_plain(cp_breakdown))
    trade_hdr_html = (
        "<div style='display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px'>"
        "<div style='font-size:.72rem;font-weight:800;color:#00e5ff;letter-spacing:.18em'>RECOMMENDED TRADE</div>"
        "<span class='cf-tip cf-tip-ico' tabindex='0' aria-label='Why this trade'>"
        "<span class='cf-tip-ico-mark'>ⓘ</span>"
        f"<span class='cf-tiptext'>{why_trade_tip}</span></span>"
        "<span style='font-size:.62rem;color:#94a3b8'>Why this trade?</span></div>"
    )

    # ── RECOMMENDED TRADE (optimal strike from options engine) ──
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
        master_html = (
            f"<div class='trade-master'>"
            f"{trade_hdr_html}"
            f"{iv_badge_html}"
            f"<p style='color:#e2e8f0;font-size:1.05rem;line-height:1.55;margin:0 0 14px 0;font-weight:600'>{headline}</p>"
            f"<div class='strike-big' style='margin:8px 0 6px 0'>${_html_mod.escape(strike_s)}</div>"
            f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px'>Desk optimal strike · {iv_line}DTE {dte_m}</div>"
            f"<div style='font-size:.75rem;font-weight:700;color:#a5f3fc;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px'>Broker checklist</div>"
            f"<div class='rh-stepper'>{stepper}</div>"
            f"<p style='color:#64748b;font-size:.78rem;margin:14px 0 0 0'>Quotes can lag. Confirm credit in the app before you send the order.</p>"
            f"</div>"
        )
    elif not opt_exps:
        _iv_off = _iv_rank_pill_html(ticker, price, None, stub="offline")
        master_html = (
            f"<div class='trade-master'>"
            f"{trade_hdr_html}"
            f"{_iv_off}"
            f"<p style='color:#e2e8f0;font-size:1rem;margin:0'>Options chain is offline. Retry when the pit is open or jump to Cash Flow Strategies.</p>"
            f"</div>"
        )
    else:
        # Fallback when strict OI/volume filters remove every strike.
        # We still propose the nearest sensible OTM line from the current chain.
        fallback_kind = None
        fallback_row = None
        br = struct in ("BULLISH", "RANGING")
        if br and isinstance(bluf_calls, pd.DataFrame) and not bluf_calls.empty:
            c = bluf_calls.copy()
            c["strike"] = pd.to_numeric(c.get("strike"), errors="coerce")
            c["bid"] = pd.to_numeric(c.get("bid"), errors="coerce").fillna(0.0)
            c["ask"] = pd.to_numeric(c.get("ask"), errors="coerce").fillna(0.0)
            c["mid"] = (c["bid"] + c["ask"]) / 2.0
            c = c[(c["strike"] > price) & (c["mid"] > 0.01)].copy()
            if not c.empty:
                c["otm"] = (c["strike"] / price - 1.0) * 100.0
                c["target_gap"] = (c["otm"] - 5.0).abs()
                fallback_row = c.sort_values(["target_gap", "strike"]).iloc[0]
                fallback_kind = "cc"
        if fallback_row is None and isinstance(bluf_puts, pd.DataFrame) and not bluf_puts.empty:
            p = bluf_puts.copy()
            p["strike"] = pd.to_numeric(p.get("strike"), errors="coerce")
            p["bid"] = pd.to_numeric(p.get("bid"), errors="coerce").fillna(0.0)
            p["ask"] = pd.to_numeric(p.get("ask"), errors="coerce").fillna(0.0)
            p["mid"] = (p["bid"] + p["ask"]) / 2.0
            p = p[(p["strike"] < price) & (p["mid"] > 0.01)].copy()
            if not p.empty:
                p["otm"] = (1.0 - p["strike"] / price) * 100.0
                p["target_gap"] = (p["otm"] - 5.0).abs()
                fallback_row = p.sort_values(["target_gap", "strike"], ascending=[True, False]).iloc[0]
                fallback_kind = "csp"

        if fallback_row is not None and bluf_exp:
            _f_strike = float(fallback_row["strike"])
            _f_mid = float(fallback_row["mid"])
            _f_prem = _f_mid * 100.0
            _f_iv_raw = float(pd.to_numeric(fallback_row.get("impliedVolatility"), errors="coerce") or 0.0)
            _f_iv_pct = _f_iv_raw * 100.0 if _f_iv_raw > 0 else ref_iv_bluf
            _iv_fb = _iv_rank_pill_html(ticker, price, _f_iv_pct, stub=None if _f_iv_pct else "no_strike")
            if fallback_kind == "cc":
                _f_headline = (
                    f"FALLBACK LINE: SELL {nc}x {_html_mod.escape(ticker)} ${_f_strike:.0f} CALLS EXP {bluf_exp}. "
                    f"EST CREDIT ${_f_prem * nc:,.0f}."
                )
                _f_note = "Strict desk liquidity filters blocked every strike; this is the nearest tradable OTM call."
            else:
                _f_headline = (
                    f"FALLBACK LINE: SELL 1x {_html_mod.escape(ticker)} ${_f_strike:.0f} PUTS EXP {bluf_exp}. "
                    f"EST CREDIT ${_f_prem:,.0f}."
                )
                _f_note = "Strict desk liquidity filters blocked every strike; this is the nearest tradable OTM put."
            master_html = (
                f"<div class='trade-master'>"
                f"{trade_hdr_html}"
                f"{_iv_fb}"
                f"<p style='color:#e2e8f0;font-size:1rem;line-height:1.5;margin:0 0 10px 0;font-weight:600'>{_f_headline}</p>"
                f"<div class='strike-big' style='margin:6px 0 4px 0'>${_f_strike:.0f}</div>"
                f"<div style='color:#94a3b8;font-size:.85rem'>{_f_note}</div>"
                f"</div>"
            )
        else:
            _iv_ns = _iv_rank_pill_html(ticker, price, ref_iv_bluf, stub="no_strike" if not ref_iv_bluf else None)
            _fallback_action = _html_mod.escape(action_strat.title())
            master_html = (
                f"<div class='trade-master'>"
                f"{trade_hdr_html}"
                f"{_iv_ns}"
                f"<p style='color:#e2e8f0;font-size:1rem;line-height:1.5;margin:0 0 8px 0'>"
                f"Desk filters are too strict for this snapshot. Use a manual {_fallback_action} line around 3-7% OTM on the nearest monthly expiry."
                f"</p>"
                f"<p style='color:#94a3b8;font-size:.85rem;margin:0'>"
                f"Reference spot: ${price:,.2f}. Open Cash Flow Strategies for full chain selection."
                f"</p>"
                f"</div>"
            )

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
    #  SECTION 1 — TECHNICAL CHART (fragment: overlay toggles without refetching Yahoo)
    # ══════════════════════════════════════════════════════════════════
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

    dash_tab_setup, dash_tab_cashflow, dash_tab_intel = st.tabs(
        [
            "Setup & quant",
            "Cashflow & strikes",
            "Risk, scanner & intel",
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

                # Hurst Exponent — market regime filter
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

                st.markdown(f"""<div class='qe'>
                    <div style='font-size:.75rem;color:#8b5cf6;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE SCORE</div>
                    <div style='font-size:3rem;font-weight:800;color:{qs_color};font-family:JetBrains Mono,monospace'>{qs:.0f}</div>
                    <div style='font-size:.85rem;color:#94a3b8'>Your overall score from 5 independent checks</div></div>""", unsafe_allow_html=True)
                for k, v in qb.items():
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
                    st.dataframe(
                        _style_price_levels_table(_fib_df, mode="fib", spot=price),
                        column_config=_PRICE_LEVEL_COLUMN_CONFIG,
                        use_container_width=True,
                        hide_index=True,
                    )
                _explain("What are Fibonacci levels?",
                    "After a big move, stocks tend to pull back to specific levels before continuing. The key levels are 38.2%, 50%, and 61.8%. "
                    "The 61.8% level is called the golden ratio. It is the most watched level by professional traders. "
                    "Why you care: set your put strikes near Fibonacci support. You collect cash AND you buy at a natural price floor.", "neutral")
                if st.checkbox("Gann Square of 9", key="exp_1"):
                    gl = TA.gann_sq9(price)
                    _gann_df = _df_price_levels(gl, price)
                    st.dataframe(
                        _style_price_levels_table(_gann_df, mode="gann", spot=price),
                        column_config=_PRICE_LEVEL_COLUMN_CONFIG,
                        use_container_width=True,
                        hide_index=True,
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
                for d, src in all_divs[-5:]:
                    st.markdown(f"<div class='ac'>{'🟢' if d['type'] == 'bullish' else '🔴'} <strong>{d['type'].title()} {src} divergence</strong> near ${d['price']:.2f} on {d['idx'].strftime('%Y-%m-%d')}</div>", unsafe_allow_html=True)
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
            #  SECTION 4 \u2014 CASH-FLOW STRATEGIES
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="strategies" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("Cash Flow Strategies", f"Concrete strikes for {ticker} at ${price:.2f}. Lift them straight into your ticket.",
                     tip_plain="Start with the optimal line the desk highlights. Covered calls need stock on hand. Cash secured puts monetize patience. Spreads are for when you want a hard loss ceiling.")
            st.markdown(
                f"<div class='tc'><div style='text-align:center'><span style='color:#64748b;font-size:.8rem'>ANALYZING</span><br>"
                f"<span style='font-size:1.4rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(ticker)} @ ${price:.2f}</span></div></div>",
                unsafe_allow_html=True,
            )

            if opt_exps:
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
                if not calls.empty or not puts.empty:
                    s1, s2 = st.columns(2)
                    with s1:
                        st.markdown("#### Covered Calls")
                        cc = Opt.covered_calls(price, calls, dte, rfr)
                        if cc:
                            opt_cc = next((c for c in cc if c.get("optimal")), cc[0])
                            b = opt_cc; nc_s = 1
                            opt_html = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                            in_zone = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                            delta_color = "#10b981" if in_zone else "#f59e0b"
                            st.markdown(f"<div class='sb'>{opt_html}<strong>SELL {nc_s}x ${b['strike']:.0f}C @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color}'>\u0394 {b['delta']:.2f}</strong><br>Premium: <strong style='color:#10b981'>${b['prem_100'] * nc_s:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Ann: {b['ann_yield']:.1f}% | OI: {b['oi']:,}</span></div>", unsafe_allow_html=True)
                            if st.checkbox("All CC strikes", key="exp_5"):
                                _cc_df = _options_scan_dataframe(cc, put_table=False)
                                st.dataframe(
                                    _style_propdesk_highlight(_cc_df),
                                    column_config=_options_scan_column_config(put_table=False),
                                    use_container_width=True,
                                    hide_index=True,
                                )
                        else:
                            st.info("No covered call strikes met pricing/liquidity checks in this snapshot. Try a nearby expiry or refresh.")
                    with s2:
                        st.markdown("#### Cash Secured Puts")
                        csp = Opt.cash_secured_puts(price, puts, dte, rfr)
                        if csp:
                            opt_csp = next((c for c in csp if c.get("optimal")), csp[0])
                            b = opt_csp
                            opt_html_p = '<div style="font-size:.7rem;font-weight:700;color:#06b6d4;margin-bottom:6px">\U0001f3af OPTIMAL PROP-DESK STRIKE</div>' if b.get("optimal") else ""
                            in_zone_p = Opt.DELTA_LOW <= abs(b["delta"]) <= Opt.DELTA_HIGH
                            delta_color_p = "#10b981" if in_zone_p else "#f59e0b"
                            st.markdown(f"<div class='sb'>{opt_html_p}<strong>SELL 1x ${b['strike']:.0f}P @ ${b['mid']:.2f}</strong><br><span style='font-size:.85rem;color:#94a3b8'>Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | <strong style='color:{delta_color_p}'>\u0394 {b['delta']:.2f}</strong><br>Premium: <strong style='color:#10b981'>${b['prem_100']:,.0f}</strong> | OTM: {b['otm_pct']:.1f}% | Eff buy: ${b['eff_buy']:.2f} | OI: {b['oi']:,}</span></div>", unsafe_allow_html=True)
                            if st.checkbox("All CSP strikes", key="exp_6"):
                                _csp_df = _options_scan_dataframe(csp, put_table=True)
                                st.dataframe(
                                    _style_propdesk_highlight(_csp_df),
                                    column_config=_options_scan_column_config(put_table=True),
                                    use_container_width=True,
                                    hide_index=True,
                                )
                        else:
                            st.info("No put strikes met pricing/liquidity checks in this snapshot. Try a nearby expiry or refresh.")

                    _explain("\U0001f9e0 What are Delta and Theta?",
                        "<strong>Delta is your win probability.</strong> A Delta of 0.16 means you have an 84 percent chance to keep all the cash and keep your shares. Lower Delta means safer. "
                        "<strong>Theta is your daily paycheck.</strong> Every day that passes, the option loses value. That lost value goes straight into your pocket. Time is literally paying you. "
                        "<strong>OI is how busy the market is.</strong> Higher OI means more traders are active. That means you get better prices when you sell. We filter out anything below 100 OI to protect you.", "neutral")

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
                                    A Blue Diamond fired {(df.index[-1] - latest_d['date']).days} day(s) ago at ${latest_d['price']:.2f} with confluence {latest_d['score']}/9.
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
                                    Confluence dropped to {latest_d['score']}/9. Momentum is exhausting.
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
                st.warning("Options data currently unavailable for this ticker.")

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

                # Kelly Criterion — mathematically optimal allocation
                k_full, k_half = 0.0, 0.0
                k_source = ""
                if bluf_cc:
                    k_pop = min(85, max(50, 100 - bluf_cc["otm_pct"] * 5))
                    k_win = bluf_cc["prem_100"]
                    k_loss = k_win * 3
                    k_full, k_half = kelly_criterion(k_pop, k_win, k_loss)
                    k_source = f"CC ${bluf_cc['strike']:.0f}"
                elif bluf_csp:
                    k_pop = min(85, max(50, 100 - bluf_csp["otm_pct"] * 5))
                    k_win = bluf_csp["prem_100"]
                    k_loss = bluf_csp["strike"] * 100 - k_win
                    k_full, k_half = kelly_criterion(k_pop, k_win, k_loss)
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
                        f"Display max {k_cap:.0f}% for risk hygiene.{capped_note}</div></div>",
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
            #  SECTION 7 — MARKET SCANNER (multi-ticker diamond & confluence scan)
            # ══════════════════════════════════════════════════════════════════
            st.markdown('<div id="scanner" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
            _section("🔎 Market Scanner", "One pass across the list for Diamonds, confluence stacks, and Gold Zone distance.",
                     tip_plain="Sort mentally by confluence, then hunt for a live Blue Diamond. If nothing clears the bar, flat is a position.")

            watchlist_tickers = [t.strip().upper() for t in scanner_watchlist.split(",") if t.strip()]
            if watchlist_tickers:
                if st.button("Scan Watchlist", key="run_scanner"):
                    scanner_results = []
                    n_scan = len(watchlist_tickers)
                    workers = min(8, max(1, n_scan))
                    scan_progress = st.progress(0)
                    done_ct = 0
                    scan_failed = []
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        future_map = {pool.submit(scan_single_ticker, tkr): tkr for tkr in watchlist_tickers}
                        for fut in as_completed(future_map):
                            done_ct += 1
                            tkr = future_map[fut]
                            scan_progress.progress(done_ct / n_scan, text=f"Scanning {tkr}… ({done_ct}/{n_scan})")
                            try:
                                result = fut.result()
                                if result:
                                    scanner_results.append(result)
                            except Exception as e:
                                scan_failed.append((tkr, type(e).__name__))
                    scan_progress.empty()
                    if scan_failed:
                        failed_line = ", ".join(f"{_html_mod.escape(t)} ({err})" for t, err in scan_failed[:12])
                        more = f" (+{len(scan_failed) - 12} more)" if len(scan_failed) > 12 else ""
                        st.warning(f"Some symbols could not be scanned: {failed_line}{more}")

                    if scanner_results:
                        if scanner_sort_mode == "Highest confluence first":
                            scanner_results.sort(key=lambda x: x["cp_score"], reverse=True)
                        else:
                            order = {t: i for i, t in enumerate(watchlist_tickers)}
                            scanner_results.sort(key=lambda x: order.get(x["ticker"], 10_000))

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

                            st.markdown(f"""<div class='scanner-row'>
                                <div class='scanner-grid'>
                                    <div style='min-width:80px'>
                                        <div style='font-size:1.1rem;font-weight:700;color:#e2e8f0'>{r['ticker']}</div>
                                        <div class='mono' style='font-size:.9rem;color:{pc}'>${r['price']:.2f} ({r['chg_pct']:+.1f}%)</div>
                                    </div>
                                    <div style='text-align:center;min-width:70px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>QE Score</div>
                                        <div class='mono' style='color:{qec};font-weight:700'>{r['qs']:.0f}/100</div>
                                    </div>
                                    <div style='text-align:center;min-width:100px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Confluence</div>
                                        <div class='mono' style='color:{cpc};font-weight:700'>{r['cp_score']}/{r['cp_max']}</div>
                                        <div style='display:flex;gap:1px;margin-top:3px;width:80px'>{cp_mini_bar}</div>
                                    </div>
                                    <div style='text-align:center;min-width:100px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Diamond</div>
                                        <span class='diamond-badge {r["d_class"]}'>{r['d_status']}</span>
                                    </div>
                                    <div style='text-align:center;min-width:90px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Gold Zone</div>
                                        <div class='mono' style='font-size:.8rem;color:#fbbf24'>${r['gold_zone']:.2f}</div>
                                        <div style='font-size:.7rem;color:{gz_c}'>{r['dist_gz']:+.1f}%</div>
                                    </div>
                                    <div style='text-align:center;min-width:60px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Daily</div>
                                        <div style='font-size:.8rem;color:{"#10b981" if r["struct"]=="BULLISH" else ("#ef4444" if r["struct"]=="BEARISH" else "#f59e0b")}'>{r['struct']}</div>
                                    </div>
                                    <div style='flex:1;min-width:180px'>
                                        <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Summary</div>
                                        <div class='scan-summary' style='font-size:.82rem;color:#e2e8f0;line-height:1.4'>{r['summary']}</div>
                                    </div>
                                </div>
                            </div>""", unsafe_allow_html=True)

                        _explain("🔎 How to use the Scanner",
                            "Look for tickers with <strong>7+ confluence points</strong> and an active <strong>Blue Diamond</strong>. "
                            "Those are your highest-probability setups across the entire watchlist. "
                            "Tickers near their Gold Zone with rising confluence are about to trigger. "
                            "Pink Diamonds mean take profits or avoid new entries on that ticker. "
                            "Sort mentally by confluence score. The higher the number, the stronger the setup.", "neutral")
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
                    _earn_empty = "No upcoming earnings data available for this ticker."
                    if earnings_parse_failed:
                        _earn_empty += " The feed returned a value we could not parse into a date."
                    st.info(_earn_empty)
                else:
                    st.caption("Rows are newest-first. The next on-calendar print (today or later) is highlighted.")
                    st.dataframe(
                        _style_earnings_next_highlight(earn_cal_df, earn_highlight_idx),
                        column_config=_earnings_calendar_column_config(),
                        use_container_width=True,
                        hide_index=True,
                    )

            with st.expander("Quick Reference Guide", expanded=False):
                st.markdown('<div id="guide" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
                _section("Quick Reference Guide", "Plain language glossary for every signal on this desk. Keep it open during live markets.",
                         tip_plain="Reach for this when a label feels fuzzy. Clarity beats impulse every session.")
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
                    ("Market Scanner", "The Scanner checks your entire watchlist in seconds. It calculates Confluence Points, Diamond Status, Gold Zone distance, and Quant Edge for every ticker. Sort by confluence to find the strongest setups across all your stocks. Tickers with 7+ confluence and a Blue Diamond are your best opportunities."),
                ]
                for i in range(0, len(edu), 2):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i][1]}</div></div>", unsafe_allow_html=True)
                    with ec2:
                        if i + 1 < len(edu):
                            st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i + 1][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i + 1][1]}</div></div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
