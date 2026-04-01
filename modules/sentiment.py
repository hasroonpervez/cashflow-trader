"""
Sentiment, Backtest simulator, and Alerts scanner.
"""
import streamlit as st
import pandas as pd
import numpy as np
import math
from datetime import datetime

from .ta import TA
from .data import fetch_stock

try:
    from hmmlearn import hmm
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False


class QuantSentiment:
    @staticmethod
    def regime_detection(df, n_regimes=2):
        """
        Uses a Gaussian Hidden Markov Model to probabilistically classify market regimes.
        Returns a dictionary of state probabilities for the latest day.
        """
        if not HMM_AVAILABLE or df is None or len(df) < 50:
            return {0: 0.5, 1: 0.5}

        returns = np.log(df["Close"] / df["Close"].shift(1)).dropna()
        volatility = returns.rolling(window=10).std().dropna()
        data = pd.concat([returns, volatility], axis=1).dropna()
        if data.empty:
            return {0: 0.5, 1: 0.5}

        X = data.values
        model = hmm.GaussianHMM(
            n_components=n_regimes,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        try:
            model.fit(X)
            probabilities = model.predict_proba(X)
            current_probs = probabilities[-1]
            return {i: prob for i, prob in enumerate(current_probs)}
        except Exception:
            return {0: 0.5, 1: 0.5}


class Sentiment:
    @staticmethod
    def fear_greed(df, vix_val=None):
        sc = [min(100, max(0, TA.rsi(df["Close"]).iloc[-1]))]
        sma200 = df["Close"].rolling(200).mean().iloc[-1] if len(df) >= 200 else df["Close"].mean()
        sc.append(min(100, max(0, 50 + (df["Close"].iloc[-1]/sma200-1)*500)))
        if len(df) >= 20:
            sc.append(min(100, max(0, 50 + (df["Close"].iloc[-1]/df["Close"].iloc[-20]-1)*300)))
            cv = df["Close"].pct_change().iloc[-20:].std()*np.sqrt(252)*100
            hv = df["Close"].pct_change().std()*np.sqrt(252)*100
            sc.append(max(0, min(100, 100-cv/max(hv,1)*50)))
        if vix_val and vix_val > 0: sc.append(max(0, min(100, 100-(vix_val-12)*3)))
        return np.mean(sc)

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

