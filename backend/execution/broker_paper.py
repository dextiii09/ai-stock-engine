"""
Paper Broker — simulates order execution with no real money.
This is the default broker. All orders are accepted instantly at the
given price (same behaviour as before broker abstraction was added).
"""
import time
from typing import Optional, Tuple
from .broker_base import BrokerBase


class PaperBroker(BrokerBase):

    @property
    def name(self) -> str:
        return "Paper"

    @property
    def is_live(self) -> bool:
        return False

    def buy(self, symbol, qty, price, order_type="MARKET"):
        return True, f"[PAPER] BUY {qty} {symbol} @ {price:.4f} filled.", None

    def sell(self, symbol, qty, price, order_type="MARKET"):
        return True, f"[PAPER] SELL {qty} {symbol} @ {price:.4f} filled.", None

    def short(self, symbol, qty, price, order_type="MARKET"):
        return True, f"[PAPER] SHORT {qty} {symbol} @ {price:.4f} filled.", None

    def cover(self, symbol, qty, price, order_type="MARKET"):
        _oid = f"PAPER_{int(time.time()*1000)}"
        return True, f"[PAPER] COVER {qty} {symbol} @ {price}", _oid

    def get_fill_status(self, order_id: str, requested_qty: float, fallback_price: float):
        from .broker_base import FillResult
        # Paper trades execute instantly at the simulated router price in full
        return FillResult("FILLED", fallback_price, requested_qty, False, "Paper fill")
