import os
import yfinance as yf
import pandas as pd
import time
import threading
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

class BaseDataProvider:
    def get_historical_ohlcv(self, symbol: str, period: str = "2d", interval: str = "1m") -> pd.DataFrame:
        raise NotImplementedError

class YFinanceDataProvider(BaseDataProvider):
    # Per-interval TTLs:
    #   1m  → 60s   (live trading ticks; 15 calls/min → 1 call/min per symbol)
    #   5m  → 120s
    #   1h  → 600s  (10 minutes; hourly bars don't change bar-by-bar)
    #   1d  → 3600s (1 hour; daily bars are stable all day)
    #   default → 300s
    _INTERVAL_TTL: Dict[str, float] = {
        "1m":  60.0,
        "2m":  90.0,
        "5m":  120.0,
        "15m": 180.0,
        "30m": 240.0,
        "60m": 600.0,
        "1h":  600.0,
        "90m": 300.0,
        "1d":  3600.0,
        "5d":  3600.0,
        "1wk": 7200.0,
        "1mo": 7200.0,
    }
    _STALE_FALLBACK_TTL = 600.0   # max age for emergency stale fallback (10 min)

    def __init__(self):
        # Cache key: (symbol, period, interval) → (DataFrame, fetch_timestamp)
        self._cache: Dict[Tuple[str, str, str], Tuple[pd.DataFrame, float]] = {}
        self._lock = threading.Lock()

    def _ttl_for(self, interval: str) -> float:
        return self._INTERVAL_TTL.get(interval, 300.0)

    def get_historical_ohlcv(self, symbol: str, period: str = "2d", interval: str = "1m") -> pd.DataFrame:
        cache_key = (symbol, period, interval)
        ttl       = self._ttl_for(interval)
        now       = time.time()

        # ── Read-through cache: serve fresh data without hitting the network ──
        with self._lock:
            if cache_key in self._cache:
                cached_df, cached_ts = self._cache[cache_key]
                if now - cached_ts < ttl:
                    return cached_df   # Cache HIT — skip yfinance entirely

        # ── Cache miss or expired — fetch from Yahoo Finance ─────────────────
        hist = None
        backoff = 1.0
        for attempt in range(3):
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period=period, interval=interval)
                if hist is not None and not hist.empty and not hist["Close"].isna().all():
                    break
            except Exception as e:
                print(f"[YFinanceDataProvider] Attempt {attempt+1} failed for {symbol} ({period}/{interval}): {e}")

            time.sleep(backoff)
            backoff *= 2.0

        with self._lock:
            if hist is not None and not hist.empty and not hist["Close"].isna().all():
                self._cache[cache_key] = (hist, time.time())
                return hist

            # ── Stale fallback: use expired cache if yfinance failed ──────────
            if cache_key in self._cache:
                stale_df, stale_ts = self._cache[cache_key]
                age = now - stale_ts
                if age <= self._STALE_FALLBACK_TTL:
                    print(f"[YFinanceDataProvider] WARNING: yfinance failed. Serving stale cache for "
                          f"{symbol} ({period}/{interval}), age {age:.0f}s.")
                    return stale_df
                else:
                    print(f"[YFinanceDataProvider] Cache EXPIRED for {symbol} ({period}/{interval}), "
                          f"age {age:.0f}s > {self._STALE_FALLBACK_TTL:.0f}s. Refusing stale data.")

        raise RuntimeError(
            f"Yahoo Finance returned no data for {symbol} ({period}/{interval}) "
            f"and cache is absent or expired."
        )


class DataProviderFactory:
    _instance = None
    _lock = threading.Lock()

    @staticmethod
    def get_provider() -> BaseDataProvider:
        with DataProviderFactory._lock:
            if DataProviderFactory._instance is None:
                DataProviderFactory._instance = YFinanceDataProvider()
            return DataProviderFactory._instance
