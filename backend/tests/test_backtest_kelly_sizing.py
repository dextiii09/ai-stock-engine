"""
Regression tests for audit Finding #11: the backtester previously sized every
trade as a flat position_size_pct (default 10%) of capital — never Half-Kelly
— while live trading always sizes through PositionSizer (1% fixed-fractional
under 30 closed trades, hard-capped at 5% max risk). This mismatch meant
every backtest-reported Sharpe/drawdown/VaR number was not representative of
live risk (see FULL_AUDIT_2026-08-21.md, Finding #11).

`backtesting/engine.py::BacktestEngine.run()` downloads live Yahoo Finance
data and isn't practical to unit test end-to-end here, so these tests are
split into: (1) a direct test of the new `_get_realized_b()` helper, which
mirrors `SmartExecutionEngine._get_realized_b()` exactly, and (2) a static
source check that the old flat-percent sizing line is gone and Kelly sizing
is genuinely wired in — the same pattern used elsewhere in this audit for
code with heavy import-time or network side effects.
"""

import ast
import os


def _make_engine_no_download():
    """Construct a BacktestEngine without triggering __init__'s side effects
    beyond object construction (no network calls happen in __init__ itself)."""
    from backtesting.engine import BacktestEngine
    return BacktestEngine(symbol="MGC=F", initial_capital=100_000.0)


def test_sizer_is_a_real_position_sizer_instance():
    from risk.position_sizing import PositionSizer
    engine = _make_engine_no_download()
    assert isinstance(engine.sizer, PositionSizer), (
        "BacktestEngine no longer constructs a real PositionSizer — "
        "Kelly sizing wiring may have been reverted."
    )


def test_get_realized_b_matches_smart_execution_engine_formula():
    engine = _make_engine_no_download()

    # Empty history -> fallback 2.0, matching SmartExecutionEngine._get_realized_b()
    assert engine._get_realized_b() == 2.0

    # Seed a known win/loss history directly (mirrors process_trade_outcome's
    # _trade_history entries: pnl, is_win).
    engine.rl_engine._trade_history = [
        {"pnl": 200.0, "is_win": True},
        {"pnl": 300.0, "is_win": True},
        {"pnl": -100.0, "is_win": False},
        {"pnl": -50.0, "is_win": False},
    ]
    # avg_win = 250, avg_loss = 75 -> b = 250/75 = 3.333
    b = engine._get_realized_b()
    assert abs(b - 3.333) < 0.01, f"Expected b≈3.333, got {b}"


def test_backtest_loop_no_longer_sizes_by_flat_percent_of_capital():
    """
    Static check: the old flat-sizing line `alloc = capital *
    self.position_size_pct` must be gone from the entry-execution block, and
    `self.sizer.calculate_size` must be present instead. Parses the AST of
    the BacktestEngine.run() method specifically, so this doesn't just check
    "the string appears somewhere in the file" (which self.position_size_pct
    still legitimately does, in the deprecated-but-kept constructor param).
    """
    engine_path = os.path.join(
        os.path.dirname(__file__), "..", "backtesting", "engine.py"
    )
    with open(engine_path, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=engine_path)

    run_method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            run_method = node
            break
    assert run_method is not None, "BacktestEngine.run() not found"

    run_source = ast.get_source_segment(source, run_method)
    assert "capital * self.position_size_pct" not in run_source, (
        "The old flat-percent sizing (`capital * self.position_size_pct`) "
        "is back in the entry-execution path — Finding #11 has regressed."
    )
    assert "self.sizer.calculate_size(" in run_source, (
        "BacktestEngine.run() no longer calls self.sizer.calculate_size() "
        "for position sizing — Kelly sizing wiring may have been reverted."
    )
