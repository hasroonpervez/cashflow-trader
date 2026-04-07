"""Smoke tests — verify the app imports cleanly and build_context works."""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd


def test_modules_import_cleanly():
    """Every module in modules/ should import without error."""
    from modules import (  # noqa: F401
        chart,
        config,
        data,
        desk_locals,
        options,
        pages,
        render_pre_tabs,
        renderers,
        sentiment,
        signal_desk,
        ta,
        ui_helpers,
        utils,
    )


def test_safe_href_allows_only_http():
    from modules.utils import safe_href

    assert safe_href("https://example.com/x?a=1") is not None
    assert safe_href("javascript:alert(1)") is None
    assert safe_href("data:text/html,<script>") is None


def test_renderers_import():
    from modules.renderers import (
        commit_watchlist,
        render_cashflow_tab,
        render_equity_setup_desk,
        render_intel_tab,
        render_ledger_tab,
        render_setup_tab,
    )

    assert callable(render_setup_tab)


def test_build_context_returns_dash_context():
    """build_context with mocked data should return a DashContext, not None."""
    from modules.data import DeskMarketSnapshot, GlobalMarketSnapshot
    from modules.pages import DashContext, build_context

    dates = pd.date_range("2025-01-01", periods=260, freq="B")
    df = pd.DataFrame(
        {
            "Open": np.random.uniform(90, 110, 260),
            "High": np.random.uniform(100, 120, 260),
            "Low": np.random.uniform(80, 100, 260),
            "Close": np.linspace(95, 105, 260) + np.random.normal(0, 2, 260),
            "Volume": np.random.randint(1_000_000, 10_000_000, 260),
        },
        index=dates,
    )

    mock_gs = MagicMock(spec=GlobalMarketSnapshot)
    mock_gs.active_daily_df = df
    mock_gs.active_weekly_df = None
    mock_gs.active_1mo_df = None
    mock_gs.desk = MagicMock(spec=DeskMarketSnapshot)
    mock_gs.desk.macro = {"10Y Yield": {"price": 4.5, "chg": 0.0}, "VIX": {"price": 20.0, "chg": 0.0}}
    mock_gs.desk.vix_1mo_df = None

    cfg = {"watchlist": "TEST", "use_quant_models": False}

    mock_st = MagicMock()
    mock_st.session_state = {}
    mock_st.spinner = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
    mock_st.warning = MagicMock()

    with (
        patch("modules.pages.fetch_stock", return_value=df),
        patch("modules.pages.fetch_news_headlines", return_value=[]),
        patch("modules.pages.fetch_earnings_date", return_value=None),
        patch("modules.pages.fetch_options", return_value=([], [])),
        patch("modules.pages.st", mock_st),
    ):
        ctx = build_context("TEST", cfg, global_snapshot=mock_gs)

    assert isinstance(ctx, DashContext)
    assert ctx.ticker == "TEST"
    assert ctx.price > 0
