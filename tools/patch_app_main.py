"""Remove equity helper + inline tab bodies; wire DeskLocals and renderers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = ROOT / "app.py"
lines = app.read_text().splitlines()

# Drop _render_equity_setup_desk (starts at def, ends before # Migrate legacy)
start = None
end = None
for i, ln in enumerate(lines):
    if ln.startswith("def _render_equity_setup_desk("):
        start = i
    if start is not None and i > start and ln.startswith("# Migrate legacy edge_log"):
        end = i
        break
if start is None or end is None:
    raise SystemExit(f"Could not find equity block: start={start} end={end}")
lines = lines[:start] + lines[end:]

# Replace tabs + bodies: from dash_tab_setup = st.tabs through last st.rerun in ledger
s_tabs = None
e_main = None
for i, ln in enumerate(lines):
    if "dash_tab_setup, dash_tab_cashflow, dash_tab_intel, dash_tab_ledger = st.tabs(" in ln:
        s_tabs = i
    if ln == 'if __name__ == "__main__":':
        e_main = i
        break
if s_tabs is None or e_main is None:
    raise SystemExit(f"tabs/main boundary not found: {s_tabs} {e_main}")
s_tabs_real = s_tabs

# End: last non-empty line before if __name__
e = e_main - 1
while e >= 0 and lines[e].strip() == "":
    e -= 1

replacement = '''    dash_tab_setup, dash_tab_cashflow, dash_tab_intel, dash_tab_ledger = st.tabs(
        [
            "Setup & quant",
            "Cashflow & strikes",
            "Risk, scanner & intel",
            "📊 Sentinel Ledger",
        ]
    )

    desk = DeskLocals(
        ticker=ticker,
        df=df,
        df_wk=df_wk,
        df_1mo_spark=df_1mo_spark,
        vix_1mo_df=vix_1mo_df,
        macro=macro,
        news=news,
        earnings_date_raw=earnings_date_raw,
        price=price,
        prev=prev,
        chg=chg,
        chg_pct=chg_pct,
        hi52=hi52,
        lo52=lo52,
        vix_v=vix_v,
        qs=qs,
        qb=qb,
        use_quant_models=use_quant_models,
        earnings_near=earnings_near,
        earnings_dt=earnings_dt,
        days_to_earnings=days_to_earnings,
        earnings_parse_failed=earnings_parse_failed,
        earn_glance=earn_glance,
        wk_label=wk_label,
        wk_color=wk_color,
        struct=struct,
        fg=fg,
        fg_label=fg_label,
        fg_emoji=fg_emoji,
        fg_advice=fg_advice,
        macd_bull=macd_bull,
        obv_up=obv_up,
        rsi_v=rsi_v,
        h_v=h_v,
        al=al,
        gold_zone_price=gold_zone_price,
        gold_zone_components=gold_zone_components,
        cp_score=cp_score,
        cp_max=cp_max,
        cp_breakdown=cp_breakdown,
        cp_bearish=cp_bearish,
        cp_color=cp_color,
        cp_label=cp_label,
        diamonds=diamonds,
        latest_d=latest_d,
        d_wr=d_wr,
        d_avg=d_avg,
        d_n=d_n,
        daily_struct=daily_struct,
        weekly_struct=weekly_struct,
        rfr=rfr,
        bluf_cc=bluf_cc,
        bluf_csp=bluf_csp,
        bluf_exp=bluf_exp,
        bluf_dte=bluf_dte,
        bluf_calls=bluf_calls,
        bluf_puts=bluf_puts,
        opt_exps=opt_exps,
        ref_iv_bluf=ref_iv_bluf,
        nc=nc,
        action_strat=action_strat,
        action_plain=action_plain,
        mini_mode=mini_mode,
        mobile_chart_layout=mobile_chart_layout,
        qs_color=qs_color,
        qs_status=qs_status,
        scanner_watchlist=scanner_watchlist,
        scanner_sort_mode=scanner_sort_mode,
        equity_capital=equity_capital,
        global_snap=_global_snap,
        defer_meta=_defer_meta,
        risk_closes_df=_risk_closes_df,
        simple_corr_mult=_simple_corr_mult,
        cm_cached=_cm_cached,
    )

    with dash_tab_setup:
        render_setup_tab(chart_mood, desk)
    with dash_tab_cashflow:
        render_cashflow_tab(cfg, desk)
    with dash_tab_intel:
        render_intel_tab(desk)
    with dash_tab_ledger:
        render_ledger_tab(desk)'''.splitlines()

new_file = lines[:s_tabs_real] + replacement + lines[e + 1 :]
app.write_text("\n".join(new_file) + "\n")
print("Patched app.py")
