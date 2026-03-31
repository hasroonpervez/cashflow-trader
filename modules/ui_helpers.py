"""
UI helpers — reusable components, sparklines, glance cards, section dividers,
DataFrame presentation, and the Technical Zone st.fragment.
"""
import streamlit as st
import html as _html_mod
import pandas as pd
import numpy as np
import textwrap

from .ta import TA
from .data import _PLOTLY_UI_CONFIG
from .options import (
    calc_gold_zone, calc_confluence_points, detect_diamonds,
    latest_diamond_status, diamond_win_rate,
)
from .data import compute_iv_rank_proxy
from .chart import build_chart
from .config import save_config, load_config, _overlay_prefs_from_session

def _factor_checklist_labels():
    return {
        "Supertrend": "Supertrend supports buyers",
        "Ichimoku": "Price above the cloud",
        "ADX DI": "Strong trend with buyers in front",
        "OBV": "Big money accumulation",
        "Divergence": "Bullish divergence hint",
        "Gold Zone": "Above Gold Zone",
        "Structure": "Higher highs and higher lows",
    }


def _confluence_why_trade_plain(cp_breakdown):
    """One-line copy for Recommended Trade tooltip — same 7 headline rows as Diamond checklist."""
    head = (
        "7/9 Diamond headline checklist: Supertrend (2), Ichimoku cloud (2), ADX DI (1), OBV (1), "
        "Divergence (1), Gold Zone (1), Structure (1). "
    )
    if not cp_breakdown:
        return (
            head
            + "Live factor scores are not on this row yet — the strike comes from the options desk path "
            "and regime text until confluence hydrates."
        )
    flabels = _factor_checklist_labels()
    greens = [nice for k, nice in flabels.items() if cp_breakdown.get(k, {}).get("pts", 0) > 0]
    passed = len(greens)
    if passed == 0:
        return (
            head
            + "Right now 0/7 of those headline rows are green — lean smaller; this pick leans on premium "
            "selling context rather than a stacked confluence entry."
        )
    tail = ", ".join(greens[:5])
    if len(greens) > 5:
        tail += ", …"
    return head + f"Currently {passed}/7 green: {tail}."


def _iv_rank_qualitative_words(rank):
    if rank >= 70:
        return "Rich premium"
    if rank < 25:
        return "Lean premium"
    return "Fair premium"


def _iv_rank_pill_html(ticker, price, ref_iv_pct=None, *, stub=None):
    """Recommended Trade card: always show an IV rank pill — numeric proxy, or a clear stub."""
    pill_open = (
        "<div style='display:inline-flex;align-items:center;flex-wrap:wrap;gap:8px;margin:4px 0 12px 0;"
        "padding:6px 14px;border-radius:999px;border:1px solid rgba(34,211,238,.45);"
        "background:rgba(6,182,212,.12)'>"
    )
    label = "<span style='font-size:.72rem;font-weight:700;color:#a5f3fc;letter-spacing:.07em'>IV RANK (PROXY)</span>"
    if stub == "offline":
        return (
            pill_open
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>chain offline</span></div>"
        )
    if stub == "no_strike":
        return (
            pill_open
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>fallback mode active</span></div>"
        )
    try:
        ref = float(ref_iv_pct) if ref_iv_pct is not None else 0.0
    except (TypeError, ValueError):
        ref = 0.0
    if ref <= 0 or price is None or float(price) <= 0:
        return (
            pill_open
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>no reference IV</span></div>"
        )
    info = compute_iv_rank_proxy(ticker, float(price), ref)
    if info is not None:
        rnk = info["rank"]
        rk_color = "#fbbf24" if rnk > 70 else ("#34d399" if rnk < 25 else "#94a3b8")
        qual = _iv_rank_qualitative_words(rnk)
        return (
            pill_open
            + f"<span class='mono' style='font-weight:800;color:{rk_color};font-size:1.05rem'>IV Rank: {rnk:.0f}%</span>"
            + f"<span style='font-size:.78rem;color:#e2e8f0;font-weight:600'> — {qual}</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>vs listed expiries</span></div>"
        )
    return (
        pill_open
        + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>—</span>"
        + label
        + "<span style='font-size:.68rem;color:#64748b'>curve too thin to rank</span></div>"
    )


def _explain(title, body, mood="neutral"):
    """Render an explanation card with color-coded border."""
    colors = {"bull": ("#10b981", "rgba(16,185,129,.08)"),
              "bear": ("#ef4444", "rgba(239,68,68,.08)"),
              "neutral": ("#06b6d4", "rgba(6,182,212,.08)")}
    c, bg = colors.get(mood, colors["neutral"])
    st.markdown(
        f"<div class='explain' style='background:{bg};border-left-color:{c}'>"
        f"<div style='font-size:.8rem;font-weight:700;color:{c};text-transform:uppercase;"
        f"letter-spacing:.05em;margin-bottom:8px'>{title}</div>"
        f"<div style='color:#e2e8f0;font-size:.95rem;line-height:1.7'>{body}</div></div>",
        unsafe_allow_html=True)

def _section(title, subtitle="", tip_plain=""):
    """Render a prominent section divider. Optional tip_plain: short plain text shown on (i) hover."""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    tip_el = ""
    if tip_plain:
        ta = _html_mod.escape(tip_plain.strip().replace("\n", " "))
        tip_el = f"<span class='cf-tip' tabindex='0'>i<span class='cf-tiptext'>{ta}</span></span>"
    st.markdown(f"<div class='section-hdr'><h2>{title}</h2>{tip_el}{sub}</div>", unsafe_allow_html=True)

def _mini_sparkline(series, color="#00E5FF"):
    """Compact sparkline for glance cards."""
    def _to_rgba(c, alpha=0.14):
        c = (c or "").strip()
        if c.startswith("#") and len(c) == 7:
            r = int(c[1:3], 16)
            g = int(c[3:5], 16)
            b = int(c[5:7], 16)
            return f"rgba({r},{g},{b},{alpha})"
        return f"rgba(0,229,255,{alpha})"

    s = pd.Series(series).dropna()
    if s.empty:
        s = pd.Series([0.0, 0.0])
    # Light smoothing for noisy intraday prints while preserving direction.
    if len(s) >= 5:
        s = s.rolling(3, min_periods=1).mean()
    min_v = float(s.min())
    max_v = float(s.max())
    pad = max(0.001, (max_v - min_v) * 0.15)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(s))), y=s.tolist(), mode="lines",
        line=dict(color=color, width=3), hoverinfo="skip",
        fill="tozeroy", fillcolor=_to_rgba(color, 0.14)
    ))
    fig.update_layout(
        template=None, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=2, r=2, t=2, b=2), height=62,
        xaxis=dict(visible=False, fixedrange=True),
        yaxis=dict(
            visible=False, fixedrange=True, range=[min_v - pad, max_v + pad]
        ),
        showlegend=False
    )
    return fig


def _glance_sparkline_svg(series, color="#00E5FF", w=112, h=44):
    """Single SVG path sparkline for glance cards (sidebar-safe; no Plotly iframe)."""
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 2:
        s = pd.Series([0.0, 1.0] if s.empty else [float(s.iloc[0]), float(s.iloc[0]) + 1e-6])
    vals = s.tolist()
    n = len(vals)
    vmin, vmax = min(vals), max(vals)
    pad = max(1e-9, (vmax - vmin) * 0.12)
    lo, hi = vmin - pad, vmax + pad
    span = hi - lo or 1.0
    pts = []
    for i, v in enumerate(vals):
        x = 2 + (i / max(1, n - 1)) * (w - 4)
        y = h - 2 - ((v - lo) / span) * (h - 4)
        pts.append(f"{x:.1f},{y:.1f}")
    d = "M " + " L ".join(pts)
    esc_color = _html_mod.escape(color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" class="glance-spark-svg" aria-hidden="true">'
        f'<path d="{d}" fill="none" stroke="{esc_color}" stroke-width="2.25" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def _glance_metric_card(label, value_html, caption_html, series, line_color):
    """One self-contained glass card: text left, SVG sparkline right (works with sidebar open)."""
    spark = _glance_sparkline_svg(series, line_color)
    return (
        "<div class='tc glass-card glance-card glance-card-whole'>"
        "<div class='glance-row-flex'>"
        "<div class='glance-text-col'>"
        f"<div class='glance-label'>{label}</div>"
        f"{value_html}"
        f"{caption_html}"
        "</div>"
        f"<div class='glance-spark-col'>{spark}</div>"
        "</div></div>"
    )


def _render_html_block(raw_html: str) -> str:
    """Normalize multiline HTML for st.markdown so indented lines are not treated as code blocks."""
    lines = [line.strip() for line in textwrap.dedent(str(raw_html)).splitlines() if line.strip()]
    return "".join(lines)


def _parse_watchlist_string(s):
    """Split user paste (commas, newlines, semicolons) into unique uppercase tickers."""
    if not s:
        return []
    s = str(s).replace("\n", ",").replace(";", ",")
    items, seen = [], set()
    for raw in s.split(","):
        t = raw.strip().upper()
        if t and t not in seen:
            items.append(t)
            seen.add(t)
    return items


@st.fragment
def _fragment_technical_zone(
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
):
    """Charts + overlay toggles + diamond cards + gold zone copy. Reruns without refetching Yahoo data."""
    if mini_mode:
        chg_pct = 0.0
        if len(df) >= 2:
            try:
                chg_pct = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[-2]) - 1.0) * 100.0
            except Exception:
                chg_pct = 0.0
        gz_line = "—"
        gz_pct = 0.0
        try:
            if gold_zone_price:
                gz_pct = (float(price) / float(gold_zone_price) - 1.0) * 100.0
                gz_line = f"${float(gold_zone_price):.2f} ({gz_pct:+.1f}% from spot)"
        except Exception:
            gz_line = "—"
        spark7 = _glance_sparkline_svg(df["Close"].tail(7), "#00E5FF", w=220, h=56)
        chg_c = "#10b981" if chg_pct >= 0 else "#ef4444"
        tk_e = _html_mod.escape(ticker)
        st.markdown(
            f"<div class='glass-card' style='margin-bottom:12px;padding:14px 16px'>"
            f"<div style='font-size:.68rem;font-weight:800;color:#00e5ff;letter-spacing:.14em;margin-bottom:8px'>"
            f"TURBO · MOBILE STATUS</div>"
            f"<div style='display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:12px'>"
            f"<div style='flex:1;min-width:140px'>"
            f"<div class='mono' style='font-size:1.42rem;font-weight:800;color:#e2e8f0'>{tk_e} ${price:.2f}</div>"
            f"<div style='font-size:.92rem;font-weight:700;color:{chg_c};margin-top:4px'>{chg_pct:+.2f}% vs prior close</div>"
            f"<div style='font-size:.8rem;color:#94a3b8;margin-top:10px;line-height:1.5'>"
            f"<strong style='color:#cbd5e1'>Structure:</strong> {_html_mod.escape(str(struct))}<br>"
            f"<strong style='color:#cbd5e1'>Distance to Gold Zone:</strong> {gz_line}</div></div>"
            f"<div style='flex:0 0 auto;min-width:180px;text-align:right'>"
            f"<div style='font-size:.62rem;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px'>"
            f"7-DAY CLOSE SPARK</div>{spark7}</div></div>"
            f"<p style='color:#64748b;font-size:.74rem;margin:12px 0 0 0;line-height:1.45'>"
            f"No Plotly stack in Turbo — flip <strong>Turbo mode</strong> off in Mission Control for full charts.</p>"
            f"</div>",
            unsafe_allow_html=True,
        )
        _persist_overlay_prefs()
        return

    st.markdown('<div id="charts" style="position:relative;top:-80px"></div>', unsafe_allow_html=True)
    _section(
        "Technical Chart",
        f"{ticker} gets four dedicated panels: price, volume, RSI, and MACD. Zoom each one on its own. "
        "Tweak layers below; those toggles refresh the visuals without another Yahoo pull.",
        tip_plain="Candles show OHLC. EMA and Bollinger frame trend and volatility. Fib, Gann, and S/R are reference rails you can mute. Diamonds flag confluence. Gold line is the Gold Zone. Volume shows participation. RSI shows heat. MACD shows momentum versus its signal.",
    )
    st.markdown("##### Chart layers")
    o1, o2 = st.columns(2)
    with o1:
        show_ind = st.toggle("EMAs & Bollinger", key="sb_ema", on_change=_persist_overlay_prefs)
        show_gann = st.toggle("Gann Sq9", key="sb_gann", on_change=_persist_overlay_prefs)
        show_ichi = st.toggle("Ichimoku", key="sb_ichi", on_change=_persist_overlay_prefs)
        show_diamonds = st.toggle("Diamonds", key="sb_diamonds", on_change=_persist_overlay_prefs)
    with o2:
        show_fib = st.toggle("Fibonacci", key="sb_fib", on_change=_persist_overlay_prefs)
        show_sr = st.toggle("S/R levels", key="sb_sr", on_change=_persist_overlay_prefs)
        show_super = st.toggle("Supertrend", key="sb_super", on_change=_persist_overlay_prefs)
        show_gold_zone = st.toggle("Gold zone", key="sb_gold_zone", on_change=_persist_overlay_prefs)

    fig_p, fig_v, fig_r, fig_m = build_chart(
        df,
        ticker,
        show_ind,
        show_fib,
        show_gann,
        show_sr,
        show_ichi,
        show_super,
        diamonds=diamonds if show_diamonds else None,
        gold_zone=gold_zone_price if show_gold_zone else None,
        mobile_layout=bool(mobile_chart_layout),
    )
    st.plotly_chart(fig_p, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    st.divider()
    st.markdown("#### Volume")
    st.plotly_chart(fig_v, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    st.divider()
    st.markdown("#### RSI (14)")
    st.plotly_chart(fig_r, use_container_width=True, config=_PLOTLY_UI_CONFIG)
    st.divider()
    st.markdown("#### MACD")
    st.plotly_chart(fig_m, use_container_width=True, config=_PLOTLY_UI_CONFIG)

    chart_mood = "bull" if struct == "BULLISH" else ("bear" if struct == "BEARISH" else "neutral")

    if show_diamonds and diamonds:
        recent_diamonds = [d for d in diamonds if (df.index[-1] - d["date"]).days <= 30]
        if recent_diamonds:
            st.markdown("#### Recent Diamond Signals")
            d_cols = st.columns(min(len(recent_diamonds), 4))
            for idx_d, d in enumerate(recent_diamonds[-4:]):
                with d_cols[idx_d]:
                    cls = "diamond-blue" if d["type"] == "blue" else "diamond-pink"
                    icon = "🔷" if d["type"] == "blue" else "💎"
                    label = "BLUE DIAMOND: Strong Buy" if d["type"] == "blue" else "PINK DIAMOND: Take Profit"
                    age = (df.index[-1] - d["date"]).days
                    prob_txt = f"Historical win rate: {d_wr:.0f}% over {d_n} signals" if d_n > 0 else "Insufficient history"
                    st.markdown(
                        f"<div class='{cls}'>"
                        f"<div style='font-size:1.1rem;font-weight:700;margin-bottom:4px'>{icon} {label}</div>"
                        f"<div style='color:#94a3b8;font-size:.85rem'>Date: {d['date'].strftime('%b %d, %Y')} ({age}d ago)<br>"
                        f"Price: ${d['price']:.2f} | Score: {d['score']}/9 | RSI: {d['rsi']:.0f}<br>"
                        f"<span style='color:#fbbf24;font-size:.8rem'>📊 {prob_txt}</span></div></div>",
                        unsafe_allow_html=True,
                    )

            if latest_d and (df.index[-1] - latest_d["date"]).days <= 5:
                why_type = "BLUE DIAMOND" if latest_d["type"] == "blue" else "PINK DIAMOND"
                why_color = "#3b82f6" if latest_d["type"] == "blue" else "#ec4899"
                why_action = (
                    "Strong confluence aligned bullish. The market gave a high probability buy signal."
                    if latest_d["type"] == "blue"
                    else "Confluence collapsed or momentum exhausted. Time to protect gains."
                )
                flabels = _factor_checklist_labels()
                factor_lines = ""
                passed = 0
                for key, nice in flabels.items():
                    info = cp_breakdown.get(key)
                    if not info:
                        continue
                    ok = info["pts"] > 0
                    if ok:
                        passed += 1
                    mark = "&#10003;" if ok else ""
                    row_col = "#34d399" if ok else "#64748b"
                    factor_lines += (
                        f"<div style='padding:5px 0;display:flex;align-items:flex-start;gap:10px;color:{row_col};font-size:.9rem'>"
                        f"<span style='color:#34d399;font-weight:800;min-width:1.2em'>{mark}</span>"
                        f"<span><strong style='color:#e2e8f0'>{nice}</strong>"
                        f"<span style='color:#64748b;font-size:.8rem'> ({info['pts']}/{info['max']})</span></span></div>"
                    )
                wk_confirm = latest_d.get("weekly", "N/A")
                win_badge = (
                    f"<div style='margin:12px 0 8px 0'><span class='diamond-win-badge'>HISTORICAL WIN RATE: {d_wr:.0f}%</span>"
                    f"<span style='color:#94a3b8;font-size:.8rem;margin-left:10px'>({d_n} past signals)</span></div>"
                    if d_n > 0
                    else "<div style='color:#64748b;font-size:.85rem;margin:8px 0'>Not enough history for a win rate badge yet.</div>"
                )
                st.markdown(
                    f"<div style='background:rgba(15,23,42,.95);border:1px solid {why_color};border-radius:12px;padding:18px 20px;margin:12px 0'>"
                    f"<div style='font-size:.8rem;color:{why_color};text-transform:uppercase;letter-spacing:.1em;font-weight:700;margin-bottom:6px'>"
                    f"Why This {why_type}?</div>"
                    f"<div style='color:#e2e8f0;font-size:.95rem;margin-bottom:6px'>Signal fired at <strong>{latest_d['score']}/9</strong> confluence. "
                    f"Live checklist now shows <strong>{passed}/7</strong> headline factors green.</div>"
                    f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px;line-height:1.5'>{why_action}</div>"
                    f"{win_badge}"
                    f"<div style='font-size:.72rem;color:#64748b;text-transform:uppercase;margin-bottom:6px'>Diamond checklist</div>"
                    f"<div>{factor_lines}</div>"
                    f"<div style='margin-top:12px;padding-top:10px;border-top:1px solid rgba(255,255,255,.06);font-size:.8rem;color:#94a3b8'>"
                    f"Weekly filter at signal: <strong style='color:{why_color}'>{wk_confirm}</strong>. "
                    f"RSI at signal: {latest_d['rsi']:.0f}.</div></div>",
                    unsafe_allow_html=True,
                )

    if show_gold_zone:
        show_gz_detail = st.checkbox("Show Gold Zone Breakdown", value=False, key="chk_gold_zone_detail")
        if show_gz_detail:
            st.markdown(
                f"**Gold Zone Price: ${gold_zone_price:.2f}**. This is the weighted average of multiple key levels that institutional traders watch."
            )
            for comp_name, comp_val in gold_zone_components.items():
                dist = (comp_val / price - 1) * 100
                st.markdown(f"* **{comp_name}**: ${comp_val:.2f} ({dist:+.1f}% from spot)")
            _explain(
                "Why the Gold Zone matters",
                "The Gold Zone fuses four institutional magnets into one line: Volume Profile POC where the crowd traded most, "
                "the 61.8% Fibonacci anchor, the 200 day simple moving average, and the nearest Gann Square of 9 pivot. "
                "Above it, buyers still own the narrative. Below it, respect the air pocket. "
                "Treat it as the headline level on your chart.",
                "neutral",
            )

    if latest_d and latest_d["type"] == "blue" and (df.index[-1] - latest_d["date"]).days <= 3:
        next_gz = gold_zone_price
        st.markdown(
            f"<div class='ac'>🔔 <strong>Alert Suggestion:</strong> Set an alert for next Blue Diamond at <strong>${next_gz:.2f}</strong> (Gold Zone). "
            f"If {ticker} pulls back to the Gold Zone and confluence rebuilds above 7/9, that is your next high probability entry.</div>",
            unsafe_allow_html=True,
        )
    elif latest_d and latest_d["type"] == "pink" and (df.index[-1] - latest_d["date"]).days <= 3:
        st.markdown(
            f"<div class='ac'>🔔 <strong>Alert Suggestion:</strong> Pink Diamond fired at ${latest_d['price']:.2f}. "
            f"Consider taking partial profits. Set alert if {ticker} drops below Gold Zone ${gold_zone_price:.2f} for a full exit.</div>",
            unsafe_allow_html=True,
        )

    _explain(
        "\U0001f9e0 Quick read",
        "Tap the <strong>i</strong> on any section header when you want the full story. "
        "Green candles with a climbing short EMA say buyers are steering. Diamonds and the Gold Zone are your runway lights.",
        chart_mood,
    )
    _persist_overlay_prefs()


# ═════════════════════════════════════════════════════════════════════════
#  DATAFRAME PRESENTATION — column_config, numeric types, row highlights
# ═════════════════════════════════════════════════════════════════════════

_KEY_FIB_LEVEL_NAMES = frozenset({"50.0%", "61.8%"})


def _df_price_levels(levels: dict, spot: float) -> pd.DataFrame:
    """Build a numeric table for Fib / Gann level maps (label → price)."""
    rows = [
        {
            "Level": k,
            "Price": float(v),
            "vs spot (%)": (float(v) / spot - 1.0) * 100.0,
        }
        for k, v in levels.items()
    ]
    return pd.DataFrame(rows)


def _style_price_levels_table(df: pd.DataFrame, *, mode: str, spot: float):
    """Highlight key Fib retracements or the Gann level nearest spot."""
    if df.empty:
        return df
    if mode == "fib":
        def _fib_row(row):
            if row["Level"] in _KEY_FIB_LEVEL_NAMES:
                return ["background-color: rgba(245, 158, 11, 0.22); font-weight: 700"] * len(row)
            return [""] * len(row)

        sty = df.style.apply(_fib_row, axis=1)
    else:
        nearest_label = (df["Price"] - float(spot)).abs().idxmin()

        def _gann_row(row):
            if row.name == nearest_label:
                return ["background-color: rgba(34, 211, 238, 0.16); font-weight: 700"] * len(row)
            return [""] * len(row)

        sty = df.style.apply(_gann_row, axis=1)
    try:
        return sty.hide(axis="index")
    except (TypeError, ValueError, AttributeError):
        return sty.hide_index()


def _earnings_calendar_column_config():
    return {
        "Earnings date": st.column_config.DateColumn("Earnings date", format="MMM DD, YYYY"),
        "EPS estimate": st.column_config.NumberColumn("EPS estimate", format="$%.2f"),
        "Reported EPS": st.column_config.NumberColumn("Reported EPS", format="$%.2f"),
        "Surprise (%)": st.column_config.NumberColumn("Surprise (%)", format="%.2f%%"),
        "Status": st.column_config.TextColumn("Status"),
    }


def _style_earnings_next_highlight(df: pd.DataFrame, highlight_idx):
    """Subtle row fill for the next earnings date on or after today."""
    if df.empty:
        return df
    if highlight_idx is None:
        try:
            return df.style.hide(axis="index")
        except (TypeError, ValueError, AttributeError):
            return df.style.hide_index()

    hi = int(highlight_idx)

    def _row(r):
        if r.name == hi:
            return ["background-color: rgba(245, 158, 11, 0.16)"] * len(r)
        return [""] * len(r)

    sty = df.style.apply(_row, axis=1)
    try:
        return sty.hide(axis="index")
    except (TypeError, ValueError, AttributeError):
        return sty.hide_index()


_PRICE_LEVEL_COLUMN_CONFIG = {
    "Level": st.column_config.TextColumn("Level", width="large"),
    "Price": st.column_config.NumberColumn("Price", format="$%.2f"),
    "vs spot (%)": st.column_config.NumberColumn("vs spot", format="%+.2f%%"),
}


def _options_scan_dataframe(rows: list, *, put_table: bool) -> pd.DataFrame:
    """Normalize CC / CSP rows for display with stable column order."""
    cols = ["strike", "mid", "delta", "otm_pct", "prem_100", "ann_yield", "iv", "volume", "oi"]
    if put_table:
        cols.append("eff_buy")
    cols.append("optimal")
    dfp = pd.DataFrame(rows)[cols].copy()
    dfp["optimal"] = dfp["optimal"].astype(bool)
    rename = {
        "strike": "K",
        "mid": "Mid",
        "delta": "\u0394",
        "otm_pct": "OTM %",
        "prem_100": "$/100 sh",
        "ann_yield": "Ann %",
        "iv": "IV",
        "volume": "Vol",
        "oi": "OI",
        "optimal": "Prop desk",
    }
    if put_table:
        rename["eff_buy"] = "Eff. buy"
    return dfp.rename(columns=rename)


def _options_scan_column_config(*, put_table: bool):
    cfg = {
        "K": st.column_config.NumberColumn("Strike", format="$%.2f"),
        "Mid": st.column_config.NumberColumn("Mid", format="$%.2f"),
        "\u0394": st.column_config.NumberColumn("Delta", format="%.3f"),
        "OTM %": st.column_config.NumberColumn("OTM", format="%.2f%%"),
        "$/100 sh": st.column_config.NumberColumn("$/100 sh", format="$%.2f"),
        "Ann %": st.column_config.NumberColumn("Ann. yield", format="%.1f%%"),
        "IV": st.column_config.NumberColumn("IV", format="%.1f%%"),
        "Vol": st.column_config.NumberColumn("Volume", format="%.0f"),
        "OI": st.column_config.NumberColumn("OI", format="%.0f"),
    }
    if put_table:
        cfg["Eff. buy"] = st.column_config.NumberColumn("Eff. buy", format="$%.2f")
    cfg["Prop desk"] = st.column_config.CheckboxColumn(
        "Prop desk",
        help="Desk-preferred strike for this chain",
        disabled=True,
    )
    return cfg


def _style_propdesk_highlight(df: pd.DataFrame):
    """Emphasize the Prop desk optimal row (summary-style)."""
    col = "Prop desk"

    def _row(r):
        if bool(r[col]):
            return ["background-color: rgba(6, 182, 212, 0.2); font-weight: 700"] * len(r)
        return [""] * len(r)

    sty = df.style.apply(_row, axis=1)
    try:
        return sty.hide(axis="index")
    except (TypeError, ValueError, AttributeError):
        return sty.hide_index()



def _persist_overlay_prefs():
    """Persist overlay toggles from session state (used inside chart fragment)."""
    base = load_config()
    o = _overlay_prefs_from_session()
    upd = {**base, **o}
    if any(upd.get(k) != base.get(k) for k in o):
        save_config(upd)
        return upd
    return base
