"""
Regression tests for a HIGH finding in the 2026-08-21 audit (Finding #20):

`SmartExecutionEngine.closed_trades` grew unbounded for the life of a 24/7
deployment and was re-serialized to JSON in full on every trade close. The
naive fix (cap the list, like `execution_logs[-500:]`) would have silently
corrupted the lifetime PnL/win-rate totals that `/portfolio/money-tracker`
and other endpoints compute by summing over the full list — once trades aged
out of a capped list, they'd vanish from "lifetime" totals.

The actual fix: `lifetime_stats` is an O(1) running-counter dict, updated
incrementally in `_record_closed_trade()` alongside every append, persisted
independently of how much closed_trades history is retained, and backfilled
once from history on load for pre-fix state files. This test verifies:
  1. lifetime_stats accumulates correctly across multiple closed trades.
  2. closed_trades is capped at _MAX_CLOSED_TRADES while lifetime_stats is not.
  3. lifetime_stats survives (and correctly totals) trades that have aged out
     of the capped closed_trades list — the exact scenario the naive fix
     would have gotten wrong.
  4. _backfill_lifetime_stats_if_needed() correctly reconstructs lifetime_stats
     from a pre-fix closed_trades list that has no lifetime_stats yet.
"""

import pytest

from execution.smart_execution import SmartExecutionEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = SmartExecutionEngine(
        state_filename=str(tmp_path / "portfolio_state_test.json"),
        rl_state_filename=str(tmp_path / "rl_state_test.json"),
        journal_filename=str(tmp_path / "journal_test.json"),
    )
    # Isolate from any real state that _load_state() might have picked up.
    eng.closed_trades = []
    eng.lifetime_stats = {
        "total_trades": 0, "winning_trades": 0,
        "total_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
    }
    eng._lifetime_stats_backfilled = True
    return eng


def test_lifetime_stats_accumulates_incrementally(engine):
    engine._record_closed_trade({"profit_loss": 100.0})
    engine._record_closed_trade({"profit_loss": -40.0})
    engine._record_closed_trade({"profit_loss": 25.0})

    stats = engine.lifetime_stats
    assert stats["total_trades"] == 3
    assert stats["winning_trades"] == 2
    assert stats["total_pnl"] == pytest.approx(85.0)
    assert stats["gross_profit"] == pytest.approx(125.0)
    assert stats["gross_loss"] == pytest.approx(40.0)


def test_closed_trades_list_is_capped_but_lifetime_stats_is_not(engine):
    engine._MAX_CLOSED_TRADES = 5  # instance-level override to keep the test fast
    for i in range(12):
        engine._record_closed_trade({"profit_loss": 10.0 if i % 2 == 0 else -3.0})

    assert len(engine.closed_trades) == 5
    assert engine.lifetime_stats["total_trades"] == 12
    assert engine.lifetime_stats["winning_trades"] == 6
    assert engine.lifetime_stats["total_pnl"] == pytest.approx(6 * 10.0 - 6 * 3.0)


def test_lifetime_stats_correct_even_after_trades_age_out_of_capped_list(engine):
    """
    The exact bug the naive fix would introduce: summing the (now-capped)
    closed_trades list after aging-out would under-count lifetime totals.
    lifetime_stats must NOT depend on what's still in closed_trades.
    """
    engine._MAX_CLOSED_TRADES = 3
    for _ in range(10):
        engine._record_closed_trade({"profit_loss": 50.0})

    naive_sum_from_capped_list = sum(t["profit_loss"] for t in engine.closed_trades)
    assert naive_sum_from_capped_list == pytest.approx(150.0)  # only 3 remain
    assert engine.lifetime_stats["total_pnl"] == pytest.approx(500.0)  # true lifetime total
    assert engine.lifetime_stats["total_trades"] == 10


def test_backfill_reconstructs_lifetime_stats_from_pre_fix_state(engine):
    engine.closed_trades = [
        {"profit_loss": 30.0},
        {"profit_loss": -10.0},
        {"profit_loss": 0.0},
        {"profit_loss": 5.0},
    ]
    engine.lifetime_stats = {
        "total_trades": 0, "winning_trades": 0,
        "total_pnl": 0.0, "gross_profit": 0.0, "gross_loss": 0.0,
    }
    engine._lifetime_stats_backfilled = False

    engine._backfill_lifetime_stats_if_needed()

    assert engine.lifetime_stats["total_trades"] == 4
    assert engine.lifetime_stats["winning_trades"] == 2
    assert engine.lifetime_stats["total_pnl"] == pytest.approx(25.0)
    assert engine.lifetime_stats["gross_profit"] == pytest.approx(35.0)
    assert engine.lifetime_stats["gross_loss"] == pytest.approx(10.0)
    assert engine._lifetime_stats_backfilled is True

    # Calling again must be a no-op (idempotent — must not double-count).
    engine._backfill_lifetime_stats_if_needed()
    assert engine.lifetime_stats["total_trades"] == 4


def test_backfill_is_noop_when_no_history(engine):
    engine._lifetime_stats_backfilled = False
    engine._backfill_lifetime_stats_if_needed()
    assert engine.lifetime_stats["total_trades"] == 0
    assert engine._lifetime_stats_backfilled is True
