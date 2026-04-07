"""Snapshot of desk locals passed to tab renderers (no Streamlit)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.config import DEFAULT_CONFIG


@dataclass
class DeskLocals:
    """Mirrors main() unpack + intel/scanner fields used by tab bodies."""
    ticker: Any = None
    df: Any = None
    df_wk: Any = None
    df_1mo_spark: Any = None
    vix_1mo_df: Any = None
    macro: Any = None
    news: Any = None
    earnings_date_raw: Any = None
    price: Any = None
    prev: Any = None
    chg: Any = None
    chg_pct: Any = None
    hi52: Any = None
    lo52: Any = None
    vix_v: Any = None
    qs: Any = None
    qb: Any = None
    use_quant_models: Any = None
    earnings_near: Any = None
    earnings_dt: Any = None
    days_to_earnings: Any = None
    earnings_parse_failed: Any = None
    earn_glance: Any = None
    wk_label: Any = None
    wk_color: Any = None
    struct: Any = None
    fg: Any = None
    fg_label: Any = None
    fg_emoji: Any = None
    fg_advice: Any = None
    macd_bull: Any = None
    obv_up: Any = None
    rsi_v: Any = None
    h_v: Any = None
    al: Any = None
    gold_zone_price: Any = None
    gold_zone_components: Any = None
    cp_score: Any = None
    cp_max: Any = None
    cp_breakdown: Any = None
    cp_bearish: Any = None
    cp_color: Any = None
    cp_label: Any = None
    diamonds: Any = None
    latest_d: Any = None
    d_wr: Any = None
    d_avg: Any = None
    d_n: Any = None
    daily_struct: Any = None
    weekly_struct: Any = None
    rfr: Any = None
    bluf_cc: Any = None
    bluf_csp: Any = None
    bluf_exp: Any = None
    bluf_dte: Any = None
    bluf_calls: Any = None
    bluf_puts: Any = None
    opt_exps: Any = None
    ref_iv_bluf: Any = None
    nc: Any = None
    action_strat: Any = None
    action_plain: Any = None
    mini_mode: Any = None
    mobile_chart_layout: Any = None
    qs_color: Any = None
    qs_status: Any = None
    scanner_watchlist: Any = None
    scanner_sort_mode: Any = None
    auto_scan_interval: Any = None
    equity_capital: Any = None
    global_snap: Any = None
    defer_meta: Any = None
    risk_closes_df: Any = None
    simple_corr_mult: Any = None
    cm_cached: Any = None


def build_desk_locals(
    ctx: Any,
    cfg: dict,
    hud: Any,
    *,
    defer_meta: bool,
    global_snap: Any,
    risk_closes_df: Any,
    simple_corr_mult: float,
    cm_cached: Any,
) -> DeskLocals:
    """Build DeskLocals from DashContext + HUD + post-desk correlation artifacts."""
    use_quant_models = bool(cfg.get("use_quant_models", DEFAULT_CONFIG["use_quant_models"]))
    return DeskLocals(
        ticker=ctx.ticker,
        df=ctx.df,
        df_wk=ctx.df_wk,
        df_1mo_spark=ctx.df_1mo_spark,
        vix_1mo_df=ctx.vix_1mo_df,
        macro=ctx.macro,
        news=ctx.news,
        earnings_date_raw=ctx.earnings_date_raw,
        price=ctx.price,
        prev=ctx.prev,
        chg=ctx.chg,
        chg_pct=ctx.chg_pct,
        hi52=ctx.hi52,
        lo52=ctx.lo52,
        vix_v=ctx.vix_v,
        qs=ctx.qs,
        qb=ctx.qb,
        use_quant_models=use_quant_models,
        earnings_near=ctx.earnings_near,
        earnings_dt=ctx.earnings_dt,
        days_to_earnings=ctx.days_to_earnings,
        earnings_parse_failed=ctx.earnings_parse_failed,
        earn_glance=ctx.earn_glance,
        wk_label=ctx.wk_label,
        wk_color=ctx.wk_color,
        struct=ctx.struct,
        fg=ctx.fg,
        fg_label=ctx.fg_label,
        fg_emoji=ctx.fg_emoji,
        fg_advice=ctx.fg_advice,
        macd_bull=ctx.macd_bull,
        obv_up=ctx.obv_up,
        rsi_v=ctx.rsi_v,
        h_v=ctx.h_v,
        al=ctx.al,
        gold_zone_price=ctx.gold_zone_price,
        gold_zone_components=ctx.gold_zone_components,
        cp_score=ctx.cp_score,
        cp_max=ctx.cp_max,
        cp_breakdown=ctx.cp_breakdown,
        cp_bearish=ctx.cp_bearish,
        cp_color=ctx.cp_color,
        cp_label=ctx.cp_label,
        diamonds=ctx.diamonds,
        latest_d=ctx.latest_d,
        d_wr=ctx.d_wr,
        d_avg=ctx.d_avg,
        d_n=ctx.d_n,
        daily_struct=ctx.daily_struct,
        weekly_struct=ctx.weekly_struct,
        rfr=ctx.rfr,
        bluf_cc=ctx.bluf_cc,
        bluf_csp=ctx.bluf_csp,
        bluf_exp=ctx.bluf_exp,
        bluf_dte=ctx.bluf_dte,
        bluf_calls=ctx.bluf_calls,
        bluf_puts=ctx.bluf_puts,
        opt_exps=ctx.opt_exps,
        ref_iv_bluf=ctx.ref_iv_bluf,
        nc=ctx.nc,
        action_strat=ctx.action_strat,
        action_plain=ctx.action_plain,
        mini_mode=ctx.mini_mode,
        mobile_chart_layout=ctx.mobile_chart_layout,
        qs_color=ctx.qs_color,
        qs_status=ctx.qs_status,
        scanner_watchlist=hud.scanner_watchlist,
        scanner_sort_mode=hud.scanner_sort_mode,
        auto_scan_interval=cfg.get("auto_scan_interval", DEFAULT_CONFIG.get("auto_scan_interval", 300)),
        equity_capital=hud.equity_capital,
        global_snap=global_snap,
        defer_meta=defer_meta,
        risk_closes_df=risk_closes_df,
        simple_corr_mult=simple_corr_mult,
        cm_cached=cm_cached,
    )

