"""Tab renderers and equity desk: extracted from app.main() (v22 refactor)."""
from __future__ import annotations

import html as _html_mod
import math
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from modules.config import (
    DEFAULT_CONFIG,
    KELLY_DISPLAY_CAP_PCT,
    REF_NOTIONAL,
    RISK_PCT_EXAMPLE,
    journal_add_entry,
    journal_clear,
    journal_close_trade,
    load_config,
    load_journal,
    load_radar_hits,
    radar_add_hit,
    save_radar_hits,
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
    _RADAR_UNIVERSE,
    fetch_watchlist_earnings_heatmap,
    radar_broad_filter,
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
    calc_vol_skew,
    compute_explosion_score,
    fetch_options,
    kelly_criterion,
    quant_edge_score,
    scan_single_ticker,
    watchlist_correlation_matrix_cached,
)
from modules.sentiment import QuantBacktest, Sentiment, WalkForwardBacktest, run_cc_sim_cached
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
    sentinel_ledger_metrics,
    sentinel_ledger_table_rows,
    streamlit_df_widget_key,
    streamlit_show_dataframe,
    walk_up_limit_sell_per_share,
)
from modules.chart import _chart_hoverlabel, build_correlation_heatmap, build_skew_chart
from modules.data import compute_iv_rank_proxy, fetch_earnings_calendar_display, fetch_news_headlines

from .desk_locals import DeskLocals
from .utils import log_warn, safe_float, safe_href, safe_html, safe_last


def classify_vol_skew(skew_pct: Optional[float]) -> Optional[dict]:
    """Single source of truth for the put/call IV skew verdict on the Cash Flow tab.

    AUDIT (medium, ``renderers.py:1224 / 1643 / 1765``): the same tab rendered three
    mutually inconsistent skew readouts: the ±10/±3 tiered card, a one-sided
    ``> 10 / > 5`` tile that painted *every* call-skew reading green "Balanced", and
    ``calc_skew_regime``'s median-ratio bands at 1.25/1.08/0.85. A trader could read
    "Heavy Call Skew", "Balanced" and "Put Fear" for the same chain in one screen.
    All three now render this one classification off one ``calc_vol_skew`` reading.

    ``skew_pct`` is put IV minus call IV in IV points (positive = puts richer).
    Returns ``None`` when the skew is unavailable: the callers print an explicit
    "insufficient IV data" state rather than defaulting to a fake "Balanced".
    """
    try:
        v = float(skew_pct)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if v > 10:
        return {
            "skew": v,
            "color": "#f59e0b",
            "icon": "🔥",
            "label": "Heavy Put Skew",
            "short": "Puts heavily bid, prime edge is selling cash-secured puts.",
            "guide": (
                "Puts are <strong>heavily bid</strong>: smart money is paying up "
                "for downside protection. Put premium is very expensive right now. "
                "<strong>Prime edge: sell cash-secured puts</strong> and collect that "
                "rich premium while the crowd hedges."
            ),
        }
    if v > 3:
        return {
            "skew": v,
            "color": "#f59e0b",
            "icon": "⚡",
            "label": "Elevated Put Skew",
            "short": "Moderate put bid, slight edge to cash-secured puts.",
            "guide": (
                "Moderate put premium elevation: bearish hedging is active. "
                "<strong>Slight edge to selling cash-secured puts.</strong> "
                "Both strategies are viable; use Signal tab to confirm direction."
            ),
        }
    if v < -10:
        return {
            "skew": v,
            "color": "#06b6d4",
            "icon": "🚀",
            "label": "Heavy Call Skew",
            "short": "Calls heavily bid, prime edge is selling covered calls.",
            "guide": (
                "Calls are <strong>heavily bid</strong>: upside speculation is "
                "elevated. Call premium is very expensive right now. "
                "<strong>Prime edge: sell covered calls</strong> and collect that "
                "inflated call premium while the crowd chases."
            ),
        }
    if v < -3:
        return {
            "skew": v,
            "color": "#06b6d4",
            "icon": "📈",
            "label": "Elevated Call Skew",
            "short": "Calls bid above average, slight edge to covered calls.",
            "guide": (
                "Calls are bid above average: bullish speculation is active. "
                "<strong>Slight edge to selling covered calls.</strong> "
                "Either strategy is viable; use Signal tab to confirm direction."
            ),
        }
    return {
        "skew": v,
        "color": "#10b981",
        "icon": "⚖️",
        "label": "Balanced Skew",
        "short": "Put and call premium roughly equal, no hedging bias.",
        "guide": (
            "Put and call premium are roughly equal: no institutional hedging "
            "bias detected. Both covered calls and cash-secured puts offer fair "
            "premium. Let your directional view (Signal tab) decide."
        ),
    }


def expected_value_dollars(credit_100, max_loss, pop_pct) -> Optional[float]:
    """Expected value in dollars, or ``None`` when an input cannot be honestly sourced.

    AUDIT #24: the covered-call line under the "EXPECTED VALUE" card used
    ``pop_cc = min(85, max(50, 100 - otm_pct * 5))`` and ``max_loss = premium * 3``.
    Both were invented. With ``max_loss = 3P``, ``calc_ev`` collapses to
    ``P * (4 * pop - 3)``, which is zero exactly at ``otm_pct == 5.0``, so the whole
    dollar figure was a monotone restatement of "is this strike more than 5% OTM",
    dressed up as expected value under the footer "Positive means edge."

    This gate refuses to print a number unless the probability is a *measured* one
    (the 10k-path Monte Carlo PoP) and the max loss is a *real* contractual one
    (defined-risk spread). A covered call has neither a modelled loss branch nor a
    bounded downside in this app, so its EV comes back ``None`` and the card renders
    an em dash with the reason instead of a fabricated dollar amount.
    """
    try:
        c = float(credit_100)
        ml = float(max_loss)
        p = float(pop_pct)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(c) and math.isfinite(ml) and math.isfinite(p)):
        return None
    if ml <= 0 or not (0.0 <= p <= 100.0):
        return None
    return float(calc_ev(c, ml, p))


def compound_cumulative_return_pct(ret_pct) -> pd.Series:
    """Compound a series of per-trade percentage returns into a cumulative % curve.

    AUDIT (medium, ``renderers.py:2138`` with the axis labelled "Cumulative return (%)"
    at ``2190``): the covered-call simulator plotted ``ret_pct.cumsum()``. Percentages
    of a moving base do not add: 12×(+8%) and 4×(−20%) sums to +16% where the
    compounded truth is +3.1%, and because losses compound harder than gains the
    drawdowns were understated asymmetrically. Index and length are preserved (NaNs
    are skipped exactly as ``cumsum`` did) so the curve stays aligned with entry dates.
    """
    s = pd.to_numeric(pd.Series(ret_pct), errors="coerce").astype(float)
    if s.empty:
        return pd.Series(dtype=float)
    return ((1.0 + s / 100.0).cumprod() - 1.0) * 100.0


def _news_item_markdown_html(item: dict) -> str:
    """Escape headline metadata; allow only http(s) links in href."""
    title = safe_html(item.get("title") or "")
    pub = safe_html(item.get("pub") or "")
    time_ = safe_html(item.get("time") or "")
    href = safe_href(item.get("link") or "")
    lnk = (
        f"<a href='{href}' target='_blank' rel='noopener noreferrer' style='color:#06b6d4'>Read</a>"
        if href
        else ""
    )
    sep = " | " if lnk else ""
    return (
        f"<div class='ni'><strong style='color:#e2e8f0'>{title}</strong><br>"
        f"<span style='color:#64748b;font-size:.8rem'>{pub} {time_}</span>"
        f"{sep}{lnk}</div>"
    )


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
        "Equity desk: focus ticker",
        tickers,
        key=selectbox_key,
        help="Drill into breakout, risk, and support using the last scan payload.",
    )
    ticker_data = next((item for item in scanner_results if item["ticker"] == selected_ticker), None)
    if not ticker_data:
        st.warning("Select a ticker from the Equity Radar scanner above to view the setup.")
        return
    pre_diamond = ticker_data.get("pre_diamond_status") or {}
    signal = pre_diamond.get("signal_strength", "n/a")
    stop_loss = ticker_data.get("stock_stop_price", "n/a")
    price = float(ticker_data.get("price") or 0)
    qs_raw = ticker_data.get("qs", "n/a")
    cp_score = ticker_data.get("cp_score", "n/a")
    cp_max = ticker_data.get("cp_max", "n/a")
    confluence_disp = f"{cp_score}/{cp_max}" if isinstance(cp_score, (int, float)) and isinstance(cp_max, (int, float)) else "n/a"
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
                    help="Pre-diamond targets the 5-6 band; 7+ is Blue Diamond territory on the options path.",
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
            st.metric("Edge Score", qe_disp, help="Overall signal strength 0-100 across Trend, Momentum, Volume, Volatility, and Structure pillars.")
    with eq_tab2:
        st.markdown("### Trade Management")
        r_col1, r_col2, r_col3 = st.columns(3)
        with r_col1:
            with st.container(border=True):
                st.metric(
                    "Suggested Entry",
                    f"${price:,.2f}" if price else "n/a",
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
        sup = pre_diamond.get("support_proximity", "n/a")
        sup_txt = f"{float(sup):.1f}%" if isinstance(sup, (int, float)) else sup
        if sup_txt != "n/a" and not str(sup_txt).endswith("%"):
            sup_txt = f"{sup_txt}%"
        with r_col3:
            with st.container(border=True):
                st.metric(
                    "Distance to Support",
                    sup_txt,
                    help="Proximity to Shadow Low or Gold Zone floor when pre-diamond is active.",
                )
        gz = ticker_data.get("gold_zone")
        rr_txt = "n/a"
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
                rr_txt = f"{reward_px / risk_px:.2f} : 1" if risk_px else "n/a"
        except (TypeError, ValueError):
            rr_txt = "n/a"
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
                "All five gates must pass for **💎 10x Sieve**. Missing Yahoo **float/short** or chain **IV** usually fails a gate, not a verdict on the stock."
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
    st.caption("Last **60** daily closes, context for volatility coil / drift (Yahoo daily bars).")
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


def commit_watchlist(watch_items: list, selected: str, cfg: dict) -> None:
    """Persist watchlist change and trigger rerun (Phase 2.4)."""
    from modules.config import save_config

    csv = ",".join(watch_items)
    st.session_state["_sb_scanner_sync"] = csv
    st.session_state["_sb_watch_selected_sync"] = selected
    merged = {
        **cfg,
        "watchlist": csv,
        "scanner_sort_mode": cfg.get("scanner_sort_mode", DEFAULT_CONFIG["scanner_sort_mode"]),
    }
    save_config(merged)
    st.rerun()


@st.fragment
def render_setup_tab(chart_mood: str, d: DeskLocals) -> None:
    # Bind tab body free variables from DeskLocals
    ticker = d.ticker
    df = d.df
    df_wk = d.df_wk
    df_1mo_spark = d.df_1mo_spark
    vix_1mo_df = d.vix_1mo_df
    macro = d.macro
    news = d.news
    earnings_date_raw = d.earnings_date_raw
    price = d.price
    prev = d.prev
    chg = d.chg
    chg_pct = d.chg_pct
    hi52 = d.hi52
    lo52 = d.lo52
    vix_v = d.vix_v
    qs = d.qs
    qb = d.qb
    use_quant_models = d.use_quant_models
    earnings_near = d.earnings_near
    earnings_dt = d.earnings_dt
    days_to_earnings = d.days_to_earnings
    earnings_parse_failed = d.earnings_parse_failed
    earn_glance = d.earn_glance
    wk_label = d.wk_label
    wk_color = d.wk_color
    struct = d.struct
    fg = d.fg
    fg_label = d.fg_label
    fg_emoji = d.fg_emoji
    fg_advice = d.fg_advice
    macd_bull = d.macd_bull
    obv_up = d.obv_up
    rsi_v = d.rsi_v
    h_v = d.h_v
    al = d.al
    gold_zone_price = d.gold_zone_price
    gold_zone_components = d.gold_zone_components
    cp_score = d.cp_score
    cp_max = d.cp_max
    cp_breakdown = d.cp_breakdown
    cp_bearish = d.cp_bearish
    cp_color = d.cp_color
    cp_label = d.cp_label
    diamonds = d.diamonds
    latest_d = d.latest_d
    d_wr = d.d_wr
    d_avg = d.d_avg
    d_n = d.d_n
    daily_struct = d.daily_struct
    weekly_struct = d.weekly_struct
    rfr = d.rfr
    bluf_cc = d.bluf_cc
    bluf_csp = d.bluf_csp
    bluf_exp = d.bluf_exp
    bluf_dte = d.bluf_dte
    bluf_calls = d.bluf_calls
    bluf_puts = d.bluf_puts
    opt_exps = d.opt_exps
    ref_iv_bluf = d.ref_iv_bluf
    nc = d.nc
    action_strat = d.action_strat
    action_plain = d.action_plain
    mini_mode = d.mini_mode
    mobile_chart_layout = d.mobile_chart_layout
    qs_color = d.qs_color
    qs_status = d.qs_status
    scanner_watchlist = d.scanner_watchlist
    scanner_sort_mode = d.scanner_sort_mode
    auto_scan_interval = d.auto_scan_interval
    equity_capital = d.equity_capital
    global_snap = d.global_snap
    defer_meta = d.defer_meta
    risk_closes_df = d.risk_closes_df
    simple_corr_mult = d.simple_corr_mult
    cm_cached = d.cm_cached

    # ══════════════════════════════════════════════════════════════════
    #  SECTION 2 \u2014 SETUP ANALYSIS
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="setup" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("Setup Analysis", "Trend, range, or fade: here is the read and how to play it without guessing.",
             tip_plain="This block is your bias clock. Uptrends reward measured premium sales with air above price. Ranges invite two sided discipline. Downtrends demand smaller size and wider buffers.")


    sa_left, sa_right = st.columns(2)
    with sa_left:
        cls = "sb" if struct == "BULLISH" else ("sr" if struct == "BEARISH" else "sn")
        st.markdown(
            f"<div class='{cls}'><strong>Market Structure: {safe_html(struct)}</strong></div>",
            unsafe_allow_html=True,
        )
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
            # Institutional mode: replace FFD/HMM jargon with user-friendly labels
            "Institutional mode: <strong>Edge Score</strong> blends the five core pillars with "
            "<strong>Stationary Signal</strong> + <strong>Market Regime</strong> analysis (open diagnostics below)."
            if use_quant_models and isinstance(qb, dict) and qb.get("model") == "blended"
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
                label="Edge Score (Institutional)",
                value=f"{inst_score:.0f}/100",
                delta=f"{delta_q:+.0f} vs Core",
                delta_color="normal" if delta_q >= 0 else "inverse",
            )
            with st.expander("🔬 A/B Engine Diagnostics"):
                st.caption("Comparing core RSI/MA signals against institutional Stationary Signal + Market Regime analysis.")
                col1, col2 = st.columns(2)
                col1.metric("Retail Engine", f"{retail_score:.0f}")
                col2.metric("Quant Engine", f"{inst_score:.0f}", delta=f"{delta_q:+.0f} vs retail")
                _is_blended = isinstance(inst_breakdown, dict) and inst_breakdown.get("model") == "blended"
                if _is_blended:
                    st.success(
                        "Institutional mode active: **Edge Score** blends the five core pillars with "
                        "**Stationary Signal** + **Market Regime** analysis, then fuses Monte Carlo PoP when chain data exists."
                    )
                    i1, i2, i3, i4 = st.columns(4)
                    _rp  = float(inst_breakdown.get("regime_prob_high_vol") or 0.0)
                    _ffd = float(inst_breakdown.get("ffd_last") or 0.0)
                    _rc  = float(inst_breakdown.get("retail_core") or retail_score)
                    _ins = float(inst_breakdown.get("inst_signal") or inst_score)
                    # Extract per-state probabilities from the 3-state HMM
                    _rp_calm   = float(inst_breakdown.get("regime_prob_calm")   or 0.0)
                    _rp_medium = float(inst_breakdown.get("regime_prob_medium") or 0.0)
                    _rp_stress = float(inst_breakdown.get("regime_prob_stress") or 0.0)
                    # ── DIAGNOSTIC LABELS: user-facing names, no model jargon ─────
                    # "Market Regime" replaces "HMM" (user doesn't need to know it's a HMM).
                    # "Stationary Signal" replaces "FFD residual" (FFD is an internal name).
                    # "Institutional Track" replaces "Inst. track" for clarity.
                    # We show the 3-state regime breakdown: Calm / Transitional / Stress.
                    i1.metric(
                        "Market Regime (stress)",
                        f"{_rp * 100:.1f}%",
                        help=(
                            "Composite stress exposure from the 3-state Market Regime model: "
                            f"Calm {_rp_calm*100:.0f}% · Transitional {_rp_medium*100:.0f}% · Stress {_rp_stress*100:.0f}%. "
                            "Higher = model is in a choppy/high-vol state. The desk auto-reduces position size when this rises."
                        ),
                    )
                    i2.metric("Stationary Signal", f"{_ffd:.4f}", help="A momentum-memory signal derived by making prices stationary, it captures trend persistence without the drift noise of raw returns.")
                    i3.metric("Core Edge (5 pillars)", f"{_rc:.1f}", help="Average of Trend, Momentum, Volume, Volatility, and Structure scores, the base edge before institutional blending.")
                    i4.metric("Institutional Track", f"{_ins:.1f}", help="The blended institutional signal before it fuses with the core edge. Driven by Stationary Signal + Market Regime.")
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
                        "**Quant engine matched Retail.** The advanced HMM model needs at least 50 bars of history "
                        "to warm up: both scores are using the standard five-factor model below."
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
                except Exception as _e:
                    log_warn("setup tab quant backtest", _e, ticker=str(ticker))
                    st.error("Backtest simulation failed. Adjust parameters.")
            with st.expander("📊 Walk-Forward Backtest (Blue Diamonds)", expanded=False):
                st.caption(
                    "Point-in-time replay: for each bar in the lookback window, "
                    "confluence is computed using ONLY data available at that point. "
                    "When a Blue Diamond fires, we record the forward return."
                )
                _bt_cols = st.columns(3)
                with _bt_cols[0]:
                    _bt_lookback = st.number_input("Lookback (days)", 60, 365, 180, key="cf_bt_lookback")
                with _bt_cols[1]:
                    _bt_hold = st.number_input("Hold (days)", 3, 30, 10, key="cf_bt_hold")
                with _bt_cols[2]:
                    _bt_conf = st.number_input("Min confluence", 5, 9, 7, key="cf_bt_conf")

                if st.button("Run Backtest", key="cf_run_wf_bt"):
                    with st.spinner("Running walk-forward backtest..."):
                        bt_df = WalkForwardBacktest.run(
                            df,
                            df_wk,
                            lookback_days=int(_bt_lookback),
                            hold_days=int(_bt_hold),
                            min_confluence=int(_bt_conf),
                        )
                    if bt_df.empty:
                        st.info("No Blue Diamonds fired in the lookback window.")
                    else:
                        wins = int(bt_df["Win"].sum())
                        total = int(len(bt_df))
                        avg_ret = float(bt_df["Return %"].mean())
                        st.success(
                            f"**{total} signals** · Win rate **{wins/total*100:.0f}%** · "
                            f"Avg return **{avg_ret:+.2f}%** over {int(_bt_hold)} days"
                        )
                        streamlit_show_dataframe(
                            bt_df,
                            use_container_width=True,
                            hide_index=True,
                            key="cf_wf_bt_results",
                            on_select="ignore",
                            selection_mode=[],
                        )
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
    rv2 = safe_float(safe_last(TA.rsi2(df["Close"])), 50.0) if len(df) > 5 else 50
    adx_v, dip, din = TA.adx(df)
    cci_v = safe_last(TA.cci(df), default=np.nan)
    st_l, st_d = TA.supertrend(df)
    _, kj, sa_ich, sb_ich, _ = TA.ichimoku(df)
    an = safe_float(safe_last(adx_v), 0.0)

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
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>MACD</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if macd_bull else '#ef4444'}'>{'BULLISH' if macd_bull else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Hist: {safe_float(safe_last(h_v), 0.0):.3f}</div></div>", unsafe_allow_html=True)
    with ir:
        if macd_bull:
            _explain("MACD: Buyers Are Winning", "Recent momentum is stronger than the longer term average. Think of a store where this month's sales beat the quarterly average. Buyers are in charge. You can sell Covered Calls at higher strikes with more confidence.", "bull")
        else:
            _explain("MACD: Sellers Are Winning", "Recent momentum dropped below the longer term average. Think of a store where this month's sales fell below the quarterly trend. Be more careful when picking your strike prices.", "bear")

    # ADX
    il, ir = st.columns([1, 2])
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>ADX</div><div class='mono' style='font-size:1.5rem;color:{'#10b981' if an > 25 else '#f59e0b'}'>{an:.1f}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Plus DI {safe_float(safe_last(dip), 0.0):.1f} · Minus DI {safe_float(safe_last(din), 0.0):.1f}</div></div>", unsafe_allow_html=True)
    with ir:
        dip_last = safe_float(safe_last(dip), 0.0)
        din_last = safe_float(safe_last(din), 0.0)
        di_w = "Buyers via plus DI" if dip_last > din_last else "Sellers via minus DI"
        if an > 25:
            _explain("ADX: Strong Trend Detected", f"ADX is {an:.0f}. That is above 25 which means a strong trend is happening. The winner right now is: {di_w}. Think of a business with a clear growth direction. Sell your options in the direction of the trend for the safest play.", "bull" if dip_last > din_last else "bear")
        else:
            _explain("ADX: No Clear Trend", f"ADX is {an:.0f}. That is below 25 which means the market has no clear direction right now. Think of a business in a holding pattern. This is a good time for strategies that profit from sideways movement.", "neutral")

    # CCI + Supertrend row
    il, ir = st.columns([1, 2])
    stb = safe_last(st_d, 0) == 1
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>CCI (20)</div><div class='mono' style='font-size:1.5rem;color:{'#ef4444' if not pd.isna(cci_v) and cci_v > 100 else ('#10b981' if not pd.isna(cci_v) and cci_v < -100 else '#e2e8f0')}'>{cci_v:.0f}</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='tc' style='text-align:center;margin-top:8px'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Supertrend</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if stb else '#ef4444'}'>{'BULLISH' if stb else 'BEARISH'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>${safe_float(safe_last(st_l), 0.0):.2f}</div></div>", unsafe_allow_html=True)
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
        st_price = safe_float(safe_last(st_l), 0.0)
        st_txt = f"The Supertrend is your price floor. It is BULLISH at ${st_price:.2f}. As long as the stock stays above this green line, your shares are safe." if stb else f"The Supertrend is BEARISH at ${st_price:.2f}. It is acting as a falling ceiling above the price. The trend is down. Be defensive and protect your shares."
        _explain("CCI and Supertrend", cci_txt + st_txt, "bull" if stb else "bear")

    # Ichimoku + OBV row
    _sa_ich = safe_last(sa_ich)
    _sb_ich = safe_last(sb_ich)
    above_cloud = (
        _sa_ich is not None
        and _sb_ich is not None
        and not pd.isna(_sa_ich)
        and not pd.isna(_sb_ich)
        and price > max(float(_sa_ich), float(_sb_ich))
    )
    ou = obv_up
    il, ir = st.columns([1, 2])
    with il:
        st.markdown(f"<div class='tc' style='text-align:center'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>Ichimoku</div><div class='mono' style='font-size:1.2rem;color:{'#10b981' if above_cloud else '#ef4444'}'>{'ABOVE CLOUD' if above_cloud else 'IN/BELOW'}</div><div style='font-size:.7rem;color:#64748b;margin-top:6px'>Kijun: ${safe_float(safe_last(kj), 0.0):.2f}</div></div>", unsafe_allow_html=True)
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



@st.fragment
def render_cashflow_tab(cfg: dict, d: DeskLocals) -> None:
    # Bind tab body free variables from DeskLocals
    ticker = d.ticker
    df = d.df
    df_wk = d.df_wk
    df_1mo_spark = d.df_1mo_spark
    vix_1mo_df = d.vix_1mo_df
    macro = d.macro
    news = d.news
    earnings_date_raw = d.earnings_date_raw
    price = d.price
    prev = d.prev
    chg = d.chg
    chg_pct = d.chg_pct
    hi52 = d.hi52
    lo52 = d.lo52
    vix_v = d.vix_v
    qs = d.qs
    qb = d.qb
    use_quant_models = d.use_quant_models
    earnings_near = d.earnings_near
    earnings_dt = d.earnings_dt
    days_to_earnings = d.days_to_earnings
    earnings_parse_failed = d.earnings_parse_failed
    earn_glance = d.earn_glance
    wk_label = d.wk_label
    wk_color = d.wk_color
    struct = d.struct
    fg = d.fg
    fg_label = d.fg_label
    fg_emoji = d.fg_emoji
    fg_advice = d.fg_advice
    macd_bull = d.macd_bull
    obv_up = d.obv_up
    rsi_v = d.rsi_v
    h_v = d.h_v
    al = d.al
    gold_zone_price = d.gold_zone_price
    gold_zone_components = d.gold_zone_components
    cp_score = d.cp_score
    cp_max = d.cp_max
    cp_breakdown = d.cp_breakdown
    cp_bearish = d.cp_bearish
    cp_color = d.cp_color
    cp_label = d.cp_label
    diamonds = d.diamonds
    latest_d = d.latest_d
    d_wr = d.d_wr
    d_avg = d.d_avg
    d_n = d.d_n
    daily_struct = d.daily_struct
    weekly_struct = d.weekly_struct
    rfr = d.rfr
    bluf_cc = d.bluf_cc
    bluf_csp = d.bluf_csp
    bluf_exp = d.bluf_exp
    bluf_dte = d.bluf_dte
    bluf_calls = d.bluf_calls
    bluf_puts = d.bluf_puts
    opt_exps = d.opt_exps
    ref_iv_bluf = d.ref_iv_bluf
    nc = d.nc
    action_strat = d.action_strat
    action_plain = d.action_plain
    mini_mode = d.mini_mode
    mobile_chart_layout = d.mobile_chart_layout
    qs_color = d.qs_color
    qs_status = d.qs_status
    scanner_watchlist = d.scanner_watchlist
    scanner_sort_mode = d.scanner_sort_mode
    auto_scan_interval = d.auto_scan_interval
    equity_capital = d.equity_capital
    global_snap = d.global_snap
    defer_meta = d.defer_meta
    risk_closes_df = d.risk_closes_df
    simple_corr_mult = d.simple_corr_mult
    cm_cached = d.cm_cached

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
        render_equity_setup_desk(_rows_cf or [], "cf_equity_desk_cashflow", prefer_ticker=ticker)
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

        # ── IVR ENVIRONMENT CHECK ─────────────────────────────────────────────
        # IVR measures where the desk's reference IV sits between the cheapest and
        # richest ATM IV across the listed expiries. Below 30 the premium is thin,
        # so selling it carries full assignment risk for a small credit.
        #
        # AUDIT #12: this used to call compute_iv_rank_proxy(ticker, df), the
        # function takes three required positionals (sym, spot, ref_iv_pct), so the
        # TypeError was swallowed by a bare `except` that pinned _ivr_val at 50.0.
        # The warning below was therefore unreachable on every single render. The
        # three other call sites in the repo already pass the correct arity.
        # It is also a term-structure cross-section, NOT a 52-week rank (see the
        # docstring at data.py:1290), so the copy no longer claims "the past year".
        _ivr_val = None
        try:
            if ref_iv_bluf:
                _ivr_info = compute_iv_rank_proxy(ticker, float(price), float(ref_iv_bluf))
                if _ivr_info:
                    _ivr_val = safe_float(_ivr_info.get("rank"), None)
        except Exception as _e:
            log_warn("cashflow tab IV rank proxy", _e, ticker=str(ticker))
            _ivr_val = None
        if _ivr_val is not None and _ivr_val < 30:
            st.warning(
                f"⚠️ **IV Rank is low ({_ivr_val:.0f}/100)**: the reference IV sits near the cheap end of the listed expiry range. "
                "Selling premium in a low-IV environment means collecting thin credits while carrying full assignment or loss risk. "
                "**Desk rule:** wait for IVR ≥ 30 before opening new short-premium positions, "
                "or size down to 50% of your normal contract count."
            )

        # ── WEEKLY BIAS CHECK ─────────────────────────────────────────────────
        # If the weekly timeframe shows BEARISH structure, short puts are fighting
        # the dominant trend: the most dangerous combination in options selling.
        # This fires as an explicit desk override, not just a label.
        if wk_label == "BEARISH":
            st.warning(
                "⚠️ **Weekly trend is BEARISH**: selling naked puts is fighting the dominant timeframe. "
                "Prefer bear call spreads (defined-risk) over cash-secured puts. "
                "If you must sell puts, stay ≥ 10% OTM and use a 21-DTE or shorter cycle."
            )

        if opt_exps:
            st.markdown(
                f"<div class='tc'><div style='text-align:center'><span style='color:#64748b;font-size:.8rem'>ANALYZING</span><br>"
                f"<span style='font-size:1.4rem;font-weight:700;color:#e2e8f0'>{_html_mod.escape(ticker)} @ ${price:.2f}</span></div></div>",
                unsafe_allow_html=True,
            )
            sel_exp = st.selectbox("Expiration", opt_exps[:10], index=min(2, len(opt_exps) - 1), key="sel_exp")

            # ─── IV Term Structure Mini-Table ────────────────────────────────────────
            # Show ATM implied volatility across the next 3 available expirations so
            # the desk can instantly see whether the market is pricing near-term or
            # far-term risk more heavily.
            #
            #   Contango    (near IV < far IV): calm near-term; far-month risk priced in
            #   Backwardation (near IV > far IV): event fear near-term (earnings, macro)
            #
            # Each `fetch_options` call is individually cached (@st.cache_data ttl=300),
            # so repeated renders are free after the first page load.
            _term_rows = []
            for _ts_exp in opt_exps[:3]:
                try:
                    _ts_dte = max(1, (datetime.strptime(_ts_exp, "%Y-%m-%d") - datetime.now()).days)
                    _ts_result, _ = fetch_options(ticker, _ts_exp)
                    _ts_calls = (
                        _ts_result[0]
                        if isinstance(_ts_result, (tuple, list)) and len(_ts_result) == 2
                        else pd.DataFrame()
                    )
                    _ts_calls = _ts_calls if isinstance(_ts_calls, pd.DataFrame) else pd.DataFrame()
                    # ATM IV: nearest call strike to current spot price
                    if (
                        not _ts_calls.empty
                        and "strike" in _ts_calls.columns
                        and "impliedVolatility" in _ts_calls.columns
                    ):
                        _atm_row = _ts_calls.iloc[(_ts_calls["strike"] - price).abs().argsort()[:1]]
                        _raw_iv = _atm_row["impliedVolatility"].values[0] if not _atm_row.empty else None
                        if _raw_iv and np.isfinite(float(_raw_iv)) and float(_raw_iv) > 0:
                            _ts_atm_strike = float(_atm_row["strike"].values[0])
                            _term_rows.append({
                                "Expiry": _ts_exp,
                                "DTE": _ts_dte,
                                "ATM strike": f"${_ts_atm_strike:.0f}",
                                "ATM IV": round(float(_raw_iv) * 100, 1),
                            })
                except Exception as _te:
                    log_warn("term structure mini-table fetch", _te, ticker=str(ticker))

            if len(_term_rows) >= 2:
                # Determine term structure shape from first vs last row
                _ts_near = _term_rows[0]["ATM IV"]
                _ts_far  = _term_rows[-1]["ATM IV"]
                if _ts_near > _ts_far + 2:
                    _ts_shape_label = "📈 Backwardation"
                    _ts_shape_color = "#f59e0b"
                    _ts_shape_tip   = "Near-term vol is elevated: market sees an event risk ahead (earnings, macro)."
                elif _ts_far > _ts_near + 2:
                    _ts_shape_label = "📉 Contango"
                    _ts_shape_color = "#10b981"
                    _ts_shape_tip   = "Far-month vol is higher: near-term looks calm. Better environment for premium sellers."
                else:
                    _ts_shape_label = "➡️ Flat"
                    _ts_shape_color = "#94a3b8"
                    _ts_shape_tip   = "Vol is priced evenly across expirations, no strong near/far bias."

                with st.expander(
                    f"📊 IV Term Structure: {_ts_shape_label}  (near {_ts_near:.0f}% → far {_ts_far:.0f}%)",
                    expanded=False,
                ):
                    st.caption(f"**{_ts_shape_label}:** {_ts_shape_tip}")
                    # Build styled HTML rows
                    _ts_html_rows = ""
                    for _tr in _term_rows:
                        _iv_val = _tr["ATM IV"]
                        # Colour by distance from the near-term IV (highest=warmest)
                        _iv_pct_of_max = _iv_val / max(r["ATM IV"] for r in _term_rows) if _term_rows else 1.0
                        _iv_color = (
                            "#f59e0b" if _iv_pct_of_max > 0.9
                            else "#e2e8f0" if _iv_pct_of_max > 0.7
                            else "#64748b"
                        )
                        _ts_html_rows += (
                            f"<tr>"
                            f"<td style='padding:5px 10px;color:#94a3b8'>{_tr['Expiry']}</td>"
                            f"<td style='padding:5px 10px;color:#e2e8f0;text-align:center'>{_tr['DTE']} days</td>"
                            f"<td style='padding:5px 10px;color:#94a3b8;text-align:center'>{_tr['ATM strike']}</td>"
                            f"<td style='padding:5px 10px;font-weight:700;color:{_iv_color};text-align:center'>{_iv_val:.1f}%</td>"
                            f"</tr>"
                        )
                    st.markdown(
                        f"""<table style="width:100%;border-collapse:collapse;font-size:.85rem;
                                          background:rgba(15,23,42,.6);border-radius:8px">
                          <thead>
                            <tr style="border-bottom:1px solid #334155">
                              <th style="padding:5px 10px;color:#64748b;font-weight:600;text-align:left">Expiry</th>
                              <th style="padding:5px 10px;color:#64748b;font-weight:600;text-align:center">DTE</th>
                              <th style="padding:5px 10px;color:#64748b;font-weight:600;text-align:center">ATM Strike</th>
                              <th style="padding:5px 10px;color:#64748b;font-weight:600;text-align:center">ATM IV</th>
                            </tr>
                          </thead>
                          <tbody>{_ts_html_rows}</tbody>
                        </table>""",
                        unsafe_allow_html=True,
                    )

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
            except Exception as _e:
                log_warn("cashflow tab options dataframe concat", _e, ticker=str(ticker))
                opts_df = pd.DataFrame()
            if not calls.empty or not puts.empty:
                with st.expander("Full option chain, MC PoP % (every strike)", expanded=False):
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
                                        help="10k antithetic simulations: v22.0 Predictive Analytics",
                                    ),
                                },
                            )
                        else:
                            st.caption("No strikes with usable bid/ask for MC PoP in this snapshot.")
                    except Exception as _e:
                        log_warn("cashflow tab chain mc dataframe", _e, ticker=str(ticker))
                        st.caption("MC PoP chain table unavailable for this expiration.")
                _desk_poc = gold_zone_components.get("POC") if isinstance(gold_zone_components, dict) else None
                _desk_hvn = gold_zone_components.get("HVN") if isinstance(gold_zone_components, dict) else None

                # ─── Vol Skew Card ───────────────────────────────────────────────────────────
                # Compare 10%-OTM put IV vs 10%-OTM call IV.
                # Positive skew  = put IV > call IV  → puts are expensive → sell CSPs
                # Negative skew  = call IV > put IV  → calls are expensive → sell CCs
                # This is the single most important structural edge-selector for premium sellers.
                # AUDIT (medium): one calc_vol_skew reading, one classification
                # this card, the Greeks-row VOL SKEW tile and the skew-surface badge
                # all read _skew_verdict so the tab can no longer contradict itself.
                _skew_v, _skew_p_iv, _skew_c_iv = calc_vol_skew(price, calls, puts)
                _skew_verdict = classify_vol_skew(_skew_v)
                if _skew_verdict is not None:
                    _skew_color = _skew_verdict["color"]
                    _skew_icon = _skew_verdict["icon"]
                    _skew_label = _skew_verdict["label"]
                    _skew_guide = _skew_verdict["guide"]
                    # Format display values
                    _put_iv_txt  = f"{_skew_p_iv:.1f}%" if _skew_p_iv is not None else "n/a"
                    _call_iv_txt = f"{_skew_c_iv:.1f}%" if _skew_c_iv is not None else "n/a"
                    _skew_txt    = f"{_skew_verdict['skew']:+.1f}%"
                    st.markdown(
                        f"""<div style="background:rgba(15,23,42,.75);border:1.5px solid {_skew_color};
                                        border-radius:10px;padding:12px 16px;margin:6px 0 14px 0">
                          <div style="font-size:.68rem;font-weight:700;color:{_skew_color};
                                      letter-spacing:.09em;margin-bottom:8px">
                            {_skew_icon} VOL SKEW SIGNAL: STRATEGY EDGE
                          </div>
                          <div style="display:flex;gap:28px;flex-wrap:wrap;margin-bottom:8px">
                            <div>
                              <div style="font-size:.7rem;color:#64748b;margin-bottom:2px">Put IV (10% OTM)</div>
                              <div style="font-size:1.05rem;font-weight:700;color:#f87171">{_put_iv_txt}</div>
                            </div>
                            <div>
                              <div style="font-size:.7rem;color:#64748b;margin-bottom:2px">Call IV (10% OTM)</div>
                              <div style="font-size:1.05rem;font-weight:700;color:#34d399">{_call_iv_txt}</div>
                            </div>
                            <div>
                              <div style="font-size:.7rem;color:#64748b;margin-bottom:2px">Skew (Put − Call)</div>
                              <div style="font-size:1.15rem;font-weight:800;color:{_skew_color}">{_skew_txt}</div>
                            </div>
                            <div>
                              <div style="font-size:.7rem;color:#64748b;margin-bottom:2px">Signal</div>
                              <div style="font-size:.9rem;font-weight:700;color:{_skew_color}">{_skew_label}</div>
                            </div>
                          </div>
                          <div style="font-size:.82rem;color:#cbd5e1;line-height:1.55">{_skew_guide}</div>
                        </div>""",
                        unsafe_allow_html=True,
                    )

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
                            except Exception as e:
                                log_warn("ledger theta desk day (covered call track)", e, ticker=str(ticker))
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
                            # AUDIT (medium): journal_add_entry returns False on a
                            # read-only host. Discarding it made the session ledger row
                            # appear while nothing reached trade_journal.json, so the
                            # trade silently vanished on the next refresh. The close
                            # path already surfaces this; both Track Trade sites now match.
                            _jrnl_ok = journal_add_entry(
                                {
                                    "ticker": str(ticker).upper(),
                                    "option_type": "call",
                                    "strike": float(b["strike"]),
                                    "premium_100": float(b["prem_100"]),
                                    "contracts": int(nc_s),
                                    "iv": float(b.get("iv") or 0),
                                    "expiry": str(sel_exp)[:10],
                                    "entry_date": datetime.now().strftime("%Y-%m-%d"),
                                    "entry_spot": float(price),
                                    "qs_at_entry": float(qs),
                                    "status": "open",
                                }
                            )
                            if _jrnl_ok:
                                st.rerun()
                            else:
                                st.error(
                                    "Tracked in this session only: the trade journal could not be written to disk "
                                    "(read-only host?). This row will not survive a refresh."
                                )
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
                        # \u2500\u2500 CSP OPTIMAL CARD \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
                        # Assignment probability: by Black-Scholes, |put_delta| \u2248 N(-d2)
                        # which is the risk-neutral probability the put expires ITM (i.e.
                        # the stock is below the strike at expiry). This is the single most
                        # important risk metric for a cash-secured put seller.
                        # DELTA_LOW / DELTA_HIGH from Opt mark the prop-desk sweet zone.
                        _csp_assign_prob_pct = abs(b["delta"]) * 100  # e.g. |\u22120.25| \u2192 25%
                        _assign_color = (
                            "#ef4444" if _csp_assign_prob_pct > 35  # high risk
                            else "#f59e0b" if _csp_assign_prob_pct > 20  # moderate
                            else "#10b981"  # safe zone (< 20%)
                        )
                        _assign_txt = (
                            f" | <strong style='color:{_assign_color}'>Assign. risk: "
                            f"{_csp_assign_prob_pct:.0f}%</strong>"
                        )
                        st.markdown(
                            f"<div class='sb'>{opt_html_p}"
                            f"<strong>SELL 1x ${b['strike']:.0f}P @ ${b['mid']:.2f}</strong><br>"
                            f"<span style='font-size:.85rem;color:#94a3b8'>"
                            f"Exp: {sel_exp} ({dte}DTE) | IV: {b['iv']:.1f}% | "
                            f"<strong style='color:{delta_color_p}'>\u0394 {b['delta']:.2f}</strong>"
                            f"{csp_mc_pop_txt}{_assign_txt}<br>"
                            f"Premium: <strong style='color:#10b981'>${b['prem_100']:,.0f}</strong> | "
                            f"OTM: {b['otm_pct']:.1f}% | Eff buy: ${b['eff_buy']:.2f} | "
                            f"OI: {b['oi']:,}</span>"
                            f"{_theta_gamma_desk_line(b.get('theta_gamma_ratio'))}</div>",
                            unsafe_allow_html=True,
                        )
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
                            except Exception as e:
                                log_warn("ledger theta desk day (CSP track)", e, ticker=str(ticker))
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
                            # AUDIT (medium): same discarded-False bug as the CC Track
                            # Trade site above: a failed disk write must be visible.
                            _jrnl_ok = journal_add_entry(
                                {
                                    "ticker": str(ticker).upper(),
                                    "option_type": "put",
                                    "strike": float(b["strike"]),
                                    "premium_100": float(b["prem_100"]),
                                    "contracts": 1,
                                    "iv": float(b.get("iv") or 0),
                                    "expiry": str(sel_exp)[:10],
                                    "entry_date": datetime.now().strftime("%Y-%m-%d"),
                                    "entry_spot": float(price),
                                    "qs_at_entry": float(qs),
                                    "status": "open",
                                }
                            )
                            if _jrnl_ok:
                                st.rerun()
                            else:
                                st.error(
                                    "Tracked in this session only: the trade journal could not be written to disk "
                                    "(read-only host?). This row will not survive a refresh."
                                )
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

                        # ─── CSP Payoff Diagram ───────────────────────────────────────────
                        # Interactive Plotly chart showing the P&L profile of this specific
                        # cash-secured put at expiry across a range of stock prices.
                        #
                        # Mechanics of a short CSP (sell 1 contract at strike K, premium P):
                        #   • Stock ≥ K             → profit = +P  (put expires worthless)
                        #   • Stock = K − P/100     → breakeven (profit = $0)
                        #   • Stock < K             → P&L = P − (K − stock) × 100  (losing)
                        #   • Collateral locked      = K × 100  (cash pledged for assignment)
                        #
                        # Visualizing this helps the trader immediately see how much buffer
                        # they have before the trade starts losing money, and what the worst-
                        # case loss is vs. the premium received.
                        with st.expander("📉 CSP Payoff at Expiry", expanded=False):
                            try:
                                # `go` is imported at module top as `plotly.graph_objects`
                                _pf_strike    = float(b["strike"])
                                _pf_prem_100  = float(b["prem_100"])
                                _pf_breakeven = _pf_strike - _pf_prem_100 / 100.0
                                _pf_max_loss  = -(_pf_strike * 100.0 - _pf_prem_100)

                                # Price axis: 60% to 130% of strike (captures full loss range)
                                _pf_prices = np.linspace(_pf_strike * 0.60, _pf_strike * 1.30, 300)
                                _pf_pnl = np.where(
                                    _pf_prices >= _pf_strike,
                                    _pf_prem_100,                                      # OTM: keep premium
                                    _pf_prem_100 - (_pf_strike - _pf_prices) * 100.0, # ITM: lose on stock move
                                )

                                _pf_fig = go.Figure()
                                # Green fill above zero (profit zone)
                                _pf_fig.add_trace(go.Scatter(
                                    x=_pf_prices.tolist() + _pf_prices[::-1].tolist(),
                                    y=np.where(_pf_pnl >= 0, _pf_pnl, 0.0).tolist() + [0.0] * len(_pf_prices),
                                    fill="toself",
                                    fillcolor="rgba(16,185,129,0.12)",
                                    line=dict(width=0),
                                    showlegend=False,
                                    hoverinfo="skip",
                                ))
                                # Red fill below zero (loss zone)
                                _pf_fig.add_trace(go.Scatter(
                                    x=_pf_prices.tolist() + _pf_prices[::-1].tolist(),
                                    y=np.where(_pf_pnl < 0, _pf_pnl, 0.0).tolist() + [0.0] * len(_pf_prices),
                                    fill="toself",
                                    fillcolor="rgba(239,68,68,0.10)",
                                    line=dict(width=0),
                                    showlegend=False,
                                    hoverinfo="skip",
                                ))
                                # Main P&L line
                                _pf_fig.add_trace(go.Scatter(
                                    x=_pf_prices,
                                    y=_pf_pnl,
                                    mode="lines",
                                    line=dict(color="#06b6d4", width=2.5),
                                    name="P&L",
                                    hovertemplate="Stock: $%{x:.2f}<br>P&L: $%{y:,.0f}<extra></extra>",
                                ))
                                # Vertical markers: current price, strike, breakeven
                                for _vx, _vc, _vl in [
                                    (float(price), "#f59e0b", f"Spot ${price:.2f}"),
                                    (_pf_strike, "#ef4444", f"Strike ${_pf_strike:.0f}"),
                                    (_pf_breakeven, "#94a3b8", f"B/E ${_pf_breakeven:.2f}"),
                                ]:
                                    _pf_fig.add_vline(
                                        x=_vx,
                                        line_width=1.5, line_dash="dash", line_color=_vc,
                                        annotation_text=_vl,
                                        annotation_position="top",
                                        annotation_font_size=10,
                                        annotation_font_color=_vc,
                                    )
                                # Zero P&L baseline
                                _pf_fig.add_hline(y=0, line_width=1, line_color="#475569")
                                _pf_fig.update_layout(
                                    height=250,
                                    margin=dict(l=0, r=0, t=24, b=30),
                                    paper_bgcolor="rgba(0,0,0,0)",
                                    plot_bgcolor="rgba(0,0,0,0)",
                                    showlegend=False,
                                    xaxis=dict(
                                        title="Stock price at expiry",
                                        color="#64748b",
                                        gridcolor="#1e293b",
                                        tickprefix="$",
                                    ),
                                    yaxis=dict(
                                        title="P&L ($)",
                                        color="#64748b",
                                        gridcolor="#1e293b",
                                        tickprefix="$",
                                    ),
                                )
                                st.plotly_chart(_pf_fig, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                                st.caption(
                                    f"Max profit: **${_pf_prem_100:,.0f}** (stock stays above ${_pf_strike:.0f}) · "
                                    f"Breakeven: **${_pf_breakeven:.2f}** · "
                                    f"Max loss (stock → $0): **${abs(_pf_max_loss):,.0f}** "
                                    f"(collateral locked: ${_pf_strike * 100:,.0f})"
                                )
                            except Exception as _pfe:
                                log_warn("CSP payoff diagram", _pfe, ticker=str(ticker))
                                st.caption("Payoff diagram unavailable.")
                    else:
                        st.info("No put strikes met pricing/liquidity checks in this snapshot. Try a nearby expiry or refresh.")

                _explain("\U0001f9e0 What are Delta and Theta?",
                    "<strong>Delta is your win probability.</strong> A Delta of 0.16 means you have an 84 percent chance to keep all the cash and keep your shares. Lower Delta means safer. "
                    "<strong>Theta is your daily paycheck.</strong> Every day that passes, the option loses value. That lost value goes straight into your pocket. Time is literally paying you. "
                    "<strong>OI is how busy the market is.</strong> Higher OI means more traders are active. That means you get better prices when you sell. We filter out anything below 100 OI to protect you.", "neutral")

                with st.expander("📈 Volatility Skew Surface (Tail Risk)", expanded=False):
                    st.caption("Visualizing the 'Smile': Higher IV on puts indicates the market is pricing in heavy downside fear.")
                    try:
                        # AUDIT (medium): this badge used to run calc_skew_regime's
                        # median IV-ratio bands (1.25/1.08/0.85), a third, separately
                        # calibrated verdict that routinely disagreed with the Vol Skew
                        # card above and the Greeks-row tile below on the same chain.
                        # The chart still plots the full smile; only the headline
                        # verdict is unified on the one calc_vol_skew reading.
                        if _skew_verdict is not None:
                            st.markdown(
                                f"""
                                <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 15px; padding: 10px; background: rgba(15, 23, 42, 0.6); border: 1px solid #334155; border-radius: 8px;">
                                    <span style="background: {_skew_verdict['color']}; color: #0f172a; padding: 4px 10px; border-radius: 4px; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.05em;">
                                        {safe_html(_skew_verdict['label'].upper())}
                                    </span>
                                    <span style="color: #cbd5e1; font-size: 0.85rem;">{safe_html(_skew_verdict['short'])} (10% OTM put IV − call IV: {_skew_verdict['skew']:+.1f} pts)</span>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                        else:
                            st.caption("Skew verdict unavailable, no usable 10% OTM put/call IV pair in this snapshot.")
                        skew_fig = build_skew_chart(opts_df, price)
                        if skew_fig:
                            st.plotly_chart(skew_fig, use_container_width=True, config=_PLOTLY_UI_CONFIG)
                        else:
                            st.warning("Insufficient liquidity to plot the volatility skew.")
                    except Exception as e:
                        log_warn("volatility skew surface expander", e, ticker=str(ticker))

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
                                {(
                                    f"Historical probability of profit: <strong style='color:#10b981'>{d_wr:.0f}%</strong> ({d_n} signals backtested)."
                                    if d_n and int(d_n) > 0 else
                                    "No historical win rate yet: this ticker has no completed blue-diamond signals to score against."
                                )}
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
                            # AUDIT #22: the old copy claimed "a strong track record".
                            # RESEARCH_UPGRADE.md:14 measured the opposite when Blue is
                            # used as an entry: t=2.98 full sample but NEGATIVE in the
                            # second half of all 12 configurations: i.e. regime beta.
                            "It describes trend health, not a tested entry: our own backtest found Blue confluence used as an entry "
                            "was negative out of sample in every configuration tried, so treat it as a state to watch rather than a green light. "
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
                        st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>TOP CC GREEKS (r={rfr * 100:.2f}%)</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>Delta: <strong style='color:#e2e8f0'>{gr['delta']:.3f}</strong><br>Theta: <strong style='color:#10b981'>${gr['theta']:.3f}/day</strong><br>Vega: <strong style='color:#e2e8f0'>${gr['vega']:.3f}/1%IV</strong><br>Vanna: <strong style='color:#e2e8f0'>{gr.get('vanna', 0):.5f}</strong> (Δδ per 1% IV)<br>Charm: <strong style='color:#e2e8f0'>{gr.get('charm', 0):.5f}</strong> (Δδ/day)<br>Fair: <strong style='color:#e2e8f0'>${fv:.2f}</strong> | Edge: <strong style='color:{edge_c}'>${edge:+.2f}</strong></div></div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<div class='tc'><span style='color:#64748b'>No CC data for Greeks</span></div>", unsafe_allow_html=True)
                with gk2:
                    # AUDIT #24: only defined-risk lines get a dollar EV. The covered
                    # call has no modelled loss branch here (its downside is foregone
                    # upside above the strike, unbounded and undistributed), so it
                    # prints an em dash with the reason instead of the old
                    # premium×3 / 100−5·OTM% fabrication. See expected_value_dollars.
                    ev_lines = []
                    if cc:
                        b0 = cc[0]
                        _cc_mc_pop = safe_float(b0.get("mc_pop"), None)
                        _cc_pop_txt = f"MC PoP {_cc_mc_pop:.0f}%" if _cc_mc_pop is not None else "MC PoP unavailable"
                        ev_lines.append(
                            f"CC ${b0['strike']:.0f}: <strong style='color:#94a3b8'>-</strong> "
                            f"<span style='color:#64748b'>({_cc_pop_txt}; no defined max loss to price against)</span>"
                        )
                    if ps:
                        b0 = ps[0]
                        ev_ps = expected_value_dollars(b0["credit_100"], b0.get("max_loss"), b0.get("pop"))
                        if ev_ps is None:
                            ev_lines.append("Put Spread: <strong style='color:#94a3b8'>-</strong> <span style='color:#64748b'>(missing max loss or POP)</span>")
                        else:
                            ec = "#10b981" if ev_ps > 0 else "#ef4444"
                            ev_lines.append(f"Put Spread: <strong style='color:{ec}'>${ev_ps:+.0f}</strong> (POP {float(b0['pop']):.0f}%)")
                    joined = "<br>".join(ev_lines) if ev_lines else "N/A"
                    st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>EXPECTED VALUE</div><div style='margin-top:8px;color:#94a3b8;font-size:.85rem'>{joined}</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>Shown only where the max loss is contractual and the probability is modelled. A dash means the number cannot be sourced, not that the trade is flat.</div></div>", unsafe_allow_html=True)
                with gk3:
                    # AUDIT (medium): this tile used a one-sided > 10 / > 5 test that
                    # painted every negative (call-skew) reading green "Balanced".
                    # Now shares the tab's single skew classification.
                    if _skew_verdict is not None:
                        _p_iv_tile = f"{_skew_p_iv:.1f}%" if _skew_p_iv is not None else "n/a"
                        _c_iv_tile = f"{_skew_c_iv:.1f}%" if _skew_c_iv is not None else "n/a"
                        st.markdown(f"<div class='tc'><div style='font-size:.7rem;color:#64748b;text-transform:uppercase'>VOL SKEW</div><div class='mono' style='font-size:1.3rem;color:{_skew_verdict['color']};margin-top:8px'>{_skew_verdict['skew']:+.1f}%</div><div style='color:#94a3b8;font-size:.85rem;margin-top:4px'>Put IV: {_p_iv_tile} | Call IV: {_c_iv_tile}</div><div style='color:#64748b;font-size:.75rem;margin-top:6px'>{safe_html(_skew_verdict['label'])}, {safe_html(_skew_verdict['short'])}</div></div>", unsafe_allow_html=True)
                    else:
                        st.markdown("<div class='tc'><div style='font-size:.7rem;color:#64748b'>VOL SKEW</div><div style='color:#94a3b8;margin-top:8px'>Insufficient IV data</div></div>", unsafe_allow_html=True)

                _explain("\U0001f9e0 What do these numbers mean for me?",
                    "<strong>Expected Value (EV)</strong> is your long term profit margin. Think of it like calculating net profit per product after returns. Positive EV means you have a real edge. Negative means avoid the trade. "
                    "It is only shown for defined-risk lines like the put spread, where the max loss is written into the contract and the probability comes from the model. A covered call has no capped loss to price against, so it shows a dash rather than a guess. "
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



@st.fragment
def render_intel_tab(d: DeskLocals) -> None:
    # Bind tab body free variables from DeskLocals
    ticker = d.ticker
    df = d.df
    df_wk = d.df_wk
    df_1mo_spark = d.df_1mo_spark
    vix_1mo_df = d.vix_1mo_df
    macro = d.macro
    news = d.news
    earnings_date_raw = d.earnings_date_raw
    price = d.price
    prev = d.prev
    chg = d.chg
    chg_pct = d.chg_pct
    hi52 = d.hi52
    lo52 = d.lo52
    vix_v = d.vix_v
    qs = d.qs
    qb = d.qb
    use_quant_models = d.use_quant_models
    earnings_near = d.earnings_near
    earnings_dt = d.earnings_dt
    days_to_earnings = d.days_to_earnings
    earnings_parse_failed = d.earnings_parse_failed
    earn_glance = d.earn_glance
    wk_label = d.wk_label
    wk_color = d.wk_color
    struct = d.struct
    fg = d.fg
    fg_label = d.fg_label
    fg_emoji = d.fg_emoji
    fg_advice = d.fg_advice
    macd_bull = d.macd_bull
    obv_up = d.obv_up
    rsi_v = d.rsi_v
    h_v = d.h_v
    al = d.al
    gold_zone_price = d.gold_zone_price
    gold_zone_components = d.gold_zone_components
    cp_score = d.cp_score
    cp_max = d.cp_max
    cp_breakdown = d.cp_breakdown
    cp_bearish = d.cp_bearish
    cp_color = d.cp_color
    cp_label = d.cp_label
    diamonds = d.diamonds
    latest_d = d.latest_d
    d_wr = d.d_wr
    d_avg = d.d_avg
    d_n = d.d_n
    daily_struct = d.daily_struct
    weekly_struct = d.weekly_struct
    rfr = d.rfr
    bluf_cc = d.bluf_cc
    bluf_csp = d.bluf_csp
    bluf_exp = d.bluf_exp
    bluf_dte = d.bluf_dte
    bluf_calls = d.bluf_calls
    bluf_puts = d.bluf_puts
    opt_exps = d.opt_exps
    ref_iv_bluf = d.ref_iv_bluf
    nc = d.nc
    action_strat = d.action_strat
    action_plain = d.action_plain
    mini_mode = d.mini_mode
    mobile_chart_layout = d.mobile_chart_layout
    qs_color = d.qs_color
    qs_status = d.qs_status
    scanner_watchlist = d.scanner_watchlist
    scanner_sort_mode = d.scanner_sort_mode
    auto_scan_interval = d.auto_scan_interval
    equity_capital = d.equity_capital
    global_snap = d.global_snap
    defer_meta = d.defer_meta
    risk_closes_df = d.risk_closes_df
    simple_corr_mult = d.simple_corr_mult
    cm_cached = d.cm_cached
    scanner_mode = st.session_state.get("_cf_scanner_mode", DEFAULT_CONFIG["scanner_mode"])

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
        atr_v = safe_float(safe_last(TA.atr(df)), 0.0)
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
            if not risk_closes_df.empty and len(risk_closes_df.columns) >= 2:
                risk_corr = PortfolioRisk.build_correlation_matrix(risk_closes_df)
                kelly_overlap = PortfolioRisk.get_overlap_score(risk_corr, ticker)
                kelly_corr_haircut = PortfolioRisk.calc_kelly_haircut(kelly_overlap)
        except Exception as _e:
            log_warn("intel tab kelly overlap", _e, ticker=str(ticker))
            kelly_overlap = 0.0
            kelly_corr_haircut = 1.0
        kelly_effective_haircut = float(kelly_corr_haircut) * float(simple_corr_mult)

        # ── REGIME-CONDITIONAL KELLY MULTIPLIER ──────────────────────────────
        # When the HMM detects a high-volatility / choppy regime, signal reliability
        # degrades: the very indicators the Kelly formula trusts become noisier.
        # Standard practice on institutional desks: downscale Kelly by the degree of
        # "bad regime" probability so position sizes contract automatically in chop.
        #
        # Mapping (graduated, not binary to avoid cliffs):
        #   regime_prob_high_vol = 0.0  →  multiplier = 1.00  (full Kelly)
        #   regime_prob_high_vol = 0.6  →  multiplier = 0.70  (30% reduction)
        #   regime_prob_high_vol = 1.0  →  multiplier = 0.50  (half Kelly, hard floor)
        #
        # Formula: multiplier = max(0.5, 1.0 − 0.5 × regime_prob_high_vol)
        # This effectively acts as an automatic second half-Kelly when in full high-vol
        # regime: consistent with how the prop desk would manually size down in VIX spikes.
        _regime_kelly_mult = 1.0
        _regime_hmm_note = ""
        if use_quant_models and isinstance(qb, dict):
            _regime_prob_hv = float(qb.get("regime_prob_high_vol") or 0.0)
            if _regime_prob_hv > 0.05:  # threshold: ignore noise below 5%
                _regime_kelly_mult = max(0.50, 1.0 - 0.50 * _regime_prob_hv)
                _regime_hmm_note = f" · HMM regime mult ×{_regime_kelly_mult:.2f} (high-vol prob {_regime_prob_hv:.0%})"

        # Fold the regime multiplier into the effective haircut so the Kelly calls below
        # automatically receive the regime-adjusted sizing in one coefficient.
        kelly_effective_haircut = kelly_effective_haircut * _regime_kelly_mult

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
                f"Corr overlap {kelly_overlap:.2f} · overlap haircut x{kelly_corr_haircut:.2f} · simple corr x{simple_corr_mult:.2f}"
                f"{_regime_hmm_note}. Display max {k_cap:.0f}% for risk hygiene.{capped_note}</div></div>",
                unsafe_allow_html=True)
            _explain("Kelly Criterion in plain English",
                f"The Kelly formula can suggest large fractions; here we show <strong>Half Kelly</strong> then <strong>cap the headline at {k_cap:.0f}%</strong> "
                f"so the desk view stays conservative (raw half-Kelly was {k_half:.1f}%). "
                f"On a <strong>${REF_NOTIONAL:,.0f}</strong> illustrative reference, the capped line is <strong>${k_dollars:,.0f}</strong>. "
                "Scale to your own capital; Kelly is a theoretical optimum, not an order size.", "neutral")

            # ── KELLY → CONTRACT COUNT TRANSLATION ──────────────────────────
            # Kelly gives a DOLLAR ALLOCATION. To turn it into actionable contract
            # counts we divide by the per-contract cash requirement:
            #   CSP collateral  = strike × 100  (cash required to secure the put)
            #   CC  collateral  ≈ stock price × 100  (cost of 100 shares per contract)
            # We also show the premium income collected at that contract count so the
            # desk can sanity-check the yield before clicking the ticket.
            #
            # Note: k_dollars is based on REF_NOTIONAL (illustrative reference).
            # The user should substitute their own equity_capital to get their personal
            # contract count: personal_contracts = int(equity_capital * k_show/100 / collateral)
            try:
                if bluf_csp and k_dollars > 0:
                    _k_csp_collateral = float(bluf_csp["strike"]) * 100  # $ to secure 1 put
                    _k_csp_prem = float(bluf_csp["prem_100"])             # premium per contract
                    _k_contracts_csp = max(0, int(k_dollars / _k_csp_collateral)) if _k_csp_collateral > 0 else 0
                    _k_contracts_csp_personal = max(0, int(float(equity_capital) * k_show / 100 / _k_csp_collateral)) if _k_csp_collateral > 0 and equity_capital > 0 else None
                    _k_total_prem_csp = _k_csp_prem * max(1, _k_contracts_csp)
                    _personal_note = (
                        f" | Your capital ({equity_capital:,.0f}): ~{_k_contracts_csp_personal} contract{'s' if _k_contracts_csp_personal != 1 else ''}"
                        if _k_contracts_csp_personal is not None else ""
                    )
                    st.markdown(
                        f"<div class='tc'>"
                        f"<div style='font-size:.7rem;color:#64748b;text-transform:uppercase;margin-bottom:6px'>KELLY → CONTRACTS (CSP ${bluf_csp['strike']:.0f}P)</div>"
                        f"<div style='font-size:1.1rem;font-weight:700;color:#06b6d4'>"
                        f"~{_k_contracts_csp} contract{'s' if _k_contracts_csp != 1 else ''} on ${REF_NOTIONAL:,.0f} ref</div>"
                        f"<div style='font-size:.8rem;color:#94a3b8;margin-top:4px'>"
                        f"${_k_csp_collateral:,.0f} collateral each → ${_k_total_prem_csp:,.0f} premium collected"
                        f"{_personal_note}</div>"
                        f"<div style='font-size:.7rem;color:#64748b;margin-top:4px'>"
                        f"Adjust to your own capital. Each contract covers 100 shares.</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                elif bluf_cc and k_dollars > 0:
                    _k_cc_collateral = float(price) * 100   # approx cost to own 100 shares
                    _k_cc_prem = float(bluf_cc["prem_100"])  # premium per covered call
                    _k_contracts_cc = max(0, int(k_dollars / _k_cc_collateral)) if _k_cc_collateral > 0 else 0
                    _k_contracts_cc_personal = max(0, int(float(equity_capital) * k_show / 100 / _k_cc_collateral)) if _k_cc_collateral > 0 and equity_capital > 0 else None
                    _k_total_prem_cc = _k_cc_prem * max(1, _k_contracts_cc)
                    _personal_note_cc = (
                        f" | Your capital ({equity_capital:,.0f}): ~{_k_contracts_cc_personal} contract{'s' if _k_contracts_cc_personal != 1 else ''}"
                        if _k_contracts_cc_personal is not None else ""
                    )
                    st.markdown(
                        f"<div class='tc'>"
                        f"<div style='font-size:.7rem;color:#64748b;text-transform:uppercase;margin-bottom:6px'>KELLY → CONTRACTS (CC ${bluf_cc['strike']:.0f}C)</div>"
                        f"<div style='font-size:1.1rem;font-weight:700;color:#06b6d4'>"
                        f"~{_k_contracts_cc} contract{'s' if _k_contracts_cc != 1 else ''} on ${REF_NOTIONAL:,.0f} ref</div>"
                        f"<div style='font-size:.8rem;color:#94a3b8;margin-top:4px'>"
                        f"~${_k_cc_collateral:,.0f} stock exposure each → ${_k_total_prem_cc:,.0f} premium collected"
                        f"{_personal_note_cc}</div>"
                        f"<div style='font-size:.7rem;color:#64748b;margin-top:4px'>"
                        f"Requires 100 shares per contract. Adjust to your actual share count.</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            except Exception as _ke:
                log_warn("kelly contract count display", _ke, ticker=str(ticker))

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
    # ── PREMIUM SIMULATOR DISCLAIMER ─────────────────────────────────────────
    # This simulator uses run_edge_backtest() which applies a PROXY formula, NOT
    # the live Quant Edge Score. See QuantBacktest.run_edge_backtest docstring for
    # the exact formula. Use the Walk-Forward Backtest (Quant Edge tab) for a true
    # point-in-time replay of the actual desk signals. These numbers are for color only.
    st.warning(
        "**Simulator uses a simplified momentum proxy, not the live desk formula.** "
        "Premiums are modeled from historical volatility, illustrative, not a promise. "
        "Treat the run as a dress rehearsal; live fills will differ. "
        "For signal-accurate replay, use the Walk-Forward Backtest in the Quant Edge section."
    )
    bc1, bc2, bc3, bc4 = st.columns(4)
    bt_otm = bc1.slider("OTM%", 2, 15, 5, key="sim_otm") / 100
    bt_hold = bc2.slider("Hold (d)", 7, 45, 30, key="sim_hold")
    bt_per = bc3.selectbox("Period", ["6mo", "1y"], index=1, key="sim_period")
    bt_iv = bc4.slider("IV Mult", .5, 2.0, 1.0, .1, key="sim_iv")
    br = run_cc_sim_cached(ticker, bt_per, bt_otm, bt_hold, bt_iv)
    if not br.empty:
        tp = br["premium"].sum() * 1
        # ── CC SIM METRICS + MISSED UPSIDE ──────────────────────────────────
        # "Missed Upside" shows the total gain capped by selling calls on
        # winning trades: the hidden cost of covered calls on strong movers.
        # If premium collected > missed upside the strategy added value;
        # if missed_upside >> premium you sold the ceiling for too cheap.
        _missed_up_total = float(br.get("missed_upside", pd.Series([0.0])).sum()) if "missed_upside" in br.columns else 0.0
        _called_away_pct = float((br["outcome"] == "Called Away").mean() * 100) if "outcome" in br.columns else 0.0
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Trades", len(br))
        m2.metric("Win Rate", f"{(br['profit'] > 0).mean() * 100:.0f}%")
        m3.metric("Avg Ret", f"{br['ret_pct'].mean():.1f}%")
        m4.metric("Est Premium", f"${tp:,.0f}")
        m5.metric(
            "Missed Upside",
            f"${_missed_up_total:,.0f}",
            help=f"Total gain left on the table when stock was called away ({_called_away_pct:.0f}% of trades). "
                 f"If this >> Est Premium, the OTM% was too tight for the underlying's volatility.",
        )
        # AUDIT (medium): percentages of a moving base compound, they do not add.
        # cumsum() plotted 12x(+8%) and 4x(-20%) as +16% where the truth is +3.1%.
        _cum = compound_cumulative_return_pct(br["ret_pct"])
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
                    name="Compounded return",
                    hovertemplate=(
                        "<b>Covered-call sim</b><br>"
                        "Entry %{x|%Y-%m-%d}<br>"
                        "Compounded <b>%{y:+.2f}%</b><extra></extra>"
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
                    text="Modeled compounded return (equity curve, % of starting stake)",
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
                title_text="Compounded cumulative return (%)",
                ticksuffix="%",
                tickformat=".1f",
                **_PLOTLY_AXIS_TITLE,
            )
            st.plotly_chart(fig_b, use_container_width=True, config=_PLOTLY_UI_CONFIG)
        else:
            st.caption(
                f"Mini mode parks the cumulative return chart. Modeled compounded return landed at **{safe_float(safe_last(_cum), 0.0):.1f}%** across {len(br)} trades."
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

    # ── WATCHLIST EARNINGS HEAT MAP ──
    _wl_items = _parse_watchlist_string(d.scanner_watchlist or "")
    if _wl_items:
        with st.expander("📅 Watchlist Earnings Calendar", expanded=False):
            st.caption(
                "**Red = this week** (pause premium selling). "
                "**Yellow = next week** (widen buffers). "
                "**Green = clear** (safe to sell premium)."
            )
            _hm = fetch_watchlist_earnings_heatmap(tuple(_wl_items))
            if not _hm.empty:
                _tw = _hm[_hm["Urgency"] == "this_week"]
                _nw = _hm[_hm["Urgency"] == "next_week"]
                if not _tw.empty:
                    st.warning(
                        f"**{len(_tw)} ticker(s) reporting THIS WEEK:** {', '.join(_tw['Ticker'])}. "
                        "Pause new premium sales: IV crush risk."
                    )
                if not _nw.empty:
                    st.info(
                        f"**{len(_nw)} ticker(s) reporting NEXT WEEK:** {', '.join(_nw['Ticker'])}. "
                        "Widen strike buffers."
                    )
                _colors = {
                    "this_week": "#ef4444",
                    "next_week": "#f59e0b",
                    "this_month": "#94a3b8",
                    "reported": "#64748b",
                    "clear": "#10b981",
                    "unknown": "#475569",
                }
                _cells = []
                for _, _r in _hm.iterrows():
                    _c = _colors.get(_r["Urgency"], "#475569")
                    _days_label = (
                        f"{int(_r['Days'])}d" if _r["Days"] is not None and pd.notna(_r["Days"]) else "n/a"
                    )
                    _cells.append(
                        f"<div style='display:inline-flex;flex-direction:column;align-items:center;"
                        f"padding:8px 12px;margin:3px;border-radius:10px;"
                        f"border:1px solid {_c}40;background:{_c}18;min-width:72px'>"
                        f"<span style='font-size:.72rem;font-weight:800;color:{_c}'>{safe_html(_r['Ticker'])}</span>"
                        f"<span style='font-size:.62rem;color:#94a3b8;margin-top:2px'>{safe_html(str(_r['Date'] or 'n/a'))}</span>"
                        f"<span style='font-size:.58rem;font-weight:700;color:{_c}'>{_days_label}</span>"
                        f"</div>"
                    )
                st.markdown(
                    "<div style='display:flex;flex-wrap:wrap;gap:2px;margin:8px 0'>" + "".join(_cells) + "</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.info("No earnings dates available for the current watchlist.")

    # ══════════════════════════════════════════════════════════════════
    # SECTION 7: MARKET SCANNER (multi-ticker diamond and confluence scan)
    # ══════════════════════════════════════════════════════════════════
    st.markdown('<div id="scanner" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section("🔎 Market Scanner", "One pass across the list for Diamonds, confluence stacks, and Gold Zone distance.",
             tip_plain="Sort mentally by confluence, then hunt for a live Blue Diamond. If nothing clears the bar, flat is a position.")

    watchlist_tickers = _parse_watchlist_string(scanner_watchlist)
    if watchlist_tickers:
        auto_scan_interval = max(0, int(auto_scan_interval or DEFAULT_CONFIG.get("auto_scan_interval", 300)))
        from modules.config import load_config, save_config

        # Conviction hits are logged in-app to radar_hits.json and shown in the
        # Radar History expander. External webhook alerting was removed in v24.0.

        _scan_bundle = st.session_state.get("_cf_scanner_bundle")
        _now_ts = float(time.time())
        _last_scan_ts = float((_scan_bundle or {}).get("scanned_at_ts") or 0.0)
        _has_prior_scan = _last_scan_ts > 0
        _auto_due = bool(
            auto_scan_interval > 0
            and _has_prior_scan
            and (_now_ts - _last_scan_ts) >= auto_scan_interval
        )
        # AUDIT (medium): the copy used to read "Auto refresh every 300s · next in Ns",
        # which describes a timer. There is none, no `run_every`, no `st_autorefresh`
        # anywhere in the repo. The staleness check only fires when some *other*
        # interaction reruns the page, and then it blocks that interaction for tens of
        # seconds. Rather than bolt a background timer onto a scan that already stalls
        # the UI, the copy now states what actually happens.
        _auto_status = st.empty()
        if auto_scan_interval <= 0:
            _auto_status.caption("Auto rescan is off. Set a scan interval in Settings to arm it.")
        elif _has_prior_scan:
            _age = max(0, int(round(_now_ts - _last_scan_ts)))
            _mode = str((_scan_bundle or {}).get("scan_trigger") or "manual")
            if _auto_due:
                _auto_status.caption("Results are stale; rescanning now...")
            else:
                _auto_status.caption(
                    f"Last scan {_age}s ago (trigger: {_mode}). Results go stale at {auto_scan_interval}s, "
                    "there is no background timer, so the rescan runs on your next interaction with this page "
                    "after that, or press Scan Watchlist now."
                )
        else:
            _auto_status.caption(
                f"Rescan armed at {auto_scan_interval}s of staleness, but only after your first manual scan, "
                "and only on a page interaction, not on a timer."
            )
        _manual_scan = st.button("Scan Watchlist", key="run_scanner")
        if _manual_scan or _auto_due:
            with st.spinner("📡 Radar active. Scanning institutional order flow…"):
                _panel_scan = (
                    global_snap.raw_panel
                    if global_snap is not None and global_snap.raw_panel is not None
                    else None
                )
                closes_map = {}
                for tkr in watchlist_tickers:
                    try:
                        cdf = None
                        if _panel_scan is not None:
                            od = _ticker_daily_ohlcv_from_raw(_panel_scan, tkr)
                            if od is not None and "Close" in od.columns and len(od) >= 5:
                                cdf = od.iloc[-260:]
                        if cdf is None:
                            cdf = fetch_stock(tkr, "1y", "1d")
                        if cdf is not None and not cdf.empty and "Close" in cdf.columns:
                            closes_map[tkr] = pd.to_numeric(cdf["Close"], errors="coerce")
                    except Exception as e:
                        log_warn("scanner watchlist close series fetch", e, ticker=str(tkr))
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
                _spy_fetch_err = None
                try:
                    if _panel_scan is not None:
                        sspy = _ticker_daily_ohlcv_from_raw(_panel_scan, "SPY")
                        if sspy is not None and len(sspy) >= 60:
                            spy_df = sspy.iloc[-260:].copy()
                    if spy_df is None or getattr(spy_df, "empty", True):
                        spy_df = fetch_stock("SPY", "1y", "1d")
                except Exception as e:
                    _spy_fetch_err = e
                if _spy_fetch_err is not None:
                    print(
                        f"[cashflow-trader] SPY benchmark fetch failed ({type(_spy_fetch_err).__name__}): "
                        f"{_spy_fetch_err}. RS vs SPY disabled for this scan.",
                        file=sys.stderr,
                        flush=True,
                    )
                elif spy_df is None or getattr(spy_df, "empty", True):
                    print(
                        "[cashflow-trader] SPY benchmark skipped (empty or Yahoo timeout). "
                        "RS vs SPY disabled for this scan.",
                        file=sys.stderr,
                        flush=True,
                    )

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
                            panel_raw=_panel_scan,
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
                    "scanned_at_ts": float(time.time()),
                    "scan_trigger": "manual" if _manual_scan else "auto",
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

                def _ten_x_badge(score):
                    try:
                        s = int(score or 0)
                    except (TypeError, ValueError):
                        s = 0
                    if s >= 7:
                        return f"🥇 {s}/10"
                    if s >= 5:
                        return f"🥈 {s}/10"
                    return f"⚪ {s}/10"

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
                                    else "n/a"
                                ),
                                "EM Safety": r.get("EM Safety", "n/a"),
                                "GEX Regime": r.get("GEX Regime", "n/a"),
                                "Flow / Bias": r.get("Flow / Bias", "n/a"),
                                "Gold Zone Dist %": float(r["dist_gz"]),
                                "Daily": r["struct"],
                                "10x Potential": _ten_x_badge(r.get("10x Potential", 0)),
                                "10x Convexity": r.get("10x Convexity", "n/a"),
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
                                "10x Potential": st.column_config.TextColumn(
                                    "10x Potential",
                                    help="10-factor heuristic score: 7+ gold, 5-6 silver, below 5 neutral.",
                                ),
                                "10x Convexity": st.column_config.TextColumn(
                                    "10x Convexity",
                                    help="Venture-style sieve: float ≤30M, short ≥20%, BBW ≤5th pct (1y), vol Z≥4 (90d), call/put IV ≥1.1. All must pass; Yahoo data often gaps.",
                                ),
                                "Summary": st.column_config.TextColumn("Summary", width="large"),
                            },
                        )

                # AUDIT #22: this list is a WATCHLIST RANKER, not a buy trigger.
                # RESEARCH_UPGRADE.md:14 records the repo's own finding on Blue
                # confluence used as an entry: "regime beta | t=2.98 full sample,
                # NEGATIVE second half, all 12 configs", the full-sample t-stat is
                # regime exposure, and the edge inverted out of sample. The research
                # module's conclusion was `blue_diamond_rank()` = "watchlist ranker,
                # not trigger". The screen is kept because ordering candidates by
                # trend health is still useful; the "💎 CONVICTION" buy framing is not.
                _conviction = [
                    r for r in scanner_results
                    if "BLUE" in str(r.get("d_status", "")) and int(r.get("10x Potential", 0) or 0) >= 5
                ]
                if _conviction:
                    _tickers = ", ".join(
                        f"{_html_mod.escape(str(r.get('ticker')))} ({int(r.get('10x Potential', 0) or 0)}/10)"
                        for r in _conviction[:8]
                    )
                    _more = f" +{len(_conviction) - 8} more" if len(_conviction) > 8 else ""
                    st.info(f"🔷 WATCHLIST RANK, Blue Diamond + 10x score ≥ 5: {_tickers}{_more}")
                    st.caption(
                        "**This is a ranking, not an entry.** Our own research (`RESEARCH_UPGRADE.md`) tested Blue "
                        "confluence as an entry signal across 12 configurations: t = 2.98 on the full sample, but "
                        "**negative in the second half of every configuration**: the full-sample number is regime "
                        "beta, not an edge. Treat these names as candidates to watch and wait for a validated entry "
                        "(the SMA20-reclaim close, `swing_pullback_signal`), not as a buy list."
                    )

                    # Persist each conviction ONCE per ticker per day.
                    #
                    # This block reads back from the cached scanner bundle, and
                    # render_intel_tab is an @st.fragment, so any widget in the tab
                    # (expander, checkbox, selectbox) used to re-enter here and append
                    # duplicate rows. Because save_radar_hits truncates to the last 200
                    # entries, ~67 reruns silently evicted the entire genuine hit history
                    # this tab advertises as "every signal the radar has ever fired".
                    _seen = st.session_state.setdefault("_cf_logged_convictions", set())
                    _today = datetime.now().strftime("%Y-%m-%d")
                    for r in _conviction:
                        _key = (str(r.get("ticker")), _today)
                        if _key in _seen:
                            continue
                        _seen.add(_key)
                        radar_add_hit(
                            {
                                "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "ticker": r["ticker"],
                                "price": r.get("price"),
                                # AUDIT #22: logged as a ranking, not a conviction buy.
                                "source": "scanner_watchlist_rank",
                                "explosion_score": None,
                                # Derived, not assumed, the Tier-2 writer computes this
                                # properly, so hardcoding True produced contradictory
                                # rows for the same ticker in the persisted log.
                                "pre_diamond": bool((r.get("pre_diamond_status") or {}).get("is_pre_diamond", False)),
                                "signal": "🔷 WATCHLIST RANK",
                                "10x_score": r.get("10x Potential"),
                                "qs": r.get("qs"),
                                "struct": r.get("struct"),
                                "confluence": r.get("cp_score"),
                            }
                        )

                with st.expander("10x Screener (score ≥ 5)", expanded=False):
                    _ten_rows = [r for r in scanner_results if int(r.get("10x Potential", 0) or 0) >= 5]
                    if _ten_rows:
                        _ten_df = pd.DataFrame(
                            [
                                {
                                    "Ticker": r.get("ticker"),
                                    "10x Score": int(r.get("10x Potential", 0) or 0),
                                    "Diamond": r.get("d_status", "n/a"),
                                    "Flags": ", ".join(sorted((r.get("10x Flags") or {}).keys())) or "n/a",
                                    "Flow / Bias": r.get("Flow / Bias", "n/a"),
                                    "Summary": r.get("summary", "n/a"),
                                }
                                for r in _ten_rows
                            ]
                        ).sort_values(by=["10x Score", "Ticker"], ascending=[False, True])
                        streamlit_show_dataframe(
                            _ten_df,
                            use_container_width=True,
                            hide_index=True,
                            key="cf_10x_screener_df",
                            on_select="ignore",
                            selection_mode=[],
                        )
                    else:
                        st.caption("No tickers currently score 5+ on the 10x heuristic.")

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
                            sentinel_ledger=st.session_state.get("_cf_ledger"),
                            ffd_correlation_matrix=cm_cached,
                        )
                        if _alloc_rows:
                            with st.expander("$50k Kelly-style mix (Blue Diamonds only)", expanded=False):
                                st.caption(
                                    "Weights blend Quant Edge × Monte Carlo PoP. "
                                    "Each position is trimmed when its sector exceeds 20% of capital (sector guard) "
                                    "and when it's too correlated with your three largest open legs (correlation guard)."
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
                                <div style='font-size:.58rem;color:#64748b;margin-top:3px;line-height:1.25'>MC PoP {float(r.get('scanner_mc_pop') or 0):.1f}% · HVN {('n/a' if r.get('hvn_floor') is None else f"${float(r['hvn_floor']):,.0f}")} · R×{float(r.get('risk_multiplier') or 1):.2f}</div>
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
                            <div style='text-align:center;min-width:88px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>10x Potential</div>
                                <div class='mono' style='font-size:.78rem;color:#facc15;font-weight:700;line-height:1.25'>{_html_mod.escape(_ten_x_badge(r.get("10x Potential", 0)))}</div>
                            </div>
                            <div style='text-align:center;min-width:88px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>10x Sieve</div>
                                <div class='mono' style='font-size:.78rem;color:#a78bfa;font-weight:700;line-height:1.25'>{_html_mod.escape(str(r.get("10x Convexity") or "n/a"))}</div>
                            </div>
                            <div style='text-align:center;min-width:100px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>GEX Regime</div>
                                <div class='mono' style='font-size:.72rem;color:#e2e8f0;font-weight:700;line-height:1.25'>{_html_mod.escape(str(r.get("GEX Regime") or "n/a"))}</div>
                            </div>
                            <div style='text-align:center;min-width:120px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>Flow / Bias</div>
                                <div class='mono' style='font-size:.7rem;color:#e2e8f0;font-weight:700;line-height:1.25'>{_html_mod.escape(str(r.get("Flow / Bias") or "n/a"))}</div>
                            </div>
                            <div style='text-align:center;min-width:72px'>
                                <div style='font-size:.65rem;color:#64748b;text-transform:uppercase'>PoP</div>
                                <div class='mono' style='font-size:.82rem;color:#c4b5fd;font-weight:700'>{(f"{float(r.get('diamond_pop', 0)):.0f}%" if int(r.get("diamond_n") or 0) > 0 else "n/a")}</div>
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
                                sentinel_ledger=st.session_state.get("_cf_ledger"),
                                ffd_correlation_matrix=cm_cached,
                            )
                            for row in _eq_alloc:
                                _alloc_by_tkr[row["ticker"]] = int(row.get("contracts") or 0)

                        equity_rows = []
                        for r in scanner_results:
                            pre = r.get("pre_diamond_status", {"is_pre_diamond": False})
                            signal = pre.get("signal_strength", "n/a") if pre.get("is_pre_diamond") else "n/a"
                            price = float(r.get("price") or 0)
                            shares = (
                                _alloc_by_tkr.get(r["ticker"], 0)
                                if pre.get("is_pre_diamond")
                                else 0
                            )
                            equity_rows.append({
                                "Ticker": r.get("ticker", "n/a"),
                                "Signal": signal,
                                "Price": round(price, 2) if price else "n/a",
                                "Suggested Shares": shares,
                                "Stop Loss": r.get("stock_stop_price", "n/a"),
                                "QE Score": r.get("qs", 0),
                                "Support Proximity (%)": pre.get("support_proximity", "n/a"),
                                "10x Sieve": r.get("10x Convexity", "n/a"),
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
                        render_equity_setup_desk(
                            scanner_results, "cf_equity_desk_scanner", prefer_ticker=ticker
                        )
                    except Exception as _e:
                        log_warn("equity radar table fallback", _e, ticker=str(ticker))
                        st.caption(
                            "Equity Radar temporarily unavailable: showing Options Yield table instead."
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
        st.markdown(f"#### {_html_mod.escape(str(ticker))} News")
        if defer_meta:
            _hl = fetch_news_headlines(str(ticker))
            if _hl:
                for item in _hl:
                    st.markdown(_news_item_markdown_html(item), unsafe_allow_html=True)
            else:
                st.info("No news found.")
        elif news:
            for item in news:
                st.markdown(_news_item_markdown_html(item), unsafe_allow_html=True)
        else:
            st.info("No news found.")
    with m_tab:
        st.markdown("#### Macro Dashboard")
        for k, v in macro.items():
            dc = "#10b981" if v["chg"] >= 0 else "#ef4444"
            k_esc = safe_html(k)
            st.markdown(
                f"<div class='tc' style='padding:10px 14px;margin-bottom:6px'><div style='display:flex;justify-content:space-between'>"
                f"<span style='color:#94a3b8'>{k_esc}</span>"
                f"<span class='mono' style='color:#e2e8f0'>{v['price']:.2f} <span style='color:{dc}'>{v['chg']:+.2f}%</span></span></div></div>",
                unsafe_allow_html=True,
            )
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
            "Plain language glossary for every signal on this desk, including v22 **Shadow move**, **OpEx pin**, **Sentinel Ledger**, **Market Explosion Radar**, and **regime calibration**. Keep it open during live markets.",
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
            ("Edge Score", "Your overall signal strength from 0 to 100. It checks five things: Trend, Momentum, Volume, Volatility, and Structure. Above 70 means prime conditions to sell options. Below 40 means wait for a better setup."),
            ("Shadow Move (purple band)", "The <strong>Shadow</strong> is built from days when volume Z-score says <strong>whale</strong> activity (Z &gt; 2). We sort those closes by price and capture the middle <strong>70% of whale volume</strong>, that price range is shaded <strong>purple</strong> on the chart. Compare it to the gold <strong>Expected Move (1σ)</strong> rails: if the shadow is <strong>narrower</strong> than IV implies, vol may be rich; if <strong>wider</strong>, a larger move than options price may be brewing."),
            ("Shadow breakout (regime calibration)", "When <strong>spot steps outside</strong> the purple Shadow band but <strong>still sits inside</strong> the IV <strong>1σ Expected Move</strong>, the chart tab shows a <strong>purple calibration banner</strong>. Whale prints already led price <strong>past</strong> the liquidity cluster while options vol has <strong>not</strong> fully caught up, watch for institutional-led <strong>trend continuation or reversal</strong> before retail reprices risk."),
            ("Predicted OpEx pin", "A <strong>pink dotted</strong> line estimates where price may <strong>pin</strong> into expiry: we find the strongest dealer <strong>gamma wall</strong> (|GEX| near spot when it matters), then blend toward spot using your desk <strong>Θ/Γ</strong>, high decay efficiency makes the wall more <strong>magnetic</strong>. It is a positioning heuristic, not a settlement promise."),
            ("News bias (Bayesian-style)", "Headlines are scored with a <strong>weighted lexicon</strong>: <strong>forward</strong> phrases (guidance, outlook, forecast) count more than <strong>trailing</strong> words (beat, miss). A line like <em>missed earnings but raised guidance</em> tilts <strong>bullish</strong> because forward guidance outweighs the backward print. Empty or neutral text scores zero."),
            ("My Positions & Edge realization", "Use <strong>Track Trade</strong> on the optimal CC or CSP row to log a leg for this session. The ledger shows model <strong>Δ</strong>, <strong>Θ/day</strong>, and unrealized P&amp;L vs entry premium. <strong>Edge realization %</strong> compares today’s <strong>Edge Score</strong> to the score stored at track time for the <strong>active ticker</strong> (capped at 150%)."),
            ("Pin maturity: Golden zone", "For rows tracked with v22+ snapshots: inside <strong>14 DTE</strong>, if <strong>|Dist. to pin %|</strong> has <strong>shrunk</strong> versus entry and your desk <strong>Θ/day</strong> has <strong>grown</strong> versus entry, the ledger shows <strong>✨ Golden zone</strong>, the window where pin gravity and daily decay often peak together. Older rows without snapshots show a dash."),
            ("Market Scanner", "The Scanner checks your entire watchlist in seconds. It calculates Confluence Points, Diamond Status, Gold Zone distance, and Edge Score for every ticker. Sort by confluence to find the strongest setups across all your stocks. Tickers with 7+ confluence and a Blue Diamond are your best opportunities."),
            ("Market Explosion Radar", "Use the <strong>Radar</strong> tab for a two-tier hunt: <strong>Tier 1</strong> quickly filters a broad universe for squeeze/trend/relative-strength setups, then <strong>Tier 2</strong> runs deep per-ticker diagnostics (pre-diamond + 10x + GEX). Highest-scoring hits are saved to <strong>radar_hits.json</strong> so you can review signal quality over time."),
            ("Header shortcuts (Strategies/Risk/Scanner/News/Guide)", "Top nav links jump to sections inside Streamlit tabs. If you click <strong>Strategies</strong>, <strong>Risk</strong>, <strong>Scanner</strong>, <strong>News</strong>, or <strong>Guide</strong>, the app first activates the correct tab and then scrolls to that anchor. <strong>Guide</strong> also opens the Quick Reference expander automatically."),
        ]
        for i in range(0, len(edu), 2):
            ec1, ec2 = st.columns(2)
            with ec1:
                st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i][1]}</div></div>", unsafe_allow_html=True)
            with ec2:
                if i + 1 < len(edu):
                    st.markdown(f"<div class='edu-card'><strong style='font-size:.82rem;letter-spacing:.01em'>{edu[i + 1][0]}</strong><div style='color:#9fb0c7;font-size:.76rem;margin-top:5px;line-height:1.38'>{edu[i + 1][1]}</div></div>", unsafe_allow_html=True)



@st.fragment
def render_radar_tab(d: DeskLocals) -> None:
    """Market Explosion Radar: broad scan for hidden pre-breakout setups."""
    try:
        ticker = d.ticker
        _ = ticker
        cfg = load_config()

        st.markdown("### 🌎 Market Explosion Radar")
        st.caption(
            "Scans ~100 growth/momentum names for hidden **pre-breakout coils** that retail doesn't see. "
            "**Tier 1** (fast, cheap): single Yahoo batch -> squeeze/Hurst/RS/volume filter. "
            "**Tier 2** (deep): survivors get full pre-diamond + 10x + GEX analysis. "
            "Results persist in **radar_hits.json** so you can track what fired and what happened."
        )

        universe_csv = cfg.get("radar_universe", _RADAR_UNIVERSE)
        col_scan, col_status = st.columns([1, 2])
        with col_scan:
            scan_clicked = st.button(
                "🚀 Scan Market Now",
                type="primary",
                key="cf_radar_scan",
                use_container_width=True,
            )
        with col_status:
            st.empty()

        if scan_clicked:
            with st.spinner("Tier 1: Broad filter (squeeze + Hurst + RS + volume)..."):
                spy_df = fetch_stock("SPY", "1y", "1d")
                spy_closes = None
                if spy_df is not None and not spy_df.empty and "Close" in spy_df.columns:
                    spy_closes = pd.to_numeric(spy_df["Close"], errors="coerce").dropna()
                candidates = radar_broad_filter(universe_csv, spy_closes)

            if not candidates:
                st.warning(
                    "No candidates passed Tier 1 filter. Yahoo may be rate-limiting. Try again in a few minutes."
                )
                return

            st.success(
                f"Tier 1: **{len(candidates)}** candidates passed (squeeze + trend + RS filter)"
            )
            with st.expander(f"Tier 1 candidates ({len(candidates)})", expanded=False):
                st.dataframe(
                    pd.DataFrame(candidates), use_container_width=True, hide_index=True
                )

            top_n = min(25, len(candidates))
            tier2_tickers = [c["ticker"] for c in candidates[:top_n]]
            with st.spinner(
                f"Tier 2: Deep scan on top {top_n} candidates (pre-diamond + 10x + GEX)..."
            ):
                deep_results = []
                progress = st.progress(0)
                for i, tkr in enumerate(tier2_tickers):
                    progress.progress(
                        (i + 1) / top_n,
                        text=f"Deep scanning {tkr}... ({i + 1}/{top_n})",
                    )
                    try:
                        row = scan_single_ticker(tkr, spy_df=spy_df)
                        if row:
                            row["explosion_score"] = compute_explosion_score(row)
                            t1 = next((c for c in candidates if c["ticker"] == tkr), {})
                            row["tier1_pre_score"] = t1.get("pre_score", 0)
                            row["squeeze"] = t1.get("squeeze", False)
                            row["trending"] = t1.get("trending", False)
                            deep_results.append(row)
                    except Exception as e:
                        log_warn("radar tier2 deep scan", e, ticker=tkr)
                progress.empty()

            if not deep_results:
                st.warning(
                    "No tickers passed Tier 2 deep scan. Yahoo may be throttling per-ticker calls."
                )
                return

            deep_results.sort(key=lambda x: x.get("explosion_score", 0), reverse=True)
            scan_time = datetime.now().strftime("%Y-%m-%d %H:%M")
            for r in deep_results[:10]:
                radar_add_hit(
                    {
                        "scan_time": scan_time,
                        "ticker": r["ticker"],
                        "price": r.get("price"),
                        "explosion_score": r.get("explosion_score"),
                        "pre_diamond": bool(
                            (r.get("pre_diamond_status") or {}).get("is_pre_diamond")
                        ),
                        "signal": str(
                            (r.get("pre_diamond_status") or {}).get("signal_strength", "n/a")
                        ),
                        "10x_score": r.get("10x Potential"),
                        "qs": r.get("qs"),
                        "struct": r.get("struct"),
                        "confluence": r.get("cp_score"),
                    }
                )

            st.markdown("### 🔥 Top Explosive Setups")
            for r in deep_results[:10]:
                pre = r.get("pre_diamond_status") or {}
                is_pre = pre.get("is_pre_diamond", False)
                signal = pre.get("signal_strength", "n/a")
                tenx = int(r.get("10x Potential", 0) or 0)
                exp_score = r.get("explosion_score", 0)
                tkr = safe_html(r["ticker"])
                price = safe_float(r.get("price"), 0)
                qs_v = safe_float(r.get("qs"), 0)
                conf = int(r.get("cp_score", 0) or 0)
                struct = safe_html(str(r.get("struct", "n/a")))
                gex = safe_html(str(r.get("GEX Regime", "n/a")))
                d_status = safe_html(str(r.get("d_status", "n/a")))

                if exp_score >= 60:
                    border_color = "#10b981"
                    badge = "🔥 HIGH CONVICTION"
                elif exp_score >= 40:
                    border_color = "#f59e0b"
                    badge = "⚡ COILING"
                else:
                    border_color = "#64748b"
                    badge = "📊 WATCH"

                reasons = []
                if r.get("squeeze"):
                    reasons.append("volatility coiled tight (squeeze)")
                if r.get("trending"):
                    reasons.append("Hurst confirms trending regime")
                if is_pre:
                    reasons.append("pre-diamond accumulation detected")
                if tenx >= 5:
                    reasons.append(f"10x potential score {tenx}/10")
                if conf >= 5:
                    reasons.append(f"confluence {conf}/9 (rising)")
                if "STABLE" in str(r.get("GEX Regime", "")):
                    reasons.append("dealer gamma supports price")
                why_hidden = (
                    " · ".join(reasons) if reasons else "Institutional rotation in progress"
                )

                st.markdown(
                    f"<div style='border:2px solid {border_color};border-radius:14px;padding:16px 20px;"
                    f"margin:8px 0;background:{border_color}10'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px'>"
                    f"<span style='font-size:1.3rem;font-weight:800;color:#e2e8f0'>{tkr}</span>"
                    f"<span style='font-size:.75rem;font-weight:700;color:{border_color};padding:3px 10px;"
                    f"border-radius:8px;border:1px solid {border_color}40;background:{border_color}20'>"
                    f"{badge} · Score {exp_score:.0f}</span></div>"
                    f"<div style='font-size:.9rem;color:#cbd5e1;margin-bottom:6px'>"
                    f"<strong>${price:.2f}</strong> · QE {qs_v:.0f} · Conf {conf}/9 · {struct} · {gex} · {d_status}"
                    f"</div>"
                    f"<div style='font-size:.78rem;color:#94a3b8;margin-bottom:8px'>"
                    f"<strong style='color:#a5b4fc'>Why retail misses this:</strong> {safe_html(why_hidden)}</div>"
                    f"<div style='font-size:.72rem;color:#64748b'>"
                    f"Signal: {safe_html(signal)} · 10x: {tenx}/10 · Stop: ${safe_float(r.get('stock_stop_price'), 0):.2f}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )

                if st.button(
                    f"Add {r['ticker']} to watchlist",
                    key=f"cf_radar_add_{r['ticker']}",
                ):
                    wl = _parse_watchlist_string(st.session_state.get("sb_scanner", ""))
                    if r["ticker"] not in wl:
                        wl.append(r["ticker"])
                        st.session_state["_sb_scanner_sync"] = ",".join(wl)
                        from modules.config import save_config

                        b = load_config()
                        save_config({**b, "watchlist": ",".join(wl)})
                        st.success(
                            f"Added {r['ticker']} to watchlist. Rerun to scan with full desk."
                        )
                        st.rerun()
                    else:
                        st.info(f"{r['ticker']} is already in your watchlist.")

        st.divider()
        st.markdown("### 📋 Radar Hit History")
        st.caption(
            "Every signal the radar has ever fired, with timestamps. Persists across sessions."
        )
        history = load_radar_hits()
        if history:
            hist_df = pd.DataFrame(history)
            if "scan_time" in hist_df.columns:
                hist_df = hist_df.sort_values("scan_time", ascending=False)
            st.dataframe(hist_df, use_container_width=True, hide_index=True)
            if st.button("Clear radar history", key="cf_radar_clear"):
                save_radar_hits([])
                st.rerun()
        else:
            st.info("No radar hits yet. Click **Scan Market Now** above.")
    except Exception as e:
        log_warn("render_radar_tab", e, ticker=str(getattr(d, "ticker", "")))
        st.error("Radar temporarily unavailable due to a data or network issue. Please retry.")


@st.fragment
def render_ledger_tab(d: DeskLocals) -> None:
    # Bind tab body free variables from DeskLocals
    ticker = d.ticker
    df = d.df
    df_wk = d.df_wk
    df_1mo_spark = d.df_1mo_spark
    vix_1mo_df = d.vix_1mo_df
    macro = d.macro
    news = d.news
    earnings_date_raw = d.earnings_date_raw
    price = d.price
    prev = d.prev
    chg = d.chg
    chg_pct = d.chg_pct
    hi52 = d.hi52
    lo52 = d.lo52
    vix_v = d.vix_v
    qs = d.qs
    qb = d.qb
    use_quant_models = d.use_quant_models
    earnings_near = d.earnings_near
    earnings_dt = d.earnings_dt
    days_to_earnings = d.days_to_earnings
    earnings_parse_failed = d.earnings_parse_failed
    earn_glance = d.earn_glance
    wk_label = d.wk_label
    wk_color = d.wk_color
    struct = d.struct
    fg = d.fg
    fg_label = d.fg_label
    fg_emoji = d.fg_emoji
    fg_advice = d.fg_advice
    macd_bull = d.macd_bull
    obv_up = d.obv_up
    rsi_v = d.rsi_v
    h_v = d.h_v
    al = d.al
    gold_zone_price = d.gold_zone_price
    gold_zone_components = d.gold_zone_components
    cp_score = d.cp_score
    cp_max = d.cp_max
    cp_breakdown = d.cp_breakdown
    cp_bearish = d.cp_bearish
    cp_color = d.cp_color
    cp_label = d.cp_label
    diamonds = d.diamonds
    latest_d = d.latest_d
    d_wr = d.d_wr
    d_avg = d.d_avg
    d_n = d.d_n
    daily_struct = d.daily_struct
    weekly_struct = d.weekly_struct
    rfr = d.rfr
    bluf_cc = d.bluf_cc
    bluf_csp = d.bluf_csp
    bluf_exp = d.bluf_exp
    bluf_dte = d.bluf_dte
    bluf_calls = d.bluf_calls
    bluf_puts = d.bluf_puts
    opt_exps = d.opt_exps
    ref_iv_bluf = d.ref_iv_bluf
    nc = d.nc
    action_strat = d.action_strat
    action_plain = d.action_plain
    mini_mode = d.mini_mode
    mobile_chart_layout = d.mobile_chart_layout
    qs_color = d.qs_color
    qs_status = d.qs_status
    scanner_watchlist = d.scanner_watchlist
    scanner_sort_mode = d.scanner_sort_mode
    equity_capital = d.equity_capital
    global_snap = d.global_snap
    defer_meta = d.defer_meta
    risk_closes_df = d.risk_closes_df
    simple_corr_mult = d.simple_corr_mult
    cm_cached = d.cm_cached

    st.markdown('<div id="sentinel-ledger" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section(
        "📊 Sentinel Ledger",
        "Session-based simulated trade log: track desk strikes, then read portfolio-level Greeks and mark-to-model P&L.",
        tip_plain="**Pin maturity ✨ Golden zone** (≤14 DTE): |Dist. to pin %| shrinking vs entry while desk Θ/day rises vs entry, pin magnet strengthens into expiry. "
        "New **Track Trade** rows snapshot dist-to-pin and Θ/day at entry. On the chart tab, **Shadow breakout** flags spot outside the purple whale band but inside IV 1σ, early regime read.",
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
    if not _ldf.empty:
        # Use a content-keyed widget key so Streamlit creates a fresh widget if the
        # column structure ever changes (e.g. on the very first trade tracked).
        # A static key caused a "Bad setIn index" crash in Streamlit 1.39 when the
        # dataframe transitioned from 0 columns (empty ledger) to N columns.
        streamlit_show_dataframe(
            _ldf,
            use_container_width=True,
            hide_index=True,
            key=streamlit_df_widget_key("cf_sentinel_ledger", _ldf),
            on_select="ignore",
            selection_mode=[],
        )

    # ── DTE ROLL ALERTS ───────────────────────────────────────────────────────
    # Professional short-option management uses fixed DTE thresholds to decide
    # when to close/roll before theta decay accelerates toward dangerous levels.
    # The three standard desk rules:
    #   • 21 DTE ("21-days rule"): close/roll ALL short options at 21 DTE regardless
    #     of profit: gamma risk explodes inside 3 weeks; most of the theta has been
    #     captured already (50-70% of premium in the first half of the cycle).
    #   • 50% profit: close the trade at 50% of max profit whenever reached, this
    #     avoids the "last mile" risk of holding through a reversal for a small gain.
    #   • 80% profit: hard exit for high-theta trades where 80% capture represents
    #     strong execution; especially important near earnings or macro events.
    #
    # We compute current DTE from dte_at_entry and entry_date if expiry not stored.
    if _led:
        _today = datetime.now()
        _roll_alerts = []
        for _row in _led:
            try:
                _exp_str = _row.get("expiry", "")
                _entry_dte = int(_row.get("dte_at_entry", 0))
                _entry_date_str = _row.get("entry_date", "")
                _leg = _row.get("leg", _row.get("option_type", "?")).upper()
                _tkr = str(_row.get("ticker", ticker)).upper()
                _strike = float(_row.get("strike", 0))
                _prem_entry = float(_row.get("premium_100", 0))

                # Compute current DTE from stored expiry string
                _current_dte: Optional[int] = None
                if _exp_str:
                    try:
                        _exp_dt = datetime.strptime(str(_exp_str)[:10], "%Y-%m-%d")
                        _current_dte = max(0, (_exp_dt - _today).days)
                    except ValueError:
                        pass

                # Fall back: estimate DTE from entry_date + dte_at_entry
                if _current_dte is None and _entry_date_str and _entry_dte:
                    try:
                        _edt = datetime.strptime(str(_entry_date_str)[:10], "%Y-%m-%d")
                        _days_elapsed = (_today - _edt).days
                        _current_dte = max(0, _entry_dte - _days_elapsed)
                    except ValueError:
                        pass

                if _current_dte is None:
                    continue

                # ── Check 21-DTE roll threshold ──
                if _current_dte <= 21:
                    _roll_alerts.append({
                        "level": "error",
                        "msg": (
                            f"🚨 **{_tkr} {_leg} ${_strike:.0f}, {_current_dte} DTE (≤21 DTE roll threshold)**  "
                            f"Close or roll now. Gamma risk accelerates sharply inside 3 weeks. "
                            f"Most of your theta has been captured. Staying risks a sudden assignment or gap."
                        ),
                    })

                # ── Check 50% / 80% profit capture thresholds ────────────────────
                # Premium sellers' desk rule: don't ride a winner all the way to zero.
                # At 50% profit the risk/reward tilts against you, you keep 50% of
                # max gain but still carry 100% of the downside tail risk.
                # At 80% capture it's a hard desk exit: the remaining edge is tiny
                # relative to the gamma and event risk of holding.
                #
                # We compute current theoretical option price via Black-Scholes,
                # which requires the CURRENT stock price for the row's ticker.
                # For the active ticker we use the already-loaded `price`. For any
                # other tickers in the ledger we skip the alert (no live price
                # available without a fresh fetch).
                if _prem_entry > 0 and _current_dte is not None:
                    try:
                        _iv_row = float(_row.get("iv", 30) or 30) / 100.0
                        _opt_type = str(_row.get("option_type", "put")).lower().strip()
                        if _opt_type not in ("call", "put"):
                            _opt_type = "put"
                        # Use active ticker's spot price; skip rows for other tickers
                        # to avoid stale-data false alerts.
                        if _tkr == str(ticker).upper() and price is not None and price > 0:
                            _T_row = max(_current_dte, 1) / 365.0  # years to expiry
                            _bs_now = float(bs_price(
                                price, _strike, _T_row, float(rfr), _iv_row, _opt_type
                            ))
                            # Current mark per 100 shares (matches premium_100 units)
                            _current_prem_100 = _bs_now * 100.0
                            # Profit = entry premium collected − current mark to buy-back
                            # Short option: profit when current price < entry price.
                            _profit_pct = (
                                (_prem_entry - _current_prem_100) / _prem_entry * 100.0
                            ) if _prem_entry > 0 else 0.0

                            if _profit_pct >= 80.0:
                                _roll_alerts.append({
                                    "level": "error",
                                    "msg": (
                                        f"💰 **{_tkr} {_leg} ${_strike:.0f}, {_profit_pct:.0f}% profit captured (≥80% hard exit)**  "
                                        f"Entry: ${_prem_entry:,.0f} | Est. current mark: ${_current_prem_100:,.0f}.  "
                                        f"Buy this position back NOW. The remaining edge ({100-_profit_pct:.0f}%) "
                                        f"is tiny vs the tail risk of holding through a reversal or event."
                                    ),
                                })
                            elif _profit_pct >= 50.0:
                                _roll_alerts.append({
                                    "level": "warning",
                                    "msg": (
                                        f"🎯 **{_tkr} {_leg} ${_strike:.0f}, {_profit_pct:.0f}% profit captured (≥50% close rule)**  "
                                        f"Entry: ${_prem_entry:,.0f} | Est. current mark: ${_current_prem_100:,.0f}.  "
                                        f"Consider closing. You've banked half the premium "
                                        f"while still carrying full downside risk: desk rule says take it."
                                    ),
                                })
                    except Exception as _pe:
                        log_warn("profit capture alert computation", _pe, ticker=str(ticker))

            except Exception as _re:
                log_warn("DTE roll alert computation", _re, ticker=str(ticker))

        if _roll_alerts:
            st.markdown("#### 🔔 Roll Alerts")
            for _alert in _roll_alerts:
                if _alert["level"] == "error":
                    st.error(_alert["msg"])
                else:
                    st.warning(_alert["msg"])
            st.caption(
                "**Desk roll rules:** close at 21 DTE (gamma risk) · close at 50% profit (efficiency) · close at 80% profit (hard exit). "
                "Never hold a short option through earnings unless fully hedged."
            )

    _m = sentinel_ledger_metrics(_led, rfr=float(rfr), corr_matrix=cm_cached)
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        st.metric("Total portfolio Δ (equiv. shares)", f"{_m['total_delta']:,.2f}")
    with m2:
        st.metric("Total Θ / day (desk income)", f"${_m['total_theta_day']:,.2f}")
    with m3:
        st.metric(
            "Total vega (per +1 IV pt)",
            f"${_m.get('total_vega', 0.0):,.2f}",
            help="Aggregate short-option vega. Negative means portfolio loses value if implied vol rises.",
        )
    with m4:
        _var95 = _m.get("var_95_1d")
        st.metric(
            "VaR 95% (1d, delta-corr)",
            f"${_var95:,.2f}" if _var95 is not None else "n/a",
            help="Approximate 1-day 95% VaR using delta-dollar exposures, 20d realized vol, and cached watchlist correlation matrix.",
        )
    with m5:
        st.metric("Unrealized P&L (model)", f"${_m['unrealized_pnl']:,.2f}")
    with m6:
        _er = _v22.get("avg_edge_realization")
        st.metric(
            "Edge realization (avg, active tickers)",
            f"{_er:.1f}%" if _er is not None else "n/a",
            help="Current Quant Edge vs **qs_at_entry** for ledger rows on the active symbol (capped at 150%).",
        )
    if st.button("Clear Sentinel Ledger", key="cf_ledger_clear"):
        st.session_state["_cf_ledger"] = []
        st.rerun()

    # ── PERSISTENT TRADE JOURNAL ──
    st.divider()
    st.markdown("### 📓 Persistent Trade Journal")
    st.caption("Survives browser closes. Stored in `trade_journal.json`.")

    _journal = load_journal()
    if not _journal:
        st.info("No persistent trades yet. Use **Track Trade** to add entries.")
    else:
        _jrows = []
        for _ji, _je in enumerate(_journal):
            _jstatus = _je.get("status", "open")
            _jrows.append(
                {
                    "#": _ji + 1,
                    "Ticker": _je.get("ticker", "n/a"),
                    "Type": str(_je.get("option_type", "n/a")).upper(),
                    "Strike": f"${float(_je.get('strike', 0)):.0f}",
                    "Premium": f"${float(_je.get('premium_100', 0)):.0f}",
                    "Entry": _je.get("entry_date", "n/a"),
                    "Status": "✅ Closed" if _jstatus == "closed" else "🟢 Open",
                    "P&L": f"${float(_je.get('realized_pnl', 0)):.2f}" if _jstatus == "closed" else "n/a",
                }
            )
        st.dataframe(pd.DataFrame(_jrows), use_container_width=True, hide_index=True)
        _closed = [e for e in _journal if e.get("status") == "closed"]
        if _closed:
            _total_pnl = sum(float(e.get("realized_pnl", 0)) for e in _closed)
            _wins = sum(1 for e in _closed if float(e.get("realized_pnl", 0)) > 0)
            _wr = _wins / len(_closed) * 100.0
            _jm1, _jm2, _jm3 = st.columns(3)
            with _jm1:
                st.metric("Total Realized P&L", f"${_total_pnl:,.2f}")
            with _jm2:
                st.metric("Win Rate", f"{_wr:.0f}%")
            with _jm3:
                st.metric("Closed Trades", str(len(_closed)))
        _open_trades = [(_i, _e) for _i, _e in enumerate(_journal) if _e.get("status") != "closed"]
        if _open_trades:
            with st.expander("Close a trade", expanded=False):
                _labels = [
                    f"#{i+1} {e.get('ticker','?')} {str(e.get('option_type','')).upper()} ${float(e.get('strike',0)):.0f}"
                    for i, e in _open_trades
                ]
                _sel = st.selectbox("Trade", _labels, key="cf_jrnl_close_sel")
                _cpx = st.number_input("Close price ($)", min_value=0.01, value=100.0, step=0.50, key="cf_jrnl_close_px")
                if st.button("Close Trade", key="cf_jrnl_close_btn"):
                    _idx = _open_trades[_labels.index(_sel)][0]
                    if journal_close_trade(_idx, float(_cpx)):
                        st.success("Saved.")
                        st.rerun()
                    else:
                        st.error("Could not write to disk (read-only host?).")
        if st.button("Clear Journal", key="cf_jrnl_clear"):
            journal_clear()
            st.rerun()


