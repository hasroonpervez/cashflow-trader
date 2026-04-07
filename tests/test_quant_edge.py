"""Quant Edge Score — drives trade recommendation context."""
import numpy as np
import pandas as pd

from modules.options import quant_edge_score


def _make_df(n=260, trend="up", seed=42):
    """Synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    if trend == "up":
        close = np.linspace(90, 120, n) + rng.normal(0, 1, n)
    elif trend == "down":
        close = np.linspace(120, 80, n) + rng.normal(0, 1, n)
    else:
        close = 100 + rng.normal(0, 3, n)
    return pd.DataFrame(
        {
            "Open": close - rng.uniform(0, 2, n),
            "High": close + rng.uniform(0, 3, n),
            "Low": close - rng.uniform(0, 3, n),
            "Close": close,
            "Volume": rng.integers(1_000_000, 10_000_000, n),
        },
        index=dates,
    )


def test_score_range():
    qs, _ = quant_edge_score(_make_df(), vix_val=20)
    assert 0 <= qs <= 100


def test_uptrend_scores_higher_than_downtrend():
    qs_up, _ = quant_edge_score(_make_df(trend="up", seed=1), vix_val=20)
    qs_down, _ = quant_edge_score(_make_df(trend="down", seed=2), vix_val=20)
    assert qs_up > qs_down


def test_missing_vix_does_not_crash():
    qs, _ = quant_edge_score(_make_df(), vix_val=None)
    assert 0 <= qs <= 100


def test_short_dataframe_does_not_crash():
    qs, _ = quant_edge_score(_make_df(n=30), vix_val=20)
    assert 0 <= qs <= 100


def test_breakdown_has_five_pillars():
    _, qb = quant_edge_score(_make_df(), vix_val=20, use_quant=False)
    for key in ("trend", "momentum", "volume", "volatility", "structure"):
        assert key in qb, f"Missing pillar: {key}"


def test_use_quant_blended_keeps_pillars_and_model_tag():
    _, qb = quant_edge_score(_make_df(), vix_val=20, use_quant=True)
    for key in ("trend", "momentum", "volume", "volatility", "structure"):
        assert key in qb
    assert qb.get("model") == "blended"
    assert "retail_core" in qb
    assert "inst_signal" in qb


def test_nested_scores_mirror_after_build():
    from modules.pages import build_context, DashContext
    from unittest.mock import MagicMock, patch
    from modules.data import DeskMarketSnapshot, GlobalMarketSnapshot

    df = _make_df()
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
    assert ctx.scores.qs == ctx.qs
    assert ctx.prices.price == ctx.price
