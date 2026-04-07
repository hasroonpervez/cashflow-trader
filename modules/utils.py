"""Low-level utilities shared across all modules. No Streamlit, no module deps."""
from __future__ import annotations

import html as _html_mod
import math
import sys
import numpy as np
import pandas as pd


def safe_last(series, default=None):
    """Last element of Series/list, or default if empty/None/NaN."""
    if series is None:
        return default
    if isinstance(series, (pd.Series, pd.Index)):
        if len(series) == 0:
            return default
        val = series.iloc[-1]
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return default
        return val
    if isinstance(series, np.ndarray):
        if series.size == 0:
            return default
        val = series[-1]
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return default
        return val
    if isinstance(series, (list, tuple)):
        return series[-1] if series else default
    return default


def safe_float(val, default: float = 0.0) -> float:
    """Coerce to float; return default for None/NaN/Inf/non-numeric."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def safe_html(value) -> str:
    """HTML-escape any value for injection into unsafe_allow_html blocks."""
    return _html_mod.escape(str(value))


def safe_href(url) -> str | None:
    """
    Return ``url`` escaped for a literal ``href`` attribute, or ``None`` if not
    an allowed http(s) URL (blocks ``javascript:`` and other schemes).
    """
    if url is None:
        return None
    u = str(url).strip()
    if not u.startswith(("http://", "https://")):
        return None
    return _html_mod.escape(u, quote=True)


def log_warn(context: str, error: Exception, *, ticker: str = "") -> None:
    """Log error to stderr. Use instead of silent 'except Exception: pass'."""
    prefix = f"[cashflow:{ticker}] " if ticker else "[cashflow] "
    print(f"{prefix}{context}: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
