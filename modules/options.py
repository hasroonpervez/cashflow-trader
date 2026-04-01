"""
Options analytics — Black-Scholes, Greeks, EV, Kelly, Volatility Skew,
Quant Edge Score, Gold Zone, Confluence Points, Diamond Signals, Opt scanner.
"""
import streamlit as st
import pandas as pd
import numpy as np
import math
from math import log, sqrt, exp
from datetime import datetime
from concurrent.futures import as_completed
try:
    from scipy.stats import norm
except ImportError:  # keep app usable if scipy is unavailable
    norm = None

from .ta import TA
from .data import fetch_stock
from .streamlit_threading import make_script_ctx_pool, submit_with_script_ctx

try:
    from scipy.stats import norm as _norm
    _cdf = _norm.cdf; _pdf = _norm.pdf
except ImportError:
    def _cdf(x):
        a1,a2,a3,a4,a5 = 0.254829592,-0.284496736,1.421413741,-1.453152027,1.061405429
        sign = 1 if x >= 0 else -1; x = abs(x)/sqrt(2)
        t = 1.0/(1.0+0.3275911*x)
        y = 1.0-(((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*exp(-x*x)
        return 0.5*(1.0+sign*y)
    def _pdf(x):
        return exp(-0.5*x*x)/sqrt(2*3.14159265359)

def bs_price(S, K, T, r, sigma, option_type="call"):
    """Black-Scholes option price. S=spot, K=strike, T=years, r=risk-free rate, sigma=IV."""
    S, K = float(S), float(K)
    if S <= 0 or K <= 0 or not math.isfinite(S) or not math.isfinite(K):
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)
    sigma = max(sigma, 0.001)
    if T <= 0:
        return max(0, S - K) if option_type == "call" else max(0, K - S)
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    if option_type == "call":
        return S*_cdf(d1) - K*exp(-r*T)*_cdf(d2)
    return K*exp(-r*T)*_cdf(-d2) - S*_cdf(-d1)

def bs_greeks(S, K, T, r, sigma, option_type="call"):
    """Calculate Delta, Gamma, Theta (per day), Vega (per 1% IV move)."""
    S, K = float(S), float(K)
    if S <= 0 or K <= 0 or not math.isfinite(S) or not math.isfinite(K):
        return {"delta": 1.0 if option_type == "call" else -1.0, "gamma": 0, "theta": 0, "vega": 0}
    sigma = max(sigma, 0.001)
    if T <= 0:
        return {"delta": 1.0 if option_type == "call" else -1.0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
    gamma = _pdf(d1) / (S * sigma * sqrt(T))
    vega = S * _pdf(d1) * sqrt(T) / 100  # per 1% move
    if option_type == "call":
        delta = _cdf(d1)
        theta = (-S*_pdf(d1)*sigma/(2*sqrt(T)) - r*K*exp(-r*T)*_cdf(d2)) / 365
    else:
        delta = _cdf(d1) - 1
        theta = (-S*_pdf(d1)*sigma/(2*sqrt(T)) + r*K*exp(-r*T)*_cdf(-d2)) / 365
    return {"delta": round(delta, 3), "gamma": round(gamma, 4), "theta": round(theta, 3), "vega": round(vega, 3)}


# ═════════════════════════════════════════════════════════════════════════
#  EXPECTED VALUE (EV) CALCULATOR
# ═════════════════════════════════════════════════════════════════════════

def calc_ev(premium, max_loss, pop_pct):
    """Calculate Expected Value: EV = (POP * premium) - ((1-POP) * max_loss).
    Returns EV per contract. Positive = edge, negative = avoid."""
    pop = pop_pct / 100
    ev = (pop * premium) - ((1 - pop) * max_loss)
    return round(ev, 2)


def kelly_criterion(
    win_prob_pct,
    win_amount,
    loss_amount,
    use_quant=False,
    expected_return=0.0,
    variance=0.0,
    risk_free_rate=0.05,
    correlation_haircut=1.0,
    avg_mc_pop=None,
):
    """Kelly Criterion: optimal bankroll fraction.
    f* = W - (1-W)/R where W = win probability, R = win/loss payout ratio.
    Returns (full_kelly_pct, half_kelly_pct) as percentages."""
    pop_mult = 1.0
    if avg_mc_pop is not None:
        try:
            pop_mult = (max(1.0, float(avg_mc_pop)) / 85.0) ** 0.5
        except (TypeError, ValueError):
            pop_mult = 1.0
    if use_quant and variance > 0:
        full = continuous_kelly(
            expected_return,
            risk_free_rate,
            variance,
            half_kelly=False,
            correlation_haircut=correlation_haircut,
            pop_mult=pop_mult,
        )
        half = continuous_kelly(
            expected_return,
            risk_free_rate,
            variance,
            half_kelly=True,
            correlation_haircut=correlation_haircut,
            pop_mult=pop_mult,
        )
        return round(full, 1), round(half, 1)
    if loss_amount <= 0 or win_amount <= 0 or win_prob_pct <= 0 or win_prob_pct >= 100:
        return 0.0, 0.0
    W = win_prob_pct / 100
    R = win_amount / loss_amount
    if R < 1e-12:
        return 0.0, 0.0
    full_frac = max(0.0, W - (1 - W) / R) * pop_mult
    half_frac = full_frac / 2
    return round(full_frac * 100, 1), round(half_frac * 100, 1)

def bs_corrado_su(S, K, T, r, sigma, skew=0.0, kurt=3.0, option_type="call"):
    """
    Prices options using the Corrado-Su expansion to account for volatility skew
    and fat tails (kurtosis).
    """
    S, K = float(S), float(K)
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return bs_price(S, K, max(T, 0), r, max(sigma, 0.001), option_type)

    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    cdf = norm.cdf if norm is not None else _cdf
    pdf = norm.pdf if norm is not None else _pdf

    if option_type == "call":
        bs_px = S * cdf(d1) - K * np.exp(-r * T) * cdf(d2)
    else:
        bs_px = K * np.exp(-r * T) * cdf(-d2) - S * cdf(-d1)

    q3 = (1 / 6) * S * sigma * np.sqrt(T) * ((2 * sigma * np.sqrt(T)) - d1) * pdf(d1)
    q4 = (1 / 24) * S * sigma * np.sqrt(T) * (
        d1**2 - 1 - 3 * sigma * np.sqrt(T) * d1 + 3 * sigma**2 * T
    ) * pdf(d1)

    return max(0.0, float(bs_px + (skew * q3) + ((kurt - 3.0) * q4)))


def continuous_kelly(
    expected_return,
    risk_free_rate,
    variance,
    half_kelly=True,
    correlation_haircut=1.0,
    pop_mult=1.0,
):
    """
    Calculates optimal continuous-time allocation (Merton's Portfolio Problem).
    Applies a mathematical haircut if the asset is highly correlated to the portfolio.
    """
    if variance <= 0:
        return 0.0
    f_star = (expected_return - risk_free_rate) / variance
    allocation = f_star / 2.0 if half_kelly else f_star
    pm = float(pop_mult) if pop_mult is not None else 1.0
    if not np.isfinite(pm) or pm < 0:
        pm = 1.0
    final_allocation = max(0.0, min(1.0, allocation)) * 100 * correlation_haircut * pm
    return final_allocation


# ═════════════════════════════════════════════════════════════════════════
#  VOLATILITY SKEW — detects institutional hedging
# ═════════════════════════════════════════════════════════════════════════

def calc_vol_skew(price, calls_df, puts_df, otm_pct=0.10):
    """Compare IV of 10% OTM put vs 10% OTM call. Positive = put skew (bearish hedging)."""
    if calls_df is None or puts_df is None or calls_df.empty or puts_df.empty:
        return None, None, None
    target_put_strike = price * (1 - otm_pct)
    target_call_strike = price * (1 + otm_pct)
    # Find nearest strikes
    put_row = puts_df.iloc[(puts_df["strike"] - target_put_strike).abs().argsort()[:1]]
    call_row = calls_df.iloc[(calls_df["strike"] - target_call_strike).abs().argsort()[:1]]
    put_iv = put_row["impliedVolatility"].values[0] * 100 if not put_row.empty and put_row["impliedVolatility"].values[0] else None
    call_iv = call_row["impliedVolatility"].values[0] * 100 if not call_row.empty and call_row["impliedVolatility"].values[0] else None
    if put_iv and call_iv:
        skew = put_iv - call_iv
        return round(skew, 1), round(put_iv, 1), round(call_iv, 1)
    return None, put_iv, call_iv


def nearest_hvn_within_pct(price, nodes, pct=0.02):
    """Nearest HVN price within ±pct of spot. ``nodes`` from ``TA.get_volume_nodes`` (list of dicts)."""
    if price is None or price <= 0 or not nodes:
        return None, None
    p0 = float(price)
    best = None
    for n in nodes:
        if isinstance(n, dict):
            p = float(n.get("price", 0) or 0)
            w = float(n.get("volume_weight", 1.0) or 1.0)
        else:
            p, w = float(n), 1.0
        if p <= 0 or not np.isfinite(p):
            continue
        if abs(p / p0 - 1.0) > pct:
            continue
        d = abs(p - p0)
        if best is None or d < best[0]:
            best = (d, p, w)
    if best is None:
        return None, None
    return best[1], best[2]


def _quant_edge_mc_pop_boost(options_data, top_n=8):
    """Fusion term: ``0.25 * (avg MC PoP of top strikes / 100)`` for Quant Edge composite."""
    if not options_data:
        return 0.0, None
    rows = [r for r in options_data if isinstance(r, dict) and r.get("mc_pop") is not None]
    if not rows:
        return 0.0, None
    try:
        rows_sorted = sorted(
            rows,
            key=lambda x: float(x.get("score", 0) or 0),
            reverse=True,
        )[:top_n]
        arr = np.array([float(x["mc_pop"]) for x in rows_sorted], dtype=float)
        if arr.size == 0:
            return 0.0, None
        avg = float(np.mean(arr))
        return float(0.25 * (avg / 100.0)), avg
    except Exception:
        return 0.0, None


def quant_edge_score(df, vix_val=None, options_data=None, use_quant=False):
    """Composite 0-100 using five de-correlated dimensions (no Supertrend here — that
    belongs in confluence/diamond context, not double-counted with EMA trend):
    1. Trend — EMA stack only (structure of moving averages)
    2. Momentum — RSI only (single oscillator)
    3. Volume — OBV vs its own history
    4. Volatility — ATR regime + optional VIX
    5. Structure — market-structure label (not redundant with EMA slope)
    Equal 20% weights.
    """
    if use_quant:
        try:
            from .sentiment import QuantSentiment
            regime_probs = QuantSentiment.regime_detection(df)
            high_vol_regime = float(regime_probs.get(1, 0.0))
            ffd_series = TA.frac_diff_ffd(df["Close"])
            ffd_last = float(ffd_series.iloc[-1]) if ffd_series is not None and len(ffd_series) > 0 else 0.0
            edge = 50.0 + (ffd_last * 10.0) - (high_vol_regime * 20.0)
            mc_boost, mc_avg_top = _quant_edge_mc_pop_boost(options_data)
            edge = float(max(0.0, min(100.0, edge + mc_boost)))
            breakdown = {
                "regime_prob_high_vol": round(high_vol_regime, 4),
                "ffd_last": round(ffd_last, 4),
                "model": "institutional",
            }
            if mc_avg_top is not None:
                breakdown["mc_pop_top_avg"] = round(mc_avg_top, 1)
            return round(edge, 1), breakdown
        except Exception:
            pass

    sc = {}; close = df["Close"].iloc[-1]
    # 1. TREND (equal 20% weight in composite; important for premium sellers)
    if len(df) >= 200:
        e20, e50, e200 = [TA.ema(df["Close"], p).iloc[-1] for p in (20, 50, 200)]
        sc["trend"] = 95 if close > e20 > e50 > e200 else (75 if close > e50 > e200 else (55 if close > e200 else 25))
    else: sc["trend"] = 60
    # 2. MOMENTUM (single indicator: RSI — avoids collinearity with MACD/CCI)
    rv = TA.rsi(df["Close"]).iloc[-1]
    sc["momentum"] = 85 if 40 <= rv <= 60 else (65 if 30 <= rv <= 70 else 25)
    # 3. VOLUME (OBV — measures accumulation/distribution, orthogonal to price momentum)
    obv_s = TA.obv(df)
    sc["volume"] = (85 if obv_s.iloc[-1] > obv_s.iloc[-20] else 35) if len(obv_s) >= 20 else 50
    # 4. VOLATILITY (ATR regime + VIX — for premium sellers, higher = better)
    if len(df) >= 20:
        atr_s = TA.atr(df)
        cur_atr = atr_s.iloc[-1]
        avg_atr = atr_s.iloc[-60:].mean() if len(df) >= 60 else cur_atr
        atr_ratio = cur_atr / avg_atr if avg_atr > 0 else 1
        vol_score = min(100, max(20, 50 + (atr_ratio - 1) * 30))
        if vix_val and vix_val > 0:
            vix_score = min(100, max(20, 30 + (vix_val - 12) * 3))
            vol_score = (vol_score + vix_score) / 2
        sc["volatility"] = round(float(vol_score), 1)
    else:
        sc["volatility"] = 50.0
    # 5. STRUCTURE (BOS/CHOCH — pattern-based, not derived from moving averages)
    struct, _, _ = TA.market_structure(df)
    sc["structure"] = 90.0 if struct == "BULLISH" else (50.0 if struct == "RANGING" else 20.0)

    for _k in ("trend", "momentum", "volume"):
        if _k in sc and isinstance(sc[_k], (int, float)):
            sc[_k] = round(float(sc[_k]), 1)
    composite = round(float(np.mean(list(sc.values()))), 1)
    mc_boost, mc_avg_top = _quant_edge_mc_pop_boost(options_data)
    if mc_boost > 0:
        composite = round(float(max(0.0, min(100.0, composite + mc_boost))), 1)
        sc["mc_pop_edge"] = round(mc_boost, 4)
        if mc_avg_top is not None:
            sc["mc_pop_top_avg"] = round(mc_avg_top, 1)
    sc["model"] = "retail"
    return composite, sc


def quant_edge_status_line(qs: float) -> str:
    """One-line desk read aligned with DashContext.qs_status."""
    if qs > 70:
        return "PRIME SELLING ENVIRONMENT"
    if qs > 50:
        return "DECENT SETUP"
    return "STAND DOWN. WAIT FOR A CLEANER ENTRY."


def _edge_row_worker(sym: str, vix_val, use_quant: bool):
    """Fetch daily bars and compute retail vs quant edge for one symbol (thread-pool worker)."""
    df = fetch_stock(sym, "1y", "1d")
    if df is None or df.empty:
        return None
    retail_s, _ = quant_edge_score(df, vix_val=vix_val, use_quant=False)
    inst_s, _ = quant_edge_score(df, vix_val=vix_val, use_quant=use_quant)
    r_int = int(round(float(retail_s)))
    q_int = int(round(float(inst_s)))
    return {
        "Ticker": sym.upper().strip(),
        "Retail": r_int,
        "Quant": q_int,
        "Delta": q_int - r_int,
        "Preview": quant_edge_status_line(float(inst_s)),
    }


def scan_watchlist_edge_rows(watch_items: list[str], vix_val, use_quant: bool) -> tuple[list[dict], list[str]]:
    """Fetch daily bars for **every** watchlist symbol (one task each), then sort by Quant (desc), Delta (desc), Ticker.

    Returns ``(rows, failed_tickers)`` where ``failed_tickers`` are symbols with no usable OHLC after fetch.
    """
    syms = [s.strip().upper() for s in watch_items if s and str(s).strip()]
    if not syms:
        return [], []
    n_workers = max(1, min(8, len(syms)))
    rows: list[dict] = []
    ts = datetime.now().strftime("%H:%M:%S")
    with make_script_ctx_pool(n_workers) as pool:
        futures = [submit_with_script_ctx(pool, _edge_row_worker, sym, vix_val, use_quant) for sym in syms]
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if r:
                    r["Time"] = ts
                    rows.append(r)
            except Exception:
                pass
    got = {r["Ticker"] for r in rows}
    failed = [s for s in syms if s not in got]
    rows.sort(key=lambda x: (-x["Quant"], -x["Delta"], x["Ticker"]))
    return rows, failed


def weekly_trend_label(df_wk):
    """Weekly bias using MACD(12,26,9) and EMA(20) on weekly closes."""
    try:
        if df_wk is None:
            return "UNKNOWN", "#64748b"
        if not isinstance(df_wk, pd.DataFrame):
            return "UNKNOWN", "#64748b"
        if len(df_wk) < 26:
            return "UNKNOWN", "#64748b"
        if "Close" not in df_wk.columns:
            return "UNKNOWN", "#64748b"
        close = pd.to_numeric(df_wk["Close"], errors="coerce").dropna()
        if len(close) < 26:
            return "UNKNOWN", "#64748b"
        ml, sl, _ = TA.macd(close, 12, 26, 9)
        e20 = TA.ema(close, 20).iloc[-1]
        above_ema = close.iloc[-1] > e20
        macd_bull = ml.iloc[-1] > sl.iloc[-1]
        if above_ema and macd_bull:
            return "BULLISH", "#10b981"
        if not above_ema and not macd_bull:
            return "BEARISH", "#ef4444"
        return "MIXED", "#f59e0b"
    except Exception:
        return "UNKNOWN", "#64748b"


# ═════════════════════════════════════════════════════════════════════════
#  GOLD ZONE — dynamic confluence support/resistance
# ═════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=120, show_spinner=False)
def calc_gold_zone(df, df_wk=None):
    """Gold Zone: mean of POC, Fib 61.8%, Gann Sq9, and 200-day SMA (institutional anchor).
    Nearest HVN within 2% of spot is fused as a primary anchor alongside POC/Fib.
    ``df_wk`` is accepted for API compatibility; SMA 200 replaces weekly S/R in the blend."""
    price = df["Close"].iloc[-1]
    components = {}

    try:
        nodes = TA.get_volume_nodes(df)
        hvn_px, _hvn_w = nearest_hvn_within_pct(float(price), nodes, 0.02)
        if hvn_px is not None:
            components["HVN"] = round(float(hvn_px), 2)
    except Exception:
        pass

    vp = TA.volume_profile(df)
    if not vp.empty:
        components["POC"] = vp.loc[vp["volume"].idxmax(), "mid"]

    if len(df) >= 60:
        rec = df.iloc[-60:]
        hi, lo = rec["High"].max(), rec["Low"].min()
        components["Fib 61.8%"] = hi - (hi - lo) * 0.618

    if len(df) >= 200:
        components["SMA 200"] = float(df["Close"].rolling(200).mean().iloc[-1])

    gann = TA.gann_sq9(price)
    if gann:
        nearest = min(gann.values(), key=lambda x: abs(x - price))
        components["Gann Sq9"] = nearest

    if components:
        gold_zone = round(np.mean(list(components.values())), 2)
        return gold_zone, components
    return round(price, 2), {}


# ═════════════════════════════════════════════════════════════════════════
#  CONFLUENCE POINTS — 0-to-9 scoring (Startup.io-inspired, enhanced)
# ═════════════════════════════════════════════════════════════════════════

def _calc_confluence_points_core(df, df_wk=None, vix_val=None, gold_zone_price=None, rsi_period=14):
    """Same scoring as the dashboard confluence meter — not cached.
    Safe to call on ``df.iloc[:i+1]`` for point-in-time diamond detection.
    Pass ``gold_zone_price`` when the caller already computed Gold Zone on the same frame to avoid duplicate work."""
    score = 0
    breakdown = {}
    price = df["Close"].iloc[-1]

    st_l, st_d = TA.supertrend(df)
    bull = st_d.iloc[-1] == 1
    pts = 2 if bull else 0
    score += pts
    breakdown["Supertrend"] = {"pts": pts, "max": 2, "detail": "Bullish" if bull else "Bearish"}

    _, _, sa, sb, _ = TA.ichimoku(df)
    above_cloud = (not pd.isna(sa.iloc[-1]) and not pd.isna(sb.iloc[-1])
                   and price > max(sa.iloc[-1], sb.iloc[-1]))
    pts = 2 if above_cloud else 0
    score += pts
    breakdown["Ichimoku"] = {"pts": pts, "max": 2, "detail": "Above Cloud" if above_cloud else "In/Below Cloud"}

    adx_v, dip, din = TA.adx(df)
    adx_val = adx_v.iloc[-1] if not pd.isna(adx_v.iloc[-1]) else 0
    dip_val = dip.iloc[-1] if not pd.isna(dip.iloc[-1]) else 0
    din_val = din.iloc[-1] if not pd.isna(din.iloc[-1]) else 0
    adx_bull = adx_val > 25 and dip_val > din_val
    pts = 1 if adx_bull else 0
    score += pts
    breakdown["ADX DI"] = {"pts": pts, "max": 1, "detail": f"ADX {adx_val:.0f}, plus DI leading minus DI" if adx_bull else f"ADX {adx_val:.0f}"}

    obv_s = TA.obv(df)
    obv_up = obv_s.iloc[-1] > obv_s.iloc[-20] if len(obv_s) >= 20 else False
    pts = 1 if obv_up else 0
    score += pts
    breakdown["OBV"] = {"pts": pts, "max": 1, "detail": "Accumulation" if obv_up else "Distribution"}

    rsi_s = TA.rsi(df["Close"], rsi_period)
    divs = TA.detect_divergences(df["Close"], rsi_s)
    bull_div = any(d["type"] == "bullish" for d in divs[-3:])
    pts = 1 if bull_div else 0
    score += pts
    breakdown["Divergence"] = {"pts": pts, "max": 1, "detail": "Bullish Div Found" if bull_div else "None"}

    if gold_zone_price is None:
        gold_zone, _ = calc_gold_zone(df, df_wk)
    else:
        gold_zone = gold_zone_price
    above_gz = price > gold_zone
    pts = 1 if above_gz else 0
    score += pts
    breakdown["Gold Zone"] = {"pts": pts, "max": 1, "detail": f"{'Above' if above_gz else 'Below'} ${gold_zone:.2f}"}

    struct, _, _ = TA.market_structure(df)
    pts = 1 if struct == "BULLISH" else 0
    score += pts
    breakdown["Structure"] = {"pts": pts, "max": 1, "detail": struct}

    bearish = 9 - score
    return score, 9, breakdown, bearish


@st.cache_data(ttl=300)
def calc_confluence_points(df, df_wk=None, vix_val=None, gold_zone_price=None, rsi_period=14):
    """Compute 0-9 bullish confluence score with per-component breakdown.
    Returns (score, max_score, breakdown_dict, bearish_score)."""
    return _calc_confluence_points_core(df, df_wk, vix_val, gold_zone_price, rsi_period=rsi_period)


# ═════════════════════════════════════════════════════════════════════════
#  DIAMOND SIGNAL DETECTION — Blue (buy) & Pink (exit/take-profit)
# ═════════════════════════════════════════════════════════════════════════

def _blue_diamond_volume_gate(sub):
    """Blue Diamond participation: last bar volume at or above 90% of the 20-day volume SMA."""
    if len(sub) < 20 or "Volume" not in sub.columns:
        return False
    vol = float(sub["Volume"].iloc[-1])
    vma = float(sub["Volume"].iloc[-20:].mean())
    if vma <= 0:
        return False
    return vol >= 0.9 * vma


def _blue_diamond_institutional_ok(sub):
    """Filter manic blue entries: skip only true blow-offs (ATR in top ~1% of its window)
    with weak participation. Normal trend days often sit near rolling ATR highs — those
    were incorrectly blocked before, so blues never matched the chart while pinks could still fire."""
    if len(sub) < 22:
        return False
    if not _blue_diamond_volume_gate(sub):
        return False
    vol = float(sub["Volume"].iloc[-1])
    vma = float(sub["Volume"].iloc[-20:].mean())

    atr = TA.atr(sub)
    ai = float(atr.iloc[-1])
    if pd.isna(ai) or ai <= 0:
        return True
    win = min(252, len(atr))
    atr_clean = atr.iloc[-win:].dropna()
    if atr_clean.empty:
        return True
    # Rank of today's ATR in the window (1.0 = at/above everyone) — block only top-tier expansion + weak vol
    rank = float((atr_clean <= ai).sum()) / len(atr_clean)
    if rank >= 0.99 and vol < 1.05 * vma:
        return False
    return True


def _index_pos(idx_obj):
    """Normalize df.index.get_loc result to a single integer position."""
    if isinstance(idx_obj, (int, np.integer)):
        return int(idx_obj)
    if isinstance(idx_obj, slice):
        return idx_obj.start
    arr = np.asarray(idx_obj)
    return int(arr.flat[-1])


def optimal_pyramid_size(df, capital=10000.0, target_vol=0.15):
    """
    Calculates the optimal number of shares to accumulate based on inverse volatility.
    Formula: S_t = (Capital * Target_Vol) / (Realized_Vol * Price)
    """
    if len(df) < 20:
        return 0
    price = float(df["Close"].iloc[-1])
    if price <= 0:
        return 0
    # 20-day annualized realized volatility
    realized_vol = float(df["Close"].pct_change().tail(20).std() * np.sqrt(252))
    if realized_vol <= 0:
        return 0

    # Calculate share size to target a specific portfolio volatility impact
    shares = (capital * target_vol) / (realized_vol * price)
    return max(1, int(shares))


def quant_trailing_exit(df, atr_multiplier=3.0):
    """
    Calculates a volatility-adjusted trailing stop (Pink Diamond exit).
    Formula: E_t = Max(High_22) - (k * ATR_22)
    """
    if len(df) < 22:
        return float(df["Close"].iloc[-1]) * 0.95
    high_22 = float(df["High"].tail(22).max())

    # Calculate simple ATR
    high_low = df["High"] - df["Low"]
    high_close = np.abs(df["High"] - df["Close"].shift())
    low_close = np.abs(df["Low"] - df["Close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr_22 = float(tr.tail(22).mean())
    if atr_22 <= 0:
        return max(0.0, high_22)

    return max(0.0, high_22 - (atr_multiplier * atr_22))


# Only scan the last N daily bars for diamonds (each bar runs full confluence on a growing slice).
_DIAMOND_SCAN_TAIL_BARS = 320


def _hurst_adaptive_signal_periods(close: pd.Series):
    """RSI length + MACD (fast, slow, signal) from Hurst: trending → slower, mean-reverting → faster."""
    H = float(TA.hurst(close))
    if H > 0.55:
        rsi_p = 21
    elif H < 0.45:
        rsi_p = 8
    else:
        rsi_p = 14
    k = rsi_p / 14.0
    macd_fast = max(2, int(round(12 * k)))
    macd_slow = max(macd_fast + 1, int(round(26 * k)))
    macd_sig = max(2, int(round(9 * k)))
    return rsi_p, macd_fast, macd_slow, macd_sig, H


@st.cache_data(ttl=300, show_spinner=False)
def detect_diamonds(df, df_wk=None, lookback=None, use_quant=False):
    """Blue Diamond (strict): point-in-time **daily** confluence **crosses** to 7+ (was <7 prior bar),
    **daily structure BULLISH**, **weekly trend not BEARISH**, **volume ≥ 90% of 20-day volume SMA**,
    plus ATR blow-off guard inside the institutional filter.

    Pink Diamond: confluence collapse (≤3 after ≥5) **or** RSI > 75 with fading score;
    weekly bias can be **BULLISH** too (take-profit / de-risk in extended runs).

    ``lookback`` is reserved for future use (unused). Scan window is capped to the last
    ``_DIAMOND_SCAN_TAIL_BARS`` rows so long histories stay responsive."""
    diamonds = []
    n = len(df)
    if n < 55:
        return diamonds

    rsi_p, mf, ms, mg, H = _hurst_adaptive_signal_periods(df["Close"])
    rsi_series = TA.rsi(df["Close"], rsi_p)
    ml_macd, sl_macd, _ = TA.macd(df["Close"], mf, ms, mg)

    wk_bias = "UNKNOWN"
    if df_wk is not None and len(df_wk) >= 26:
        wk_bias, _ = weekly_trend_label(df_wk)

    # First index where slice has 55 rows (need stable Ichimoku / gold / structure).
    start = 54
    scan_start = max(start, n - _DIAMOND_SCAN_TAIL_BARS)
    prev_score = 0
    if scan_start > start:
        _psc, _, _, _ = _calc_confluence_points_core(
            df.iloc[:scan_start], df_wk, None, None, rsi_period=rsi_p
        )
        prev_score = int(_psc)

    for i in range(scan_start, n):
        sub = df.iloc[: i + 1]
        sc, _, bd, _ = _calc_confluence_points_core(sub, df_wk, None, None, rsi_period=rsi_p)
        struct_i = (bd.get("Structure") or {}).get("detail", "RANGING")

        rsi_i = float(rsi_series.iloc[i]) if not pd.isna(rsi_series.iloc[i]) else 50.0
        pi = float(df["Close"].iloc[i])

        macd_bull_ok = True
        if H > 0.55:
            mlv = ml_macd.iloc[i]
            slv = sl_macd.iloc[i]
            if not pd.isna(mlv) and not pd.isna(slv):
                macd_bull_ok = float(mlv) > float(slv)

        # Blue: 7+ cross + daily BULLISH + weekly not BEARISH + explicit 90% vol SMA gate + ATR filter
        is_blue_diamond = (
            sc >= 7
            and prev_score < 7
            and struct_i == "BULLISH"
            and wk_bias != "BEARISH"
            and _blue_diamond_volume_gate(sub)
            and _blue_diamond_institutional_ok(sub)
            and macd_bull_ok
        )
        size_suggestion = 0
        quant_exit_price = 0.0

        # HMM / quant sizing is expensive — run only when retail already says blue (was: every bar × O(n) HMM).
        if use_quant and is_blue_diamond:
            try:
                from .sentiment import QuantSentiment
                regime_probs = QuantSentiment.regime_detection(sub)
                safe_regime_prob = float(regime_probs.get(0, 0.5))
                if safe_regime_prob < 0.75:
                    is_blue_diamond = False
                if is_blue_diamond:
                    size_suggestion = optimal_pyramid_size(sub)
                    quant_exit_price = quant_trailing_exit(sub)
            except Exception:
                size_suggestion = 0
                quant_exit_price = 0.0

        if is_blue_diamond:
            magnet = 0
            try:
                vp_sub = TA.volume_profile(sub)
                poc_sub = (
                    float(vp_sub.loc[vp_sub["volume"].idxmax(), "mid"])
                    if not vp_sub.empty
                    else None
                )
            except Exception:
                poc_sub = None
            try:
                nodes_sub = TA.get_volume_nodes(sub)
                hvn_p, _ = nearest_hvn_within_pct(pi, nodes_sub, 0.02)
            except Exception:
                hvn_p = None
            if poc_sub is not None and hvn_p is not None:
                lo, hi = min(poc_sub, hvn_p), max(poc_sub, hvn_p)
                if lo < pi < hi:
                    magnet = 1
            diamonds.append({
                "date": df.index[i],
                "price": pi,
                "type": "blue",
                "score": sc + magnet,
                "rsi": rsi_i,
                "weekly": wk_bias,
                "suggested_shares": size_suggestion,
                "trailing_exit": quant_exit_price,
                "liquidity_magnet": magnet,
            })

        # Pink: collapse or RSI exhaustion — allow BULLISH weeks too (fade / de-risk in extended runs)
        if (sc <= 3 and prev_score >= 5) or (rsi_i > 75 and sc <= 4 and prev_score > 4):
            if wk_bias in ("BEARISH", "MIXED", "UNKNOWN", "BULLISH"):
                diamonds.append({"date": df.index[i], "price": pi, "type": "pink",
                                 "score": sc, "rsi": rsi_i, "weekly": wk_bias})

        prev_score = sc

    return diamonds


def diamond_win_rate(df, diamonds, forward_bars=10):
    """Backtest diamond signals: for Blue, check if price rose; for Pink, check
    if price fell.  Returns (win_rate_pct, avg_return_pct, sample_count)."""
    if not diamonds:
        return 0.0, 0.0, 0

    wins, total = 0, 0
    returns = []

    for d in diamonds:
        try:
            loc = df.index.get_loc(d["date"])
            idx = _index_pos(loc)
        except KeyError:
            continue
        if idx + forward_bars >= len(df):
            continue

        entry = d["price"]
        exit_p = df["Close"].iloc[idx + forward_bars]

        if d["type"] == "blue":
            ret = (exit_p - entry) / entry * 100
            if exit_p > entry:
                wins += 1
        else:
            ret = (entry - exit_p) / entry * 100
            if exit_p < entry:
                wins += 1

        returns.append(ret)
        total += 1

    if total == 0:
        return 0.0, 0.0, 0
    return round(wins / total * 100, 1), round(float(np.mean(returns)), 2), total


def latest_diamond_status(diamonds):
    """Return the most recent diamond or None."""
    if not diamonds:
        return None
    return diamonds[-1]




def scan_single_ticker(tkr, correlation_haircut=1.0):
    """Fetch data and compute all scores for a single ticker (for the scanner)."""
    try:
        df = fetch_stock(tkr, "1y", "1d")
        if df is None or len(df) < 60:
            return None
        df_wk = fetch_stock(tkr, "2y", "1wk")
        price = df["Close"].iloc[-1]
        prev = df["Close"].iloc[-2] if len(df) >= 2 else price
        chg_pct = (price / prev - 1) * 100

        qs, _ = quant_edge_score(df)
        gold_zone, gz_comp = calc_gold_zone(df, df_wk)
        cp_score, cp_max, cp_bd, _ = calc_confluence_points(df, df_wk, None, gold_zone_price=gold_zone)
        diamonds = detect_diamonds(df, df_wk)
        latest_d = latest_diamond_status(diamonds)
        dist_gz = (price / gold_zone - 1) * 100 if gold_zone else 0

        struct, _, _ = TA.market_structure(df)
        wk_lbl, _ = weekly_trend_label(df_wk)

        nodes_s = TA.get_volume_nodes(df)
        hvn_floor, _ = nearest_hvn_within_pct(price, nodes_s, 0.02)

        T_scan = 30.0 / 365.0
        sig_scan = float(df["Close"].pct_change().tail(20).std() * np.sqrt(252))
        if not np.isfinite(sig_scan) or sig_scan <= 0:
            sig_scan = 0.35
        sig_scan = float(min(0.95, max(0.12, sig_scan)))
        K_scan = price * 0.97
        prem_scan = max(0.01, float(bs_price(price, K_scan, T_scan, 0.045, sig_scan, "put")) * 0.85)
        scanner_avg_mc = float(
            MonteCarloEngine.calc_pop(
                S=float(price),
                K=float(K_scan),
                T=T_scan,
                r=0.045,
                sigma=sig_scan,
                premium=prem_scan,
                option_type="put",
                strat="short",
            )
        )

        ret = df["Close"].pct_change().dropna()
        exp_ret = float(ret.mean() * 252) if len(ret) > 0 else 0.0
        ret_var = float(ret.var() * 252) if len(ret) > 1 else 0.0
        k_full, k_half = kelly_criterion(
            55.0,
            max(1.0, abs(chg_pct)),
            max(1.0, abs(chg_pct) * 1.5),
            use_quant=True,
            expected_return=exp_ret,
            variance=ret_var,
            correlation_haircut=correlation_haircut,
            avg_mc_pop=scanner_avg_mc,
        )

        d_status = "None"
        d_class = "badge-none"
        if latest_d:
            age = (df.index[-1] - latest_d["date"]).days
            if age <= 5:
                d_status = "🔷 BLUE" if latest_d["type"] == "blue" else "💎 PINK"
                d_class = "badge-blue" if latest_d["type"] == "blue" else "badge-pink"

        if cp_score >= 7:
            summary = "Strong bullish setup. High confluence buy zone."
        elif cp_score >= 5:
            summary = "Moderate bullish lean. Watch for confirmation."
        elif cp_score >= 3:
            summary = "Mixed signals. Neutral stance recommended."
        else:
            summary = "Bearish pressure. Defensive posture advised."

        d_wr, _d_avg, d_n = diamond_win_rate(df, diamonds, forward_bars=10)

        em_safety = "—"
        try:
            iv_pct_em = np.asarray(float(sig_scan * 100.0), dtype=float)
            dte_em = np.asarray(max(1, int(np.rint(float(T_scan) * 365.25))), dtype=float)
            em_move = float(Opt.calc_expected_move(float(price), float(iv_pct_em.item()), int(dte_em.item())))
            k_put = float(K_scan)
            sp = float(price)
            em_safety = "SAFE" if k_put < (sp - em_move) else "MONITOR"
        except Exception:
            em_safety = "—"

        return {
            "ticker": tkr,
            "price": price,
            "chg_pct": chg_pct,
            "qs": qs,
            "cp_score": cp_score,
            "cp_max": cp_max,
            "d_status": d_status,
            "d_class": d_class,
            "gold_zone": gold_zone,
            "dist_gz": dist_gz,
            "struct": struct,
            "wk_trend": wk_lbl,
            "summary": summary,
            "kelly_full": k_full,
            "kelly_half": k_half,
            "Adj. Kelly %": k_half,
            "diamond_pop": float(d_wr),
            "diamond_n": int(d_n),
            "hvn_floor": float(hvn_floor) if hvn_floor is not None else None,
            "scanner_mc_pop": round(scanner_avg_mc, 1),
            "gz_hvn": gz_comp.get("HVN"),
            "EM Safety": em_safety,
        }
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════
#  OPTIONS ENGINE
# ═════════════════════════════════════════════════════════════════════════

class Opt:
    DELTA_TARGET = 0.16
    DELTA_LOW, DELTA_HIGH = 0.15, 0.20
    MIN_OI, MIN_VOL = 100, 10
    RELAXED_MIN_OI, RELAXED_MIN_VOL = 10, 1

    @staticmethod
    def calc_expected_move(price, iv, days_to_expiry):
        """Calculates the 1-Standard Deviation Implied Move (scalar or numpy-vectorized)."""
        try:
            p = np.asarray(price, dtype=float)
            iv_a = np.asarray(iv, dtype=float)
            d = np.asarray(days_to_expiry, dtype=float)
            t_years = d / 365.25
            with np.errstate(invalid="ignore"):
                em = p * (iv_a / 100.0) * np.sqrt(np.maximum(t_years, 0.0))
            ok = (d > 0) & (iv_a > 0) & np.isfinite(em)
            em = np.where(ok, em, 0.0)
            if em.size == 1:
                v = float(em.reshape(-1)[0])
                return v if np.isfinite(v) else 0.0
            return em
        except Exception:
            try:
                sz = np.asarray(price).size
                return 0.0 if sz <= 1 else np.zeros_like(np.asarray(price, dtype=float))
            except Exception:
                return 0.0

    @staticmethod
    def _simple_corr_haircut(watchlist_tickers, symbol, returns_df):
        try:
            if len(watchlist_tickers) < 2 or returns_df is None or getattr(returns_df, "empty", True):
                return 1.0
            sym = str(symbol).strip().upper()
            if sym not in returns_df.columns:
                return 1.0
            c = returns_df.corr(numeric_only=True)
            if sym not in c.columns:
                return 1.0
            others = c[sym].drop(sym, errors="ignore")
            if others.empty:
                return 1.0
            avg_corr = float(others.mean())
            if not np.isfinite(avg_corr):
                return 1.0
            return float(max(0.35, 1.0 - avg_corr))
        except Exception:
            return 1.0

    @staticmethod
    def _liquidity_magnet_bonus(strike, poc, hvn_anchor):
        try:
            if poc is None or hvn_anchor is None:
                return 0
            s, p, h = float(strike), float(poc), float(hvn_anchor)
            lo, hi = min(p, h), max(p, h)
            return 1 if lo < s < hi else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_mc_pop(**kwargs):
        try:
            return float(MonteCarloEngine.calc_pop(**kwargs))
        except Exception:
            return 50.0

    @staticmethod
    def _sc(otm, py, ann, vol, delta=None):
        base = py * .25 + min(otm, 15) * .15 + min(ann, 50) * .15 + (1 if vol and vol > 100 else 0) * .05
        if delta is not None:
            d = abs(delta)
            if Opt.DELTA_LOW <= d <= Opt.DELTA_HIGH:
                base += (1.0 - abs(d - Opt.DELTA_TARGET) / 0.05) * 5
            elif d < 0.10 or d > 0.30:
                base *= 0.5
        return base

    @staticmethod
    def covered_calls(price, calls_df, dte=30, rfr=0.045, poc=None, hvn_anchor=None):
        if calls_df is None or calls_df.empty: return []
        rows = []; T_y = max(dte, 1) / 365
        for _, r in calls_df.iterrows():
            s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
            iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
            mid = (b + a) / 2 if b > 0 and a > 0 else 0
            if s <= price or mid <= .01: continue
            if oi < Opt.MIN_OI or vol < Opt.MIN_VOL: continue
            otm = (s - price) / price * 100; py = mid / price * 100; ann = py * 365 / max(dte, 1)
            iv_dec = iv if iv > 0 else 0.5
            greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "call")
            delta = greeks["delta"]
            _tgr = _theta_gamma_ratio_from_greeks(greeks)
            mc_pop = Opt._safe_mc_pop(
                S=price,
                K=s,
                T=T_y,
                r=rfr,
                sigma=iv_dec,
                premium=mid,
                option_type="call",
                strat="short",
            )
            _mag = Opt._liquidity_magnet_bonus(s, poc, hvn_anchor)
            rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                         "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                         "prem_100": mid * 100, "breakeven": price - mid,
                         "delta": round(delta, 3), "theta_gamma_ratio": _tgr, "optimal": False,
                         "score": Opt._sc(otm, py, ann, vol, delta) + _mag, "mc_pop": round(mc_pop, 1)})
        # Relax liquidity gates if strict pass returns nothing (common on thin chains / after-hours).
        if not rows:
            for _, r in calls_df.iterrows():
                s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
                iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
                mid = (b + a) / 2 if b > 0 and a > 0 else 0
                if s <= price or mid <= .01: continue
                if oi < Opt.RELAXED_MIN_OI or vol < Opt.RELAXED_MIN_VOL: continue
                otm = (s - price) / price * 100; py = mid / price * 100; ann = py * 365 / max(dte, 1)
                iv_dec = iv if iv > 0 else 0.5
                greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "call")
                delta = greeks["delta"]
                _tgr = _theta_gamma_ratio_from_greeks(greeks)
                mc_pop = Opt._safe_mc_pop(
                    S=price,
                    K=s,
                    T=T_y,
                    r=rfr,
                    sigma=iv_dec,
                    premium=mid,
                    option_type="call",
                    strat="short",
                )
                _mag = Opt._liquidity_magnet_bonus(s, poc, hvn_anchor)
                rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                             "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                             "prem_100": mid * 100, "breakeven": price - mid,
                             "delta": round(delta, 3), "theta_gamma_ratio": _tgr, "optimal": False,
                             "score": Opt._sc(otm, py, ann, vol, delta) + _mag, "mc_pop": round(mc_pop, 1)})
        rows.sort(key=lambda x: x["score"], reverse=True)
        if rows:
            best = min(range(len(rows)), key=lambda i: abs(rows[i]["delta"] - Opt.DELTA_TARGET))
            rows[best]["optimal"] = True
        return rows[:8]

    @staticmethod
    def cash_secured_puts(price, puts_df, dte=30, rfr=0.045, poc=None, hvn_anchor=None):
        if puts_df is None or puts_df.empty: return []
        rows = []; T_y = max(dte, 1) / 365
        for _, r in puts_df.iterrows():
            s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
            iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
            mid = (b + a) / 2 if b > 0 and a > 0 else 0
            if s >= price or mid <= .01: continue
            if oi < Opt.MIN_OI or vol < Opt.MIN_VOL: continue
            otm = (price - s) / price * 100; py = mid / s * 100; ann = py * 365 / max(dte, 1)
            iv_dec = iv if iv > 0 else 0.5
            greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "put")
            delta = greeks["delta"]
            _tgr = _theta_gamma_ratio_from_greeks(greeks)
            mc_pop = Opt._safe_mc_pop(
                S=price,
                K=s,
                T=T_y,
                r=rfr,
                sigma=iv_dec,
                premium=mid,
                option_type="put",
                strat="short",
            )
            _mag = Opt._liquidity_magnet_bonus(s, poc, hvn_anchor)
            rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                         "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                         "prem_100": mid * 100, "eff_buy": s - mid, "cash_req": s * 100,
                         "delta": round(delta, 3), "theta_gamma_ratio": _tgr, "optimal": False,
                         "score": Opt._sc(otm, py, ann, vol, delta) + _mag, "mc_pop": round(mc_pop, 1)})
        if not rows:
            for _, r in puts_df.iterrows():
                s, b, a = r.get("strike", 0), r.get("bid", 0), r.get("ask", 0)
                iv = r.get("impliedVolatility", 0); vol, oi = r.get("volume", 0) or 0, r.get("openInterest", 0) or 0
                mid = (b + a) / 2 if b > 0 and a > 0 else 0
                if s >= price or mid <= .01: continue
                if oi < Opt.RELAXED_MIN_OI or vol < Opt.RELAXED_MIN_VOL: continue
                otm = (price - s) / price * 100; py = mid / s * 100; ann = py * 365 / max(dte, 1)
                iv_dec = iv if iv > 0 else 0.5
                greeks = bs_greeks(price, s, T_y, rfr, iv_dec, "put")
                delta = greeks["delta"]
                _tgr = _theta_gamma_ratio_from_greeks(greeks)
                mc_pop = Opt._safe_mc_pop(
                    S=price,
                    K=s,
                    T=T_y,
                    r=rfr,
                    sigma=iv_dec,
                    premium=mid,
                    option_type="put",
                    strat="short",
                )
                _mag = Opt._liquidity_magnet_bonus(s, poc, hvn_anchor)
                rows.append({"strike": s, "bid": b, "ask": a, "mid": mid, "iv": iv * 100 if iv else 0,
                             "volume": vol, "oi": oi, "otm_pct": otm, "prem_yield": py, "ann_yield": ann,
                             "prem_100": mid * 100, "eff_buy": s - mid, "cash_req": s * 100,
                             "delta": round(delta, 3), "theta_gamma_ratio": _tgr, "optimal": False,
                             "score": Opt._sc(otm, py, ann, vol, delta) + _mag, "mc_pop": round(mc_pop, 1)})
        rows.sort(key=lambda x: x["score"], reverse=True)
        if rows:
            best = min(range(len(rows)), key=lambda i: abs(abs(rows[i]["delta"]) - Opt.DELTA_TARGET))
            rows[best]["optimal"] = True
        return rows[:8]

    @staticmethod
    def credit_spreads(price, opts_df, stype="put_credit"):
        if opts_df is None or opts_df.empty: return []
        rows = []; strikes = sorted(opts_df["strike"].unique())
        for i in range(len(strikes)):
            for j in range(i + 1, min(i + 6, len(strikes))):
                ss = strikes[i] if stype == "call_credit" else strikes[j]
                ls = strikes[j] if stype == "call_credit" else strikes[i]
                sr, lr = opts_df[opts_df["strike"] == ss], opts_df[opts_df["strike"] == ls]
                if sr.empty or lr.empty: continue
                s_oi = (sr["openInterest"].values[0] or 0) if "openInterest" in sr.columns else 0
                s_vol = (sr["volume"].values[0] or 0) if "volume" in sr.columns else 0
                l_oi = (lr["openInterest"].values[0] or 0) if "openInterest" in lr.columns else 0
                l_vol = (lr["volume"].values[0] or 0) if "volume" in lr.columns else 0
                if s_oi < Opt.MIN_OI or s_vol < Opt.MIN_VOL: continue
                if l_oi < Opt.MIN_OI or l_vol < Opt.MIN_VOL: continue
                sm = (sr["bid"].values[0] + sr["ask"].values[0]) / 2
                lm = (lr["bid"].values[0] + lr["ask"].values[0]) / 2
                cr = sm - lm; w = abs(ss - ls)
                if cr <= 0 or w <= cr: continue
                ml = (w - cr) * 100
                otm = ((price - ss) / price * 100) if stype == "put_credit" else ((ss - price) / price * 100)
                if otm < 0: continue
                pop = max(30, min(95, (1 - cr / w) * 100))
                rows.append({"short": ss, "long": ls, "credit": cr, "credit_100": cr * 100,
                             "max_loss": ml, "width": w, "rr": cr / (w - cr), "pop": pop, "otm_pct": otm,
                             "be": ss - cr if stype == "put_credit" else ss + cr})
        rows.sort(key=lambda x: x["rr"] * x["pop"], reverse=True)
        return rows[:8]


def calc_skew_regime(opts_df, spot_price):
    """
    Calculates the volatility skew regime by comparing OTM put IV to OTM call IV.
    Returns a tuple: (Regime Label, Hex Color, Description)
    """
    if opts_df is None or opts_df.empty or "impliedVolatility" not in opts_df.columns:
        return "Unknown", "#94a3b8", "Insufficient data."

    df = opts_df[(opts_df["impliedVolatility"] > 0.05) & (opts_df["impliedVolatility"] < 3.0)].copy()
    if df.empty or "type" not in df.columns or "strike" not in df.columns:
        return "Unknown", "#94a3b8", "Insufficient data."

    otm_puts = df[(df["type"] == "put") & (df["strike"] < spot_price)]
    otm_calls = df[(df["type"] == "call") & (df["strike"] > spot_price)]
    if otm_puts.empty or otm_calls.empty:
        return "Neutral / Illiquid", "#94a3b8", "Not enough OTM options to determine regime."

    avg_put_iv = float(pd.to_numeric(otm_puts["impliedVolatility"], errors="coerce").median())
    avg_call_iv = float(pd.to_numeric(otm_calls["impliedVolatility"], errors="coerce").median())
    if not np.isfinite(avg_put_iv) or not np.isfinite(avg_call_iv) or avg_call_iv <= 0:
        return "Unknown", "#94a3b8", "Insufficient data."

    skew_ratio = avg_put_iv / avg_call_iv
    if skew_ratio > 1.25:
        return "CRASH HEDGING", "#ef4444", f"Severe downside fear. Put IV is {skew_ratio:.2f}x higher than Call IV."
    if skew_ratio > 1.08:
        return "BEARISH SKEW", "#f97316", f"Downside protection. Put IV is {skew_ratio:.2f}x higher than Call IV."
    if skew_ratio < 0.85:
        return "UPSIDE MANIA", "#22c55e", f"Call frenzy. Call IV is {(1 / skew_ratio):.2f}x higher than Put IV."
    return "BALANCED SMILE", "#3b82f6", f"Neutral skew. Put and Call IV are relatively balanced (Ratio: {skew_ratio:.2f})."


class PortfolioRisk:
    @staticmethod
    def build_correlation_matrix(closes_df, window=60):
        """
        Takes a DataFrame where columns are tickers and rows are daily closing prices.
        Returns a rolling correlation matrix based on log returns.
        """
        if closes_df is None or closes_df.empty or len(closes_df) < window:
            return None

        # Institutional standard: use log returns for correlation, not absolute price.
        log_returns = np.log(closes_df / closes_df.shift(1)).dropna()
        recent_returns = log_returns.tail(window)
        if recent_returns.empty:
            return None
        return recent_returns.corr()

    @staticmethod
    def get_overlap_score(corr_matrix, ticker):
        """
        Calculates the average correlation of a specific ticker against the rest of the matrix.
        """
        if corr_matrix is None or ticker not in corr_matrix.columns or len(corr_matrix.columns) < 2:
            return 0.0

        # Drop self-correlation (which is always 1.0) and get the mean of the rest.
        others = corr_matrix[ticker].drop(labels=[ticker], errors="ignore")
        if others.empty:
            return 0.0
        return float(others.mean())

    @staticmethod
    def calc_kelly_haircut(overlap_score):
        """
        Determines the Kelly multiplier based on correlation risk.
        > 0.8: Extreme Overlap (50% Haircut)
        > 0.6: High Overlap (25% Haircut)
        < 0.0: True Hedge (20% Sizing Boost)
        """
        if overlap_score >= 0.8:
            return 0.50
        if overlap_score >= 0.6:
            return 0.75
        if overlap_score <= 0.0:
            return 1.20
        return 1.0


class MonteCarloEngine:
    @staticmethod
    def calc_pop(
        S,
        K,
        T,
        r,
        sigma,
        premium,
        option_type="put",
        strat="short",
        simulations=10000,
        dividend_yield=0.0,
        skew=0.0,
    ):
        """
        Vectorized GBM Monte Carlo Probability of Profit (PoP).
        Antithetic standard normals + fixed seed (42) for stable Streamlit reruns.
        Optional dividend yield in the drift; optional skew tilts shocks (Edgeworth-style,
        complementary to Corrado–Su closed-form pricing elsewhere in this module).
        """
        if T <= 0 or sigma <= 0 or S <= 0:
            return 50.0

        sims = int(max(100, simulations))
        half = max(1, sims // 2)
        rng = np.random.default_rng(seed=42)
        Z_half = rng.standard_normal(half)
        Z = np.concatenate([Z_half, -Z_half])
        if abs(float(skew)) > 1e-12:
            Z = Z + (float(skew) / 6.0) * (Z**2 - 1.0)

        drift = r - float(dividend_yield) - 0.5 * sigma**2
        S_T = S * np.exp(drift * T + sigma * np.sqrt(T) * Z)

        if option_type == "put":
            be = (K - premium)
            if strat == "short":
                success = np.sum(S_T >= be)
            else:
                success = np.sum(S_T < be)
        elif option_type == "call":
            be = (K + premium)
            if strat == "short":
                success = np.sum(S_T <= be)
            else:
                success = np.sum(S_T > be)
        else:
            return 50.0

        n_paths = int(Z.shape[0])
        return float((success / n_paths) * 100.0) if n_paths > 0 else 50.0


def _norm_cdf_vec(z):
    """Vectorized normal CDF for numpy arrays (SciPy if available)."""
    z = np.asarray(z, dtype=float)
    if norm is not None:
        return norm.cdf(z)
    return np.vectorize(_cdf, otypes=[float])(z)


def _vectorized_theta_gamma(S, K_arr, T_y, r, sigma_arr, option_type):
    """Black–Scholes per-day theta and gamma for 1D strike/IV arrays (calls or puts)."""
    S = float(S)
    K_arr = np.asarray(K_arr, dtype=float)
    sigma_arr = np.maximum(np.asarray(sigma_arr, dtype=float), 0.001)
    T_y = max(float(T_y), 1e-12)
    sqrtT = np.sqrt(T_y)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(S / K_arr) + (r + 0.5 * sigma_arr**2) * T_y) / (sigma_arr * sqrtT)
        d2 = d1 - sigma_arr * sqrtT
    pdf = np.exp(-0.5 * d1 * d1) / np.sqrt(2.0 * np.pi)
    gamma = pdf / (S * sigma_arr * sqrtT)
    exp_rt = np.exp(-r * T_y)
    if option_type == "call":
        cdf_d2 = _norm_cdf_vec(d2)
        theta = (-S * pdf * sigma_arr / (2 * sqrtT) - r * K_arr * exp_rt * cdf_d2) / 365.0
    else:
        cdf_nd2 = _norm_cdf_vec(-d2)
        theta = (-S * pdf * sigma_arr / (2 * sqrtT) + r * K_arr * exp_rt * cdf_nd2) / 365.0
    return theta, gamma


def _theta_gamma_ratio_from_greeks(greeks):
    try:
        gm = float(greeks.get("gamma") or 0.0)
        if abs(gm) < 1e-12:
            return None
        return round(float(greeks.get("theta") or 0.0) / gm, 4)
    except (TypeError, ValueError):
        return None


def build_chain_mc_dataframe(price, calls_df, puts_df, dte, rfr=0.045):
    """Every strike in the Yahoo chain with vectorized Θ/Γ and MC PoP % (short premium)."""
    T_y = max(int(dte), 1) / 365.0
    rows = []
    S = float(price)
    for label, sub, otype in (("Call", calls_df, "call"), ("Put", puts_df, "put")):
        if sub is None or sub.empty:
            continue
        sub = sub.copy()
        strike = pd.to_numeric(sub.get("strike"), errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(sub.get("bid"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        a = pd.to_numeric(sub.get("ask"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        mid = np.where((b > 0) & (a > 0), (b + a) / 2.0, 0.0)
        iv = pd.to_numeric(sub.get("impliedVolatility"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        iv_dec = np.where(iv > 0, iv, 0.5)
        valid = (mid > 0.01) & (strike > 0) & np.isfinite(strike) & np.isfinite(mid)
        if not np.any(valid):
            continue
        kv = strike[valid]
        midv = mid[valid]
        bv, av = b[valid], a[valid]
        ivv = iv_dec[valid]
        iv_pct_col = np.where(iv[valid] > 0, iv[valid] * 100.0, ivv * 100.0)
        theta_v, gamma_v = _vectorized_theta_gamma(S, kv, T_y, rfr, ivv, otype)
        tg = np.where(np.abs(gamma_v) > 1e-12, theta_v / gamma_v, np.nan)
        for i in range(kv.shape[0]):
            try:
                mc = MonteCarloEngine.calc_pop(
                    S,
                    float(kv[i]),
                    T_y,
                    rfr,
                    float(ivv[i]),
                    float(midv[i]),
                    option_type=otype,
                    strat="short",
                )
                tgi = float(tg[i]) if np.isfinite(tg[i]) else None
                rows.append(
                    {
                        "Type": label,
                        "Strike": float(kv[i]),
                        "Bid": float(bv[i]),
                        "Ask": float(av[i]),
                        "Mid": round(float(midv[i]), 4),
                        "IV %": round(float(iv_pct_col[i]), 2),
                        "Θ/Γ": round(tgi, 4) if tgi is not None else None,
                        "MC PoP %": round(float(mc), 1),
                    }
                )
            except Exception:
                continue
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.reset_index(drop=True)

