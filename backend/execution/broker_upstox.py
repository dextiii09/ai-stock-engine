"""
Upstox API v2 Broker
Requires: UPSTOX_ACCESS_TOKEN in .env

Executes trades against the Upstox v2 API.
Includes mapping to resolve Yahoo Finance tickers (e.g. RELIANCE.NS)
into Upstox Instrument Keys (e.g. NSE_EQ|INE002A01018).
"""
import os
import json
import gzip
import ssl
import urllib.request
import urllib.parse
from io import BytesIO
from typing import Dict, Any, Optional, Tuple
import pandas as pd
from .broker_base import BrokerBase


class UpstoxBroker(BrokerBase):
    """
    Live broker using Upstox API v2.
    Orders are Delivery (D) by default, or Intraday (I) if specified.
    """
    BASE_URL = "https://api.upstox.com/v2"
    INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

    def __init__(self, access_token: Optional[str] = None):
        self._access_token = access_token or os.getenv("UPSTOX_ACCESS_TOKEN", "")
        self.instruments = {}
        self.ssl_context = ssl._create_unverified_context()
        self._connected = bool(self._access_token)
        if self._connected:
            self._load_instruments()

    def _load_instruments(self):
        """Lazy load instrument keys from Upstox assets."""
        try:
            req = urllib.request.Request(self.INSTRUMENTS_URL, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=self.ssl_context) as response:
                with gzip.GzipFile(fileobj=BytesIO(response.read())) as f:
                    df = pd.read_csv(f)
            if 'tradingsymbol' in df.columns and 'instrument_key' in df.columns:
                self.instruments = dict(zip(df['tradingsymbol'], df['instrument_key']))
                print(f"[UpstoxBroker] Loaded {len(self.instruments)} instruments.")
        except Exception as e:
            print(f"[UpstoxBroker] Failed to load Upstox instruments: {e}")

    def _get_instrument_key(self, ticker: str) -> str:
        clean_ticker = ticker.split('.')[0].upper()
        if clean_ticker in self.instruments:
            return self.instruments[clean_ticker]
        elif f"{clean_ticker}-EQ" in self.instruments:
            return self.instruments[f"{clean_ticker}-EQ"]
        return f"NSE_EQ|{clean_ticker}" # Fallback guess format

    @property
    def name(self) -> str:
        return "Upstox"

    @property
    def is_live(self) -> bool:
        return True

    def normalize_quantity(self, symbol: str, qty: float) -> float:
        return float(int(round(float(qty))))

    def _place_order(
        self,
        symbol: str,
        qty: int,
        transaction_type: str,
        order_type: str = "MARKET",
        product: str = "D"
    ) -> Tuple[bool, str, Optional[str]]:
        # Ironclad safety lock: prevent real-money execution unless explicitly enabled in .env
        live_enabled = os.getenv("ENABLE_LIVE_REAL_MONEY_TRADING", "false").lower() == "true"
        if not live_enabled:
            msg = "[SAFETY LOCK] Real money trading is disabled (ENABLE_LIVE_REAL_MONEY_TRADING != true). Order blocked."
            print(f"[UpstoxBroker] {msg}")
            return False, msg, None

        if not self._connected:
            return False, "Upstox not connected. Missing token.", None
            
        instrument_key = self._get_instrument_key(symbol)

        
        payload = {
            "quantity": qty,
            "product": product,
            "validity": "DAY",
            "price": 0,
            "tag": "ai_stock_analyst",
            "instrument_token": instrument_key,
            "order_type": order_type,
            "transaction_type": transaction_type,
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False
        }
        
        url = f"{self.BASE_URL}/order/place"
        data_encoded = json.dumps(payload).encode('utf-8')
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self._access_token}'
        }
        req = urllib.request.Request(url, data=data_encoded, headers=headers, method='POST')
        
        try:
            with urllib.request.urlopen(req, context=self.ssl_context) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                if res_data.get('status') == 'success':
                    order_id = res_data['data']['order_id']
                    msg = f"[UPSTOX] {transaction_type} {qty} {symbol} placed. ID={order_id}"
                    print(msg)
                    return True, msg, str(order_id)
                else:
                    return False, f"[UPSTOX] Order Failed: {res_data}", None
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            msg = f"[UPSTOX] HTTP Error {e.code}: {error_body}"
            print(msg)
            return False, msg, None
        except Exception as e:
            msg = f"[UPSTOX] Connection error: {e}"
            print(msg)
            return False, msg, None

    def buy(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "BUY", order_type, product="D")

    def sell(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "SELL", order_type, product="D")

    def short(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "SELL", order_type, product="I")

    def cover(self, symbol, qty, price, order_type="MARKET"):
        return self._place_order(symbol, qty, "BUY", order_type, product="I")

    def get_account_info(self) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "Not connected"}
            
        url = f"{self.BASE_URL}/user/get-funds-and-margin"
        req = urllib.request.Request(url, headers={
            'Accept': 'application/json',
            'Authorization': f'Bearer {self._access_token}'
        })
        
        try:
            with urllib.request.urlopen(req, context=self.ssl_context) as response:
                data = json.loads(response.read().decode('utf-8'))
                if data.get('status') == 'success':
                    equity = data['data']['equity']
                    return {
                        "available_cash": equity.get("available_margin", 0),
                        "used_margin": equity.get("used_margin", 0),
                        "broker": "Upstox",
                    }
                return {"error": str(data)}
        except Exception as e:
            return {"error": str(e)}
