"""
Pre-tab UI: watchlist editor (@st.fragment), Mission Control, tape, config flush,
and post-context header through execution strip. Imported only from app.py (after renderers).
"""
from __future__ import annotations

import html as _html_mod
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

from modules.chart import build_correlation_heatmap
from modules.config import DEFAULT_CONFIG, ConfigTransaction, load_config, save_config
from modules.data import (
    _PLOTLY_UI_CONFIG,
    compute_iv_rank_proxy,
    fetch_global_market_bundle,
    fetch_news_headlines,
)
from modules.options import Opt, kelly_criterion, watchlist_correlation_matrix_cached
from modules.renderers import commit_watchlist
from modules.sentiment import Sentiment
from modules.signal_desk import (
    bento_accents_from_consensus,
    bento_box_html,
    compute_desk_consensus,
    consensus_banner_html,
    consensus_compact_html,
    institutional_heatmap_ribbon_html,
    suggested_shares_atr_risk,
    traders_note_markdown,
    unified_probability_dial_html,
)
from modules.streamlit_threading import make_script_ctx_pool, submit_with_script_ctx
from modules.ta import TA
from modules.ui_helpers import (
    _confluence_why_trade_plain,
    _glance_metric_card,
    _iv_rank_pill_html,
    _parse_watchlist_string,
    _render_html_block,
    earnings_runway_spark_series,
    expected_move_safety_html,
    render_mode_badge,
    sentinel_ledger_table_rows,
    walk_up_limit_sell_per_share,
)
from modules.utils import log_warn, safe_float, safe_html, safe_last


@dataclass
class HudState:
    watch_items: List[str]
    scanner_watchlist: str
    scanner_sort_mode: str
    ticker: str
    equity_capital: int


@st.fragment
def render_watchlist_editor_fragment(cfg_tx: ConfigTransaction) -> None:
    """Watchlist editor only — isolated rerun scope (Phase 3.3)."""
    _wl_expanded = bool(st.session_state.pop("_open_watchlist_editor", False))

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
                    commit_watchlist(watch_items_sb, sel, dict(cfg_tx.current))
            if down_clicked and sel in watch_items_sb:
                idx = watch_items_sb.index(sel)
                if idx < len(watch_items_sb) - 1:
                    watch_items_sb[idx + 1], watch_items_sb[idx] = watch_items_sb[idx], watch_items_sb[idx + 1]
                    scanner_watchlist_sb = ",".join(watch_items_sb)
                    st.session_state["_sb_scanner_sync"] = scanner_watchlist_sb
                    st.session_state["_sb_watch_selected_sync"] = sel
                    commit_watchlist(watch_items_sb, sel, dict(cfg_tx.current))
            if remove_clicked and sel in watch_items_sb:
                watch_items_sb = [t for t in watch_items_sb if t != sel]
                _nsel = watch_items_sb[0] if watch_items_sb else ""
                commit_watchlist(watch_items_sb, _nsel, dict(cfg_tx.current))
            if sort_az and watch_items_sb:
                watch_items_sb = sorted(watch_items_sb)
                sel2 = st.session_state.get("sb_watch_selected")
                _ssel = watch_items_sb[0]
                if sel2 in watch_items_sb:
                    _ssel = sel2
                commit_watchlist(watch_items_sb, _ssel, dict(cfg_tx.current))
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
                commit_watchlist(watch_items_sb, add_ticker, dict(cfg_tx.current))
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


def apply_auto_watchlist_to_cfg_tx(cfg_tx: ConfigTransaction) -> None:
    _auto_wl = _parse_watchlist_string(st.session_state.get("sb_scanner", ""))
    if _auto_wl:
        _auto_csv = ",".join(_auto_wl)
        _disk_cfg = load_config()
        if _auto_csv != (_disk_cfg.get("watchlist") or ""):
            cfg_tx.update(
                watchlist=_auto_csv,
                scanner_sort_mode=_disk_cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"]),
            )


def render_mission_control_hud(cfg_tx: ConfigTransaction, cfg: dict, saved_scanner_mode: str) -> HudState:
    scanner_watchlist_raw = st.session_state.get("sb_scanner", cfg.get("watchlist", ""))
    watch_items = _parse_watchlist_string(scanner_watchlist_raw)
    scanner_watchlist = ",".join(watch_items)

    if watch_items:
        if "_sb_watch_selected_sync" in st.session_state:
            st.session_state["sb_watch_selected"] = st.session_state.pop("_sb_watch_selected_sync")
        if st.session_state.get("sb_watch_selected") not in watch_items:
            st.session_state["sb_watch_selected"] = watch_items[0]
        ticker = st.session_state.get("sb_watch_selected", watch_items[0])
    else:
        st.session_state.pop("sb_watch_selected", None)
        ticker = "PLTR"

    equity_capital = 10000
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
                if save_config({**b, "scanner_mode": scanner_mode}):
                    st.toast(f"Switched to {scanner_mode}.", icon="✅")
                else:
                    st.toast(
                        f"{scanner_mode} is active for this session; config could not be written to disk.",
                        icon="⚠️",
                    )

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

    return HudState(
        watch_items=watch_items,
        scanner_watchlist=scanner_watchlist,
        scanner_sort_mode=scanner_sort_mode,
        ticker=ticker,
        equity_capital=equity_capital,
    )


def render_tape_open_editor_flush(
    cfg_tx: ConfigTransaction,
    hud: HudState,
) -> Tuple[dict, Any]:
    """Yahoo bundle, watchlist tape, prefs flush, disk toast. Returns (cfg, global_snap)."""
    watch_items = hud.watch_items
    ticker = hud.ticker
    scanner_watchlist = hud.scanner_watchlist
    scanner_sort_mode = hud.scanner_sort_mode

    _BUNDLE_WALL_TIMEOUT = 18
    _cache_key = (tuple(watch_items), str(ticker).strip().upper())
    _prev_snap = st.session_state.get("_cf_global_market_bundle")
    _prev_key = st.session_state.get("_cf_global_market_key")
    _global_snap = None
    _tp = None
    _timed_out = False
    try:
        from concurrent.futures import TimeoutError as _FTE

        _tp = make_script_ctx_pool(max_workers=1)
        _fut = submit_with_script_ctx(_tp, fetch_global_market_bundle, tuple(watch_items), ticker)
        _global_snap = _fut.result(timeout=_BUNDLE_WALL_TIMEOUT)
    except _FTE:
        _timed_out = True
        log_warn(
            f"global bundle wall timeout ({_BUNDLE_WALL_TIMEOUT}s)",
            TimeoutError("yf.download too slow for Cloud health check"),
        )
        _global_snap = _prev_snap if _prev_key == _cache_key else _prev_snap
    except Exception as _e:
        log_warn("global bundle fetch", _e)
        _global_snap = _prev_snap
    finally:
        if _tp is not None:
            try:
                # Critical for Cloud health-check: do not block on slow Yahoo worker teardown.
                _tp.shutdown(wait=False, cancel_futures=_timed_out)
            except Exception as _e:
                log_warn("global bundle worker shutdown", _e)

    if _global_snap is None:
        from modules.data import GlobalMarketSnapshot, DeskMarketSnapshot, _macro_defaults_tuple

        _m0, _v0 = _macro_defaults_tuple()
        _global_snap = GlobalMarketSnapshot(
            DeskMarketSnapshot({s: None for s in watch_items}, _m0, _v0),
            pd.DataFrame(),
            None,
            None,
            None,
            None,
            tuple(watch_items),
            tuple(watch_items[:20]),
            {},
            {},
        )
        st.toast("Yahoo data still loading — tape prices may be stale. Refresh in ~30s.", icon="⏳")

    st.session_state["_cf_global_market_bundle"] = _global_snap
    st.session_state["_cf_global_market_key"] = _cache_key

    if watch_items:
        st.markdown('<p class="cf-tape-title">Watchlist tape</p>', unsafe_allow_html=True)
        st.caption("Tap a symbol to promote it to the active ticker. Daily move is versus the prior session close (cached).")
        _tape_pcts = _global_snap.desk.tape_pcts
        _TAPE_CHUNK = 8
        tape_i = 0
        for row_start in range(0, len(watch_items), _TAPE_CHUNK):
            row_tickers = watch_items[row_start : row_start + _TAPE_CHUNK]
            tape_cols = st.columns(_TAPE_CHUNK)
            for j in range(_TAPE_CHUNK):
                with tape_cols[j]:
                    if j >= len(row_tickers):
                        st.empty()
                        continue
                    tkr = row_tickers[j]
                    pct = _tape_pcts.get(tkr)
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

    watch_cfg = {**cfg_tx.current, "watchlist": scanner_watchlist, "scanner_sort_mode": scanner_sort_mode}
    if watch_cfg != cfg_tx.current:
        cfg_tx.update(watchlist=scanner_watchlist, scanner_sort_mode=scanner_sort_mode)

    prefs_cfg = {
        **cfg_tx.current,
        "strat_focus": st.session_state.get("sb_strat_radio", DEFAULT_CONFIG["strat_focus"]),
        "strat_horizon": st.session_state.get("sb_horizon_radio", DEFAULT_CONFIG["strat_horizon"]),
        "mini_mode": bool(st.session_state.get("sb_mini_mode", cfg_tx.current.get("mini_mode", False))),
        "use_quant_models": bool(
            st.session_state.get(
                "sb_use_quant", cfg_tx.current.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"])
            )
        ),
    }
    if prefs_cfg != cfg_tx.current:
        cfg_tx.update(
            strat_focus=prefs_cfg["strat_focus"],
            strat_horizon=prefs_cfg["strat_horizon"],
            mini_mode=prefs_cfg["mini_mode"],
            use_quant_models=prefs_cfg["use_quant_models"],
        )

    _pending_cfg_keys = frozenset(cfg_tx.pending_keys)
    _flush_ok = cfg_tx.flush()
    cfg = cfg_tx.current
    if not _flush_ok and "watchlist" in _pending_cfg_keys and not st.session_state.get("_cf_watchlist_disk_warned"):
        st.session_state["_cf_watchlist_disk_warned"] = True
        st.toast(
            "Watchlist not written to disk. Use Streamlit Secrets `watchlist` for Cloud, or run the app locally.",
            icon="⚠️",
        )

    return cfg, _global_snap


def render_desk_after_context(
    ctx: Any,
    cfg: dict,
    hud: HudState,
    _global_snap: Any,
    ema_extension_warn_pct: float,
) -> Tuple[str, str, pd.DataFrame, float, Optional[Any]]:
    """
    Consensus header → glance row → recommended trade → bluf_html → execution strip → alerts.
    Returns (master_html, bluf_html, _risk_closes_df, _simple_corr_mult, _cm_cached).
    """
    ticker = hud.ticker
    watch_items = hud.watch_items
    df = ctx.df
    df_wk = ctx.df_wk
    df_1mo_spark = ctx.df_1mo_spark
    vix_1mo_df = ctx.vix_1mo_df
    price = ctx.price
    prev = ctx.prev
    chg = ctx.chg
    chg_pct = ctx.chg_pct
    hi52 = ctx.hi52
    lo52 = ctx.lo52
    vix_v = ctx.vix_v
    qs = ctx.qs
    qb = ctx.qb
    use_quant_models = bool(cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))
    earnings_near = ctx.earnings_near
    earnings_dt = ctx.earnings_dt
    days_to_earnings = ctx.days_to_earnings
    earnings_parse_failed = ctx.earnings_parse_failed
    earn_glance = ctx.earn_glance
    wk_label = ctx.wk_label
    wk_color = ctx.wk_color
    struct = ctx.struct
    fg = ctx.fg
    fg_label = ctx.fg_label
    fg_emoji = ctx.fg_emoji
    fg_advice = ctx.fg_advice
    macd_bull = ctx.macd_bull
    obv_up = ctx.obv_up
    rsi_v = ctx.rsi_v
    h_v = ctx.h_v
    al = ctx.al
    gold_zone_price = ctx.gold_zone_price
    gold_zone_components = ctx.gold_zone_components
    cp_score = ctx.cp_score
    cp_max = ctx.cp_max
    cp_breakdown = ctx.cp_breakdown
    cp_bearish = ctx.cp_bearish
    cp_color = ctx.cp_color
    cp_label = ctx.cp_label
    diamonds = ctx.diamonds
    latest_d = ctx.latest_d
    d_wr = ctx.d_wr
    d_avg = ctx.d_avg
    d_n = ctx.d_n
    daily_struct = ctx.daily_struct
    weekly_struct = ctx.weekly_struct
    rfr = ctx.rfr
    bluf_cc = ctx.bluf_cc
    bluf_csp = ctx.bluf_csp
    bluf_exp = ctx.bluf_exp
    bluf_dte = ctx.bluf_dte
    bluf_calls = ctx.bluf_calls
    bluf_puts = ctx.bluf_puts
    opt_exps = ctx.opt_exps
    ref_iv_bluf = ctx.ref_iv_bluf
    nc = ctx.nc
    action_strat = ctx.action_strat
    action_plain = ctx.action_plain
    mini_mode = ctx.mini_mode
    mobile_chart_layout = ctx.mobile_chart_layout
    qs_color = ctx.qs_color
    qs_status = ctx.qs_status

    st.session_state["_cf_earnings_days"] = days_to_earnings

    _tku_rs = str(ticker).upper().strip()
    _rs_map = getattr(_global_snap, "rs_spy_ratio_map", None) or {}
    _rs_row = _rs_map.get(_tku_rs) if isinstance(_rs_map, dict) else None
    _rs_for_desk = float(_rs_row) if _rs_row is not None and np.isfinite(float(_rs_row)) else None
    _er_note = None
    try:
        _led_note = st.session_state.get("_cf_ledger") or []
        _, _sum_note = sentinel_ledger_table_rows(
            _led_note,
            active_ticker=_tku_rs,
            active_qs=float(qs),
            pin_map=st.session_state.get("_cf_opex_pin_map") or {},
            rfr=float(getattr(ctx, "rfr", 0.045)),
        )
        _er_note = _sum_note.get("avg_edge_realization")
    except Exception as e:
        log_warn("sentinel ledger edge note for consensus", e, ticker=str(ticker))
        _er_note = None
    try:
        _fund_sieve = (getattr(_global_snap, "fundamental_sieve_map", None) or {}).get(_tku_rs)
    except Exception as e:
        log_warn("fundamental sieve lookup", e, ticker=str(ticker))
        _fund_sieve = None
    _consensus = compute_desk_consensus(
        ctx, df, rs_spy_ratio=_rs_for_desk, fundamental_sieve=_fund_sieve
    )

    render_mode_badge(use_quant_models)
    st.markdown(
        "<div style='margin:2px 0 10px 0'>"
        "<span style='font-size:0.72rem;color:#c4b5fd;padding:3px 10px;border-radius:6px;"
        "border:1px solid rgba(139,92,246,0.45);background:rgba(76,29,149,0.22);font-weight:600;letter-spacing:0.04em'>"
        "v22.0 · PREDICTIVE ANALYTICS</span></div>",
        unsafe_allow_html=True,
    )

    st.session_state["_cf_bluf_cc_pick"] = bluf_cc
    st.session_state["_cf_bluf_csp_pick"] = bluf_csp
    st.session_state["_cf_gamma_flip"] = None
    try:
        _gf_ctx = getattr(ctx, "gamma_flip", None)
        if _gf_ctx is not None and np.isfinite(float(_gf_ctx)):
            st.session_state["_cf_gamma_flip"] = float(_gf_ctx)
    except (TypeError, ValueError):
        st.session_state["_cf_gamma_flip"] = None

    _tku = str(ticker).strip().upper()
    _risk_closes_df = pd.DataFrame()
    _portfolio_lr_df = pd.DataFrame()
    _simple_corr_mult = 1.0
    try:
        _risk_syms = list(dict.fromkeys([str(t).strip().upper() for t in watch_items if t]))[:20]
        if _tku not in _risk_syms:
            _risk_syms.append(_tku)
        _risk_closes_df = _global_snap.risk_closes_df
        if len(_risk_closes_df.columns) >= 2 and len(_risk_closes_df) >= 5:
            _portfolio_lr_df = TA.ffd_returns_from_closes(_risk_closes_df, d=0.4)
            if _portfolio_lr_df.empty:
                _portfolio_lr_df = np.log(_risk_closes_df / _risk_closes_df.shift(1)).dropna()
            _simple_corr_mult = Opt._simple_corr_haircut(_risk_syms, _tku, _portfolio_lr_df)
    except Exception as e:
        log_warn("portfolio risk closes / corr mult", e, ticker=_tku)
        _risk_closes_df = pd.DataFrame()
        _portfolio_lr_df = pd.DataFrame()
        _simple_corr_mult = 1.0

    _cm_cached = None
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
    except Exception as e:
        log_warn("building correlation heatmap for portfolio risk expander", e, ticker=_tku)
    try:
        if (
            _cm_cached is not None
            and not _cm_cached.empty
            and _tku in [str(c).strip().upper() for c in _cm_cached.columns]
        ):
            _colu = [str(c).strip().upper() for c in _cm_cached.columns]
            if _tku in _colu:
                _ser = _cm_cached[_tku]
                _peers = _ser.drop(labels=[_tku], errors="ignore")
                if len(_peers):
                    _mx = float(_peers.max())
                    _peer = str(_peers.idxmax())
                    if _mx > 0.75:
                        st.warning(
                            f"**Correlated book risk:** `{_html_mod.escape(_tku)}` vs `{_html_mod.escape(_peer)}` "
                            f"≈ **{_mx:.2f}** on this matrix — positions may move together; size and hedges accordingly."
                        )
    except Exception as e:
        log_warn("correlated book risk warning from correlation matrix", e, ticker=_tku)

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

    if not mini_mode:
        _rs_u = _consensus.get("rs_spy_ratio")
        if _rs_u is not None and np.isfinite(float(_rs_u)):
            _rs_ln = f"RS vs SPY (~90d batch ratio) **{float(_rs_u):.2f}** — tilt in the blend"
        else:
            _rs_ln = "RS vs SPY: **not in batch map** — RS tilt neutral in the blend"
        st.markdown(
            unified_probability_dial_html(
                ticker,
                float(_consensus.get("unified_probability") or 0),
                qs=float(qs),
                conf_pct=float(100.0 * cp_score / max(1, int(cp_max))),
                rs_line=_rs_ln,
            ),
            unsafe_allow_html=True,
        )

    if mini_mode:
        st.markdown(consensus_compact_html(ticker, _consensus), unsafe_allow_html=True)
    else:
        st.markdown(consensus_banner_html(ticker, _consensus), unsafe_allow_html=True)
        st.markdown(
            traders_note_markdown(
                ticker,
                ctx,
                df,
                _consensus,
                alpha_realization_pct=_er_note,
                turbo_desk=False,
            )
        )
        st.markdown(institutional_heatmap_ribbon_html(_consensus), unsafe_allow_html=True)
        _acc = bento_accents_from_consensus(_consensus)
        _b1 = bento_box_html(
            "THE SETUP",
            "Is the spring coiled?",
            _consensus["setup_hint"].replace("**", ""),
            accent=_acc["setup"],
        )
        _b2 = bento_box_html(
            "THE MOMENTUM",
            "Is flow confirming?",
            _consensus["momentum_hint"].replace("**", ""),
            accent=_acc["momentum"],
        )
        _b3 = bento_box_html(
            "THE EXIT",
            "Where is the plan?",
            _consensus["exit_hint"].replace("**", ""),
            accent=_acc["exit"],
        )
        bc1, bc2, bc3 = st.columns(3)
        with bc1:
            st.markdown(_b1, unsafe_allow_html=True)
        with bc2:
            st.markdown(_b2, unsafe_allow_html=True)
        with bc3:
            st.markdown(_b3, unsafe_allow_html=True)
        with st.expander("Calculate position size (conviction × Kelly-style risk vs ATR stop)", expanded=False):
            _cm = float(_consensus.get("conviction_multiplier") or 1.0)
            _cl = str(_consensus.get("conviction_label") or "")
            st.caption(
                "Not connected to your broker. Enter **account size** and **base risk %**; stop distance uses "
                "~**1.5× 14d ATR** below spot. **Conviction multiplier** (COIL / ICEBERG / SWEEP from the heatmap) "
                "scales effective risk: **1.0×** baseline, **1.25×** COIL and/or absorption, **1.5×** VWAP urgency, **2.0×** all three."
            )
            st.markdown(
                f"<div style='font-size:0.78rem;color:#a5b4fc;margin:0 0 10px 0;padding:8px 12px;border-radius:10px;"
                f"border:1px solid rgba(129,140,248,0.35);background:rgba(67,56,202,0.12)'>"
                f"<strong style='color:#c4b5fd'>Active conviction</strong> · ×{_cm:.2f} — {_html_mod.escape(_cl)}</div>",
                unsafe_allow_html=True,
            )
            _pc1, _pc2 = st.columns(2)
            with _pc1:
                _acct = st.number_input("Account ($)", min_value=0.0, value=100000.0, step=1000.0, key="cf_pos_acct")
            with _pc2:
                _rpct = st.number_input("Base risk per trade (%)", min_value=0.1, max_value=5.0, value=1.0, step=0.1, key="cf_pos_risk")
            _atr_u = float(_consensus.get("atr_last") or 0)
            _eff_r = float(_rpct) * _cm
            _sh = suggested_shares_atr_risk(_acct, _eff_r, float(price), _atr_u, 1.5)
            if _sh is not None and _sh > 0 and _atr_u > 0:
                _stop = float(price) - 1.5 * _atr_u
                st.success(
                    f"~**{_sh:,}** shares ≈ **{_eff_r:.2f}%** effective risk of `${_acct:,.0f}` "
                    f"(**{_rpct:.1f}%** × **{_cm:.2f}** conviction) if stop ≈ **${_stop:,.2f}** "
                    f"(**1.5× ATR** ≈ `${1.5 * _atr_u:,.2f}` below **${price:,.2f}**)."
                )
            else:
                st.info("ATR or price unavailable — cannot size from this snapshot.")
            if int(getattr(ctx, "d_n", 0) or 0) >= 3 and float(getattr(ctx, "d_wr", 0) or 0) > 0:
                _w = float(max(1.0, min(99.0, ctx.d_wr)))
                _kf, _kh = kelly_criterion(_w, 1.0, 1.0, use_quant=False)
                st.caption(
                    f"Illustrative **binary Kelly** from diamond win rate **{_w:.0f}%** vs **1:1** payoff: "
                    f"full **{_kf}%** · half **{_kh}%** of bankroll — not a recommendation; use your own edge math."
                )

    if earnings_near and earnings_dt:
        _ed = earnings_dt.strftime("%b %d, %Y") if hasattr(earnings_dt, "strftime") else str(earnings_dt)
        st.markdown(
            f"""<div style='background:linear-gradient(135deg,rgba(245,158,11,.15),rgba(217,119,6,.1));
            border:2px solid #f59e0b;border-radius:12px;padding:16px 20px;margin:0 0 16px 0'>
            <span style='font-size:1.1rem;color:#f59e0b;font-weight:700'>⚠️ EARNINGS IN {days_to_earnings} DAYS</span>
            <span style='color:#94a3b8;font-size:.9rem;display:block;margin-top:4px'>
            Implied volatility is rich because the print is close. Picture a retailer marking up tags before a holiday rush.
            Assignment risk on short calls jumps with that backdrop. We pause auto alerts until after {safe_html(_ed)}.</span></div>""",
            unsafe_allow_html=True,
        )

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
    except Exception as e:
        log_warn("fetch headlines for trade header", e, ticker=str(ticker))
        _headlines_v19 = []
        _news_bias_v19 = None
    _inst_flow_lbl = "—"
    try:
        _dp_tr = TA.get_dark_pool_proxy(df)
        if _dp_tr is not None and len(_dp_tr) and "dark_pool_alert" in _dp_tr.columns:
            _inst_flow_lbl = (
                "High Accumulation" if bool(safe_last(_dp_tr["dark_pool_alert"], False)) else "Normal"
            )
    except Exception as e:
        log_warn("computing dark pool proxy for institutional flow label", e, ticker=str(ticker))
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
        except Exception as _e:
            log_warn("render_desk_after_context parse bluf expiry", _e, ticker=str(ticker))
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

        def _fallback_pick(df_opt, side):
            if not isinstance(df_opt, pd.DataFrame) or df_opt.empty:
                return None
            w = df_opt.copy()
            w["strike"] = pd.to_numeric(w.get("strike"), errors="coerce")
            w["bid"] = pd.to_numeric(w.get("bid"), errors="coerce").fillna(0.0)
            w["ask"] = pd.to_numeric(w.get("ask"), errors="coerce").fillna(0.0)
            w["lastPrice"] = pd.to_numeric(w.get("lastPrice"), errors="coerce").fillna(0.0)
            w["mid"] = (w["bid"] + w["ask"]) / 2.0
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
            except Exception as _e:
                log_warn("render_desk_after_context fallback expiry dte", _e, ticker=str(ticker))
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
        _e20 = safe_last(TA.ema(df["Close"], 20))
        if _e20 is not None and not pd.isna(_e20) and float(_e20) > 0:
            ema_dist_pct = abs(price / float(_e20) - 1.0) * 100.0

    d_badge_html = ""
    if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
        if latest_d["type"] == "blue":
            d_badge_html = "<span class='diamond-badge badge-blue'>🔷 BLUE DIAMOND ACTIVE</span>"
        else:
            d_badge_html = "<span class='diamond-badge badge-pink'>💎 PINK DIAMOND: TAKE PROFIT</span>"
    else:
        d_badge_html = "<span class='diamond-badge badge-none'>◇ No Active Diamond</span>"

    iv_rank_info = compute_iv_rank_proxy(ticker, price, ref_iv_bluf) if ref_iv_bluf else None
    ext_warn_html = ""
    if ema_dist_pct is not None and ema_dist_pct > ema_extension_warn_pct:
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

    cp_bar_html = ""
    for i in range(cp_max):
        filled = i < cp_score
        color = "#10b981" if filled and cp_score >= 7 else ("#f59e0b" if filled and cp_score >= 4 else ("#ef4444" if filled else "#1e293b"))
        cp_bar_html += f"<div style='flex:1;height:10px;background:{color};border-radius:5px;margin:0 1px'></div>"

    gz_gap_pct = ((price / gold_zone_price - 1) * 100) if gold_zone_price else 0.0
    show_gold_glance = bool(st.session_state.get("sb_gold_zone", True))
    _wk_l = safe_html(wk_label)
    _cp_lab = safe_html(cp_label)
    _qs_st = safe_html(qs_status)
    _ds = safe_html(daily_struct)
    _ws = safe_html(weekly_struct)
    bluf_html = f"""<div class='bluf'>
        <div style='display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px'>
            <div>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>QUANT EDGE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{qs_color}'>{qs:.0f}</span>
                <span style='color:{qs_color};font-size:.9rem;margin-left:8px'>{_qs_st}</span>
            </div>
            <div style='text-align:center'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.1em'>CONFLUENCE</div>
                <span class='mono' style='font-size:2.5rem;font-weight:800;color:{cp_color}'>{cp_score}/{cp_max}</span>
                <span style='color:{cp_color};font-size:.9rem;display:block'>{_cp_lab}</span>
                <div style='display:flex;gap:2px;margin-top:6px;width:160px'>{cp_bar_html}</div>
            </div>
            <div style='text-align:right'>
                <div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>WEEKLY TREND</div>
                <span style='font-size:1.2rem;font-weight:700;color:{wk_color}'>{_wk_l}</span>
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
                <span style='font-size:.85rem;color:{"#10b981" if daily_struct=="BULLISH" else ("#ef4444" if daily_struct=="BEARISH" else "#f59e0b")}'>Daily: {_ds}</span>
                <span style='margin:0 8px;color:#334155'>|</span>
                <span style='font-size:.85rem;color:{"#10b981" if weekly_struct=="BULLISH" else ("#ef4444" if weekly_struct=="BEARISH" else "#f59e0b")}'>Weekly: {_ws}</span>
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

    st.markdown('<div id="execution" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _ex_left, _ex_right = st.columns([1.25, 1])
    with _ex_left:
        st.markdown(_render_html_block(master_html), unsafe_allow_html=True)
    with _ex_right:
        st.markdown(_render_html_block(bluf_html), unsafe_allow_html=True)

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

    return master_html, bluf_html, _risk_closes_df, _simple_corr_mult, _cm_cached
