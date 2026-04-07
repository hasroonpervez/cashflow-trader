"""Low-level utilities — no Streamlit, no module imports."""
from __future__ import annotations

import html as _html_mod
import math
import sys
import pandas as pd


def safe_last(series, default=None):
    """Return the last element of a Series/list, or default if empty/None."""
    if series is None:
        return default
    if isinstance(series, pd.Series):
        if series.empty:
            return default
        val = series.iloc[-1]
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return default
        return val
    if isinstance(series, (list, tuple)):
        return series[-1] if series else default
    return default


def safe_float(val, default: float = 0.0) -> float:
    """Coerce val to float, returning default for None/NaN/Inf/non-numeric."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def safe_html(value) -> str:
    """HTML-escape any value for safe injection into unsafe_allow_html blocks."""
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
    """Log an error to stderr with context. Use instead of silent `pass`."""
    prefix = f"[cashflow-trader:{ticker}] " if ticker else "[cashflow-trader] "
    print(
        f"{prefix}{context}: {type(error).__name__}: {error}",
        file=sys.stderr,
        flush=True,
    )
