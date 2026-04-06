"""
Page section renderers — each function renders one section of the dashboard.
All share a DashContext dataclass computed once in main().
"""
import streamlit as st
import html as _html_mod
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime

from .ta import TA
from .data import (
    fetch_stock, fetch_options, fetch_macro,
    fetch_news_headlines, fetch_earnings_date, fetch_earnings_calendar_display,
    _PLOTLY_UI_CONFIG, _PLOTLY_GRID, _PLOTLY_FONT_MAIN,
    _PLOTLY_PAPER_BG, _PLOTLY_PLOT_BG, _PLOTLY_CASH_UP, _PLOTLY_CASH_DOWN,
    _client_suggests_mobile_chart,
)
from .options import (
    bs_price, bs_greeks, calc_ev, kelly_criterion, calc_vol_skew,
    quant_edge_score, weekly_trend_label, calc_gold_zone,
    calc_confluence_points, detect_diamonds, latest_diamond_status,
    diamond_win_rate, scan_single_ticker, Opt,
)
from .sentiment import Sentiment, Backtest, Alerts, run_cc_sim_cached
from .chart import build_chart
from .config import (
    load_config, save_config, DEFAULT_CONFIG, CONFIG_PATH,
    _hydrate_sidebar_prefs, _overlay_prefs_from_session,
    REF_NOTIONAL, RISK_PCT_EXAMPLE, KELLY_DISPLAY_CAP_PCT,
    EMA_EXTENSION_WARN_PCT,
)
from .streamlit_threading import make_script_ctx_pool, submit_with_script_ctx
from .ui_helpers import (
    _factor_checklist_labels, _confluence_why_trade_plain,
    _iv_rank_qualitative_words, _iv_rank_pill_html,
    _explain, _section, _mini_sparkline, _glance_sparkline_svg,
    _glance_metric_card, _render_html_block, _parse_watchlist_string,
    _fragment_technical_zone, _df_price_levels,
    _earnings_calendar_column_config,
    _persist_overlay_prefs,
)
import plotly.graph_objects as go


@dataclass
class DashContext:
    """All computed data for the current ticker — built once, passed to every section."""
    ticker: str = ""
    cfg: dict = field(default_factory=dict)
    df: Any = None           # pd.DataFrame daily
    df_wk: Any = None        # pd.DataFrame weekly
    df_1mo_spark: Any = None
    vix_1mo_df: Any = None
    macro: dict = field(default_factory=dict)
    news: list = field(default_factory=list)
    earnings_date_raw: Any = None
    price: float = 0.0
    prev: float = 0.0
    chg: float = 0.0
    chg_pct: float = 0.0
    hi52: float = 0.0
    lo52: float = 0.0
    vix_v: float = 0.0
    qs: float = 0.0
    qb: dict = field(default_factory=dict)
    struct: str = ""
    wk_label: str = ""
    wk_color: str = ""
    fg: float = 0.0
    fg_label: str = ""
    fg_emoji: str = ""
    fg_advice: str = ""
    rsi_v: float = 0.0
    macd_bull: bool = False
    h_v: object = None
    obv_up: bool = True
    al: list = field(default_factory=list)
    # Diamond / Gold / Confluence
    gold_zone_price: float = 0.0
    gold_zone_components: dict = field(default_factory=dict)
    cp_score: int = 0
    cp_max: int = 9
    cp_breakdown: dict = field(default_factory=dict)
    cp_bearish: int = 0
    cp_color: str = ""
    cp_label: str = ""
    diamonds: list = field(default_factory=list)
    latest_d: Any = None
    d_wr: float = 0.0
    d_avg: float = 0.0
    d_n: int = 0
    qs_color: str = ""
    qs_status: str = ""
    daily_struct: str = ""
    weekly_struct: str = ""
    # Options
    rfr: float = 0.045
    bluf_cc: Any = None
    bluf_csp: Any = None
    bluf_exp: Any = None
    bluf_dte: int = 0
    bluf_calls: Any = None
    bluf_puts: Any = None
    gamma_flip: Any = None
    opt_exps: list = field(default_factory=list)
    cc_scan_rows: list = field(default_factory=list)
    csp_scan_rows: list = field(default_factory=list)
    ref_iv_bluf: Any = None
    nc: int = 1
    action_strat: str = ""
    action_plain: str = ""
    master_html: str = ""
    bluf_html: str = ""
    # Earnings
    earnings_near: bool = False
    earnings_dt: Any = None
    days_to_earnings: Any = None
    earnings_parse_failed: bool = False
    earn_glance: str = ""
    # Layout
    mini_mode: bool = False
    mobile_chart_layout: bool = False
    chart_mood: str = "neutral"
    # Watchlist
    watch_items: list = field(default_factory=list)
    scanner_watchlist: str = ""
    scanner_sort_mode: str = ""


def build_context(ticker: str, cfg: dict) -> Optional[DashContext]:
    """Fetch all data and compute all scores. Returns None if data unavailable."""
    ctx = DashContext(ticker=ticker, cfg=cfg)
    ctx.mini_mode = bool(st.session_state.get("sb_mini_mode", False))
    ctx.mobile_chart_layout = _client_suggests_mobile_chart()

    # ── Parallel fetch ──
    with st.spinner(f"Loading {ticker}..."):
        with make_script_ctx_pool(6) as pool:
            f_df = submit_with_script_ctx(pool, fetch_stock, ticker, "1y", "1d")
            f_wk = submit_with_script_ctx(pool, fetch_stock, ticker, "2y", "1wk")
            f_1mo = submit_with_script_ctx(pool, fetch_stock, ticker, "1mo", "1d")
            f_macro = submit_with_script_ctx(pool, fetch_macro)
            f_news = submit_with_script_ctx(pool, fetch_news_headlines, ticker)
            f_earn = submit_with_script_ctx(pool, fetch_earnings_date, ticker)

            ctx.df = f_df.result()
            ctx.df_wk = f_wk.result()
            ctx.df_1mo_spark = f_1mo.result()
            ctx.macro, ctx.vix_1mo_df = f_macro.result()
            ctx.news = f_news.result()
            ctx.earnings_date_raw = f_earn.result()

    if ctx.df is None or ctx.df.empty:
        return None

    df = ctx.df
    ctx.price = float(df["Close"].iloc[-1])
    ctx.prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else ctx.price
    ctx.chg = ctx.price - ctx.prev
    ctx.chg_pct = ctx.chg / ctx.prev * 100
    ctx.hi52 = float(df["High"].max())
    ctx.lo52 = float(df["Low"].min())
    ctx.vix_v = ctx.macro.get("VIX", {}).get("price", 0)
    use_quant = bool(ctx.cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))

    # Earnings
    _parse_earnings(ctx)

    # Trend / sentiment
    ctx.wk_label, ctx.wk_color = weekly_trend_label(ctx.df_wk)
    ctx.struct, _, _ = TA.market_structure(df)
    ctx.fg = Sentiment.fear_greed(df, ctx.vix_v)
    ctx.fg_label, ctx.fg_emoji, ctx.fg_advice = Sentiment.interpret(ctx.fg)

    ml_v, sl_v, h_v = TA.macd(df["Close"])
    ctx.macd_bull = ml_v.iloc[-1] > sl_v.iloc[-1]
    ctx.h_v = h_v
    obv_s = TA.obv(df)
    ctx.obv_up = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else True
    ctx.rsi_v = float(TA.rsi(df["Close"]).iloc[-1])
    ctx.al = Alerts.scan(df, ticker, ctx.vix_v)

    # Gold (initial) → options (uses POC/HVN) → gamma flip → Gold fuse → confluence → diamonds
    ctx.gold_zone_price, ctx.gold_zone_components = calc_gold_zone(df, ctx.df_wk)
    ctx.daily_struct = ctx.struct
    ctx.weekly_struct = "UNKNOWN"
    if ctx.df_wk is not None and len(ctx.df_wk) >= 20:
        ctx.weekly_struct, _, _ = TA.market_structure(ctx.df_wk)

    # Options fetch (enables MC-PoP fusion into Quant Edge when chain rows exist)
    _fetch_options_context(ctx)
    ctx.gamma_flip = None
    try:
        if ctx.bluf_calls is not None and ctx.bluf_puts is not None:
            _c = ctx.bluf_calls.copy() if not ctx.bluf_calls.empty else pd.DataFrame()
            _p = ctx.bluf_puts.copy() if not ctx.bluf_puts.empty else pd.DataFrame()
            if not _c.empty:
                _c["type"] = "call"
            if not _p.empty:
                _p["type"] = "put"
            if not _c.empty or not _p.empty:
                _odf = pd.concat([_c, _p], ignore_index=True)
                _Ty = max(1, int(ctx.bluf_dte or 30)) / 365.0
                _hvn_px = [
                    float(n["price"])
                    for n in TA.get_volume_nodes(df)
                    if n.get("price") is not None and np.isfinite(float(n["price"]))
                ]
                _gex = Opt.calc_gamma_exposure(
                    _odf,
                    ctx.price,
                    rfr=ctx.rfr,
                    T_years=_Ty,
                    hvn_prices=_hvn_px or None,
                )
                ctx.gamma_flip = Opt.find_gamma_flip(_gex)
                _tg_pin = None
                for _leg in (ctx.bluf_cc, ctx.bluf_csp):
                    if isinstance(_leg, dict) and _leg.get("theta_gamma_ratio") is not None:
                        try:
                            _tg_pin = float(_leg["theta_gamma_ratio"])
                            if np.isfinite(_tg_pin):
                                break
                        except (TypeError, ValueError):
                            pass
                _pin = Opt.predict_opex_pin(_gex, _tg_pin, spot_price=float(ctx.price))
                st.session_state["_cf_opex_pin"] = _pin
                _pmap = dict(st.session_state.get("_cf_opex_pin_map") or {})
                _pmap[str(ctx.ticker).strip().upper()] = _pin
                st.session_state["_cf_opex_pin_map"] = _pmap
    except Exception:
        ctx.gamma_flip = None
        st.session_state["_cf_opex_pin"] = None

    ctx.gold_zone_price, ctx.gold_zone_components = calc_gold_zone(
        df, ctx.df_wk, gamma_flip_price=ctx.gamma_flip
    )
    ctx.cp_score, ctx.cp_max, ctx.cp_breakdown, ctx.cp_bearish = calc_confluence_points(
        df, ctx.df_wk, ctx.vix_v, gold_zone_price=ctx.gold_zone_price
    )
    ctx.diamonds = detect_diamonds(
        df,
        ctx.df_wk,
        use_quant=bool(ctx.cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"])),
        gamma_flip_price=ctx.gamma_flip,
        gold_zone_price=ctx.gold_zone_price,
        ticker_symbol=ctx.ticker,
    )
    ctx.latest_d = latest_diamond_status(ctx.diamonds)
    ctx.d_wr, ctx.d_avg, ctx.d_n = diamond_win_rate(df, ctx.diamonds, forward_bars=10)

    ctx.cp_color = "#10b981" if ctx.cp_score >= 7 else ("#f59e0b" if ctx.cp_score >= 4 else "#ef4444")
    ctx.cp_label = "STRONG BULLISH" if ctx.cp_score >= 7 else ("BULLISH LEAN" if ctx.cp_score >= 5 else ("MIXED" if ctx.cp_score >= 3 else "BEARISH"))
    _opt_edge_rows = list(ctx.cc_scan_rows or []) + list(ctx.csp_scan_rows or [])
    ctx.qs, ctx.qb = quant_edge_score(
        df,
        ctx.vix_v,
        options_data=_opt_edge_rows if _opt_edge_rows else None,
        use_quant=use_quant,
    )
    ctx.qs_color = "#10b981" if ctx.qs > 70 else ("#f59e0b" if ctx.qs > 50 else "#ef4444")
    ctx.qs_status = "PRIME SELLING ENVIRONMENT" if ctx.qs > 70 else ("DECENT SETUP" if ctx.qs > 50 else "STAND DOWN. WAIT FOR A CLEANER ENTRY.")

    # Chart mood
    ctx.chart_mood = "bull" if ctx.struct == "BULLISH" else ("bear" if ctx.struct == "BEARISH" else "neutral")

    try:
        _sh = TA.get_shadow_move(df)
        st.session_state["_cf_shadow_move"] = _sh
        st.session_state["_cf_regime_shadow_breakout"] = None
        if isinstance(_sh, dict) and ctx.price and float(ctx.price) > 0:
            _ivb = getattr(ctx, "ref_iv_bluf", None)
            _dte_b = int(getattr(ctx, "bluf_dte", None) or 0)
            if _ivb is not None and float(_ivb) > 0 and _dte_b > 0:
                px = float(ctx.price)
                _em = float(Opt.calc_expected_move(px, float(_ivb), _dte_b))
                if np.isfinite(_em) and _em > 0:
                    lo_s, hi_s = float(_sh["low"]), float(_sh["high"])
                    if np.isfinite(lo_s) and np.isfinite(hi_s) and hi_s > lo_s:
                        el, eu = px - _em, px + _em
                        outside_shadow = px < lo_s or px > hi_s
                        inside_em = el <= px <= eu
                        if outside_shadow and inside_em:
                            st.session_state["_cf_regime_shadow_breakout"] = {
                                "active": True,
                                "ticker": str(ctx.ticker).strip().upper(),
                            }
    except Exception:
        st.session_state["_cf_shadow_move"] = None
        st.session_state["_cf_regime_shadow_breakout"] = None

    return ctx


def _parse_earnings(ctx: DashContext):
    """Parse earnings date into context fields."""
    ctx.earnings_near = False
    ctx.earnings_dt = None
    ctx.days_to_earnings = None
    ctx.earnings_parse_failed = False
    if ctx.earnings_date_raw is not None:
        try:
            if isinstance(ctx.earnings_date_raw, str):
                ctx.earnings_dt = datetime.strptime(ctx.earnings_date_raw[:10], "%Y-%m-%d")
            else:
                ctx.earnings_dt = pd.Timestamp(ctx.earnings_date_raw).to_pydatetime()
            if hasattr(ctx.earnings_dt, "tzinfo") and ctx.earnings_dt.tzinfo:
                ctx.earnings_dt = ctx.earnings_dt.replace(tzinfo=None)
            ctx.days_to_earnings = (ctx.earnings_dt - datetime.now()).days
            if 0 <= ctx.days_to_earnings <= 14:
                ctx.earnings_near = True
        except Exception:
            ctx.earnings_parse_failed = True
            ctx.earnings_dt = None
            ctx.days_to_earnings = None

    if ctx.earnings_dt is not None and ctx.days_to_earnings is not None:
        if ctx.days_to_earnings < 0:
            ctx.earn_glance = f"Reported {abs(ctx.days_to_earnings)} days ago ({ctx.earnings_dt.strftime('%b %d')})"
        elif ctx.days_to_earnings == 0:
            ctx.earn_glance = "Earnings today"
        else:
            ctx.earn_glance = f"{ctx.days_to_earnings} days: {ctx.earnings_dt.strftime('%b %d, %Y')}"
    else:
        ctx.earn_glance = "Date unavailable from feed"


def _fetch_options_context(ctx: DashContext):
    """Populate options-related fields in context."""
    ctx.rfr = ctx.macro.get("10Y Yield", {}).get("price", 4.5) / 100
    ctx.bluf_cc, ctx.bluf_csp, ctx.bluf_exp, ctx.bluf_dte = None, None, None, 0
    ctx.bluf_calls, ctx.bluf_puts = pd.DataFrame(), pd.DataFrame()
    ctx.opt_exps = []
    ctx.cc_scan_rows, ctx.csp_scan_rows = [], []
    _poc = ctx.gold_zone_components.get("POC") if isinstance(ctx.gold_zone_components, dict) else None
    _hvn_a = ctx.gold_zone_components.get("HVN") if isinstance(ctx.gold_zone_components, dict) else None
    tk_hdr = _html_mod.escape(ctx.ticker)
    try:
        _, ctx.opt_exps = fetch_options(ctx.ticker)
        if ctx.opt_exps:
            ctx.bluf_exp = ctx.opt_exps[min(2, len(ctx.opt_exps) - 1)]
            try:
                ctx.bluf_dte = max(1, (datetime.strptime(str(ctx.bluf_exp)[:10], "%Y-%m-%d") - datetime.now()).days)
            except Exception:
                ctx.bluf_exp, ctx.bluf_dte = None, 0
            if ctx.bluf_exp:
                bluf_opt, _ = fetch_options(ctx.ticker, ctx.bluf_exp)
                ctx.bluf_calls, ctx.bluf_puts = (
                    bluf_opt if isinstance(bluf_opt, (tuple, list)) and len(bluf_opt) == 2 else (pd.DataFrame(), pd.DataFrame())
                )
                ctx.bluf_calls = ctx.bluf_calls if isinstance(ctx.bluf_calls, pd.DataFrame) else pd.DataFrame()
                ctx.bluf_puts = ctx.bluf_puts if isinstance(ctx.bluf_puts, pd.DataFrame) else pd.DataFrame()
                cc_list = (
                    Opt.covered_calls(
                        ctx.price,
                        ctx.bluf_calls,
                        ctx.bluf_dte,
                        ctx.rfr,
                        poc=_poc,
                        hvn_anchor=_hvn_a,
                    )
                    if not ctx.bluf_calls.empty
                    else []
                )
                csp_list = (
                    Opt.cash_secured_puts(
                        ctx.price,
                        ctx.bluf_puts,
                        ctx.bluf_dte,
                        ctx.rfr,
                        poc=_poc,
                        hvn_anchor=_hvn_a,
                    )
                    if not ctx.bluf_puts.empty
                    else []
                )
                ctx.cc_scan_rows = list(cc_list or [])
                ctx.csp_scan_rows = list(csp_list or [])
                if cc_list:
                    ctx.bluf_cc = next((c for c in cc_list if c.get("optimal")), cc_list[0])
                if csp_list:
                    ctx.bluf_csp = next((c for c in csp_list if c.get("optimal")), csp_list[0])
    except Exception as e:
        ctx.opt_exps, ctx.bluf_cc, ctx.bluf_csp, ctx.bluf_exp, ctx.bluf_dte = [], None, None, None, 0
        st.warning(
            f"Options chain could not be loaded for {tk_hdr}. Strike suggestions and IV context may be limited. ({type(e).__name__})"
        )

    ctx.ref_iv_bluf = None
    if ctx.bluf_cc and ctx.bluf_cc.get("iv"):
        try:
            ctx.ref_iv_bluf = float(ctx.bluf_cc["iv"])
        except (TypeError, ValueError):
            pass
    elif ctx.bluf_csp and ctx.bluf_csp.get("iv"):
        try:
            ctx.ref_iv_bluf = float(ctx.bluf_csp["iv"])
        except (TypeError, ValueError):
            pass

    # Put skew: OTM put IV ≥ 20% above OTM call IV (normalized ratio) → lean CSP even on neutral tape
    skew_puts_rich = False
    try:
        _, _piv, _civ = calc_vol_skew(ctx.price, ctx.bluf_calls, ctx.bluf_puts)
        if (
            _piv is not None
            and _civ is not None
            and float(_civ) > 0
            and float(_piv) >= float(_civ) * 1.20
        ):
            skew_puts_rich = True
    except Exception:
        skew_puts_rich = False

    # Determine strategy
    ctx.nc = 1
    if ctx.struct == "BULLISH" and ctx.fg > 50:
        ctx.action_strat = "SELL COVERED CALLS"
        ctx.action_plain = (
            f"If you hold at least 100 shares, sell {ctx.nc} covered call contract(s) above the current price. "
            f"You collect premium today. If {ctx.ticker} stays below the strike by expiration, you keep the cash and your shares."
        )
    elif ctx.fg < 35:
        ctx.action_strat = "SELL CASH SECURED PUTS"
        ctx.action_plain = (
            f"The tape is defensive (fear score {ctx.fg:.0f}). Protection costs more, which pays you to sell it. "
            f"Sell cash secured puts under spot. Assignment simply means you own {ctx.ticker} at the strike you chose."
        )
    elif skew_puts_rich and ctx.struct != "BEARISH":
        ctx.action_strat = "SELL CASH SECURED PUTS"
        ctx.action_plain = (
            f"Volatility skew shows puts are materially richer than calls (hedging demand). "
            f"Even with a neutral tape, selling cash secured puts under {ctx.ticker} captures that premium."
        )
    elif ctx.struct != "BEARISH":
        ctx.action_strat = "BULL PUT SPREAD"
        ctx.action_plain = "Defined risk credit spread: bank the credit while the broker caps the worst case."
    else:
        ctx.action_strat = "BEAR CALL SPREAD"
        ctx.action_plain = "Defined risk credit spread when sellers control the tape; you cap upside risk on the structure."
