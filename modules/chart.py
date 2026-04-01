"""
Chart builder — four-panel Plotly figures (price, volume, RSI, MACD).
"""
import html as _html_mod
import pandas as pd
import numpy as np
import plotly.graph_objects as go

from .ta import TA
from .options import Opt

def _index_pos(idx_obj):
    """Normalize df.index.get_loc result to a single integer position."""
    if isinstance(idx_obj, (int, np.integer)):
        return int(idx_obj)
    if isinstance(idx_obj, slice):
        return idx_obj.start
    arr = np.asarray(idx_obj)
    return int(arr.flat[-1])

# Re-export plotly theme constants (originally in data.py)
from .data import (
    _PLOTLY_UI_CONFIG, _PLOTLY_PAPER_BG, _PLOTLY_PLOT_BG, _PLOTLY_GRID,
    _PLOTLY_FONT_MAIN, _PLOTLY_AXIS_TITLE, _PLOTLY_CASH_UP, _PLOTLY_CASH_DOWN,
    _PLOTLY_BLUE, _PLOTLY_BLUE_DEEP, _PLOTLY_BLUE_DEEPER, _PLOTLY_SLATE,
    compute_iv_earnings_chart_overlay,
)

def _levels_nearest(levels, price, n):
    """Pick the n prices closest to `price` (clearest S/R vs far-away clusters)."""
    if not levels:
        return []
    return sorted(set(levels), key=lambda x: abs(float(x) - price))[:n]


def _chart_hoverlabel():
    return dict(
        bgcolor="rgba(15, 23, 42, 0.96)",
        bordercolor="rgba(100, 116, 139, 0.45)",
        font=dict(size=12, family="Inter, system-ui, sans-serif", color="#f8fafc"),
        align="left",
    )


def build_chart(df, ticker, show_ind=True, show_fib=True, show_gann=True, show_sr=True,
                show_ichi=False, show_super=False, diamonds=None, gold_zone=None,
                mobile_layout=False, em_lower=None, em_upper=None, em_expiry=None,
                em_iv_pct=None, em_days_to_expiry=None, gamma_flip_price=None,
                earnings_days_to=None, iv_overlay_symbol=None):
    """Build four separate figures: price (+ overlays), volume, RSI, MACD — easier to read than one stacked chart.

    When ``mobile_layout`` is True (narrow UA / phone), the price panel drops the legend, tightens margins,
    fixes height, and pins Fib / Gann / Gold annotations to the left so labels do not sit on the candles."""
    last_px = float(df["Close"].iloc[-1])
    try:
        if (
            em_lower is None
            and em_upper is None
            and em_iv_pct is not None
            and em_days_to_expiry is not None
            and float(em_iv_pct) > 0
            and int(em_days_to_expiry) > 0
        ):
            _em = float(
                Opt.calc_expected_move(last_px, float(em_iv_pct), int(em_days_to_expiry))
            )
            em_lower = last_px - _em
            em_upper = last_px + _em
    except Exception:
        pass
    ann_side = "left" if mobile_layout else "right"
    _legend_font = dict(size=11, color="#f1f5f9", family="Inter, system-ui, sans-serif")
    _legend_title_font = dict(size=12, color="#e2e8f0", family="Inter, system-ui, sans-serif")
    uirev = f"{ticker}_tech"
    _tk = _html_mod.escape(str(ticker))

    fig_p = go.Figure()
    fig_p.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            increasing_line_color=_PLOTLY_CASH_UP, decreasing_line_color=_PLOTLY_CASH_DOWN,
            increasing_fillcolor=_PLOTLY_CASH_UP, decreasing_fillcolor=_PLOTLY_CASH_DOWN,
            increasing_line_width=1.35, decreasing_line_width=1.35,
            name="Price",
            # Keep native candlestick hover for maximum Plotly-version compatibility.
        )
    )
    if show_ind:
        for p, c in [(20, "#60a5fa"), (50, _PLOTLY_BLUE), (200, _PLOTLY_BLUE_DEEPER)]:
            if len(df) >= p:
                fig_p.add_trace(
                    go.Scatter(
                        x=df.index, y=TA.ema(df["Close"], p), mode="lines",
                        line=dict(color=c, width=1.1), name=f"EMA {p}", opacity=0.92,
                        hovertemplate=f"EMA {p}: $%{{y:,.2f}}<extra></extra>",
                    )
                )
        u, _m, lo = TA.bollinger(df["Close"])
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=u, line=dict(color="rgba(100,116,139,0.55)", width=1),
                name="Bollinger", legendgroup="bb", showlegend=True,
                hovertemplate="BB upper: $%{y:,.2f}<extra></extra>",
            )
        )
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=lo, line=dict(color="rgba(100,116,139,0.55)", width=1),
                fill="tonexty", fillcolor="rgba(59,130,246,0.06)",
                name="BB lower", legendgroup="bb", showlegend=False,
                hovertemplate="BB lower: $%{y:,.2f}<extra></extra>",
            )
        )
    if show_ichi:
        t, k, sa, sb, _ = TA.ichimoku(df)
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=t, line=dict(color="#38bdf8", width=1.1), name="Tenkan", opacity=0.85,
                hovertemplate="Tenkan: $%{y:,.2f}<extra></extra>",
            )
        )
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=k, line=dict(color="#818cf8", width=1.1), name="Kijun", opacity=0.85,
                hovertemplate="Kijun: $%{y:,.2f}<extra></extra>",
            )
        )
        fig_p.add_trace(
            go.Scatter(x=df.index, y=sa, line=dict(color="rgba(16,185,129,0.25)", width=0),
                       name="Senkou A", showlegend=False)
        )
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=sb, line=dict(color="rgba(248,113,113,0.22)", width=0),
                fill="tonexty", fillcolor="rgba(52,211,153,0.06)", name="Ichimoku cloud",
                hovertemplate="Ichimoku cloud<extra></extra>",
            )
        )
    if show_super:
        st_l, _st_d = TA.supertrend(df)
        fig_p.add_trace(
            go.Scatter(
                x=df.index, y=st_l, mode="lines",
                line=dict(color=_PLOTLY_BLUE_DEEP, width=2), name="Supertrend",
                hovertemplate="Supertrend: $%{y:,.2f}<extra></extra>",
            )
        )
    if show_fib and len(df) >= 50:
        rec = df.iloc[-60:]
        fl = TA.fib_retracement(rec["High"].max(), rec["Low"].min())
        fib_draw_order = ["0.0%", "38.2%", "50.0%", "61.8%", "100.0%"]
        fib_labeled = {"38.2%", "50.0%", "61.8%"}
        fib_short = {"0.0%": "0%", "100.0%": "100%"}
        for lab in fib_draw_order:
            if lab not in fl:
                continue
            lev = fl[lab]
            ann = ""
            if lab in fib_labeled:
                ann = f"{lab.split('.')[0]}% · ${lev:.2f}"
            elif lab in fib_short:
                ann = f"{fib_short[lab]} ${lev:.2f}"
            lw = 1.9 if lab in fib_labeled else 1.1
            op = 0.62 if lab in fib_labeled else 0.38
            fig_p.add_hline(
                y=lev, line_dash="dot", line_color="rgba(59,130,246,0.5)", line_width=lw,
                opacity=op, annotation_text=ann, annotation_position=ann_side,
                annotation_font=dict(size=10, color="rgba(147,197,253,0.95)"),
            )
    if show_gann:
        gl = TA.gann_sq9(last_px)
        near = sorted(gl.items(), key=lambda x: abs(x[1] - last_px))[:3]
        for i, (_lab, lev) in enumerate(near, start=1):
            fig_p.add_hline(
                y=lev, line_dash="dash", line_color="rgba(250,204,21,0.42)", line_width=1.2,
                opacity=0.55, annotation_text=f"G{i} ${lev:.0f}", annotation_position=ann_side,
                annotation_font=dict(size=9, color="rgba(253,224,71,0.9)"),
            )
    if show_sr:
        sups, ress = TA.find_sr(df)
        for s in _levels_nearest(sups, last_px, 2):
            fig_p.add_hline(
                y=s, line_dash="solid", line_color="rgba(34,197,94,0.45)", line_width=1.2,
                opacity=0.55, annotation_text=f"S {s:.2f}", annotation_position="left",
                annotation_font=dict(size=9, color="rgba(134,239,172,0.95)"),
            )
        for r in _levels_nearest(ress, last_px, 2):
            fig_p.add_hline(
                y=r, line_dash="solid", line_color="rgba(248,113,113,0.45)", line_width=1.2,
                opacity=0.55, annotation_text=f"R {r:.2f}", annotation_position="left",
                annotation_font=dict(size=9, color="rgba(254,202,202,0.95)"),
            )
    if gold_zone is not None:
        fig_p.add_hline(
            y=gold_zone, line_dash="solid", line_color="#eab308", line_width=3, opacity=0.9,
            annotation_text=f"Gold ${gold_zone:.2f}", annotation_position=ann_side,
            annotation_font=dict(color="#fde047", size=11, family="JetBrains Mono"),
        )

    _gf = None
    try:
        if gamma_flip_price is not None and np.isfinite(float(gamma_flip_price)):
            _gf = float(gamma_flip_price)
    except (TypeError, ValueError):
        _gf = None
    if _gf is not None:
        fig_p.add_hline(
            y=_gf,
            line_dash="dash",
            line_color="#39FF14",
            line_width=2,
            opacity=0.95,
            annotation_text="GAMMA FLIP (Volatility Trigger)",
            annotation_position=ann_side,
            annotation_font=dict(size=10, color="#39FF14", family="JetBrains Mono"),
        )
        if float(last_px) < _gf:
            try:
                y_lo = float(df["Low"].min()) * 0.997
                y_hi = float(df["High"].max()) * 1.003
                if np.isfinite(y_lo) and np.isfinite(y_hi) and y_hi > y_lo:
                    fig_p.add_hrect(
                        y0=y_lo,
                        y1=y_hi,
                        fillcolor="rgba(255, 0, 0, 0.05)",
                        line_width=0,
                        layer="below",
                    )
            except Exception:
                pass

    try:
        if (
            em_lower is not None
            and em_upper is not None
            and np.isfinite(float(em_lower))
            and np.isfinite(float(em_upper))
        ):
            el, eu = float(em_lower), float(em_upper)
            fig_p.add_hline(
                y=eu,
                line_dash="dash",
                line_color="#eab308",
                line_width=1.5,
                opacity=0.95,
                annotation_text="Expected Move (1-σ)",
                annotation_position=ann_side,
                annotation_font=dict(size=10, color="#eab308"),
            )
            fig_p.add_hline(
                y=el,
                line_dash="dash",
                line_color="#eab308",
                line_width=1.5,
                opacity=0.95,
            )
            if em_expiry is not None:
                try:
                    t0 = df.index[-1]
                    t1 = pd.Timestamp(em_expiry)
                    if hasattr(t0, "tzinfo") and t0.tzinfo is not None and t1.tzinfo is None:
                        t1 = t1.tz_localize(t0.tzinfo)
                    elif hasattr(t1, "tzinfo") and t1.tzinfo is not None and getattr(t0, "tzinfo", None) is None:
                        t0 = pd.Timestamp(t0).tz_localize(None)
                        t1 = pd.Timestamp(t1).tz_localize(None)
                    if t1 > pd.Timestamp(t0):
                        fig_p.add_trace(
                            go.Scatter(
                                x=[t0, t1, t1, t0],
                                y=[last_px, eu, el, last_px],
                                fill="toself",
                                fillcolor="rgba(234,179,8,0.1)",
                                line=dict(color="rgba(234,179,8,0.35)", width=1),
                                mode="lines",
                                name="Probability cone (1-σ)",
                                showlegend=True,
                                hoverinfo="skip",
                            )
                        )
                except Exception:
                    pass
    except Exception:
        pass

    try:
        hvn_levels = TA.get_volume_nodes(df)
        if hvn_levels:
            prices = np.array(
                [float(n["price"]) for n in hvn_levels if isinstance(n, dict) and n.get("price") is not None],
                dtype=float,
            )
            weights = np.array(
                [
                    float(n.get("volume_weight", 1.0) or 1.0)
                    for n in hvn_levels
                    if isinstance(n, dict) and n.get("price") is not None
                ],
                dtype=float,
            )
            if prices.size > 0 and weights.size == prices.size:
                wn = weights / (np.nanmax(weights) + 1e-12)
                gz_ref = float(gold_zone) if gold_zone is not None and np.isfinite(float(gold_zone)) else None
                near_gz = (
                    np.abs(prices - gz_ref) / (gz_ref + 1e-12) <= 0.02
                    if gz_ref is not None and gz_ref > 0
                    else np.zeros(prices.shape[0], dtype=bool)
                )
                order = np.argsort(np.abs(prices - last_px))[:10]
                for idx in order:
                    y = float(prices[idx])
                    base_w = 1.0 + 2.2 * float(wn[idx])
                    op = 0.32 + 0.48 * float(wn[idx])
                    r0, g0, b0 = 167, 139, 250
                    if near_gz[idx]:
                        base_w += 1.1
                        op = min(0.92, op + 0.18)
                        r0, g0, b0 = 139, 92, 246
                    fig_p.add_hline(
                        y=y,
                        line_dash="dash",
                        line_color=f"rgba({r0},{g0},{b0},{min(0.85, 0.38 + 0.45 * float(wn[idx]))})",
                        line_width=max(1.0, min(4.0, base_w)),
                        opacity=min(0.9, op),
                        annotation_text="HVN (Institutional Liquidity)",
                        annotation_position=ann_side,
                        annotation_font=dict(size=9, color=f"rgba({min(255, r0 + 40)},{min(255, g0 + 40)},{min(255, b0 + 30)},0.92)"),
                    )
    except Exception:
        pass

    if diamonds is not None:
        blue_d = [d for d in diamonds if d["type"] == "blue"]
        pink_d = [d for d in diamonds if d["type"] == "pink"]
        # Slightly smaller markers: legend row height matches line swatches better than size 17.
        _dm = dict(symbol="diamond", size=13, line=dict(color="rgba(248,250,252,0.95)", width=1.5))
        if blue_d:
            fig_p.add_trace(
                go.Scatter(
                    x=[d["date"] for d in blue_d],
                    y=[d["price"] * 0.985 for d in blue_d],
                    mode="markers",
                    marker={**_dm, "color": "#2563eb"},
                    name="Blue diamond",
                    legendgroup="diamond_blue",
                    hovertemplate="<b>Blue diamond</b><br>%{x|%Y-%m-%d}<br><b>$%{customdata:,.2f}</b><br>7+ confluence cross up (buy / add zone)<extra></extra>",
                    customdata=[d["price"] for d in blue_d],
                )
            )
        else:
            # Legend key only when no blue in history: tiny marker off last close so the chart matches the key.
            fig_p.add_trace(
                go.Scatter(
                    x=[df.index[-1]],
                    y=[last_px * 1.004],
                    mode="markers",
                    marker={**_dm, "color": "#2563eb", "size": 8, "opacity": 0.35},
                    name="Blue diamond",
                    legendgroup="diamond_blue",
                    hovertemplate="<b>Blue diamond</b><br>Same marker as on chart when a buy signal fires.<br>"
                    "Fires on <b>7+ confluence cross up</b>, <b>daily BULLISH structure</b>, weekly trend <b>not BEARISH</b>, "
                    "<b>volume ≥ 90% of 20d vol SMA</b>, plus ATR participation filter.<br>"
                    "<i>No blue diamond in loaded history yet.</i><extra></extra>",
                )
            )
        if pink_d:
            fig_p.add_trace(
                go.Scatter(
                    x=[d["date"] for d in pink_d],
                    y=[d["price"] * 1.015 for d in pink_d],
                    mode="markers",
                    marker={**_dm, "color": "#e11d48"},
                    name="Pink diamond",
                    legendgroup="diamond_pink",
                    hovertemplate="<b>Pink diamond</b><br>%{x|%Y-%m-%d}<br><b>$%{customdata:,.2f}</b><br>Exit / de-risk (confluence fade or RSI exhaustion)<extra></extra>",
                    customdata=[d["price"] for d in pink_d],
                )
            )
        else:
            fig_p.add_trace(
                go.Scatter(
                    x=[df.index[-1]],
                    y=[last_px * 0.996],
                    mode="markers",
                    marker={**_dm, "color": "#e11d48", "size": 8, "opacity": 0.35},
                    name="Pink diamond",
                    legendgroup="diamond_pink",
                    hovertemplate="<b>Pink diamond</b><br>Same marker as on chart for take-profit / defensive posture.<br>"
                    "<i>No pink diamond in loaded history yet.</i><extra></extra>",
                )
            )

    _p_height = 450 if mobile_layout else 540
    _p_margin = dict(l=5, r=5, t=52, b=40) if mobile_layout else dict(l=56, r=88, t=56, b=44)
    _p_show_legend = not mobile_layout
    _iv_lines = []
    try:
        _sym_ov = iv_overlay_symbol if iv_overlay_symbol else ticker
        _ivp = None
        try:
            if em_iv_pct is not None and float(em_iv_pct) > 0:
                _ivp = float(em_iv_pct)
        except (TypeError, ValueError):
            _ivp = None
        _ov = compute_iv_earnings_chart_overlay(
            df, str(_sym_ov).upper().strip(), earnings_days_to, _ivp, float(last_px)
        )
        if _ov.get("show_crush") and _ov.get("avg_crush_pct") is not None:
            _cr = float(_ov["avg_crush_pct"])
            _iv_lines.append(f"Avg. Post-Earnings IV Crush: {_cr:+.1f}%")
        if _ov.get("vega_risk"):
            _iv_lines.append("⚠️ VEGA RISK: IV Crush likely")
    except Exception:
        pass
    _iv_ann_text = "<br>".join(_iv_lines) if _iv_lines else ""
    _iv_annotations = []
    if _iv_ann_text:
        _iv_annotations.append(
            dict(
                xref="paper",
                yref="paper",
                x=0.99,
                y=0.99,
                xanchor="right",
                yanchor="top",
                text=_iv_ann_text,
                showarrow=False,
                align="right",
                font=dict(size=10, color="#a5b4fc", family="Inter, system-ui, sans-serif"),
                bgcolor="rgba(15,23,42,0.72)",
                bordercolor="rgba(99,102,241,0.35)",
                borderwidth=1,
                borderpad=4,
            )
        )
    fig_p.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        title=dict(
            text=f"<b>{ticker}</b> · price & overlays",
            x=0.01, xanchor="left", y=0.98, yanchor="top",
            font=dict(size=15, color="#f1f5f9", family="Inter, system-ui, sans-serif"),
        ),
        height=_p_height,
        margin=_p_margin,
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=_p_show_legend,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            font=_legend_font,
            bgcolor="rgba(15, 23, 42, 0.78)",
            bordercolor="rgba(100,116,139,0.45)",
            borderwidth=1,
            traceorder="normal",
            itemwidth=34,
            itemsizing="constant",
            title_text="Overlays",
            title_font=_legend_title_font,
        ),
        hoverlabel=_chart_hoverlabel(),
        annotations=_iv_annotations,
    )
    fig_p.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_p.update_yaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        title_text="Price",
        tickprefix="$",
        tickformat=",.2f",
        **_PLOTLY_AXIS_TITLE,
    )

    vc = [_PLOTLY_CASH_UP if c >= o else _PLOTLY_CASH_DOWN for c, o in zip(df["Close"], df["Open"])]
    fig_v = go.Figure(
        data=[
            go.Bar(
                x=df.index, y=df["Volume"], marker_color=vc, name="Volume", opacity=0.58,
                hovertemplate="Volume: %{y:,.0f} shares<extra></extra>",
            )
        ]
    )
    _vm = dict(l=5, r=5, t=24, b=36) if mobile_layout else dict(l=56, r=28, t=28, b=44)
    fig_v.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        height=200 if mobile_layout else 240,
        margin=_vm,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=False,
        hoverlabel=_chart_hoverlabel(),
    )
    fig_v.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_v.update_yaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        title_text="Volume (shares)",
        tickformat=",.0f",
        **_PLOTLY_AXIS_TITLE,
    )

    fig_r = go.Figure()
    fig_r.add_trace(
        go.Scatter(
            x=df.index, y=TA.rsi(df["Close"]), line=dict(color=_PLOTLY_BLUE_DEEP, width=2), name="RSI",
            hovertemplate="<b>RSI (14)</b><br>%{y:.1f}<extra></extra>",
        )
    )
    fig_r.add_hline(y=70, line_dash="dot", line_color="rgba(248,113,113,0.35)")
    fig_r.add_hline(y=50, line_dash="dot", line_color=_PLOTLY_GRID)
    fig_r.add_hline(y=30, line_dash="dot", line_color="rgba(52,211,153,0.35)")
    if diamonds:
        rsi_track = TA.rsi(df["Close"])
        bx, by, px, py = [], [], [], []
        for d in diamonds:
            try:
                ix = _index_pos(df.index.get_loc(d["date"]))
            except (KeyError, TypeError, IndexError):
                continue
            rv = float(rsi_track.iloc[ix]) if not pd.isna(rsi_track.iloc[ix]) else 50.0
            if d["type"] == "blue":
                bx.append(d["date"])
                by.append(rv)
            else:
                px.append(d["date"])
                py.append(rv)
        _dm_rsi = dict(symbol="diamond", size=15, line=dict(color="rgba(248,250,252,0.95)", width=2))
        if bx:
            fig_r.add_trace(
                go.Scatter(
                    x=bx, y=by, mode="markers",
                    marker={**_dm_rsi, "color": "#2563eb"},
                    name="Blue diamond", showlegend=False,
                    hovertemplate="<b>Blue diamond</b><br>%{x|%Y-%m-%d}<br>RSI %{y:.1f}<extra></extra>",
                )
            )
        if px:
            fig_r.add_trace(
                go.Scatter(
                    x=px, y=py, mode="markers",
                    marker={**_dm_rsi, "color": "#e11d48"},
                    name="Pink diamond", showlegend=False,
                    hovertemplate="<b>Pink diamond</b><br>%{x|%Y-%m-%d}<br>RSI %{y:.1f}<extra></extra>",
                )
            )
    _rm = dict(l=5, r=5, t=24, b=36) if mobile_layout else dict(l=56, r=28, t=28, b=44)
    fig_r.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        height=220 if mobile_layout else 260,
        margin=_rm,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=False,
        hoverlabel=_chart_hoverlabel(),
    )
    fig_r.update_yaxes(
        range=[0, 100],
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        title_text="RSI",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_r.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )

    ml, sl, hist = TA.macd(df["Close"])
    hc = [_PLOTLY_CASH_UP if v >= 0 else _PLOTLY_CASH_DOWN for v in hist]
    fig_m = go.Figure()
    fig_m.add_trace(
        go.Scatter(
            x=df.index, y=ml, line=dict(color=_PLOTLY_BLUE_DEEP, width=1.6), name="MACD",
            hovertemplate="<b>MACD</b><br>%{y:.4f}<extra></extra>",
        )
    )
    fig_m.add_trace(
        go.Scatter(
            x=df.index, y=sl, line=dict(color=_PLOTLY_SLATE, width=1.1), name="Signal",
            hovertemplate="<b>Signal</b><br>%{y:.4f}<extra></extra>",
        )
    )
    fig_m.add_trace(
        go.Bar(
            x=df.index, y=hist, marker_color=hc, name="Histogram", opacity=0.58,
            hovertemplate="<b>Histogram</b><br>%{y:+.4f}<extra></extra>",
        )
    )
    _mm = dict(l=5, r=5, t=28, b=36) if mobile_layout else dict(l=56, r=28, t=36, b=44)
    fig_m.update_layout(
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        height=240 if mobile_layout else 280,
        margin=_mm,
        hovermode="x unified",
        uirevision=uirev,
        showlegend=not mobile_layout,
        legend=dict(
            orientation="h",
            bgcolor="rgba(15,23,42,0.78)",
            bordercolor="rgba(148,163,184,0.35)",
            borderwidth=1,
            x=0.99, xanchor="right", y=0.99, yanchor="top",
            font=dict(size=10, color="#94a3b8"),
        ),
        hoverlabel=_chart_hoverlabel(),
    )
    fig_m.update_xaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=False,
        tickformat="%b %d<br>%Y",
        title_text="Date",
        **_PLOTLY_AXIS_TITLE,
    )
    fig_m.update_yaxes(
        showgrid=True,
        gridcolor=_PLOTLY_GRID,
        gridwidth=1,
        zeroline=True,
        zerolinecolor="rgba(128,128,128,0.25)",
        zerolinewidth=1,
        title_text="MACD",
        **_PLOTLY_AXIS_TITLE,
    )

    return fig_p, fig_v, fig_r, fig_m


def build_skew_chart(opts_df, spot_price):
    """
    Builds a Volatility Smile/Skew chart using Plotly.
    Visualizes the Implied Volatility across strikes for puts and calls.
    """
    if opts_df is None or opts_df.empty or "impliedVolatility" not in opts_df.columns:
        return None

    # Filter obvious anomalies / illiquid tails for a cleaner curve.
    df = opts_df[(opts_df["impliedVolatility"] > 0.05) & (opts_df["impliedVolatility"] < 3.0)].copy()
    if df.empty:
        return None

    calls = df[df["type"] == "call"].sort_values("strike")
    puts = df[df["type"] == "put"].sort_values("strike")

    fig = go.Figure()

    if not puts.empty:
        fig.add_trace(
            go.Scatter(
                x=puts["strike"],
                y=puts["impliedVolatility"],
                mode="lines+markers",
                name="Puts (Fear/Downside)",
                line=dict(color="#ef4444", width=2, shape="spline"),
                marker=dict(size=6, color="#ef4444"),
            )
        )

    if not calls.empty:
        fig.add_trace(
            go.Scatter(
                x=calls["strike"],
                y=calls["impliedVolatility"],
                mode="lines+markers",
                name="Calls (Greed/Upside)",
                line=dict(color="#22c55e", width=2, shape="spline"),
                marker=dict(size=6, color="#22c55e"),
            )
        )

    fig.add_vline(
        x=spot_price,
        line_dash="dash",
        line_color="#94a3b8",
        annotation_text="Spot Price",
        annotation_position="top left",
    )

    fig.update_layout(
        title=dict(text="Implied Volatility Skew (The Smile)", font=dict(size=14, color="#e2e8f0")),
        xaxis_title="Strike Price",
        yaxis_title="Implied Volatility",
        template="plotly_dark",
        paper_bgcolor=_PLOTLY_PAPER_BG,
        plot_bgcolor=_PLOTLY_PLOT_BG,
        font=_PLOTLY_FONT_MAIN,
        margin=dict(l=40, r=20, t=50, b=40),
        height=320,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1),
        hoverlabel=_chart_hoverlabel(),
    )
    fig.update_yaxes(tickformat=".1%")

    return fig


def build_correlation_heatmap(corr_matrix):
    """Renders a Plotly heatmap for the correlation matrix."""
    import plotly.express as px

    if corr_matrix is None or corr_matrix.empty:
        return None

    fig = px.imshow(
        corr_matrix,
        text_auto=".2f",
        aspect="auto",
        color_continuous_scale="RdYlGn_r",
        zmin=-1,
        zmax=1,
    )
    fig.update_layout(
        title=dict(
            text="Portfolio Correlation Matrix (Fake Diversification Radar)",
            font=dict(size=14, color="#e2e8f0"),
        ),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
        height=400,
    )
    return fig
