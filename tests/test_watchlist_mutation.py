"""Watchlist reorder / selection helpers (no Streamlit)."""


def test_move_up_swap():
    w = ["A", "B", "C"]
    sel = "B"
    idx = w.index(sel)
    assert idx > 0
    w[idx - 1], w[idx] = w[idx], w[idx - 1]
    assert w == ["B", "A", "C"]


def test_move_down_swap():
    w = ["A", "B", "C"]
    sel = "B"
    idx = w.index(sel)
    assert idx < len(w) - 1
    w[idx + 1], w[idx] = w[idx], w[idx + 1]
    assert w == ["A", "C", "B"]


def test_remove_symbol():
    w = ["A", "B", "C"]
    sel = "B"
    w = [t for t in w if t != sel]
    assert w == ["A", "C"]


def test_sort_az():
    w = ["ZETA", "AMD", "PLTR"]
    assert sorted(w) == ["AMD", "PLTR", "ZETA"]
