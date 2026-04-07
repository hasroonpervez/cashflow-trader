"""One-off generator: builds modules/desk_locals.py and modules/renderers.py from app.py slices."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text().splitlines()

DESK_FIELDS = [
    "ticker",
    "df",
    "df_wk",
    "df_1mo_spark",
    "vix_1mo_df",
    "macro",
    "news",
    "earnings_date_raw",
    "price",
    "prev",
    "chg",
    "chg_pct",
    "hi52",
    "lo52",
    "vix_v",
    "qs",
    "qb",
    "use_quant_models",
    "earnings_near",
    "earnings_dt",
    "days_to_earnings",
    "earnings_parse_failed",
    "earn_glance",
    "wk_label",
    "wk_color",
    "struct",
    "fg",
    "fg_label",
    "fg_emoji",
    "fg_advice",
    "macd_bull",
    "obv_up",
    "rsi_v",
    "h_v",
    "al",
    "gold_zone_price",
    "gold_zone_components",
    "cp_score",
    "cp_max",
    "cp_breakdown",
    "cp_bearish",
    "cp_color",
    "cp_label",
    "diamonds",
    "latest_d",
    "d_wr",
    "d_avg",
    "d_n",
    "daily_struct",
    "weekly_struct",
    "rfr",
    "bluf_cc",
    "bluf_csp",
    "bluf_exp",
    "bluf_dte",
    "bluf_calls",
    "bluf_puts",
    "opt_exps",
    "ref_iv_bluf",
    "nc",
    "action_strat",
    "action_plain",
    "mini_mode",
    "mobile_chart_layout",
    "qs_color",
    "qs_status",
    "scanner_watchlist",
    "scanner_sort_mode",
    "equity_capital",
    "global_snap",
    "defer_meta",
    "risk_closes_df",
    "simple_corr_mult",
    "cm_cached",
]


def extract(start: int, end: int, dedent: int = 8) -> str:
    chunk = APP[start - 1 : end]
    out = []
    for ln in chunk:
        if not ln.strip():
            out.append("")
            continue
        if len(ln) >= dedent and ln[:dedent] == " " * dedent:
            out.append(ln[dedent:])
        else:
            out.append(ln)
    return "\n".join(out)


def strip_pltr_block(setup: str) -> str:
    """Remove hardcoded PLTR strategic intelligence block (Phase 2.5 Option A)."""
    pat = re.compile(
        r"\n[ \t]*if ticker == \"PLTR\":\n(?:[ \t]+.*\n)*?(?=\n[ \t]*sa_left,)",
        re.MULTILINE,
    )
    return pat.sub("\n", setup, count=1)


def write_desk_locals():
    lines = [
        '"""Snapshot of desk locals passed to tab renderers (no Streamlit)."""',
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from typing import Any",
        "",
        "",
        "@dataclass",
        "class DeskLocals:",
        '    """Mirrors main() unpack + intel/scanner fields used by tab bodies."""',
    ]
    for f in DESK_FIELDS:
        lines.append(f"    {f}: Any = None")
    lines.append("")
    (ROOT / "modules" / "desk_locals.py").write_text("\n".join(lines) + "\n")


def build_unpack_assignments() -> str:
    lines = ["    # Bind tab body free variables from DeskLocals"]
    for f in DESK_FIELDS:
        lines.append(f"    {f} = d.{f}")
    return "\n".join(lines)


IMPORT_BLOCK = '''
"""Tab renderers and equity desk — extracted from app.main() (v22 refactor)."""
from __future__ import annotations

import html as _html_mod
import math
import re
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from modules.config import (
    DEFAULT_CONFIG,
    KELLY_DISPLAY_CAP_PCT,
    REF_NOTIONAL,
    RISK_PCT_EXAMPLE,
)
from modules.data import (
    _PLOTLY_AXIS_TITLE,
    _PLOTLY_BLUE,
    _PLOTLY_CASH_DOWN,
    _PLOTLY_CASH_UP,
    _PLOTLY_FONT_MAIN,
    _PLOTLY_GRID,
    _PLOTLY_PAPER_BG,
    _PLOTLY_PLOT_BG,
    _PLOTLY_UI_CONFIG,
    _ticker_daily_ohlcv_from_raw,
    fetch_global_market_bundle,
    fetch_stock,
    list_option_expiration_dates,
)
from modules.options import (
    Opt,
    PortfolioRisk,
    bs_greeks,
    bs_price,
    build_chain_mc_dataframe,
    calc_ev,
    calc_skew_regime,
    fetch_options,
    kelly_criterion,
    quant_edge_score,
    scan_single_ticker,
    watchlist_correlation_matrix_cached,
)
from modules.sentiment import QuantBacktest, Sentiment, run_cc_sim_cached
from modules.signal_desk import suggested_shares_atr_risk, whale_session_x_for_chart
from modules.ta import TA
from modules.ui_helpers import (
    SCANNER_WHALE_FLOW_BIAS_HELP,
    _PRICE_LEVEL_COLUMN_CONFIG,
    _df_price_levels,
    _earnings_calendar_column_config,
    _explain,
    _fragment_rolling_edge_capture,
    _options_scan_column_config,
    _options_scan_dataframe,
    _parse_watchlist_string,
    _section,
    _theta_gamma_desk_line,
    earnings_runway_spark_series,
    ledger_theta_desk_day,
    streamlit_df_widget_key,
    streamlit_show_dataframe,
    walk_up_limit_sell_per_share,
)
from modules.chart import build_correlation_heatmap, build_skew_chart
from modules.data import compute_iv_rank_proxy, fetch_earnings_calendar_display, fetch_news_headlines

from .desk_locals import DeskLocals
from .utils import log_warn, safe_float, safe_last, safe_html
'''

EQUITY_FN = '''
def render_equity_setup_desk(scanner_results, selectbox_key: str, prefer_ticker=None) -> None:
    """Delta-One equity drill-down from cached scanner rows; optional 60D close chart (one fetch per focus ticker)."""
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
            with st.container(border=True):
                st.metric(
                    "Volatility State",
                    pre_diamond.get("volatility_state", "NORMAL"),
                    help="SQUEEZED means bottom 25% of 60-day ATR (or BBW) range when pre-diamond fired.",
                )
        with col2:
            with st.container(border=True):
                st.metric(
                    "Confluence Score",
                    confluence_disp,
                    help="Pre-diamond targets the 5–6 band; 7+ is Blue Diamond territory on the options path.",
                )
        with col3:
            with st.container(border=True):
                st.metric(
                    "Relative Strength",
                    "Strong vs SPY" if "🔥" in str(signal) else "Neutral/Weak",
                    help="3-day return vs SPY when the pre-diamond stack triggered.",
                )
        qe_disp = f"{float(qs_raw):.0f}/100" if isinstance(qs_raw, (int, float)) else str(qs_raw)
        with st.container(border=True):
            st.metric("Quant Edge (QE)", qe_disp, help="Same QE score as the scanner row.")
    with eq_tab2:
        st.markdown("### Trade Management")
        r_col1, r_col2, r_col3 = st.columns(3)
        with r_col1:
            with st.container(border=True):
                st.metric(
                    "Suggested Entry",
                    f"${price:,.2f}" if price else "—",
                    help="Spot from the scan bar.",
                )
        with r_col2:
            with st.container(border=True):
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
            with st.container(border=True):
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
        with st.container(border=True):
            st.metric(
                "Risk / Reward (to Gold Zone)",
                rr_txt,
                help="(Gold Zone − spot) ÷ (spot − stop) per share when all inputs exist; illustrative target only.",
            )

    _cvx = ticker_data.get("convexity_sieve")
    if isinstance(_cvx, dict) and _cvx.get("gates"):
        with st.expander("🧪 Asymmetric Convexity sieve (diagnostics)", expanded=False):
            st.caption(
                "All five gates must pass for **💎 10x Sieve**. Missing Yahoo **float/short** or chain **IV** usually fails a gate — not a verdict on the stock."
            )
            _g = _cvx["gates"]
            for label, key in (
                ("Float ≤30M", "float"),
                ("Short ≥20%", "short"),
                ("BBW ≤5th pct (1y)", "bbw"),
                ("Vol Z ≥4 (90d)", "vol_z"),
                ("Call IV / Put IV ≥1.1", "skew"),
            ):
                block = _g.get(key) or {}
                st.write(f"**{label}:** {'✅' if block.get('ok') else '⬜'} `{block}`")

    st.divider()
    st.markdown("### 📊 Structure visualizer")
    st.caption("Last **60** daily closes — context for volatility coil / drift (Yahoo daily bars).")
    try:
        from modules.data import fetch_stock as _eq_fetch

        _eq_df = _eq_fetch(str(selected_ticker).upper(), "1y", "1d")
    except Exception as e:
        log_warn("equity desk structure fetch", e, ticker=str(selected_ticker))
        _eq_df = None
    if _eq_df is not None and not _eq_df.empty and "Close" in _eq_df.columns:
        _chart_data = pd.DataFrame({"Close": pd.to_numeric(_eq_df["Close"], errors="coerce")}).dropna().tail(60)
        if not _chart_data.empty:
            with st.container(border=True):
                _wx = whale_session_x_for_chart(_eq_df, z_threshold=4.0)
                try:
                    _fig_eq = go.Figure(
                        data=[
                            go.Scatter(
                                x=_chart_data.index,
                                y=_chart_data["Close"],
                                mode="lines",
                                name="Close",
                                line=dict(color="#3b82f6", width=2),
                            )
                        ]
                    )
                    if _wx is not None:
                        _fig_eq.add_vline(
                            x=_wx,
                            line_width=1,
                            line_dash="dash",
                            line_color="#22d3ee",
                            annotation_text="Whale vol",
                            annotation_position="top",
                        )
                    _fig_eq.update_layout(
                        height=220,
                        margin=dict(l=8, r=8, t=28, b=8),
                        template="plotly_dark",
                        paper_bgcolor=_PLOTLY_PAPER_BG,
                        plot_bgcolor=_PLOTLY_PLOT_BG,
                        showlegend=False,
                        xaxis=dict(showgrid=True, gridcolor=_PLOTLY_GRID),
                        yaxis=dict(showgrid=True, gridcolor=_PLOTLY_GRID),
                    )
                    st.plotly_chart(_fig_eq, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                except Exception as e:
                    log_warn("equity desk plotly chart", e, ticker=str(selected_ticker))
                    try:
                        st.line_chart(
                            _chart_data,
                            y="Close",
                            color="#3b82f6",
                            height=200,
                            use_container_width=True,
                        )
                    except TypeError:
                        st.line_chart(_chart_data, height=200, use_container_width=True)
        else:
            st.caption("Not enough clean close data for a spark window.")
    else:
        st.caption("Price history unavailable for this symbol right now.")
'''


def write_renderers():
    setup = strip_pltr_block(extract(1652, 2152))
    cash = extract(2154, 2573)
    intel = extract(2575, 3403)
    intel = (
        intel.replace("_global_snap", "global_snap")
        .replace("_defer_meta", "defer_meta")
        .replace("_risk_closes_df", "risk_closes_df")
        .replace("_simple_corr_mult", "simple_corr_mult")
        .replace("_cm_cached", "cm_cached")
    )
    cash = cash.replace("_render_equity_setup_desk", "render_equity_setup_desk")
    ledger = extract(3405, 3456)

    unpack = build_unpack_assignments()

    body = f'''{IMPORT_BLOCK.strip()}

{EQUITY_FN.strip()}


def commit_watchlist(watch_items: list, selected: str, cfg: dict) -> None:
    """Persist watchlist change and trigger rerun (Phase 2.4)."""
    from modules.config import save_config

    csv = ",".join(watch_items)
    st.session_state["_sb_scanner_sync"] = csv
    st.session_state["_sb_watch_selected_sync"] = selected
    merged = {{
        **cfg,
        "watchlist": csv,
        "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"]),
    }}
    save_config(merged)
    st.rerun()


@st.fragment
def render_setup_tab(chart_mood: str, d: DeskLocals) -> None:
{unpack}

{setup}


@st.fragment
def render_cashflow_tab(cfg: dict, d: DeskLocals) -> None:
{unpack}

{cash}


@st.fragment
def render_intel_tab(d: DeskLocals) -> None:
{unpack}

{intel}


@st.fragment
def render_ledger_tab(d: DeskLocals) -> None:
{unpack}

{ledger}
'''
    (ROOT / "modules" / "renderers.py").write_text(body + "\n")


def main():
    write_desk_locals()
    write_renderers()
    print("Wrote modules/desk_locals.py and modules/renderers.py")


if __name__ == "__main__":
    main()
