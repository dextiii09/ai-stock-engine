"""
Unit tests for live-broker execution reconciliation and race condition handling.

Tests cover:
  1. Live BUY REJECTED with zero fill -> hard abort, no position booked, balance untouched
  2. Live BUY TIMEOUT with confirmed cancel (zero fill) -> clean no-op abort
  3. Live BUY TIMEOUT with cancel race (cancel fails, order actually FILLED) -> position booked correctly with real fill
  4. Live BUY PARTIAL fill on entry -> holding reflects filled_qty, not requested qty
  5. Live SELL PARTIAL fill on exit -> remaining shares retained in active_holdings, proportional revenue credited
  6. Live COVER PARTIAL fill on exit -> remaining short shares retained, proportional margin and profit credited
"""

import asyncio
import pytest
import sys
import os
import tempfile
from typing import Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from execution.broker_base import BrokerBase, FillResult
from execution.smart_execution import SmartExecutionEngine


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class MockLiveBroker(BrokerBase):
    def __init__(self):
        self._is_live = True
        self.cancel_responses = []
        self.fill_responses = []
        self.buy_response = (True, "Order placed", "OID_BUY_1")
        self.sell_response = (True, "Order placed", "OID_SELL_1")
        self.short_response = (True, "Order placed", "OID_SHORT_1")
        self.cover_response = (True, "Order placed", "OID_COVER_1")
        self.placed_orders = []
        self.cancelled_orders = []

    @property
    def is_live(self) -> bool:
        return self._is_live

    @property
    def name(self) -> str:
        return "MockLiveBroker"

    def normalize_quantity(self, symbol: str, qty: float) -> float:
        return float(qty)

    def buy(self, symbol, qty, price, order_type="MARKET"):
        self.placed_orders.append(("BUY", symbol, qty, price))
        return self.buy_response

    def sell(self, symbol, qty, price, order_type="MARKET"):
        self.placed_orders.append(("SELL", symbol, qty, price))
        return self.sell_response

    def short(self, symbol, qty, price, order_type="MARKET"):
        self.placed_orders.append(("SHORT", symbol, qty, price))
        return self.short_response

    def cover(self, symbol, qty, price, order_type="MARKET"):
        self.placed_orders.append(("COVER", symbol, qty, price))
        return self.cover_response

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        self.cancelled_orders.append(order_id)
        if self.cancel_responses:
            return self.cancel_responses.pop(0)
        return True, f"Cancelled {order_id}"

    def get_fill_status(self, order_id: str, requested_qty: float, fallback_price: float) -> FillResult:
        if self.fill_responses:
            return self.fill_responses.pop(0)
        return FillResult("FILLED", fallback_price, requested_qty, False, "Filled")

    def get_account_info(self):
        return {"balance": 10000.0}


def _make_live_engine(balance: float = 10_000.0):
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
    eng.broker = MockLiveBroker()
    return eng


def _decision(signal: str = "BUY", confidence: float = 0.9) -> dict:
    return {
        "signal": signal,
        "direction": "LONG" if signal == "BUY" else "SHORT",
        "confidence": confidence,
        "threshold": 0.5,
        "buy_conviction": confidence if signal == "BUY" else 0.1,
        "sell_conviction": 0.1 if signal == "BUY" else confidence,
        "reason": f"test {signal}",
        "regime": "Trending Bull" if signal == "BUY" else "Trending Bear",
        "session_quality": "NORMAL",
        "entry_features": {},
        "price": 100.0,
        "rsi_14": 55.0,
        "macd_hist": 0.5,
        "atr_14": 1.0,
        "vwap": 100.0,
        "volume": 100_000,
        "halt_trading_for_day": False,
        "halt_trading_for_week": False,
        "daily_drawdown_pct": 0.0,
        "cash_pct": 80.0,
        "active_holdings": [],
        "open_trade_count": 0,
        "trading_mode": "Normal",
        "agent_weights": {},
        "lstm_signal": "NEUTRAL",
        "lstm_confidence": 0.5,
        "mtf_confluence": {"alignment": "BULLISH", "detail": "ok"},
    }


class TestLiveReconciliation:

    def test_live_buy_rejected_with_zero_fill_aborts(self):
        """Exchange rejection must cleanly abort with 0 positions booked and 0 balance change."""
        eng = _make_live_engine(10_000.0)
        eng.broker.fill_responses = [
            FillResult("REJECTED", 0.0, 0.0, False, "Exchange margin insufficient")
        ]

        ok, msg = _run(eng.execute_trade("AAPL", 100.0, _decision("BUY")))

        assert ok is False
        assert "rejected" in msg.lower() or "zero fill" in msg.lower()
        assert len(eng.active_holdings) == 0
        assert eng.portfolio_balance == 10_000.0

    def test_live_buy_timeout_with_confirmed_cancel_aborts(self):
        """TIMEOUT followed by confirmed cancel (REJECTED status with 0 fill) aborts cleanly."""
        eng = _make_live_engine(10_000.0)
        eng.broker.fill_responses = [
            FillResult("TIMEOUT", 100.0, 0.0, True, "Initial 15s poll timed out"),
            FillResult("REJECTED", 0.0, 0.0, False, "Order CANCELLED at exchange with 0 fill"),
        ]
        eng.broker.cancel_responses = [(True, "Cancelled OID_BUY_1")]

        ok, msg = _run(eng.execute_trade("AAPL", 100.0, _decision("BUY")))

        assert ok is False
        assert "cancelled" in msg.lower() or "zero fill" in msg.lower()
        assert len(eng.active_holdings) == 0
        assert eng.portfolio_balance == 10_000.0
        assert "OID_BUY_1" in eng.broker.cancelled_orders

    def test_live_buy_timeout_race_condition_reveals_fill(self):
        """TIMEOUT where cancel fails because order just FILLED: books real fill and avoids invisible position."""
        eng = _make_live_engine(10_000.0)
        real_fill_price = 101.25
        real_fill_qty = 10.0
        
        eng.broker.fill_responses = [
            FillResult("TIMEOUT", 100.0, 0.0, True, "Initial 15s poll timed out"),
            FillResult("FILLED", real_fill_price, real_fill_qty, False, "Order completed at broker"),
        ]
        eng.broker.cancel_responses = [(False, "Order is already COMPLETE")]

        ok, msg = _run(eng.execute_trade("AAPL", 100.0, _decision("BUY")))

        assert ok is True
        assert len(eng.active_holdings) == 1
        holding = eng.active_holdings[0]
        assert holding["entry_price"] == real_fill_price
        assert holding["shares"] == real_fill_qty
        assert holding["is_synthetic_price"] is False
        expected_cost = real_fill_qty * real_fill_price
        assert eng.portfolio_balance == pytest.approx(10_000.0 - expected_cost)

    def test_live_buy_partial_fill_on_entry(self):
        """PARTIAL fill on entry records actual filled_qty rather than requested size."""
        eng = _make_live_engine(10_000.0)
        partial_price = 100.50
        partial_qty = 4.0

        eng.broker.fill_responses = [
            FillResult("PARTIAL", partial_price, partial_qty, False, "Partial fill 4 of 10")
        ]

        ok, msg = _run(eng.execute_trade("AAPL", 100.0, _decision("BUY")))

        assert ok is True
        assert len(eng.active_holdings) == 1
        holding = eng.active_holdings[0]
        assert holding["shares"] == partial_qty
        assert holding["entry_price"] == partial_price
        expected_cost = partial_qty * partial_price
        assert eng.portfolio_balance == pytest.approx(10_000.0 - expected_cost)

    def test_live_sell_partial_fill_on_exit(self):
        """PARTIAL fill on SELL retains un-sold remainder in active_holdings and credits real revenue."""
        eng = _make_live_engine(10_000.0)
        initial_shares = 10.0
        initial_entry_px = 100.0

        # Seed an existing LONG holding
        long_holding = {
            "symbol": "AAPL",
            "shares": initial_shares,
            "entry_price": initial_entry_px,
            "current_price": 110.0,
            "value": initial_shares * 110.0,
            "direction": "LONG",
            "stop_loss": 95.0,
            "take_profit": 120.0,
        }
        eng.active_holdings = [long_holding]

        # Broker only partially fills 6 shares on SELL
        sold_qty = 6.0
        sold_px = 110.0
        eng.broker.fill_responses = [
            FillResult("PARTIAL", sold_px, sold_qty, False, "Filled 6 of 10 shares")
        ]

        ok, msg = _run(eng.execute_trade("AAPL", 110.0, _decision("SELL")))

        assert ok is True
        # Holding must NOT be deleted
        assert len(eng.active_holdings) == 1
        assert eng.active_holdings[0]["shares"] == pytest.approx(initial_shares - sold_qty)
        # Revenue = (6 * 110) - 0.1% comm = 660 - 0.66 = 659.34
        expected_revenue = (sold_qty * sold_px) - (sold_qty * sold_px * 0.001)
        assert eng.portfolio_balance == pytest.approx(10_000.0 + expected_revenue)

    def test_live_cover_partial_fill_on_exit(self):
        """PARTIAL fill on COVER retains un-covered short remainder and returns proportional margin."""
        eng = _make_live_engine(10_000.0)
        initial_shares = 10.0
        initial_entry_px = 100.0
        margin_reserved = 200.0  # $200 margin for 10 shares

        # Seed an existing SHORT holding
        short_holding = {
            "symbol": "AAPL",
            "shares": initial_shares,
            "entry_price": initial_entry_px,
            "current_price": 90.0,
            "value": initial_shares * 90.0,
            "direction": "SHORT",
            "margin_reserved": margin_reserved,
            "stop_loss": 105.0,
            "take_profit": 80.0,
        }
        eng.active_holdings = [short_holding]

        # Broker only partially covers 5 shares at $90.0
        covered_qty = 5.0
        cover_px = 90.0
        eng.broker.fill_responses = [
            FillResult("PARTIAL", cover_px, covered_qty, False, "Covered 5 of 10 shares")
        ]

        ok, msg = _run(eng.execute_trade("AAPL", 90.0, _decision("BUY")))

        assert ok is True
        # Holding must NOT be deleted
        assert len(eng.active_holdings) == 1
        assert eng.active_holdings[0]["shares"] == pytest.approx(initial_shares - covered_qty)
        # Margin fraction = 5 / 10 = 0.5 -> $100 margin returned
        # Profit = 5 * (100 - 90) - (5 * 90 * 0.001) = 50 - 0.45 = 49.55
        # Revenue = 100 + 49.55 = 149.55
        expected_revenue = 100.0 + (covered_qty * (initial_entry_px - cover_px)) - (covered_qty * cover_px * 0.001)
        assert eng.portfolio_balance == pytest.approx(10_000.0 + expected_revenue)
