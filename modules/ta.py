"""
Technical Analysis engine — TA class with all indicators.
EMA, SMA, RSI, MACD, Bollinger, ATR, Stoch, VWAP, Ichimoku, Supertrend,
ADX, CCI, OBV, Volume Profile, Divergences, Fibonacci, Gann, S/R, FVG,
Market Structure, Hurst exponent.
"""
import pandas as pd
import numpy as np
import math
from datetime import timedelta

class TA:
    @staticmethod
    def ema(s, p): return s.ewm(span=p, adjust=False).mean()
    @staticmethod
    def sma(s, p): return s.rolling(window=p).mean()

    @staticmethod
    def get_weights_ffd(d, size):
        w = [1.0]
        for k in range(1, size):
            w.append(-w[-1] * (d - k + 1) / k)
        return np.array(w).reshape(-1, 1)

    @staticmethod
    def frac_diff_ffd(series, d=0.45, thres=1e-5):
        """Applies Fixed-Width Window Fractional Differentiation."""
        if series is None or len(series) == 0:
            return pd.Series(dtype=float)
        w = TA.get_weights_ffd(d, len(series))
        w_ = w[np.abs(w) >= thres]
        w_ = w_[::-1]
        res = []
        for i in range(len(w_) - 1, len(series)):
            window = series.iloc[i - len(w_) + 1: i + 1].values
            res.append(np.dot(window, w_)[0])
        return pd.Series(res, index=series.index[len(w_) - 1:])

    @staticmethod
    def rsi(s, p=14):
        d = s.diff()
        g = d.where(d > 0, 0).rolling(p).mean()
        l = (-d.where(d < 0, 0)).rolling(p).mean()
        return 100 - 100 / (1 + g / l)

    @staticmethod
    def rsi2(s): return TA.rsi(s, 2)

    @staticmethod
    def macd(s, fast=12, slow=26, sig=9):
        ef = s.ewm(span=fast, adjust=False).mean()
        es = s.ewm(span=slow, adjust=False).mean()
        ml = ef - es; sl = ml.ewm(span=sig, adjust=False).mean()
        return ml, sl, ml - sl

    @staticmethod
    def bollinger(s, p=20, sd=2):
        m = s.rolling(p).mean(); st = s.rolling(p).std()
        return m + st * sd, m, m - st * sd

    @staticmethod
    def atr(df, p=14):
        hl = df["High"] - df["Low"]
        hc = abs(df["High"] - df["Close"].shift())
        lc = abs(df["Low"] - df["Close"].shift())
        return pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(p).mean()

    @staticmethod
    def stoch(df, k=14, d=3):
        lo = df["Low"].rolling(k).min(); hi = df["High"].rolling(k).max()
        kv = 100 * (df["Close"] - lo) / (hi - lo)
        return kv, kv.rolling(d).mean()

    @staticmethod
    def vwap(df):
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        return (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()

    @staticmethod
    def ichimoku(df):
        t = (df["High"].rolling(9).max() + df["Low"].rolling(9).min()) / 2
        k = (df["High"].rolling(26).max() + df["Low"].rolling(26).min()) / 2
        sa = ((t + k) / 2).shift(26)
        sb = ((df["High"].rolling(52).max() + df["Low"].rolling(52).min()) / 2).shift(26)
        return t, k, sa, sb, df["Close"].shift(-26)

    @staticmethod
    def supertrend(df, period=10, mult=3.0):
        """Supertrend — FIXED: uses numpy arrays to avoid pandas chained indexing warnings."""
        atr_v = TA.atr(df, period).values
        hl2 = ((df["High"] + df["Low"]) / 2).values
        close = df["Close"].values
        n = len(df)
        up = hl2 + mult * atr_v
        dn = hl2 - mult * atr_v
        direction = np.empty(n)
        st_line = np.empty(n)
        direction[0] = 1
        st_line[0] = dn[0] if not np.isnan(dn[0]) else close[0]
        for i in range(1, n):
            if np.isnan(up[i]) or np.isnan(dn[i]):
                direction[i] = direction[i-1]
                st_line[i] = st_line[i-1]
                continue
            if close[i] > up[i-1]:
                direction[i] = 1
            elif close[i] < dn[i-1]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]
            if direction[i] == 1:
                st_line[i] = max(dn[i], st_line[i-1]) if direction[i-1] == 1 else dn[i]
            else:
                st_line[i] = min(up[i], st_line[i-1]) if direction[i-1] == -1 else up[i]
        return pd.Series(st_line, index=df.index), pd.Series(direction, index=df.index)

    @staticmethod
    def adx(df, p=14):
        atr_v = TA.atr(df, p)
        dm_p = df["High"].diff(); dm_n = -df["Low"].diff()
        dm_p = dm_p.where((dm_p > dm_n) & (dm_p > 0), 0)
        dm_n = dm_n.where((dm_n > dm_p) & (dm_n > 0), 0)
        di_p = 100 * dm_p.rolling(p).mean() / atr_v
        di_n = 100 * dm_n.rolling(p).mean() / atr_v
        dx = 100 * abs(di_p - di_n) / (di_p + di_n)
        return dx.rolling(p).mean(), di_p, di_n

    @staticmethod
    def cci(df, p=20):
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        sma_tp = tp.rolling(p).mean()
        mad = tp.rolling(p).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma_tp) / (0.015 * mad)

    @staticmethod
    def obv(df):
        return (np.sign(df["Close"].diff()) * df["Volume"]).fillna(0).cumsum()

    @staticmethod
    def volume_profile(df, bins=20):
        pr = np.linspace(df["Low"].min(), df["High"].max(), bins + 1)
        rows = []
        for i in range(len(pr) - 1):
            mask = (df["Close"] >= pr[i]) & (df["Close"] < pr[i+1])
            rows.append({"mid": (pr[i]+pr[i+1])/2, "volume": df.loc[mask, "Volume"].sum()})
        return pd.DataFrame(rows)

    @staticmethod
    def get_volume_nodes(df, bins=60, lookback_days=90):
        """High-volume nodes (HVN) from volume-at-price over the recent window."""
        if df.empty or len(df) < 10:
            return []
        if "Close" not in df.columns or "Volume" not in df.columns:
            return []
        recent = df.tail(lookback_days).copy()
        cmin = float(recent["Close"].min())
        cmax = float(recent["Close"].max())
        price_range = cmax - cmin
        if not np.isfinite(price_range) or price_range <= 0:
            return []
        bin_width = price_range / bins
        edges = np.arange(cmin, cmax + bin_width, bin_width)
        if len(edges) < 2:
            return []
        recent = recent.copy()
        recent["price_bin"] = pd.cut(recent["Close"], bins=edges, include_lowest=True)
        vprofile = recent.groupby("price_bin", observed=True)["Volume"].sum()
        if vprofile.empty:
            return []
        mu = float(vprofile.mean())
        sig = float(vprofile.std())
        if not np.isfinite(sig) or sig <= 0:
            hvn_threshold = mu
        else:
            hvn_threshold = mu + 1.5 * sig
        hvn = vprofile[vprofile > hvn_threshold]
        out = []
        for ivl in hvn.index:
            try:
                px = float(ivl.mid)
                vw = float(vprofile.loc[ivl])
                if np.isfinite(px) and vw >= 0:
                    out.append({"price": px, "volume_weight": vw})
            except (AttributeError, TypeError, ValueError, KeyError):
                continue
        out.sort(key=lambda x: x["price"])
        return out

    @staticmethod
    def detect_divergences(price_series, indicator_series, lookback=30):
        divs = []
        p = price_series.iloc[-lookback:]
        ind = indicator_series.iloc[-lookback:]
        for i in range(5, len(p) - 1):
            if p.iloc[i] < p.iloc[i-5:i].min() and ind.iloc[i] > ind.iloc[i-5:i].min():
                divs.append({"type": "bullish", "idx": p.index[i], "price": p.iloc[i]})
            if p.iloc[i] > p.iloc[i-5:i].max() and ind.iloc[i] < ind.iloc[i-5:i].max():
                divs.append({"type": "bearish", "idx": p.index[i], "price": p.iloc[i]})
        return divs[-5:]

    @staticmethod
    def fib_retracement(high, low):
        d = high - low
        return {f"{r:.1%}": high - d * r for r in [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]}

    @staticmethod
    def gann_sq9(price):
        sqrt_p = math.sqrt(price); levels = {}
        for i in range(-4, 5):
            if i == 0: continue
            levels[f"Card {'+'if i>0 else ''}{i*180} deg"] = round((sqrt_p + i * 0.5) ** 2, 2)
            levels[f"Ord {'+'if i>0 else ''}{i*90} deg"] = round((sqrt_p + i * 0.25) ** 2, 2)
        return dict(sorted(levels.items(), key=lambda x: x[1]))

    @staticmethod
    def gann_angles(df, lookback=60):
        recent = df.iloc[-lookback:]
        si = recent["Low"].idxmin(); sp = recent.loc[si, "Low"]
        sb = list(recent.index).index(si)
        av = TA.atr(df).iloc[-1]
        if pd.isna(av) or av <= 0: av = sp * 0.02
        bs = len(recent) - 1 - sb
        return {n: round(sp + av * r * bs, 2) for n, r in {"1x1":1,"2x1":2,"1x2":.5,"3x1":3,"1x3":1/3}.items()}, sp

    @staticmethod
    def gann_time_cycles(df):
        recent = df.iloc[-120:]
        si = recent["Low"].idxmin(); sp = list(df.index).index(si)
        results = []
        for c in [30, 60, 90, 120, 180, 360]:
            tp = sp + c
            if tp < len(df):
                results.append({"cycle": c, "date": df.index[tp], "status": "PAST"})
            else:
                results.append({"cycle": c, "date": df.index[-1] + timedelta(days=tp - len(df) + 1), "status": "UPCOMING"})
        return results

    @staticmethod
    def find_sr(df, window=20):
        highs = df["High"].rolling(window, center=True).max()
        lows = df["Low"].rolling(window, center=True).min()
        res_l, sup_l = [], []
        for i in range(window, len(df) - window):
            if df["High"].iloc[i] == highs.iloc[i]: res_l.append(df["High"].iloc[i])
            if df["Low"].iloc[i] == lows.iloc[i]: sup_l.append(df["Low"].iloc[i])
        def cluster(lv, thr=0.02):
            if not lv: return []
            lv = sorted(set(lv)); cs = [[lv[0]]]
            for v in lv[1:]:
                if (v - cs[-1][-1]) / cs[-1][-1] < thr: cs[-1].append(v)
                else: cs.append([v])
            return [np.mean(c) for c in cs]
        return cluster(sup_l), cluster(res_l)

    @staticmethod
    def fvg(df):
        gaps = []
        for i in range(2, len(df)):
            if df["Low"].iloc[i] > df["High"].iloc[i-2]:
                gaps.append({"type":"bullish","top":df["Low"].iloc[i],"bottom":df["High"].iloc[i-2],"date":df.index[i]})
            elif df["High"].iloc[i] < df["Low"].iloc[i-2]:
                gaps.append({"type":"bearish","top":df["Low"].iloc[i-2],"bottom":df["High"].iloc[i],"date":df.index[i]})
        return gaps[-10:]

    @staticmethod
    def market_structure(df, lb=5):
        sh, sl = [], []
        for i in range(lb, len(df) - lb):
            seg = df.iloc[i-lb:i+lb+1]
            if df["High"].iloc[i] == seg["High"].max(): sh.append((df.index[i], df["High"].iloc[i]))
            if df["Low"].iloc[i] == seg["Low"].min(): sl.append((df.index[i], df["Low"].iloc[i]))
        if len(sh) >= 2 and len(sl) >= 2:
            if sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1]: return "BULLISH", sh, sl
            if sh[-1][1] < sh[-2][1] and sl[-1][1] < sl[-2][1]: return "BEARISH", sh, sl
        return "RANGING", sh, sl

    @staticmethod
    def hurst(series):
        """Hurst exponent via variance ratio (aggregated variance method).
        Uses log returns. Var(q-period returns) scales as q^(2H).
        H > 0.55 = trending, H < 0.45 = mean-reverting, ~0.5 = random walk."""
        ts = series.dropna().values
        if len(ts) < 100:
            return 0.5
        rets = np.diff(np.log(ts))
        rets = rets[np.isfinite(rets)]
        if len(rets) < 80:
            return 0.5
        lags = [2, 4, 8, 16, 32, 64]
        lags = [q for q in lags if q < len(rets) // 4]
        if len(lags) < 3:
            return 0.5
        log_lags, log_vars = [], []
        for q in lags:
            agg = np.array([rets[i:i + q].sum() for i in range(0, len(rets) - q + 1, q)])
            if len(agg) < 5:
                continue
            v = np.var(agg, ddof=1)
            if v > 0:
                log_lags.append(np.log(q))
                log_vars.append(np.log(v))
        if len(log_lags) < 3:
            return 0.5
        slope = np.polyfit(log_lags, log_vars, 1)[0]
        H = slope / 2.0
        return round(float(np.clip(H, 0, 1)), 3)

