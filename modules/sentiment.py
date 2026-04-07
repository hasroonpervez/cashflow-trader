"""
Sentiment, Backtest simulator, and Alerts scanner.
"""
import contextlib
import io
import logging
import streamlit as st
import pandas as pd
import numpy as np
import math
from datetime import datetime

from .ta import TA
from .data import fetch_stock
from .utils import log_warn, safe_float, safe_last

try:
    from hmmlearn import hmm
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False

# hmmlearn/sklearn can spam stderr with "Model is not converging" and stall on tiny / wild series.
_HMM_MAX_ROWS = 200
_HMM_N_ITER = 18
_HMM_TOL = 0.15

# (phrase, sentiment +1 bull / -1 bear, tier: forward-looking vs trailing)
_NEWS_LEXICON = [
    # Forward — higher Bayesian weight (guidance / outlook dominates mixed prints)
    ("raises full-year guidance", +1, "forward"),
    ("raises guidance", +1, "forward"),
    ("raised guidance", +1, "forward"),
    ("lifting guidance", +1, "forward"),
    ("strong guidance", +1, "forward"),
    ("upbeat guidance", +1, "forward"),
    ("forecast beat", +1, "forward"),
    ("forecast beats", +1, "forward"),
    ("outlook raised", +1, "forward"),
    ("outlook improves", +1, "forward"),
    ("positive outlook", +1, "forward"),
    ("bullish outlook", +1, "forward"),
    ("revenue forecast", +1, "forward"),
    ("eps forecast", +1, "forward"),
    ("forward guidance", +1, "forward"),
    ("next quarter outlook", +1, "forward"),
    ("fiscal year outlook", +1, "forward"),
    ("raises outlook", +1, "forward"),
    ("raises revenue outlook", +1, "forward"),
    ("accelerating growth", +1, "forward"),
    ("pipeline strong", +1, "forward"),
    ("record backlog", +1, "forward"),
    ("lowers guidance", -1, "forward"),
    ("cuts guidance", -1, "forward"),
    ("weak outlook", -1, "forward"),
    ("cautious outlook", -1, "forward"),
    ("disappointing guidance", -1, "forward"),
    # Trailing — lower weight (backward-looking print)
    ("missed earnings", -1, "trailing"),
    ("missed estimates", -1, "trailing"),
    ("misses estimates", -1, "trailing"),
    ("earnings miss", -1, "trailing"),
    ("revenue miss", -1, "trailing"),
    ("eps miss", -1, "trailing"),
    ("beat earnings", +1, "trailing"),
    ("beats estimates", +1, "trailing"),
    ("earnings beat", +1, "trailing"),
    ("revenue beat", +1, "trailing"),
    ("top line beat", +1, "trailing"),
    ("bottom line beat", +1, "trailing"),
    ("surprise profit", +1, "trailing"),
    # Generic (medium tier — trailing-style weight)
    ("upgrade", +1, "trailing"),
    ("downgrade", -1, "trailing"),
    ("bullish", +1, "trailing"),
    ("bearish", -1, "trailing"),
    ("surge", +1, "trailing"),
    ("plunge", -1, "trailing"),
    ("rally", +1, "trailing"),
    ("selloff", -1, "trailing"),
    ("bankrupt", -1, "trailing"),
    ("investigation", -1, "trailing"),
    ("lawsuit", -1, "trailing"),
    ("strong demand", +1, "trailing"),
    ("weak demand", -1, "trailing"),
]
_NEWS_LEXICON.sort(key=lambda x: -len(x[0]))

_FORWARD_W, _TRAIL_W = 1.45, 0.82


class QuantSentiment:
    @staticmethod
    def regime_detection(df, n_regimes=2):
        """
        Uses a Gaussian Hidden Markov Model to probabilistically classify market regimes.
        Returns a dictionary of state probabilities for the latest day.
        """
        from .ta import TA

        if not HMM_AVAILABLE or df is None or len(df) < 50:
            return {0: 0.5, 1: 0.5}

        stationary_close = TA.apply_ffd(df["Close"], d=0.4)
        if stationary_close is None or len(stationary_close) < 40:
            return {0: 0.5, 1: 0.5}

        returns = stationary_close.diff().replace([np.inf, -np.inf], np.nan).dropna()
        volatility = returns.rolling(window=10).std().dropna()
        data = pd.concat([returns, volatility], axis=1).dropna()
        if data.empty or len(data) < 40:
            return {0: 0.5, 1: 0.5}

        X = np.asarray(data.values, dtype=np.float64)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        # Tail only: faster fit, stable for Cloud; last row stays the "current" bar.
        if len(X) > _HMM_MAX_ROWS:
            X = X[-_HMM_MAX_ROWS:]
        # Light scale — helps full-cov numerical stability; we use diag below anyway.
        std = X.std(axis=0)
        std = np.where(std < 1e-8, 1.0, std)
        X = X / std

        model = hmm.GaussianHMM(
            n_components=n_regimes,
            covariance_type="diag",
            n_iter=_HMM_N_ITER,
            tol=_HMM_TOL,
            random_state=42,
        )
        hmm_log = logging.getLogger("hmmlearn")
        prev_lvl = hmm_log.level
        try:
            hmm_log.setLevel(logging.CRITICAL)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                model.fit(X)
            probabilities = model.predict_proba(X)
            current_probs = probabilities[-1]
            return {i: float(prob) for i, prob in enumerate(current_probs)}
        except Exception as e:
            log_warn("QuantSentiment.regime_detection HMM fit", e)
            return {0: 0.5, 1: 0.5}
        finally:
            hmm_log.setLevel(prev_lvl)


class Sentiment:
    @staticmethod
    def analyze_news_bias(headlines):
        """
        Bayesian-style weighted lexicon: neutral prior, **forward** phrases (guidance, outlook,
        forecast) outweigh **trailing** prints (beat/miss). Mixed headlines resolve toward
        stronger forward signals. Score in ``[-1, 1]``; empty input → ``0.0``.
        """
        if not headlines:
            return 0.0
        prior = 0.0
        headline_scores = []
        for h in headlines:
            if isinstance(h, dict):
                t = str(h.get("title") or "")
            else:
                t = str(h)
            t_low = t.lower()
            if not t_low.strip():
                continue
            work = t_low
            log_evidence = 0.0
            for phrase, direction, tier in _NEWS_LEXICON:
                if phrase in work:
                    w = _FORWARD_W if tier == "forward" else _TRAIL_W
                    log_evidence += float(direction) * w
                    work = work.replace(phrase, " ", 1)
            if abs(log_evidence) < 1e-9:
                continue
            headline_scores.append(float(np.tanh(log_evidence / 2.8)))
        if not headline_scores:
            return 0.0
        combined = prior + float(np.sum(headline_scores))
        denom = float(len(headline_scores))
        return float(np.clip(np.tanh(combined / max(1.0, denom)), -1.0, 1.0))

    @staticmethod
    def fear_greed(df, vix_val=None):
        closes = df["Close"]
        rsi_s = TA.rsi(closes)
        sc = [min(100, max(0, safe_float(safe_last(rsi_s), 50.0)))]
        close_last = safe_float(safe_last(closes), 0.0)
        if len(df) >= 200:
            sma200 = safe_float(safe_last(closes.rolling(200).mean()), close_last)
        else:
            sma200 = safe_float(float(closes.mean()), close_last) if len(df) else close_last
        if sma200 and abs(sma200) > 1e-12:
            sc.append(min(100, max(0, 50 + (close_last / sma200 - 1) * 500)))
        else:
            sc.append(50.0)
        if len(df) >= 20:
            c20 = safe_float(closes.iloc[-20], close_last)
            if c20 and abs(c20) > 1e-12:
                sc.append(min(100, max(0, 50 + (close_last / c20 - 1) * 300)))
            tail_pct = closes.pct_change().iloc[-20:]
            cv = safe_float(tail_pct.std(), 0.0) * np.sqrt(252) * 100
            hv = safe_float(closes.pct_change().std(), 0.0) * np.sqrt(252) * 100
            sc.append(max(0, min(100, 100 - cv / max(hv, 1) * 50)))
        if vix_val and vix_val > 0:
            sc.append(max(0, min(100, 100 - (vix_val - 12) * 3)))
        return float(np.mean(sc))

    @staticmethod
    def interpret(s):
        if s >= 80: return "Extreme Greed","🔴","Everyone is euphoric. Sell calls aggressively and collect the hype premium."
        if s >= 60: return "Greed","🟠","Market is confident. Sell covered calls at higher strikes to ride the wave."
        if s >= 40: return "Neutral","🟡","Market is calm. Standard premium selling works great here."
        if s >= 20: return "Fear","🟢","Fear is elevated. Premiums are fat. Sell aggressively and collect extra cash."
        return "Extreme Fear","💚","Maximum panic. Premiums are huge. Sell puts at deep discounts and get paid."

class Backtest:
    @staticmethod
    def cc_sim(df, otm_pct=.05, hold=30, iv_m=1.0):
        """Quick premium heuristic sweep — not Black-Scholes; live desk uses ``bs_price`` paths."""
        results = []; rvol = df["Close"].pct_change().rolling(20).std()*np.sqrt(252)
        i = 20
        while i < len(df) - hold:
            entry = df["Close"].iloc[i]; strike = entry*(1+otm_pct)
            iv = rvol.iloc[i]
            if pd.isna(iv) or iv <= 0: iv = 0.5
            iv *= iv_m; tf = math.sqrt(hold/365)
            d1a = otm_pct/(iv*tf) if iv*tf > 0 else 1
            prem = entry*iv*tf*max(.05,.4-.3*min(d1a,2)); prem = max(prem, entry*.003)
            exit_p = df["Close"].iloc[i+hold]
            if exit_p >= strike: profit = (strike-entry)+prem; out = "Called Away"
            else: profit = prem+(exit_p-entry); out = "Expired OTM"
            results.append({"entry_date":df.index[i],"exit_date":df.index[i+hold],
                "entry":entry,"strike":strike,"exit":exit_p,"iv_est":iv*100,
                "premium":prem,"profit":profit,"ret_pct":profit/entry*100,"outcome":out})
            i += hold
        return pd.DataFrame(results)


@st.cache_data(ttl=120, show_spinner=False)
def run_cc_sim_cached(ticker: str, period: str, otm_pct: float, hold_days: int, iv_mult: float) -> pd.DataFrame:
    """Premium simulator: reuse cached OHLC; avoids recomputing the same sweep on every interaction."""
    df_bt = fetch_stock(ticker, period, "1d")
    if df_bt is None or len(df_bt) < hold_days + 20:
        return pd.DataFrame()
    return Backtest.cc_sim(df_bt, otm_pct, hold_days, iv_mult)


class Alerts:
    @staticmethod
    def scan(df, ticker, vix_val=None):
        alerts = []; close = df["Close"].iloc[-1]; rv = TA.rsi(df["Close"]).iloc[-1]
        if rv < 30: alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} RSI is {rv:.1f}. Stock is oversold. Great time to sell puts and collect cash."})
        elif rv > 70: alerts.append({"t":"bearish","p":"MEDIUM","m":f"{ticker} RSI is {rv:.1f}. Stock is overbought. Sell covered calls now."})
        ml, sl, _ = TA.macd(df["Close"])
        if len(ml) >= 2:
            if ml.iloc[-1] > sl.iloc[-1] and ml.iloc[-2] <= sl.iloc[-2]:
                alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} MACD just crossed bullish. Buyers are taking over."})
            elif ml.iloc[-1] < sl.iloc[-1] and ml.iloc[-2] >= sl.iloc[-2]:
                alerts.append({"t":"bearish","p":"MEDIUM","m":f"{ticker} MACD just crossed bearish. Sellers are gaining control."})
        u, _, lo = TA.bollinger(df["Close"])
        if len(u)>1:
            bw = (u.iloc[-1]-lo.iloc[-1])/((u.iloc[-1]+lo.iloc[-1])/2)*100
            if bw < 5: alerts.append({"t":"neutral","p":"HIGH","m":f"{ticker} Bollinger squeeze detected. A big move is coming soon."})
        if vix_val and vix_val > 30: alerts.append({"t":"bullish","p":"HIGH","m":f"VIX is {vix_val:.1f}. Extreme fear. Premiums are huge right now."})
        elif vix_val and vix_val > 25: alerts.append({"t":"bullish","p":"MEDIUM","m":f"VIX is {vix_val:.1f}. Fear is elevated. Good time to sell options."})
        st_l, st_d = TA.supertrend(df)
        if len(st_d) >= 2:
            if st_d.iloc[-1]==1 and st_d.iloc[-2]==-1: alerts.append({"t":"bullish","p":"HIGH","m":f"{ticker} Supertrend just flipped BULLISH. The price floor is rising."})
            elif st_d.iloc[-1]==-1 and st_d.iloc[-2]==1: alerts.append({"t":"bearish","p":"HIGH","m":f"{ticker} Supertrend just flipped BEARISH. The price ceiling is falling."})
        rsi_s = TA.rsi(df["Close"]); divs = TA.detect_divergences(df["Close"], rsi_s)
        for d in divs[-2:]:
            alerts.append({"t":d["type"],"p":"MEDIUM","m":f"{ticker} RSI {d['type']} divergence near ${d['price']:.2f}. Early warning of a reversal."})
        return alerts


class QuantBacktest:
    @staticmethod
    def run_edge_backtest(df, threshold=70, hold_days=5):
        """
        Runs a fast, vectorized historical backtest using a momentum/volatility proxy
        to simulate historical edge scores without locking up the UI.
        """
        if df is None or len(df) < hold_days + 50:
            return None

        df_bt = df.copy()
        if "Close" not in df_bt.columns:
            return None

        sma50 = df_bt["Close"].rolling(50).mean()
        trend_score = np.where(df_bt["Close"] > sma50, 60, 40)

        delta = df_bt["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 0.001)
        rsi = 100 - (100 / (1 + rs))

        volatility = df_bt["Close"].pct_change().rolling(20).std() * np.sqrt(252) * 100
        vol_penalty = np.where(volatility > 30, -20, 0)

        df_bt["Hist_Edge"] = np.clip((trend_score * 0.4) + (rsi * 0.6) + vol_penalty, 0, 100)
        df_bt["Signal"] = np.where(df_bt["Hist_Edge"] >= threshold, 1, 0)
        df_bt["Forward_Return"] = df_bt["Close"].shift(-hold_days) / df_bt["Close"] - 1.0

        trades = df_bt[df_bt["Signal"] == 1].dropna(subset=["Forward_Return"]).copy()
        if trades.empty:
            return None

        win_rate = (trades["Forward_Return"] > 0).mean() * 100
        avg_win = trades[trades["Forward_Return"] > 0]["Forward_Return"].mean() * 100
        avg_loss = trades[trades["Forward_Return"] <= 0]["Forward_Return"].mean() * 100
        if np.isnan(avg_win):
            avg_win = 0.0
        if np.isnan(avg_loss):
            avg_loss = 0.0

        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

        trades["Equity_Curve"] = (1 + trades["Forward_Return"]).cumprod() * 10000
        trade_returns = trades["Forward_Return"]
        tr_std = trade_returns.std()
        sharpe = (trade_returns.mean() / tr_std) * np.sqrt(252 / hold_days) if tr_std and tr_std > 0 else 0.0

        cum_max = trades["Equity_Curve"].cummax()
        drawdown = (trades["Equity_Curve"] - cum_max) / cum_max
        max_dd = drawdown.min() * 100

        return {
            "Total_Trades": int(len(trades)),
            "Win_Rate": float(win_rate),
            "Expectancy": float(expectancy),
            "Sharpe": float(sharpe),
            "Max_DD": float(max_dd),
            "Equity_Curve": trades[["Equity_Curve"]],
        }

