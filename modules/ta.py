"""
Technical Analysis engine: TA class with all indicators.
EMA, SMA, RSI, MACD, Bollinger, ATR, Stoch, VWAP, Ichimoku, Supertrend,
ADX, CCI, OBV, Volume Profile, Divergences, Fibonacci, Gann, S/R, FVG,
Market Structure, Hurst exponent.
"""
import pandas as pd
import numpy as np
import math
from datetime import timedelta
from typing import Optional
from numpy.lib.stride_tricks import sliding_window_view
from .utils import log_warn, safe_float, safe_last

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
    def apply_ffd(series, d=0.4, max_lags=50, thres=1e-5):
        """Fixed-width fractional differentiation (max ``max_lags`` weights) for stationarity with memory.

        Vectorized via ``sliding_window_view``; caps expansion at **50** lags to keep UI responsive.
        """
        if series is None:
            return pd.Series(dtype=float)
        s = pd.to_numeric(pd.Series(series), errors="coerce").ffill().bfill()
        if len(s) < 2:
            return pd.Series(dtype=float, index=s.index)
        cap = min(max_lags + 1, len(s))
        cap = max(2, cap)
        w = TA.get_weights_ffd(d, cap).flatten()
        w = w[np.abs(w) >= thres]
        if w.size == 0:
            w = np.array([1.0], dtype=np.float64)
        if w.size > max_lags + 1:
            w = w[: max_lags + 1].astype(np.float64, copy=False)
        L = int(w.size)
        vals = s.to_numpy(dtype=np.float64)
        n = len(vals)
        if n < L:
            return pd.Series(dtype=float, index=s.index)
        w_rev = w[::-1].astype(np.float64, copy=False)
        sw = sliding_window_view(vals, L)
        out = sw @ w_rev
        idx = s.index[L - 1 :]
        return pd.Series(out, index=idx)

    @staticmethod
    def frac_diff_ffd(series, d=0.45, thres=1e-5):
        """Delegates to :meth:`apply_ffd` with a **50-lag** cap (v21+)."""
        return TA.apply_ffd(series, d=d, max_lags=50, thres=thres)

    @staticmethod
    def ffd_returns_from_closes(closes_wide, d=0.4, max_lags=50):
        """Inner-joined first differences of FFD levels per column (Pearson / sizing inputs).

        Tickers with fewer than ``max_lags + 15`` valid closes cannot be fractionally
        differenced and are excluded. AUDIT (medium, ta.py:74): that exclusion used to be
        silent, so a short-history name simply vanished from the correlation matrix and
        every downstream overlap/haircut lookup returned "no correlation", i.e. **full
        size**: for exactly the names we know least about. The dropped names are now
        logged and published on ``.attrs['ffd_dropped_insufficient']`` so callers can tell
        "measured as uncorrelated" apart from "never measured".
        """
        min_closes = int(max_lags) + 15
        if closes_wide is None or getattr(closes_wide, "empty", True):
            return TA._tag_ffd_attrs(pd.DataFrame(), [], min_closes)
        work = closes_wide.copy()
        work.columns = [str(c).strip().upper() for c in work.columns]
        work = work.apply(pd.to_numeric, errors="coerce")
        parts = {}
        dropped = []
        for c in work.columns:
            col = work[c].dropna()
            if len(col) < min_closes:
                dropped.append(str(c))
                continue
            fd = TA.apply_ffd(col, d=d, max_lags=max_lags)
            if fd is not None and len(fd) >= 4:
                parts[c] = fd
            else:
                dropped.append(str(c))
        if dropped:
            log_warn(
                "TA.ffd_returns_from_closes dropped tickers with insufficient history",
                ValueError(f"need >= {min_closes} closes; dropped {sorted(dropped)}"),
            )
        if len(parts) < 2:
            return TA._tag_ffd_attrs(pd.DataFrame(), dropped, min_closes)
        merged = pd.concat(parts, axis=1, join="inner")
        if merged.shape[0] < 3:
            return TA._tag_ffd_attrs(pd.DataFrame(), dropped, min_closes)
        return TA._tag_ffd_attrs(merged.diff().dropna(how="any"), dropped, min_closes)

    @staticmethod
    def _tag_ffd_attrs(frame, dropped, min_closes):
        """Stamp the FFD exclusion list onto the result (see ffd_returns_from_closes)."""
        frame.attrs["ffd_dropped_insufficient"] = sorted(str(x) for x in dropped)
        frame.attrs["ffd_min_closes_required"] = int(min_closes)
        return frame

    @staticmethod
    def _whale_zscore_window(df):
        """10-day volume baseline when short-horizon vol dominates; 40-day when tape is calm."""
        w_mid = 30
        if df is None or df.empty or "Volume" not in df.columns:
            return w_mid
        if "Close" not in df.columns:
            return w_mid
        close = pd.to_numeric(df["Close"], errors="coerce")
        lr = np.log(close / close.shift(1)).dropna()
        if len(lr) < 40:
            return w_mid
        sig10 = float(lr.iloc[-10:].std(ddof=0))
        sig40 = float(lr.iloc[-40:].std(ddof=0))
        if not np.isfinite(sig10) or not np.isfinite(sig40) or sig40 <= 1e-12:
            return w_mid
        rvi = sig10 / sig40
        cr = close.dropna()
        er = 0.5
        if len(cr) >= 21:
            change = abs(safe_float(safe_last(cr), 0.0) - safe_float(safe_last(cr.iloc[:-20]), 0.0))
            path = float(cr.diff().abs().iloc[-20:].sum())
            if path > 1e-12:
                er = change / path
        if rvi >= 1.15 or (rvi >= 1.08 and er < 0.22):
            return 10
        if rvi <= 0.88 or (rvi <= 0.95 and er >= 0.55):
            return 40
        return w_mid

    @staticmethod
    def rsi(s, p=14):
        """Wilder's RSI: EWM with com=p-1 (α=1/p), matching TradingView/Bloomberg.
        Previous implementation used simple rolling mean which gives systematically
        different (incorrect) RSI values, distorting all signal logic downstream."""
        delta = pd.to_numeric(s, errors="coerce").diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=p - 1, min_periods=p, adjust=False).mean()
        avg_loss = loss.ewm(com=p - 1, min_periods=p, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100.0 - (100.0 / (1.0 + rs))

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
    def true_range(df):
        """Wilder's True Range: max(H-L, |H-C_prev|, |L-C_prev|). First bar falls back to H-L."""
        hl = df["High"] - df["Low"]
        hc = (df["High"] - df["Close"].shift()).abs()
        lc = (df["Low"] - df["Close"].shift()).abs()
        return pd.concat([hl, hc, lc], axis=1).max(axis=1)

    @staticmethod
    def atr(df, p=14):
        """Wilder's ATR: RMA (EWM with α=1/p) of True Range, matching TradingView/Bloomberg.

        AUDIT (medium, ta.py:145): the previous implementation was ``TR.rolling(p).mean()``,
        a *simple* moving average. That diverges from every charting platform by +2.33% on
        average and up to 40.79%, and it was inconsistent with ``TA.rsi`` directly below,
        which was deliberately Wilder-ised with a docstring calling simple means incorrect.
        The difference is not cosmetic: an SMA drops a spike bar completely once it leaves
        the window, while Wilder's RMA decays it, which is why RMA-based stops stay wide
        after a gap. Warm-up NaNs are preserved (``min_periods=p``) so callers that guard on
        ``len(df) >= 15`` behave exactly as before.
        """
        p = max(1, int(p))
        return TA.true_range(df).ewm(alpha=1.0 / float(p), adjust=False, min_periods=p).mean()

    @staticmethod
    def stoch(df, k=14, d=3):
        """Stochastic oscillator with zero-division guard for halts / pre-market bars."""
        lo = df["Low"].rolling(k).min()
        hi = df["High"].rolling(k).max()
        denom = (hi - lo).replace(0, np.nan)  # avoid inf when hi==lo
        kv = 100 * (df["Close"] - lo) / denom
        return kv, kv.rolling(d).mean()

    @staticmethod
    def vwap(df):
        """Period-anchored VWAP from first bar in DataFrame.
        Zero-volume guard prevents inf on bars with no trades."""
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_vol = df["Volume"].cumsum()
        denom = cum_vol.replace(0, np.nan)
        return (tp * df["Volume"]).cumsum() / denom

    @staticmethod
    def ichimoku(df):
        t = (df["High"].rolling(9).max() + df["Low"].rolling(9).min()) / 2
        k = (df["High"].rolling(26).max() + df["Low"].rolling(26).min()) / 2
        sa = ((t + k) / 2).shift(26)
        sb = ((df["High"].rolling(52).max() + df["Low"].rolling(52).min()) / 2).shift(26)
        return t, k, sa, sb, df["Close"].shift(-26)

    @staticmethod
    def supertrend(df, period=10, mult=3.0):
        """Supertrend: FIXED: uses numpy arrays to avoid pandas chained indexing warnings."""
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
        """Wilder's ADX/DI with zero-division guards on ATR and DI sum.

        AUDIT (medium, ta.py:218): ADX inherited the SMA ATR from ``TA.atr`` and then added
        *two more* simple means (``dm.rolling(p).mean()`` and ``dx.rolling(p).mean()``) where
        Wilder specifies RMA smoothing at all three stages. Both the level and the lag were
        wrong versus any charting platform, against a hard ``adx_val > 25`` gate in
        ``options.py:640``. All three stages are now RMA (α = 1/p).
        """
        p = max(1, int(p))
        alpha = 1.0 / float(p)
        atr_v = TA.atr(df, p).replace(0, np.nan)
        dm_p = df["High"].diff(); dm_n = -df["Low"].diff()
        dm_p = dm_p.where((dm_p > dm_n) & (dm_p > 0), 0.0)
        dm_n = dm_n.where((dm_n > dm_p) & (dm_n > 0), 0.0)
        di_p = 100 * dm_p.ewm(alpha=alpha, adjust=False, min_periods=p).mean() / atr_v
        di_n = 100 * dm_n.ewm(alpha=alpha, adjust=False, min_periods=p).mean() / atr_v
        di_sum = (di_p + di_n).replace(0, np.nan)
        dx = 100 * (di_p - di_n).abs() / di_sum
        return dx.ewm(alpha=alpha, adjust=False, min_periods=p).mean(), di_p, di_n

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
        av = safe_float(safe_last(TA.atr(df)), np.nan)
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
    def get_dark_pool_proxy(df):
        """Adaptive volume Z-score against the **prior** w bars (w = 10/30/40 from RVI + ER).

        AUDIT #26: the baseline used to include the bar being scored
        (``vol.rolling(w)`` with ``ddof=0``), which algebraically caps z at exactly
        √(w−1): 3.0000 at w=10, 5.3852 at w=30, 6.2450 at w=40. ``detect_diamonds``
        grades ``zlv > 3.0`` for its 2-point whale tier (``options.py:909``), so that tier
        was provably unreachable in the choppy regime that selects w=10, the exact regime
        where an institutional print matters most. Scoring the current bar against a
        baseline that excludes it (``vol.shift(1)``) is the correct anomaly-z construction
        and removes the ceiling entirely: a 20× print now reads ~19σ at any window.
        """
        if df is None or df.empty or "Volume" not in df.columns:
            return pd.DataFrame()
        vol = pd.to_numeric(df["Volume"], errors="coerce")
        w = int(TA._whale_zscore_window(df))
        nobs = int(vol.notna().sum())
        # shift(1) consumes one observation, so the window must leave a prior bar behind.
        w = max(5, min(w, max(5, nobs - 1)))
        prior = vol.shift(1)
        mu = prior.rolling(w, min_periods=w).mean()
        sd = prior.rolling(w, min_periods=w).std(ddof=0)
        denom = sd.where((sd.notna()) & (sd > 0), np.nan)
        z = (vol - mu) / denom
        z = z.fillna(0.0).replace([np.inf, -np.inf], 0.0)
        is_whale = z > 2.0
        idx = vol.index
        wl = np.full(len(idx), int(w), dtype=np.int32)
        return pd.DataFrame(
            {
                "vol_mean_roll": mu,
                "vol_std_roll": sd,
                "vol_mean_30": mu,
                "vol_std_30": sd,
                "whale_lookback": wl,
                "volume_z_score": z,
                "is_whale_alert": is_whale,
                "dark_pool_alert": is_whale,
            },
            index=df.index,
        )

    @staticmethod
    def get_shadow_move(df, volume_z_score=None, lookback=30, whale_mass=0.70):
        """Whale-volume **shadow band**: central ``whale_mass`` of volume on bars with Z > 2.

        Compare the resulting price width to IV-based Expected Move for a **liquidity vs options**
        read. Returns ``dict`` with ``low``, ``high``, ``width``, ``n_whale_bars`` or ``None``.
        """
        if df is None or df.empty or "Close" not in df.columns or "Volume" not in df.columns:
            return None
        tail = df.tail(max(int(lookback), 10)).copy()
        if tail.empty:
            return None
        if volume_z_score is None:
            dp = TA.get_dark_pool_proxy(df)
            if dp is None or dp.empty or "volume_z_score" not in dp.columns:
                return None
            z = dp["volume_z_score"].reindex(tail.index)
        else:
            z = pd.Series(volume_z_score, dtype=float).reindex(tail.index)
        whale = tail.loc[z > 2.0]
        if whale.empty or len(whale) < 2:
            return None
        vol = pd.to_numeric(whale["Volume"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        pr = pd.to_numeric(whale["Close"], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(vol) & np.isfinite(pr) & (vol >= 0)
        vol, pr = vol[m], pr[m]
        if vol.size < 2 or np.sum(vol) <= 0:
            return None
        order = np.argsort(pr)
        prs = pr[order]
        v = vol[order]
        cum = np.cumsum(v)
        total = float(cum[-1])
        lo_q = max(0.0, (1.0 - float(whale_mass)) / 2.0) * total
        hi_q = min(total, (1.0 + float(whale_mass)) / 2.0 * total)
        i_lo = int(np.searchsorted(cum, lo_q, side="left"))
        i_hi = int(np.searchsorted(cum, hi_q, side="right")) - 1
        i_lo = int(np.clip(i_lo, 0, len(prs) - 1))
        i_hi = int(np.clip(i_hi, 0, len(prs) - 1))
        if i_lo > i_hi:
            i_lo, i_hi = i_hi, i_lo
        lo_px, hi_px = float(prs[i_lo]), float(prs[i_hi])
        if hi_px < lo_px:
            lo_px, hi_px = hi_px, lo_px
        width = hi_px - lo_px
        if not np.isfinite(width) or width < 0:
            return None
        return {
            "low": lo_px,
            "high": hi_px,
            "width": width,
            "n_whale_bars": int(len(whale)),
        }

    # AUDIT #27: measured null distribution of the Anis-Lloyd-corrected R/S estimator.
    # 4,000 pure Gaussian random walks per n ∈ {60, 100, 150, 251, 500, 1000}: the corrected
    # estimate is centred on 0.500 (raw was 0.524, that bias is what made 26% of pure noise
    # read as "trending") and its dispersion is well described by SE(H) ≈ 0.23 / ln(n)
    # (measured sd·ln(n) = 0.225, 0.229, 0.229, 0.222, 0.221, 0.214).
    _HURST_RS_SE_COEF = 0.23
    # The consumers of this number cut at 0.45 / 0.55 (signal_desk.py:595/604,
    # options.py:1217, renderers.py:422). A verdict is only emitted when the estimate clears
    # BOTH ±2·SE of the null AND those published cutoffs, so a caller branching on 0.55 can
    # never be branching on noise. Measured false-classification rate on the null: 4.0%.
    _HURST_MIN_EDGE = 0.05

    @staticmethod
    def _anis_lloyd_expected_rs(n: int) -> Optional[float]:
        """E[R/S] for i.i.d. noise (Anis & Lloyd 1976, Peters' small-sample form)."""
        n = int(n)
        if n < 4:
            return None
        i = np.arange(1, n, dtype=float)
        tail = float(np.sum(np.sqrt((n - i) / i)))
        if n > 340:
            front = (n - 0.5) / n * (n * math.pi / 2.0) ** -0.5
        else:
            front = (n - 0.5) / n * math.exp(
                math.lgamma((n - 1) / 2.0) - 0.5 * math.log(math.pi) - math.lgamma(n / 2.0)
            )
        out = front * tail
        return float(out) if math.isfinite(out) and out > 0 else None

    @staticmethod
    def hurst_rs_stderr(n: int) -> Optional[float]:
        """Standard error of the R/S Hurst estimate on ``n`` returns (see ``_HURST_RS_SE_COEF``)."""
        n = int(n)
        if n < 20:
            return None
        return float(TA._HURST_RS_SE_COEF / math.log(float(n)))

    @staticmethod
    def hurst_rs_estimate(close_prices, window: int = 252) -> Optional[dict]:
        """Bias-corrected R/S Hurst with its uncertainty. ``None`` when data are insufficient.

        Returns ``{'h', 'stderr', 'n', 'edge', 'significant', 'regime'}`` where ``regime`` is
        ``'TRENDING'`` / ``'MEAN_REVERTING'`` / ``'RANDOM_WALK'`` and ``significant`` is False
        whenever the ±2·SE interval spans a decision threshold. Read ``h`` for display only
        branch on ``regime``/``significant``, never on ``h`` alone (AUDIT #27).
        """
        try:
            s = np.asarray(
                pd.Series(close_prices, dtype=float).dropna().values[-int(window) :], dtype=float
            )
            if s.size < 40 or np.any(s <= 0):
                return None
            lr = np.diff(np.log(s))
            lr = lr[np.isfinite(lr)]
            n = int(lr.size)
            if n < 30:
                return None
            y = np.cumsum(lr - float(np.mean(lr)))
            r_rng = float(np.max(y) - np.min(y))
            # ddof=0: the Anis-Lloyd expectation is derived for the ML standard deviation.
            sig = float(np.std(lr, ddof=0))
            if sig < 1e-12 or r_rng <= 0:
                return None
            e_rs = TA._anis_lloyd_expected_rs(n)
            if e_rs is None:
                return None
            # H = 0.5 + [log(R/S) - log(E[R/S] under i.i.d.)] / log(n). Subtracting the
            # small-sample expectation is what re-centres the null on 0.5 (AUDIT #27).
            h = 0.5 + (math.log(r_rng / sig) - math.log(e_rs)) / math.log(float(n))
            if not math.isfinite(h):
                return None
            h = float(np.clip(h, 0.0, 1.0))
            se = TA.hurst_rs_stderr(n)
            if se is None:
                return None
            edge = max(2.0 * se, TA._HURST_MIN_EDGE)
            if h - 0.5 > edge:
                regime, significant = "TRENDING", True
            elif 0.5 - h > edge:
                regime, significant = "MEAN_REVERTING", True
            else:
                regime, significant = "RANDOM_WALK", False
            return {
                "h": h,
                "stderr": float(se),
                "n": n,
                "edge": float(edge),
                "significant": bool(significant),
                "regime": regime,
            }
        except Exception as _e:
            log_warn("TA.hurst_rs_estimate", _e)
            return None

    @staticmethod
    def hurst_regime(close_prices, window: int = 252) -> Optional[str]:
        """``'TRENDING'`` / ``'MEAN_REVERTING'``, or ``None`` when the estimate is not
        distinguishable from a random walk (or there is not enough data). Prefer this over
        thresholding the raw exponent."""
        est = TA.hurst_rs_estimate(close_prices, window=window)
        if est is None or not est["significant"]:
            return None
        return str(est["regime"])

    @staticmethod
    def calculate_hurst_exponent(
        close_prices, window: int = 252, require_significance: bool = True
    ) -> Optional[float]:
        """Anis-Lloyd-corrected R/S Hurst on the last ``window`` closes. ``Optional[float]``.

        AUDIT #27: the previous version was raw ``log(R/S)/log(n)``, which carries the
        Anis-Lloyd small-sample bias: measured mean 0.524 (sd 0.042) on 400 *pure random
        walks* of 251 returns, so **26.2% of pure noise was labelled trending** by the
        ``> 0.55`` cutoff its own docstring published. The docstring's "SE ≈ 0.09 at 252
        bars" was wrong in both directions.

        Two changes: the estimate is bias-corrected (null now centred on 0.500), and with
        ``require_significance`` (the default) a number is returned **only** when it clears
        ±2·SE of the measured null *and* the 0.45/0.55 cutoffs its callers use. Otherwise
        ``None``: never a confident regime label built on noise. Every caller already
        handles ``None`` as "no regime read" (``signal_desk.py:594``, ``options.py:1216``,
        ``data.py:995``), so a ``None`` here degrades to the random-walk prior rather than
        to a fabricated verdict. Pass ``require_significance=False`` to display the raw
        corrected estimate alongside ``hurst_rs_stderr``.
        """
        est = TA.hurst_rs_estimate(close_prices, window=window)
        if est is None:
            return None
        if require_significance and not est["significant"]:
            return None
        return float(est["h"])

    @staticmethod
    def hurst(series):
        """Hurst exponent, float-returning, with the random-walk prior of 0.5 as the default.

        AUDIT #27: this used to be a *second, different* estimator, aggregated-variance
        slope/2: with only 5 usable lags at n=251. Measured on pure Gaussian random walks
        it returned mean 0.472 with sd 0.105, labelling **64% of pure noise** as either
        trending or mean-reverting, and it disagreed with ``calculate_hurst_exponent`` by
        ~0.05 in mean on identical data while sharing the same 0.55/0.45 cutoffs. Keeping
        two estimators that contradict each other at the decision boundary is worse than
        keeping one, so this now delegates to the bias-corrected R/S estimator; the
        variance-ratio method is simply too noisy to use at n=252.

        Stays float-returning (rather than Optional) because ``options.py:781`` does
        ``float(TA.hurst(close))`` and ``renderers.py:421`` formats it unconditionally
        0.5 is the honest "no measurable regime" answer for both.
        """
        try:
            est = TA.calculate_hurst_exponent(series, window=252, require_significance=True)
        except Exception as _e:
            log_warn("TA.hurst", _e)
            return 0.5
        if est is None:
            return 0.5
        return round(float(est), 3)

    @staticmethod
    def get_correlation_matrix(
        price_history_dict, lookback_days=90, ffd_d=0.4, max_lags=50, min_obs=60
    ):
        """Pearson correlation of **FFD return** innovations across tickers (``lookback_days`` daily bars).

        ``price_history_dict`` maps ticker → ``pd.Series`` of closes (DatetimeIndex) or
        a DataFrame with a ``Close`` column. Series are aligned with ``join='inner'`` on
        dates so mismatched lengths do not skew pairwise samples.

        AUDIT (medium, ta.py:566): the "90-day" matrix was built from **39 observations**
        ``tail(90)`` was taken *before* the FFD convolution burned 50 lags, and the final
        ``diff()`` cost one more. Pearson SE at n=39 is ≈0.167 against knife-edge cutoffs at
        0.75 (``options.py:963``), 0.80 (``options.py:2079``) and 0.6/0.8
        (``options.py:2387``), a true ρ of 0.55 crosses 0.75 roughly one time in eight.
        Two fixes: retain ``lookback_days + max_lags + 1`` closes so ``lookback_days``
        innovations actually survive the transform, and return an **empty** frame when
        fewer than ``min_obs`` survive anyway. Empty is the existing "unknown" signal
        every caller already treats an empty/None matrix as "apply no correlation penalty"
: so a matrix too thin to trust can no longer trigger a penalty. The realised
        observation count is published on ``.attrs['n_obs']``.
        """
        if not price_history_dict:
            return pd.DataFrame()
        series_list = []
        for sym, data in price_history_dict.items():
            if data is None:
                continue
            label = str(sym).strip().upper()
            if not label:
                continue
            if isinstance(data, pd.Series):
                s = pd.to_numeric(data, errors="coerce")
            elif isinstance(data, pd.DataFrame) and "Close" in data.columns:
                s = pd.to_numeric(data["Close"], errors="coerce")
            else:
                continue
            if s is None or len(s) < 5:
                continue
            series_list.append(s.rename(label))
        if len(series_list) < 2:
            return pd.DataFrame()
        wide = pd.concat(series_list, axis=1, join="inner")
        if wide.empty or len(wide) < 5:
            return pd.DataFrame()
        lb = max(5, int(lookback_days))
        ml = max(1, int(max_lags))
        # Keep the FFD warm-up on top of the requested window: the convolution consumes
        # ``max_lags`` bars and the trailing diff() one more before the first usable row.
        wide = wide.tail(lb + ml + 1).dropna(how="all")
        ffd_ret = TA.ffd_returns_from_closes(wide, d=ffd_d, max_lags=ml)
        n_obs = 0 if ffd_ret is None or ffd_ret.empty else int(len(ffd_ret))
        floor = max(3, int(min_obs))
        if n_obs < floor:
            out = pd.DataFrame()
            out.attrs["n_obs"] = n_obs
            out.attrs["insufficient_observations"] = True
            out.attrs["min_obs_required"] = floor
            out.attrs["ffd_dropped_insufficient"] = list(
                getattr(ffd_ret, "attrs", {}).get("ffd_dropped_insufficient", [])
            )
            return out
        out = ffd_ret.corr(method="pearson")
        out.attrs["n_obs"] = n_obs
        out.attrs["insufficient_observations"] = False
        out.attrs["min_obs_required"] = floor
        out.attrs["ffd_dropped_insufficient"] = list(
            getattr(ffd_ret, "attrs", {}).get("ffd_dropped_insufficient", [])
        )
        return out

