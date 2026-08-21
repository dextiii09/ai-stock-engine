"""
Interactive Brokers Broker (via ib_insync)
Requires: pip install ib_insync

Setup:
  1. Install TWS (Trader Workstation) or IB Gateway on your machine.
  2. Enable the API in TWS: File > Global Config > API > Settings
     - Check "Enable ActiveX and Socket Clients"
     - Set port (default 7497 for paper, 7496 for live)
  3. Set IBKR_HOST (default 127.0.0.1), IBKR_PORT (default 7497),
     IBKR_CLIENT_ID (default 1) in your .env file.

Symbol mapping:
  US equities: 'AAPL' -> Stock('AAPL', 'SMART', 'USD')
  Futures:     'MNQ=F' -> Future('MNQ', exchange='CME', currency='USD')
               'MGC=F' -> Future('MGC', exchange='COMEX', currency='USD')
"""

import os
from typing import Dict, Any, Optional, Tuple
from .broker_base import BrokerBase

# Futures symbol map: Yahoo Finance ticker -> (IB symbol, exchange, currency)
FUTURES_MAP = {
    "MNQ=F": ("MNQ", "CME",   "USD"),
    "MGC=F": ("MGC", "COMEX", "USD"),
    "ES=F":  ("ES",  "CME",   "USD"),
    "GC=F":  ("GC",  "COMEX", "USD"),
    "NQ=F":  ("NQ",  "CME",   "USD"),
}


def _make_contract(symbol: str):
    """
    Convert a symbol string to an ib_insync Contract object.
    Supports US equities and common futures.
    """
    from ib_insync import Stock, Future

    if symbol in FUTURES_MAP:
        ib_sym, exch, curr = FUTURES_MAP[symbol]
        return Future(ib_sym, exchange=exch, currency=curr)

    # NSE/BSE suffixes — route to correct Indian exchange with INR currency
    if symbol.upper().endswith(".NS"):
        clean = symbol[:-3].upper()
        return Stock(clean, "NSE", "INR")
    if symbol.upper().endswith(".BO"):
        clean = symbol[:-3].upper()
        return Stock(clean, "BSE", "INR")

    # Generic US equity fallback
    clean = symbol.upper()
    return Stock(clean, "SMART", "USD")


class IBKRBroker(BrokerBase):
    """
    Live broker using Interactive Brokers via ib_insync.
    Connects to TWS or IB Gateway running on localhost.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        self._host      = host      or os.getenv("IBKR_HOST", "127.0.0.1")
        self._port      = port      or int(os.getenv("IBKR_PORT", "7497"))
        self._client_id = client_id or int(os.getenv("IBKR_CLIENT_ID", "1"))
        self._ib = None
        self._connected = False
        self._connect()

    def _connect(self):
        try:
            from ib_insync import IB
            self._ib = IB()
            self._ib.connect(self._host, self._port, clientId=self._client_id, timeout=10)
            self._connected = True
            print(f"[IBKRBroker] Connected to TWS at {self._host}:{self._port}")
        except ImportError:
            print("[IBKRBroker] ib_insync not installed. Run: pip install ib_insync")
        except Exception as e:
            print(f"[IBKRBroker] Connection failed: {e}")
            self._connected = False

    @property
    def name(self) -> str:
        return "IBKR"

    @property
    def is_live(self) -> bool:
        # TODO: Return True only when get_fill_status polling is properly implemented
        return False

    def normalize_quantity(self, symbol: str, qty: float) -> float:
        """IBKR supports fractional US equities/crypto but futures trade in
        whole contracts. Round futures (…=F) to integer contracts (sub-contract
        → 0, rejected by caller); keep everything else fractional to 4 dp
        (IV&V C2 — never silently truncate to 0)."""
        if symbol.upper().endswith("=F"):
            return float(int(round(float(qty))))
        return round(float(qty), 4)

    def _place_order(
        self,
        symbol: str,
        qty: int,
        action: str,           # 'BUY' or 'SELL'
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> Tuple[bool, str, Optional[str]]:
        # Ironclad safety lock: prevent real-money execution unless explicitly enabled in .env
        live_enabled = os.getenv("ENABLE_LIVE_REAL_MONEY_TRADING", "false").lower() == "true"
        if not live_enabled:
            msg = "[SAFETY LOCK] Real money trading is disabled (ENABLE_LIVE_REAL_MONEY_TRADING != true). Order blocked."
            print(f"[IBKRBroker] {msg}")
            return False, msg, None

        if not self._connected or self._ib is None:
            return False, "IBKR not connected. Ensure TWS/Gateway is running.", None

        try:
            from ib_insync import MarketOrder, LimitOrder
            contract  = _make_contract(symbol)
            order     = MarketOrder(action, qty) if order_type == "MARKET" else LimitOrder(action, qty, price)
            trade     = self._ib.placeOrder(contract, order)
            order_id  = str(trade.order.orderId)
            msg = f"[IBKR] {action} {qty} {symbol}. OrderId={order_id}"
            print(msg)
            return True, msg, order_id
        except Exception as e:
            msg = f"[IBKR] Order failed for {symbol}: {e}"
            print(msg)
            return False, msg, None

    def buy(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "BUY", order_type)

    def sell(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "SELL", order_type)

    def short(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "SELL", order_type)

    def cover(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "BUY", order_type)

    def get_fill_status(self, order_id: str, requested_qty: float, fallback_price: float):
        from .broker_base import FillResult
        # TODO: Implement robust ib_insync trade polling
        import logging
        logging.getLogger("ai_stock.execution").warning(f"[IBKR] get_fill_status not implemented for {order_id}, returning TIMEOUT")
        return FillResult("TIMEOUT", fallback_price, 0.0, True, "Not implemented")

    def get_account_info(self) -> Dict[str, Any]:
        if not self._connected or self._ib is None:
            return {"error": "Not connected"}
        try:
            summary = self._ib.accountSummary()
            info = {item.tag: item.value for item in summary}
            return {
                "available_cash":   float(info.get("AvailableFunds", 0)),
                "net_liquidation":  float(info.get("NetLiquidation", 0)),
                "buying_power":     float(info.get("BuyingPower", 0)),
                "broker": "IBKR",
            }
        except Exception as e:
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        if not self._connected or self._ib is None:
            return False, "Not connected."
        try:
            from ib_insync import Trade
            open_trades = self._ib.openTrades()
            for trade in open_trades:
                if str(trade.order.orderId) == order_id:
                    self._ib.cancelOrder(trade.order)
                    return True, f"[IBKR] Order {order_id} cancelled."
            return False, f"[IBKR] Order {order_id} not found in open trades."
        except Exception as e:
            return False, str(e)
