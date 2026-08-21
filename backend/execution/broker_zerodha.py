"""
Zerodha Kite Connect Broker
Requires: pip install kiteconnect

Setup:
  1. Create a Zerodha developer app at https://developers.kite.trade/
  2. Get your api_key and api_secret
  3. On first run, call generate_session(request_token) with the token
     from the OAuth redirect to get an access_token.
  4. Set ZERODHA_API_KEY, ZERODHA_API_SECRET, ZERODHA_ACCESS_TOKEN
     in your .env file.

Exchange mapping:
  NSE symbols (e.g. RELIANCE.NS)  -> strip .NS, exchange="NSE"
  BSE symbols (e.g. RELIANCE.BO)  -> strip .BO, exchange="BSE"
  Futures / options -> exchange="NFO"
"""

import os
import re
from typing import Dict, Any, Optional, Tuple
from .broker_base import BrokerBase


def _strip_suffix(symbol: str) -> Tuple[str, str]:
    """
    Returns (clean_symbol, exchange).
    E.g. 'RELIANCE.NS' -> ('RELIANCE', 'NSE')
         'NIFTYBEES.NS' -> ('NIFTYBEES', 'NSE')
    """
    if symbol.upper().endswith(".NS"):
        return symbol[:-3].upper(), "NSE"
    if symbol.upper().endswith(".BO"):
        return symbol[:-3].upper(), "BSE"
    return symbol.upper(), "NSE"


class ZerodhaBroker(BrokerBase):
    """
    Live broker using Zerodha Kite Connect API.
    All orders are CNC (delivery) by default for equities.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        self._api_key      = api_key      or os.getenv("ZERODHA_API_KEY", "")
        self._api_secret   = api_secret   or os.getenv("ZERODHA_API_SECRET", "")
        self._access_token = access_token or os.getenv("ZERODHA_ACCESS_TOKEN", "")
        self._kite = None
        self._connected = False
        self._connect()

    def _connect(self):
        try:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self._api_key)
            self._kite.set_access_token(self._access_token)
            self._connected = True
            print(f"[ZerodhaBroker] Connected to Kite Connect.")
        except ImportError:
            print("[ZerodhaBroker] kiteconnect not installed. Run: pip install kiteconnect")
        except Exception as e:
            print(f"[ZerodhaBroker] Connection failed: {e}")
            self._connected = False

    @property
    def name(self) -> str:
        return "Zerodha"

    @property
    def is_live(self) -> bool:
        return True

    def normalize_quantity(self, symbol: str, qty: float) -> float:
        """Indian cash-equity orders are whole shares. Round to the nearest
        integer; a sub-share size rounds to 0 so the caller rejects it (IV&V C2)
        rather than the engine silently booking a phantom fractional position."""
        return float(int(round(float(qty))))

    def _place_order(
        self,
        symbol: str,
        qty: int,
        transaction_type: str,
        order_type: str = "MARKET",
        product: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[str]]:
        # Ironclad safety lock: prevent real-money execution unless explicitly enabled in .env
        #
        # IV&V finding 2026-08-21: short() and cover() previously reimplemented
        # order placement inline instead of calling this method, which silently
        # dropped this exact safety check — a SHORT or COVER signal would place
        # a real order on the live exchange even with
        # ENABLE_LIVE_REAL_MONEY_TRADING left at its safe default, while BUY/SELL
        # stayed correctly blocked. UpstoxBroker and IBKRBroker were already
        # correct (all 4 methods route through their _place_order). All 4
        # Zerodha methods now do too, so the lock covers every order type.
        live_enabled = os.getenv("ENABLE_LIVE_REAL_MONEY_TRADING", "false").lower() == "true"
        if not live_enabled:
            msg = "[SAFETY LOCK] Real money trading is disabled (ENABLE_LIVE_REAL_MONEY_TRADING != true). Order blocked."
            print(f"[ZerodhaBroker] {msg}")
            return False, msg, None

        if not self._connected or self._kite is None:
            return False, "Zerodha not connected. Check credentials.", None

        clean, exchange = _strip_suffix(symbol)
        try:
            from kiteconnect import KiteConnect
            otype = KiteConnect.ORDER_TYPE_MARKET if order_type == "MARKET" else KiteConnect.ORDER_TYPE_LIMIT
            ttype = (
                KiteConnect.TRANSACTION_TYPE_BUY
                if transaction_type == "BUY"
                else KiteConnect.TRANSACTION_TYPE_SELL
            )
            ptype = product or KiteConnect.PRODUCT_CNC   # CNC (delivery) unless caller requests MIS (intraday)
            order_id = self._kite.place_order(
                variety=KiteConnect.VARIETY_REGULAR,
                exchange=exchange,
                tradingsymbol=clean,
                transaction_type=ttype,
                quantity=qty,
                order_type=otype,
                product=ptype,
            )
            msg = f"[ZERODHA] {transaction_type} {qty} {clean} order placed. ID={order_id}"
            print(msg)
            return True, msg, str(order_id)
        except Exception as e:
            msg = f"[ZERODHA] Order failed for {clean}: {e}"
            print(msg)
            return False, msg, None

    def buy(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "BUY", order_type)

    def sell(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "SELL", order_type)

    def short(self, symbol, qty, price, order_type="MARKET"):
        # Zerodha supports intraday shorts via MIS product. "MIS" is passed as
        # a literal (not KiteConnect.PRODUCT_MIS) so this doesn't require
        # importing kiteconnect before _place_order's own connected-check —
        # if the package isn't installed, _place_order still fails gracefully
        # with (False, msg, None) instead of an uncaught ImportError.
        return self._place_order(symbol, qty, "SELL", order_type, product="MIS")

    def cover(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "BUY", order_type, product="MIS")

    def cancel_order(self, order_id: str) -> Tuple[bool, str]:
        if not self._connected or self._kite is None:
            return False, "Not connected"
        try:
            self._kite.cancel_order(variety=self._kite.VARIETY_REGULAR, order_id=order_id)
            return True, f"Cancelled {order_id}"
        except Exception as e:
            return False, f"Cancel failed: {e}"

    def get_fill_status(self, order_id: str, requested_qty: float, fallback_price: float):
        from .broker_base import FillResult
        if not self._connected or self._kite is None:
            return FillResult("TIMEOUT", fallback_price, 0.0, True, "Broker not connected")
        
        import time
        for _ in range(15):
            try:
                history = self._kite.order_history(order_id=order_id)
                if history:
                    last = history[-1]
                    status = last.get("status")
                    filled = float(last.get("filled_quantity", 0) or 0)

                    if status == "COMPLETE":
                        price = last.get("average_price")
                        if price and filled > 0:
                            return FillResult("FILLED" if filled >= requested_qty else "PARTIAL",
                                               float(price), filled, False, "Filled")
                        return FillResult("TIMEOUT", fallback_price, 0.0, True, "COMPLETE status but no fill data")

                    if status in ("REJECTED", "CANCELLED"):
                        if filled > 0:
                            price = float(last.get("average_price") or fallback_price)
                            return FillResult("PARTIAL", price, filled, price == fallback_price,
                                               last.get("status_message", status))
                        return FillResult("REJECTED", 0.0, 0.0, False,
                                           last.get("status_message", status))
            except Exception as e:
                import logging
                logging.getLogger("ai_stock.execution").warning(f"[ZERODHA] order_history poll failed for {order_id}: {e}")
            time.sleep(1)
            
        return FillResult("TIMEOUT", fallback_price, 0.0, True,
                           f"Polling timed out after 15s, order {order_id} status unresolved")

    def get_account_info(self) -> Dict[str, Any]:
        if not self._connected or self._kite is None:
            return {"error": "Not connected"}
        try:
            margins = self._kite.margins()
            return {
                "available_cash": margins.get("equity", {}).get("available", {}).get("cash", 0),
                "used_margin":    margins.get("equity", {}).get("utilised", {}).get("debits", 0),
                "broker": "Zerodha",
            }
        except Exception as e:
            return {"error": str(e)}

    def generate_session(self, request_token: str) -> str:
        """
        Call this once with the OAuth request_token to get an access_token.
        Save the returned token as ZERODHA_ACCESS_TOKEN in your .env.
        """
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=self._api_key)
        data = kite.generate_session(request_token, api_secret=self._api_secret)
        access_token = data["access_token"]
        print(f"[ZerodhaBroker] Access token: {access_token}")
        print("Set ZERODHA_ACCESS_TOKEN in your .env file and restart the server.")
        return access_token
