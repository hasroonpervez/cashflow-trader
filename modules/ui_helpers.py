"""
UI helpers: reusable components, sparklines, glance cards, section dividers,
DataFrame presentation, and the Technical Zone st.fragment.
"""
import hashlib
import inspect
import re
import streamlit as st
import html as _html_mod
import pandas as pd
import numpy as np
import textwrap
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

from .ta import TA
from .data import _PLOTLY_UI_CONFIG, compute_iv_rank_proxy, fetch_news_headlines
from .sentiment import Sentiment
from .options import (
    Opt,
    calc_gold_zone, calc_confluence_points, detect_diamonds,
    latest_diamond_status, diamond_win_rate,
    scan_watchlist_edge_rows, quant_edge_status_line,
)
from .chart import build_chart
from .config import save_config, load_config, _overlay_prefs_from_session, _persist_overlay_prefs

# Watchlist scanner: "Flow / Bias" column (whale Z-score + NLP headline flags).
SCANNER_WHALE_FLOW_BIAS_HELP = (
    "Whale Alert (Z-Score): Measures volume deviation from the 30-day mean. "
    "Z > 2.0 indicates 97.7th percentile institutional activity. "
    "Flags also include bullish/bearish news bias from cached Yahoo headlines (NLP)."
)


def streamlit_df_widget_key(prefix: str, data) -> str:
    """Element key for ``st.dataframe`` that tracks content shape + checksum.

    Avoids Streamlit frontend ``setIn`` crashes when row counts or cell values change between
    reruns (especially with ``column_config``). Do not pass ``pandas.Styler`` here — use the
    underlying ``DataFrame`` instead.
    """
    df = data
    try:
        if hasattr(data, "data") and not isinstance(data, pd.DataFrame):
            df = data.data
    except Exception:
        df = data
    if df is None:
        return f"{prefix}_none"
    if not isinstance(df, pd.DataFrame):
        return f"{prefix}_other"
    if df.empty:
        return f"{prefix}_empty"
    try:
        blob = df.reset_index(drop=True).astype(str).to_csv(index=False).encode("utf-8", errors="replace")
        digest = hashlib.sha256(blob).hexdigest()[:16]
    except Exception:
        digest = "err"
    return f"{prefix}_{df.shape[0]}x{df.shape[1]}_{digest}"


def streamlit_show_dataframe(data, /, **kwargs):
    """Call ``st.dataframe`` with only kwargs supported by the installed Streamlit version.

    Streamlit Cloud can resolve a slightly different Streamlit build than ``requirements.txt``;
    unsupported parameters (``key``, ``height``, ``selection_mode``, ``on_select``, …) raise
    ``TypeError``, which the hosted runner often surfaces as a redacted ``RuntimeError``.
    """
    sig = inspect.signature(st.dataframe)
    kw = {k: v for k, v in kwargs.items() if k in sig.parameters}
    if "key" in kw and kw["key"] is not None:
        ks = str(kw["key"])
        kw["key"] = re.sub(r"[^a-zA-Z0-9_]", "_", ks)[:120]
    return st.dataframe(data, **kw)


def render_mode_badge(use_quant: bool):
    """Renders a sleek, non-intrusive badge indicating the active mathematical engine."""
    if use_quant:
        badge_html = (
            "<span style='background: linear-gradient(90deg, #1e3a8a 0%, #312e81 100%); "
            "color: #60a5fa; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; "
            "font-weight: 600; letter-spacing: 0.05em; border: 1px solid #1e40af;'>"
            "🔬 INSTITUTIONAL MODE</span>"
        )
    else:
        badge_html = (
            "<span style='background: #1e293b; color: #94a3b8; padding: 2px 8px; "
            "border-radius: 4px; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em; "
            "border: 1px solid #334155;'>📊 RETAIL MODE</span>"
        )
    st.markdown(badge_html, unsafe_allow_html=True)


def _theta_gamma_desk_line(theta_gamma_ratio):
    """Θ/Γ line for Diamond / recommended-trade context (desk CC or CSP row)."""
    if theta_gamma_ratio is None:
        return ""
    try:
        r = float(theta_gamma_ratio)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(r):
        return ""
    if r > 2.0:
        return (
            "<div style='margin:10px 0 4px 0;font-size:.88rem;color:#94a3b8'>"
            f"Θ/Γ Ratio: <strong style='color:#e2e8f0'>{r:.2f}</strong> · "
            "<span style='color:#10b981'>✅ High Decay Efficiency</span></div>"
        )
    if r < 0.5:
        return (
            "<div style='margin:10px 0 4px 0;font-size:.88rem;color:#94a3b8'>"
            f"Θ/Γ Ratio: <strong style='color:#e2e8f0'>{r:.2f}</strong> · "
            "<span style='color:#f59e0b'>⚠️ Gamma Risk (Squeeze Likely)</span></div>"
        )
    return (
        "<div style='margin:10px 0 4px 0;font-size:.88rem;color:#94a3b8'>"
        f"Θ/Γ Ratio: <strong style='color:#e2e8f0'>{r:.2f}</strong></div>"
    )


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


def _confluence_why_trade_plain(cp_breakdown, *, options_chain_available=True):
    """One-line copy for Recommended Trade tooltip (same 7 headline rows as Diamond checklist)."""
    if not options_chain_available:
        return (
            "No Yahoo expirations yet. This card cannot pin a strike or IV rank. "
            "Use Cash Flow then Refresh options data, or use your broker. Tape quality is still in Quant Edge and Confluence above."
        )
    head = (
        "7/9 Diamond headline checklist: Supertrend (2), Ichimoku cloud (2), ADX DI (1), OBV (1), "
        "Divergence (1), Gold Zone (1), Structure (1). "
    )
    if not cp_breakdown:
        return (
            head
            + "Live factor scores are not on this row yet. The strike comes from the options desk path "
            "and regime text until confluence hydrates."
        )
    flabels = _factor_checklist_labels()
    greens = [nice for k, nice in flabels.items() if cp_breakdown.get(k, {}).get("pts", 0) > 0]
    passed = len(greens)
    if passed == 0:
        return (
            head
            + "Right now 0/7 of those headline rows are green. Lean smaller; this pick leans on premium "
            "selling context rather than a stacked confluence entry."
        )
    tail = ", ".join(greens[:5])
    if len(greens) > 5:
        tail += ", plus more"
    return head + f"Currently {passed}/7 green: {tail}."


def _iv_rank_qualitative_words(rank):
    if rank >= 70:
        return "Rich premium"
    if rank < 25:
        return "Lean premium"
    return "Fair premium"


def walk_up_limit_sell_per_share(bid, mid):
    """
    Walk-up limit for short premium (e.g. Robinhood): quote between bid and mid to improve fill quality.
    Returns per-share credit limit, or None if mid is unusable.
    """
    try:
        b = float(bid) if bid is not None else 0.0
        m = float(mid) if mid is not None else 0.0
    except (TypeError, ValueError):
        return None
    if m <= 0 or not np.isfinite(m):
        return None
    if not np.isfinite(b):
        b = 0.0
    b = max(0.0, b)
    w = (b + m) / 2.0
    return float(w) if np.isfinite(w) and w > 0 else None


def expected_move_safety_html(price, strike, iv_pct, dte):
    """Safety line + EM range for Recommended Trade / Diamond context (1-σ implied move)."""
    if strike is None or price is None:
        return ""
    try:
        px_ = float(price)
        k = float(strike)
        ivp = float(iv_pct or 0)
        dte_i = int(dte or 0)
        if dte_i <= 0 or ivp <= 0 or px_ <= 0:
            return ""
        em = float(Opt.calc_expected_move(px_, ivp, dte_i))
        lo, hi = px_ - em, px_ + em
        inside = lo <= k <= hi
        safety = (
            "⚠️ INSIDE EXPECTED MOVE (Monitor Gamma)"
            if inside
            else "✅ OUTSIDE EXPECTED MOVE (High Safety)"
        )
        return (
            f"<div style='margin:10px 0;font-size:.88rem;line-height:1.55;color:#e2e8f0'>"
            f"<strong>Safety Status:</strong> {safety}<br>"
            f"<span style='color:#94a3b8'>Expected Move Range: ${lo:.2f} - ${hi:.2f}</span></div>"
        )
    except Exception:
        return ""


def _iv_rank_pill_html(ticker, price, ref_iv_pct=None, *, stub=None):
    """Recommended Trade card: always show an IV rank pill (numeric proxy, or a clear stub)."""
    pill_open = (
        "<div style='display:inline-flex;align-items:center;flex-wrap:wrap;gap:8px;margin:4px 0 12px 0;"
        "padding:6px 14px;border-radius:999px;border:1px solid rgba(34,211,238,.45);"
        "background:rgba(6,182,212,.12)'>"
    )
    label = "<span style='font-size:.72rem;font-weight:700;color:#a5f3fc;letter-spacing:.07em'>IV RANK (PROXY)</span>"
    if stub == "offline":
        return (
            pill_open
            + label
            + "<span style='margin-left:10px;font-size:.8rem;font-weight:700;color:#94a3b8'>No expirations</span>"
            + "<span style='font-size:.68rem;color:#64748b;margin-left:8px'>IV rank needs a chain. Cash Flow, then Refresh.</span></div>"
        )
    if stub == "no_strike":
        return (
            pill_open
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>n/a</span>"
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
            + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>n/a</span>"
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
            + f"<span style='font-size:.78rem;color:#e2e8f0;font-weight:600'> ({qual})</span>"
            + label
            + "<span style='font-size:.68rem;color:#64748b'>vs listed expiries</span></div>"
        )
    return (
        pill_open
        + "<span class='mono' style='font-weight:800;color:#64748b;font-size:1.05rem'>n/a</span>"
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


@st.fragment(run_every=90.0)
def _fragment_rolling_edge_capture():
    """Full-watchlist quant vs retail edge log + matrix; reruns on a timer without blocking the rest of the app."""
    st.caption(
        "Full watchlist scan about every **90 seconds**. **Highest Quant** sorts to the top. "
        "**Edge gap** is Quant score minus Retail score (each 0 to 100). "
        "This desk targets **premium income** (covered calls, cash secured puts): stronger Quant usually means a better "
        "environment for that style, **not** a simple buy list. Use confluence, diamonds, and your own rules."
    )
    wl = _parse_watchlist_string(st.session_state.get("sb_scanner", ""))
    use_q = bool(st.session_state.get("_cf_use_quant_models", False))
    vx = st.session_state.get("_cf_vix_snapshot")
    try:
        vxf = float(vx) if vx is not None else 0.0
    except (TypeError, ValueError):
        vxf = 0.0
    vix_arg = vxf if vxf > 0 else None

    if not wl:
        st.info("Add tickers under **Edit watchlist symbols** to populate the edge matrix.")
        return

    with st.spinner("Scanning watchlist for edge scores…"):
        rows, failed_syms = scan_watchlist_edge_rows(wl, vix_arg, use_q)
    if rows:
        st.session_state.edge_log = pd.DataFrame(rows)
        st.session_state["_edge_matrix_updated"] = datetime.now().strftime("%H:%M:%S")
    else:
        st.warning("Could not load daily prices for any watchlist symbol. Check symbols or try again shortly.")

    df_log = st.session_state.edge_log
    if df_log is None or df_log.empty:
        return

    if "Preview" not in df_log.columns:
        df_log = df_log.copy()
        df_log["Preview"] = df_log["Quant"].apply(lambda q: quant_edge_status_line(float(q)))

    # Enforce score ordering (Quant high to low) for table + charts even if session held stale rows.
    df_log = df_log.sort_values(by=["Quant", "Delta", "Ticker"], ascending=[False, False, True]).reset_index(drop=True)

    _mean_edge_help = (
        "Mean edge gap: the average of (Quant minus Retail) across all names in this scan. "
        "Both scores are 0 to 100. Positive means the Quant engine is usually more favorable toward premium selling "
        "style conditions than the five pillar retail model. It is not a buy or sell signal for any one stock."
    )
    _q_gt_r_help = (
        "Percentage of tickers where Quant is strictly greater than Retail in this scan. "
        "When this is high, most symbols look stronger under the Quant read than under the retail composite."
    )
    _max_div_help = (
        "Largest positive edge gap (Quant minus Retail) on your list. The subtitle names that ticker. "
        "A large value means Quant liked that tape much more than Retail in the same snapshot."
    )
    _min_div_help = (
        "Most negative edge gap: Retail beat Quant by the widest margin. The subtitle names that ticker. "
        "Use it to see where the two engines disagree most."
    )

    try:
        _n_ok = len(df_log)
        _n_wl = len(wl)
        st.caption(
            f"Last scan **{st.session_state.get('_edge_matrix_updated', 'n/a')}** | "
            f"**{_n_ok}** of **{_n_wl}** symbols | sorted **Quant high to low**"
        )
        if failed_syms:
            st.caption("No daily bars: " + ", ".join(f"`{s}`" for s in failed_syms))
        mean_delta = df_log["Delta"].mean()
        hit_rate = (df_log["Quant"] > df_log["Retail"]).mean() * 100
        best_idx = df_log["Delta"].idxmax()
        worst_idx = df_log["Delta"].idxmin()
        best_ticker = df_log.loc[best_idx, "Ticker"]
        best_delta = int(df_log.loc[best_idx, "Delta"])
        worst_ticker = df_log.loc[worst_idx, "Ticker"]
        worst_delta = int(df_log.loc[worst_idx, "Delta"])
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("Mean Edge Δ", f"{mean_delta:+.1f}", help=_mean_edge_help)
        sc2.metric("Quant > Retail", f"{hit_rate:.0f}%", help=_q_gt_r_help)
        sc3.metric(
            "Max Divergence",
            f"{best_delta:+d}",
            delta=best_ticker,
            delta_color="off",
            help=_max_div_help,
        )
        sc4.metric(
            "Min Divergence",
            f"{worst_delta:+d}",
            delta=worst_ticker,
            delta_color="off",
            help=_min_div_help,
        )

        df_latest = df_log.drop_duplicates(subset=["Ticker"], keep="first").copy()
        df_latest = df_latest.sort_values(by=["Quant", "Delta", "Ticker"], ascending=[False, False, True])
        df_latest["Size_Score"] = df_latest["Quant"].apply(lambda x: max(1, int(x)))
        if "Preview" not in df_latest.columns:
            df_latest["Preview"] = df_latest["Quant"].apply(lambda q: quant_edge_status_line(float(q)))

        with st.container(border=True):
            st.markdown(
                "<div style='font-size:0.72rem;font-weight:800;color:#a5b4fc;letter-spacing:.12em;margin:0 0 6px 0'>"
                "READ THE TAPE</div>"
                "<div style='font-size:1.05rem;font-weight:700;color:#f1f5f9;margin:0 0 8px 0'>"
                "Strongest Quant names (bar length = score)</div>"
                "<div style='font-size:0.82rem;color:#94a3b8;line-height:1.45;margin:0 0 12px 0'>"
                "Green bars: Quant above Retail. Red bars: Retail above Quant. "
                "Hover a bar for Retail, edge gap, and the short preview line.</div>",
                unsafe_allow_html=True,
            )
            top_n = min(18, len(df_latest))
            bar_df = df_latest.head(top_n)
            cd = np.column_stack(
                [bar_df["Retail"].values, bar_df["Delta"].values, bar_df["Preview"].values]
            )
            fig_bar = go.Figure(
                go.Bar(
                    x=bar_df["Quant"].values,
                    y=bar_df["Ticker"].values,
                    orientation="h",
                    customdata=cd,
                    hovertemplate=(
                        "<b>%{y}</b><br>Quant: %{x}<br>Retail: %{customdata[0]}<br>"
                        "Edge gap: %{customdata[1]:+d}<br><i>%{customdata[2]}</i><extra></extra>"
                    ),
                    marker=dict(
                        color=bar_df["Delta"].values,
                        colorscale=[[0.0, "#dc2626"], [0.5, "#475569"], [1.0, "#059669"]],
                        cmin=-35,
                        cmax=35,
                        line=dict(width=0),
                    ),
                )
            )
            fig_bar.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(30,41,59,0.45)",
                margin=dict(l=4, r=8, t=8, b=4),
                height=max(220, 26 * top_n),
                xaxis=dict(
                    title=dict(text="Quant score (0 to 100)", font=dict(size=11, color="#94a3b8")),
                    range=[0, 105],
                    gridcolor="rgba(148,163,184,0.12)",
                    zeroline=False,
                    tickfont=dict(color="#cbd5e1"),
                ),
                yaxis=dict(tickfont=dict(size=12, color="#e2e8f0"), autorange="reversed"),
                showlegend=False,
                font=dict(color="#94a3b8", size=11),
            )
            st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})

            st.markdown(
                "<div style='font-size:0.72rem;font-weight:800;color:#a5b4fc;letter-spacing:.12em;margin:16px 0 6px 0'>"
                "RELATIVE SIZE MAP</div>"
                "<div style='font-size:0.82rem;color:#94a3b8;line-height:1.45;margin:0 0 10px 0'>"
                "Box size tracks Quant score. Color tracks edge gap (Quant minus Retail). "
                "Same data as the bars; use whichever view is easier on your eyes.</div>",
                unsafe_allow_html=True,
            )
            # Diverging scale with a *dark* neutral band (not pale yellow): white labels stay readable on every tile.
            _edge_gap_colorscale = [
                [0.0, "#7f1d1d"],
                [0.35, "#b91c1c"],
                [0.5, "#1e293b"],
                [0.65, "#15803d"],
                [1.0, "#14532d"],
            ]
            _d_abs = float(df_latest["Delta"].abs().max() or 0)
            _d_span = max(15.0, _d_abs * 1.15, 1.0)

            fig_tm = px.treemap(
                df_latest,
                path=[px.Constant("Watchlist"), "Ticker"],
                values="Size_Score",
                color="Delta",
                color_continuous_scale=_edge_gap_colorscale,
                range_color=(-_d_span, _d_span),
                color_continuous_midpoint=0,
                custom_data=["Retail", "Quant", "Delta", "Preview"],
            )
            fig_tm.update_traces(
                marker=dict(line=dict(width=2.5, color="rgba(2,6,23,0.95)")),
                hovertemplate=(
                    "<b>%{label}</b><br>Quant: %{customdata[1]}<br>Retail: %{customdata[0]}<br>"
                    "Edge gap: %{customdata[2]:+d}<br><i>%{customdata[3]}</i><extra></extra>"
                ),
                textinfo="label+text",
                texttemplate="<b>%{label}</b><br>Q %{customdata[1]}<br>gap %{customdata[2]:+d}",
                textfont=dict(size=13, color="#f8fafc", family="system-ui, sans-serif"),
                insidetextfont=dict(size=13, color="#f8fafc", family="system-ui, sans-serif"),
                outsidetextfont=dict(size=12, color="#e2e8f0", family="system-ui, sans-serif"),
            )
            fig_tm.update_layout(
                margin=dict(t=28, l=6, r=6, b=6),
                height=420,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#cbd5e1", size=11),
                title=dict(
                    text="Live Market Edge Matrix (Quant high to low, full watchlist)",
                    font=dict(size=14, color="#f1f5f9"),
                    x=0.02,
                    xanchor="left",
                ),
                coloraxis_colorbar=dict(
                    title=dict(
                        text="Edge gap<br><sub>Quant minus Retail (points)</sub>",
                        font=dict(size=11, color="#94a3b8"),
                    ),
                    thickness=14,
                    tickfont=dict(color="#cbd5e1", size=10),
                    tickformat=".0f",
                    len=0.72,
                ),
            )
            st.plotly_chart(fig_tm, use_container_width=True)
    except Exception:
        pass

    st.divider()
    try:
        csv_data = df_log.to_csv(index=False).encode("utf-8")
        dl_col1, dl_col2 = st.columns([8, 2])
        with dl_col2:
            st.download_button(
                label="📥 Export to CSV",
                data=csv_data,
                file_name=f"quant_edge_log_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
    except Exception:
        pass
    st.session_state.edge_log = df_log
    _edge_gap_help = (
        "Edge gap is Quant score minus Retail score (each rounded 0 to 100). "
        "Positive: Quant reads more favorable premium selling conditions than the retail five pillars. "
        "Negative: Retail reads stronger. Not a standalone buy or sell signal; combine with confluence and your plan."
    )
    streamlit_show_dataframe(
        df_log,
        use_container_width=True,
        hide_index=True,
        key=streamlit_df_widget_key("cf_edge_log", df_log),
        on_select="ignore",
        selection_mode=[],
        column_config={
            "Time": st.column_config.TextColumn("Time"),
            "Ticker": st.column_config.TextColumn("Ticker", width="small"),
            "Retail": st.column_config.NumberColumn(
                "Retail",
                format="%d",
                help="Five pillar retail composite score (0 to 100) for this snapshot.",
            ),
            "Quant": st.column_config.NumberColumn(
                "Quant",
                format="%d",
                help="Quant / institutional style score (0 to 100). With institutional mode on, may blend FFD and regime inputs.",
            ),
            "Delta": st.column_config.NumberColumn("Edge gap", format="%+d", help=_edge_gap_help),
            "Preview": st.column_config.TextColumn(
                "Preview",
                width="large",
                help="Short desk line driven by the Quant score (prime selling context vs stand down).",
            ),
        },
    )


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
    **_st_fragment_extras,
):
    """Charts + overlay toggles + diamond cards + gold zone copy. Reruns without refetching Yahoo data."""
    # Quant mode is stored in session_state (not passed as a kwarg) because @st.fragment reruns
    # may not forward arbitrary kwargs to the inner function reliably on all Streamlit versions.
    # _st_fragment_extras absorbs stale keys (e.g. use_quant) from fragment cache / older deploys.
    use_quant = bool(st.session_state.get("_cf_use_quant_models", False))
    if mini_mode:
        chg_pct = 0.0
        if len(df) >= 2:
            try:
                chg_pct = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[-2]) - 1.0) * 100.0
            except Exception:
                chg_pct = 0.0
        gz_line = "n/a"
        gz_pct = 0.0
        try:
            if gold_zone_price:
                gz_pct = (float(price) / float(gold_zone_price) - 1.0) * 100.0
                gz_line = f"${float(gold_zone_price):.2f} ({gz_pct:+.1f}% from spot)"
        except Exception:
            gz_line = "n/a"
        spark7 = _glance_sparkline_svg(df["Close"].tail(7), "#00E5FF", w=220, h=56)
        chg_c = "#10b981" if chg_pct >= 0 else "#ef4444"
        tk_e = _html_mod.escape(ticker)
        st.markdown(
            f"<div class='glass-card' style='margin-bottom:12px;padding:14px 16px'>"
            f"<div style='font-size:.68rem;font-weight:800;color:#00e5ff;letter-spacing:.14em;margin-bottom:8px'>"
            f"TURBO MOBILE STATUS</div>"
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
            f"No Plotly stack in Turbo. Turn <strong>Turbo mode</strong> off in Mission Control for full charts.</p>"
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
        tip_plain="Candles show OHLC. EMA and Bollinger frame trend and volatility. Fib, Gann, and S/R are reference rails you can mute. Diamonds flag confluence. Gold line is the Gold Zone. **Gamma Flip:** the price level where market-maker hedging accelerates volatility (neon dashed line when chain GEX resolves). Volume shows participation. RSI shows heat. MACD shows momentum versus its signal.",
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

    _em_ctx = st.session_state.get("_cf_chart_em")
    _iv_em = _dte_em = _exp_em = None
    if isinstance(_em_ctx, dict):
        _iv_em = _em_ctx.get("iv_pct")
        _dte_em = _em_ctx.get("dte")
        _exp_em = _em_ctx.get("expiry")
    _gf_chart = st.session_state.get("_cf_gamma_flip")
    try:
        if _gf_chart is not None:
            _gf_chart = float(_gf_chart)
            if not np.isfinite(_gf_chart):
                _gf_chart = None
        else:
            _gf_chart = None
    except (TypeError, ValueError):
        _gf_chart = None
    _earn_dte = st.session_state.get("_cf_earnings_days")
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
        em_iv_pct=_iv_em,
        em_days_to_expiry=_dte_em if _dte_em and int(_dte_em) > 0 else None,
        em_expiry=_exp_em,
        gamma_flip_price=_gf_chart,
        earnings_days_to=_earn_dte,
        iv_overlay_symbol=ticker,
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
                        f"Price: ${d['price']:.2f} | Score: {d['score']} (composite) | RSI: {d['rsi']:.0f}<br>"
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
                quant_overlay = ""
                if latest_d["type"] == "blue" and use_quant:
                    suggested_shares = int(latest_d.get("suggested_shares", 0) or 0)
                    trailing_exit = float(latest_d.get("trailing_exit", 0.0) or 0.0)
                    if suggested_shares > 0 and trailing_exit > 0:
                        quant_overlay = (
                            f"<div style='margin:10px 0 12px 0;padding:10px 12px;border:1px solid rgba(59,130,246,.4);"
                            f"border-radius:10px;background:rgba(59,130,246,.08);font-size:.9rem;line-height:1.6;color:#dbeafe'>"
                            f"💎 Blue Diamond Active: Accumulate {suggested_shares} Shares (Target Vol: 15%)<br>"
                            f"🛑 Trailing Exit (Pink Diamond) dynamically set at ${trailing_exit:.2f}</div>"
                        )
                _em_safe_d = st.session_state.get("_cf_em_safety")
                _diamond_em_html = ""
                if isinstance(_em_safe_d, dict) and _em_safe_d.get("strike") is not None:
                    _diamond_em_html = expected_move_safety_html(
                        _em_safe_d.get("price"),
                        _em_safe_d.get("strike"),
                        _em_safe_d.get("iv_pct"),
                        _em_safe_d.get("dte"),
                    )
                _bluf_desk = (
                    st.session_state.get("_cf_bluf_cc_pick")
                    if latest_d["type"] == "blue"
                    else st.session_state.get("_cf_bluf_csp_pick")
                )
                _tgr_desk = (
                    _theta_gamma_desk_line(_bluf_desk.get("theta_gamma_ratio"))
                    if isinstance(_bluf_desk, dict)
                    else ""
                )
                _d_inst = "—"
                _d_news = "—"
                try:
                    _dpd = TA.get_dark_pool_proxy(df)
                    if _dpd is not None and len(_dpd) and "dark_pool_alert" in _dpd.columns:
                        _d_inst = "High Accumulation" if bool(_dpd["dark_pool_alert"].iloc[-1]) else "Normal"
                except Exception:
                    pass
                try:
                    _dhd = fetch_news_headlines(ticker)
                    _bsd = float(Sentiment.analyze_news_bias(_dhd)) if _dhd else 0.0
                    if _dhd:
                        _d_news = "Positive" if _bsd > 0.15 else ("Negative" if _bsd < -0.15 else "Neutral")
                except Exception:
                    pass
                _flow_diamond_html = (
                    f"<div style='margin:10px 0;padding:8px 12px;border-radius:8px;border:1px solid rgba(148,163,184,.22);"
                    f"font-size:.82rem;color:#cbd5e1;line-height:1.5'>"
                    f"<strong style='color:#93c5fd'>Institutional Flow:</strong> {_html_mod.escape(str(_d_inst))}<br>"
                    f"<strong style='color:#93c5fd'>News Sentiment:</strong> {_html_mod.escape(str(_d_news))}</div>"
                )
                st.markdown(
                    f"<div style='background:rgba(15,23,42,.95);border:1px solid {why_color};border-radius:12px;padding:18px 20px;margin:12px 0'>"
                    f"<div style='font-size:.8rem;color:{why_color};text-transform:uppercase;letter-spacing:.1em;font-weight:700;margin-bottom:6px'>"
                    f"Why This {why_type}?</div>"
                    f"<div style='color:#e2e8f0;font-size:.95rem;margin-bottom:6px'>Signal strength: <strong>{latest_d['score']}</strong> composite "
                    f"(9-pt confluence plus desk modifiers). Live checklist: <strong>{passed}/7</strong> headline factors green.</div>"
                    f"<div style='color:#94a3b8;font-size:.88rem;margin-bottom:12px;line-height:1.5'>{why_action}</div>"
                    f"{_diamond_em_html}"
                    f"{quant_overlay}"
                    f"{_flow_diamond_html}"
                    f"{_tgr_desk}"
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
#  DATAFRAME PRESENTATION: column_config, numeric types, row highlights
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
    cols = ["strike", "mid", "delta", "theta_gamma_ratio", "otm_pct", "prem_100", "ann_yield", "iv", "mc_pop", "volume", "oi"]
    if put_table:
        cols.append("eff_buy")
    cols.append("optimal")
    dfp = pd.DataFrame(rows)
    if "theta_gamma_ratio" not in dfp.columns:
        dfp["theta_gamma_ratio"] = None
    dfp = dfp[cols].copy()
    dfp["optimal"] = dfp["optimal"].astype(bool)
    rename = {
        "strike": "K",
        "mid": "Mid",
        "delta": "\u0394",
        "theta_gamma_ratio": "\u0398/\u0393",
        "otm_pct": "OTM %",
        "prem_100": "$/100 sh",
        "ann_yield": "Ann %",
        "iv": "IV",
        "mc_pop": "MC PoP %",
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
        "\u0398/\u0393": st.column_config.NumberColumn(
            "\u0398/\u0393",
            format="%.4f",
            help="Theta divided by Gamma (per-day theta / gamma) — desk gamma-risk context.",
        ),
        "OTM %": st.column_config.NumberColumn("OTM", format="%.2f%%"),
        "$/100 sh": st.column_config.NumberColumn("$/100 sh", format="$%.2f"),
        "Ann %": st.column_config.NumberColumn("Ann. yield", format="%.1f%%"),
        "IV": st.column_config.NumberColumn("IV", format="%.1f%%"),
        "MC PoP %": st.column_config.NumberColumn(
            "MC PoP %",
            format="%.1f%%",
            help="10k antithetic simulations — v19 Dark Pool & News Bias Mode",
        ),
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
