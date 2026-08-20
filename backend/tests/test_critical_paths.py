"""
T-1 — Unit tests for critical capital-accounting paths.

Tests cover:
  • execute_trade: LONG/SHORT entry, duplicate guard, zero-balance block,
                   stop-cooldown block
  • force_close: revenue credit with slippage/commission, A-3 phantom-balance
                 guard, profitable SHORT close
  • get_total_equity: cash + mark-to-market, unrealised loss
  • PositionSizer.calculate_size: positive output, position cap, zero balance
  • PortfolioRiskManager (circuit breaker): daily halt, weekly halt, no-halt
  • GlobalRiskAggregator: daily halt, weekly halt, no-halt, equity sum

Run with:
    cd backend
    python -B -m pytest tests/test_critical_paths.py -v
"""

import asyncio
import pytest
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_engine(balance: float = 10_000.0):
    import tempfile
    from execution.smart_execution import SmartExecutionEngine

    tmp = tempfile.mktemp(suffix=".json")
    eng = SmartExecutionEngine(
        state_filename=os.path.basename(tmp),
        rl_state_filename=os.path.basename(tmp) + ".rl",
        initial_balance=balance,
        journal_filename=os.path.basename(tmp) + ".journal",
    )
    eng.portfolio_balance = balance
    eng.active_holdings = []
    eng.closed_trades = []
    eng.broker.is_live = False
    return eng


def _long_decision(confidence: float = 0.9) -> dict:
    return {
        "signal":          "BUY",
        "direction":       "LONG",
        "confidence":      confidence,
        "threshold":       0.5,
        "buy_conviction":  confidence,
        "sell_conviction": 0.1,
        "reason":          "test BUY",
        "regime":          "Trending Bull",
        "session_quality": "NORMAL",
        "entry_features":  {},
    }


def _short_decision(confidence: float = 0.9) -> dict:
    return {
        "signal":          "SELL",
        "direction":       "SHORT",
        "confidence":      confidence,
        "threshold":       0.5,
        "buy_conviction":  0.1,
        "sell_conviction": confidence,
        "reason":          "test SELL",
        "regime":          "Trending Bear",
        "session_quality": "NORMAL",
        "entry_features":  {},
    }


def _tick(price: float = 100.0, **kwargs) -> dict:
    base = {
        "price":              price,
        "rsi_14":             55.0,
        "macd_hist":          0.5,
        "atr_14":             1.0,
        "vwap":               price,
        "volume":             100_000,
        "halt_trading_for_day":  False,
        "halt_trading_for_week": False,
        "daily_drawdown_pct": 0.0,
        "cash_pct":           80.0,
        "active_holdings":    [],
        "open_trade_count":   0,
        "session_quality":    "NORMAL",
        "regime":             "Trending Bull",
        "trading_mode":       "Normal",
        "agent_weights":      {},
        "lstm_signal":        "NEUTRAL",
        "lstm_confidence":    0.5,
        "mtf_confluence":     {"alignment": "BULLISH", "detail": "ok"},
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# execute_trade
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteTrade:

    def test_long_entry_reduces_balance(self):
        eng = _make_engine(10_000.0)
        ok, msg = _run(eng.execute_trade("AAPL", 100.0, {**_long_decision(), **_tick()}))
        if ok:
            assert eng.portfolio_balance < 10_000.0, "Balance must decrease after BUY"
            assert len(eng.active_holdings) == 1
        else:
            # Monte Carlo veto or Kelly sized to 0 — not an accounting error
            assert any(w in msg.lower() for w in ("veto", "size", "balance", "kelly", "shares"))

    def test_short_entry_reserves_margin(self):
        eng = _make_engine(10_000.0)
        ok, msg = _run(eng.execute_trade("AAPL", 100.0, {**_short_decision(), **_tick()}))
        if ok:
            assert eng.portfolio_balance < 10_000.0
        # Balance must never INCREASE on entry
        assert eng.portfolio_balance <= 10_000.0

    def test_duplicate_long_blocked(self):
        """Opening a second LONG on the same symbol must be rejected."""
        eng = _make_engine(50_000.0)
        _run(eng.execute_trade("AAPL", 100.0, {**_long_decision(), **_tick()}))
        bal_after_first = eng.portfolio_balance
        ok2, msg2 = _run(eng.execute_trade("AAPL", 100.0, {**_long_decision(), **_tick()}))
        assert not ok2, "Duplicate LONG should be blocked"
        assert eng.portfolio_balance == bal_after_first

    def test_zero_balance_blocked(self):
        """With $0 capital Kelly returns 0 shares → trade must be rejected."""
        eng = _make_engine(0.0)
        ok, msg = _run(eng.execute_trade("AAPL", 100.0, {**_long_decision(), **_tick()}))
        assert not ok
        assert eng.portfolio_balance == 0.0

    def test_stop_cooldown_blocks_reentry(self):
        """60-second stop-cooldown must block immediate re-entry on the same symbol."""
        eng = _make_engine(10_000.0)
        eng._stop_cooldown["AAPL"] = time.time()  # inject recent stop-out
        ok, msg = _run(eng.execute_trade("AAPL", 100.0, {**_long_decision(), **_tick()}))
        assert not ok
        assert "cooldown" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# force_close  (A-3: credit AFTER confirmed remove)
# ─────────────────────────────────────────────────────────────────────────────

class TestForceClose:

    def _open_long(self, eng, symbol="AAPL", price=100.0, shares=10):
        """Inject a holding directly to isolate force_close from execute_trade."""
        holding = {
            "symbol":        symbol,
            "direction":     "LONG",
            "entry_price":   price,
            "shares":        shares,
            "value":         round(price * shares, 4),
            "stop_loss":     price * 0.97,
            "take_profit":   price * 1.06,
            "current_price": price,
            "change":        0.0,
            "sparkline":     [],
            "best_price":    price,
        }
        eng.active_holdings.append(holding)
        eng.portfolio_balance -= price * shares
        return holding

    def test_close_credits_correct_amount(self):
        """Revenue (gross minus slippage + 0.1% commission) must be within $3 of gross."""
        eng = _make_engine(10_000.0)
        holding = self._open_long(eng, price=100.0, shares=10)
        bal_before = eng.portfolio_balance
        ok, msg = _run(eng.force_close(holding, 110.0, "TAKE_PROFIT"))
        assert ok
        gross = 10 * 110.0  # 1 100
        # Commission = shares * fill_price * 0.1% ≈ $1.10; slippage ≤ 10 bps ≈ $1.10
        credited = eng.portfolio_balance - bal_before
        assert gross - 3.0 <= credited <= gross, (
            f"Expected credit in [{gross - 3.0:.2f}, {gross:.2f}], got {credited:.4f}"
        )

    def test_close_removes_from_holdings(self):
        eng = _make_engine(10_000.0)
        holding = self._open_long(eng)
        _run(eng.force_close(holding, 95.0, "STOP_LOSS"))
        assert holding not in eng.active_holdings

    def test_double_close_no_phantom_credit(self):
        """A-3: closing the same holding twice must not double-credit the balance."""
        eng = _make_engine(10_000.0)
        holding = self._open_long(eng, price=100.0, shares=10)
        _run(eng.force_close(holding, 110.0, "TAKE_PROFIT"))
        bal_after_first = eng.portfolio_balance
        ok2, msg2 = _run(eng.force_close(holding, 120.0, "TAKE_PROFIT"))
        assert not ok2, "Second force_close on removed holding must fail"
        assert eng.portfolio_balance == bal_after_first, (
            "A-3 phantom balance: balance must not change on duplicate close"
        )

    def test_short_close_credits_profit(self):
        """SHORT close at a lower price must increase balance (profitable)."""
        eng = _make_engine(50_000.0)
        entry, shares = 100.0, 5
        holding = {
            "symbol":        "AAPL",
            "direction":     "SHORT",
            "entry_price":   entry,
            "shares":        shares,
            "value":         round(entry * shares, 4),
            "stop_loss":     entry * 1.05,
            "take_profit":   entry * 0.94,
            "current_price": entry,
            "change":        0.0,
            "sparkline":     [],
            "best_price":    entry,
        }
        eng.active_holdings.append(holding)
        margin_reserved = round(entry * shares * 0.15, 4)
        eng.portfolio_balance -= margin_reserved
        bal_before = eng.portfolio_balance
        ok, msg = _run(eng.force_close(holding, 90.0, "TAKE_PROFIT"))
        assert ok
        assert eng.portfolio_balance > bal_before, "Profitable SHORT close must increase balance"


# ─────────────────────────────────────────────────────────────────────────────
# get_total_equity
# ─────────────────────────────────────────────────────────────────────────────

class TestGetTotalEquity:

    def test_no_holdings_equals_cash(self):
        eng = _make_engine(10_000.0)
        assert eng.get_total_equity() == pytest.approx(10_000.0, rel=1e-4)

    def test_equity_includes_holding_value(self):
        eng = _make_engine(10_000.0)
        eng.portfolio_balance = 9_000.0
        eng.active_holdings = [{
            "symbol":        "AAPL",
            "direction":     "LONG",
            "shares":        10,
            "entry_price":   100.0,
            "value":         1_000.0,
            "current_price": 100.0,
            "change":        0.0,
            "sparkline":     [],
        }]
        assert eng.get_total_equity() == pytest.approx(10_000.0, rel=1e-4)

    def test_equity_reflects_unrealised_loss(self):
        eng = _make_engine(10_000.0)
        eng.portfolio_balance = 9_000.0
        eng.active_holdings = [{
            "symbol":        "AAPL",
            "direction":     "LONG",
            "shares":        10,
            "entry_price":   100.0,
            "value":         800.0,
            "current_price": 80.0,
            "change":        -20.0,
            "sparkline":     [],
        }]
        assert eng.get_total_equity() == pytest.approx(9_800.0, rel=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# PositionSizer.calculate_size
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculateSize:

    def _sizer(self):
        from risk.position_sizing import PositionSizer
        return PositionSizer()

    def test_returns_positive_shares(self):
        result = self._sizer().calculate_size(0.9, 10_000.0, 100.0)
        assert result["shares"] > 0

    def test_max_position_pct_cap(self):
        """No single position should consume more than 16% of balance."""
        s = self._sizer()
        result = s.calculate_size(0.9, 10_000.0, 1.0,
                                  n_closed_trades=50, recent_win_rate=0.55)
        cost = result["shares"] * 1.0
        assert cost <= 10_000.0 * 0.16, (
            f"Position cost ${cost:.2f} exceeds 16% of $10 000"
        )

    def test_zero_balance_returns_zero(self):
        result = self._sizer().calculate_size(0.9, 0.0, 100.0)
        assert result["shares"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Circuit breaker  (PortfolioRiskManager)
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreaker:

    def test_daily_halt_fires_on_threshold(self):
        from risk.portfolio_risk import PortfolioRiskManager
        import tempfile, datetime
        pm = PortfolioRiskManager(state_file=tempfile.mktemp(suffix=".json"))
        pm.daily_start_capital = 10_000.0
        pm._last_reset_date    = datetime.date.today()
        result = pm.analyze([], 10_000.0 * 0.96)  # 4% loss, limit 3%
        assert result["halt_trading_for_day"]

    def test_no_halt_below_threshold(self):
        from risk.portfolio_risk import PortfolioRiskManager
        import tempfile, datetime
        pm = PortfolioRiskManager(state_file=tempfile.mktemp(suffix=".json"))
        pm.daily_start_capital = 10_000.0
        pm._last_reset_date    = datetime.date.today()
        result = pm.analyze([], 10_000.0 * 0.98)  # 2% loss, below 3% limit
        assert not result["halt_trading_for_day"]

    def test_weekly_halt_fires(self):
        from risk.portfolio_risk import PortfolioRiskManager
        import tempfile, datetime
        pm = PortfolioRiskManager(state_file=tempfile.mktemp(suffix=".json"))
        today = datetime.date.today()
        pm.weekly_start_capital = 10_000.0
        pm._last_reset_week     = tuple(today.isocalendar()[:2])
        result = pm.analyze([], 10_000.0 * 0.93)  # 7% loss, limit 6%
        assert result["halt_trading_for_week"]


# ─────────────────────────────────────────────────────────────────────────────
# GlobalRiskAggregator  (cross-market circuit breaker)
# ─────────────────────────────────────────────────────────────────────────────

class TestGlobalRiskAggregator:

    def _mock_engine(self, equity: float):
        class _FakeEngine:
            market = "TEST"
            def get_total_equity(self): return equity
        return _FakeEngine()

    def test_no_halt_below_threshold(self):
        from risk.global_risk import GlobalRiskAggregator
        import tempfile, datetime
        ga = GlobalRiskAggregator(state_file=tempfile.mktemp(suffix=".json"))
        ga.daily_start_equity = 100_000.0
        ga._last_reset_date   = datetime.date.today()
        ga.register_engines([self._mock_engine(49_000.0), self._mock_engine(49_000.0)])
        assert not ga.check()["global_halt"]

    def test_halt_fires_at_5pct_daily(self):
        from risk.global_risk import GlobalRiskAggregator
        import tempfile, datetime
        ga = GlobalRiskAggregator(state_file=tempfile.mktemp(suffix=".json"))
        ga.daily_start_equity = 100_000.0
        ga._last_reset_date   = datetime.date.today()
        # 6% combined loss → above 5% threshold
        ga.register_engines([self._mock_engine(47_000.0), self._mock_engine(47_000.0)])
        result = ga.check()
        assert result["global_halt"]
        assert "daily" in result["halt_reason"].lower()

    def test_halt_fires_at_10pct_weekly(self):
        """11% weekly loss must trigger global halt; weekly_dd_pct must be >= 10%."""
        from risk.global_risk import GlobalRiskAggregator
        import tempfile, datetime
        ga = GlobalRiskAggregator(state_file=tempfile.mktemp(suffix=".json"))
        today = datetime.date.today()
        ga.weekly_start_equity = 100_000.0
        ga._last_reset_week    = tuple(today.isocalendar()[:2])
        ga.daily_start_equity  = 100_000.0
        ga._last_reset_date    = today
        ga.register_engines([self._mock_engine(44_500.0), self._mock_engine(44_500.0)])
        result = ga.check()
        assert result["global_halt"], "Should halt on 11% combined loss"
        assert result["global_weekly_dd_pct"] >= 10.0, (
            f"Weekly drawdown should be >= 10%, got {result['global_weekly_dd_pct']:.2f}%"
        )

    def test_equity_by_market_sums_correctly(self):
        from risk.global_risk import GlobalRiskAggregator, INR_USD_RATE
        import tempfile
        ga = GlobalRiskAggregator(state_file=tempfile.mktemp(suffix=".json"))
        class _E:
            def __init__(self, m, v): self.market = m; self._v = v
            def get_total_equity(self): return self._v
        # Test USD + USD
        ga.register_engines([_E("US", 10_000.0), _E("STOCKS", 5_000.0)])
        assert ga.total_equity() == pytest.approx(15_000.0)
        # Test USD + INDIA (normalized via INR_USD_RATE)
        ga.register_engines([_E("US", 10_000.0), _E("INDIA", 5_000.0)])
        assert ga.total_equity() == pytest.approx(10_000.0 + 5_000.0 * INR_USD_RATE)


class TestAdaptiveStops:
    """Unit tests for initial ATR stop calculation and breakeven trailing stop ratchet."""

    def test_calculate_initial_stop_and_target(self):
        from risk.adaptive_stops import AdaptiveStopLoss
        stops = AdaptiveStopLoss()
        res_buy = stops.calculate(current_price=100.0, signal="BUY", volatility_proxy=0.02)
        assert res_buy["stop_loss"] < 100.0
        assert res_buy["take_profit"] > 100.0
        assert pytest.approx(res_buy["stop_loss"], 0.01) == 95.0       # 100 - (100 * 0.02 * 2.5) = 95.0 (1.0R = 5.0)
        assert pytest.approx(res_buy["tp1_target"], 0.01) == 107.5     # 100 + (5.0 * 1.5) = 107.5 (1.5R)
        assert pytest.approx(res_buy["tp2_target"], 0.01) == 115.0     # 100 + (5.0 * 3.0) = 115.0 (3.0R)
        assert pytest.approx(res_buy["take_profit"], 0.01) == 115.0    # TP2 = 115.0

        res_short = stops.calculate(current_price=100.0, signal="SELL", volatility_proxy=0.02)
        assert res_short["stop_loss"] > 100.0
        assert res_short["take_profit"] < 100.0
        assert pytest.approx(res_short["tp1_target"], 0.01) == 92.5     # 100 - (5.0 * 1.5) = 92.5
        assert pytest.approx(res_short["tp2_target"], 0.01) == 85.0     # 100 - (5.0 * 3.0) = 85.0


    def test_trailing_stop_breakeven_ratchet_long(self):
        from risk.adaptive_stops import AdaptiveStopLoss
        stops = AdaptiveStopLoss()
        # Entry at 100.0, initial stop at 95.0 (distance 5.0)
        # Price moves to 105.0 (+1.0R / +5.0 profit)
        res = stops.update_trailing(
            current_price=105.0,
            signal="BUY",
            current_stop=95.0,
            best_price=100.0,
            volatility_proxy=0.02,
            entry_price=100.0,
        )
        assert res["stop_moved"] is True
        assert res["best_price"] == 105.0
        # Breakeven ratchet ensures stop is AT LEAST entry_price (100.0)
        assert res["new_stop"] >= 100.0

    def test_trailing_stop_breakeven_ratchet_short(self):
        from risk.adaptive_stops import AdaptiveStopLoss
        stops = AdaptiveStopLoss()
        # Entry at 100.0, initial stop at 105.0
        # Price drops to 95.0 (+1.0R in profit for short)
        res = stops.update_trailing(
            current_price=95.0,
            signal="SELL",
            current_stop=105.0,
            best_price=100.0,
            volatility_proxy=0.02,
            entry_price=100.0,
        )
        assert res["stop_moved"] is True
        assert res["best_price"] == 95.0
        # Breakeven ratchet ensures stop is AT MOST entry_price (100.0)
        assert res["new_stop"] <= 100.0

    def test_trailing_stop_never_moves_against_trade(self):
        from risk.adaptive_stops import AdaptiveStopLoss
        stops = AdaptiveStopLoss()
        # LONG: price falls from 100.0 to 98.0
        res = stops.update_trailing(
            current_price=98.0,
            signal="BUY",
            current_stop=95.0,
            best_price=100.0,
            volatility_proxy=0.02,
            entry_price=100.0,
        )
        # Stop should remain at 95.0, not move down
        assert res["new_stop"] == 95.0
        assert res["stop_moved"] is False


class TestQuantPerfectionPillars:
    """Unit tests for the 5 Pillars of Quant Perfection."""

    def test_partial_close_scales_out_and_ratchets_stop(self):
        engine = _make_engine(balance=10000.0)
        
        # Simulate an active long position
        holding = {
            "symbol": "MNQ=F",
            "shares": 10.0,
            "entry_price": 100.0,
            "current_price": 107.5,
            "value": 1075.0,
            "change": 7.5,
            "stop_loss": 95.0,
            "initial_stop": 95.0,
            "take_profit": 115.0,
            "tp1_target": 107.5,
            "tp2_target": 115.0,
            "tp1_hit": False,
            "direction": "LONG",
        }
        engine.active_holdings = [holding]
        engine.portfolio_balance = 9000.0

        # Execute 50% scale-out at TP1 (107.5)
        ok, msg = _run(engine.partial_close(holding, price=107.5, fraction=0.5, reason="TP1_1.5R"))
        assert ok is True
        assert holding["shares"] == 5.0
        assert holding["tp1_hit"] is True
        # Stop loss must be ratcheted to Breakeven (at or above entry price 100.0)
        assert holding["stop_loss"] >= 100.0
        # Balance must increase with realized profits
        assert engine.portfolio_balance > 9500.0
        assert len(engine.closed_trades) == 1
        assert engine.closed_trades[0]["profit_loss"] > 0


    def test_metagate_threshold_raised_to_65(self):
        from analytics.meta_gate import GATE_THRESHOLD
        assert GATE_THRESHOLD == 0.65

    def test_confluence_strict_htf_veto(self):
        from data.timeframe_confluence import TimeframeConfluenceEngine
        engine = TimeframeConfluenceEngine()
        confluence = {
            "daily_trend": "BEAR",
            "hourly_trend": "BEAR",
            "tick_trend": "BULL",
            "alignment": "OPPOSED",
            "confidence_multiplier": 0.5,
            "detail": "Timeframes in opposition"
        }
        decision = {"signal": "BUY", "confidence": 0.85, "reason": "Bullish breakout"}
        result = engine.apply_to_decision(decision, confluence, signal_direction="BUY")
        assert result["signal"] == "WAIT"
        assert "MTF VETO" in result["reason"]

    def test_regime_directional_veto(self):
        from agents.master import MasterAgent
        agent = MasterAgent()
        
        # Test long entry vetoed in Trending Bear regime
        data_bear = {
            "regime": "Trending Bear",
            "trading_mode": "Normal",
            "agent_weights": {a.name: 1.0 for a in agent.committee}
        }
        # Mock committee to return strong BUY
        for c in agent.committee:
            c.evaluate = lambda sym, d: {"signal": "BUY", "confidence": 0.9, "reason": "Strong setup"}
            
        res = agent.evaluate("MNQ=F", data_bear)
        assert res["signal"] == "WAIT"
        assert "Regime VETO" in res["reason"]


