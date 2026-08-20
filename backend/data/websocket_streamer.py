import asyncio
import json
import time
import logging
from typing import Dict, Any, Optional

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger('uvicorn.error')

SYMBOL_MAP = {
    'BTC-USD': 'btcusdt',
    'ETH-USD': 'ethusdt',
    'SOL-USD': 'solusdt',
    'BNB-USD': 'bnbusdt',
}

REVERSE_MAP = {v: k for k, v in SYMBOL_MAP.items()}


class CryptoWebSocketStreamer:
    _instance = None

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        self._last_heartbeat: float = 0.0

    @classmethod
    def get_instance(cls) -> 'CryptoWebSocketStreamer':
        if cls._instance is None:
            cls._instance = CryptoWebSocketStreamer()
        return cls._instance

    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        sym_key = symbol.upper()
        cached = self._cache.get(sym_key)
        if cached:
            if time.time() - cached.get('timestamp', 0) < 60.0:
                return cached
        return None

    def update_tick(self, symbol: str, tick: Dict[str, Any]):
        self._cache[symbol.upper()] = tick

    async def start(self):
        if self._is_running or not AIOHTTP_AVAILABLE:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._stream_loop())
        logger.info('[CryptoWebSocketStreamer] Background WebSocket listener started.')

    async def stop(self):
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info('[CryptoWebSocketStreamer] Stopped.')

    async def _stream_loop(self):
        streams = '/'.join([f'{v}@ticker' for v in SYMBOL_MAP.values()])
        url = f'wss://stream.binance.com:9443/ws/{streams}'

        while self._is_running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, heartbeat=20.0, timeout=15.0) as ws:
                        logger.info('[CryptoWebSocketStreamer] Connected to Binance live WebSocket feed.')
                        async for msg in ws:
                            if not self._is_running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                    stream_sym = data.get('s', '').lower()
                                    app_sym = REVERSE_MAP.get(stream_sym)
                                    if app_sym:
                                        cur_p = float(data.get('c', 0.0))
                                        high_p = float(data.get('h', cur_p))
                                        low_p = float(data.get('l', cur_p))
                                        open_p = float(data.get('o', cur_p))
                                        vol = float(data.get('v', 0.0))
                                        bid_p = float(data.get('b', cur_p))
                                        ask_p = float(data.get('a', cur_p))

                                        self._cache[app_sym] = {
                                            'symbol': app_sym,
                                            'price': cur_p,
                                            'high': high_p,
                                            'low': low_p,
                                            'open': open_p,
                                            'volume': vol,
                                            'bid': bid_p,
                                            'ask': ask_p,
                                            'timestamp': time.time(),
                                            'data_source': 'Binance WebSocket (Live 0-Delay)',
                                        }
                                        self._last_heartbeat = time.time()
                                except Exception:
                                    pass
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f'[CryptoWebSocketStreamer] WebSocket reconnecting in 5s: {e}')
                await asyncio.sleep(5)
