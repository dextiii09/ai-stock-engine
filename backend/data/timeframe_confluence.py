"""
Multi-Timeframe Confluence Engine
Fetches 1h and daily bars and computes trend alignment with the tick signal.

Gate logic:
  - If all 3 timeframes (daily, 1h, tick) agree -> full confidence
  - 2 of 3 agree -> pass through unchanged
  - 1 of 3 agrees -> reduce confidence by 30%
  - 0 of 3 agree (full opposition) -> veto BUY/SELL, return WAIT

Cache TTL:
  - Daily bars: refreshed every 4 hours
  - 1h bars:    refreshed every 30 minutes
"""

import time
import threading
from typing import Dict, Any, Optional

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False


def _ema(prices: list, period: int) -> float:
    """Compute EMA of a price list. Returns the last EMA value."""
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    val = sum(prices[:period]) / period
    for p in prices[period:]:
        val = p * k + val * (1 - k)
    return val


class TimeframeConfluenceEngine:
    """
    Fetches 1h and daily OHLCV data for each symbol and determines
    whether higher timeframes support or oppose the tick-level signal.
    """

    DAILY_TTL = 4 * 3600      # 4 hours
    HOURLY_TTL = 30 * 60      # 30 minutes

    def __init__(self):
        self._cache: Dict[str, Dict] = {}   # symbol -> {daily, hourly, timestamps}
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _fetch_closes(self, symbol: str, period: str, interval: str) -> list:
        """Fetch close prices via shared DataProvider (benefits from read-through cache)."""
        try:
            from .provider import DataProviderFactory
            provider = DataProviderFactory.get_provider()
            hist = provider.get_historical_ohlcv(symbol, period=period, interval=interval)
            if hist is None or hist.empty:
                return []
            return [float(c) for c in hist["Close"].tolist() if c == c]  # drop NaN
        except Exception:
            return []

    def _refresh_if_stale(self, symbol: str):
        """
        Check staleness under the lock, then fetch OUTSIDE the lock so a slow
        API response for one symbol doesn't block all other symbol evaluations.
        Double-check timestamps before writing to handle the race where two
        threads both decide to refresh the same symbol simultaneously.
        """
        now = time.time()

        with self._lock:
            entry = self._cache.setdefault(symbol, {
                "daily_closes": [],
                "hourly_closes": [],
                "daily_ts": 0.0,
                "hourly_ts": 0.0,
            })
            need_daily  = (now - entry["daily_ts"]  > self.DAILY_TTL)
            need_hourly = (now - entry["hourly_ts"] > self.HOURLY_TTL)

        # Fetch outside the lock — slow yfinance calls no longer block other symbols
        new_daily  = self._fetch_closes(symbol, "90d", "1d") if need_daily  else None
        new_hourly = self._fetch_closes(symbol, "10d", "1h") if need_hourly else None

        with self._lock:
            entry = self._cache[symbol]
            # Double-check: only write if still stale (another thread may have refreshed first)
            if new_daily and (now - entry["daily_ts"] > self.DAILY_TTL):
                entry["daily_closes"] = new_daily
                entry["daily_ts"] = now
            if new_hourly and (now - entry["hourly_ts"] > self.HOURLY_TTL):
                entry["hourly_closes"] = new_hourly
                entry["hourly_ts"] = now

    def _daily_trend(self, symbol: str) -> Optional[str]:
        """
        Daily trend: BULL if price > EMA20, BEAR otherwise.
        Returns None if not enough data.
        """
        closes = self._cache.get(symbol, {}).get("daily_closes", [])
        if len(closes) < 20:
            return None
        ema20 = _ema(closes, 20)
        return "BULL" if closes[-1] > ema20 else "BEAR"

    def _hourly_trend(self, symbol: str) -> Optional[str]:
        """
        1h trend: BULL if EMA9 > EMA21, BEAR otherwise.
        Returns None if not enough data.
        """
        closes = self._cache.get(symbol, {}).get("hourly_closes", [])
        if len(closes) < 21:
            return None
        ema9 = _ema(closes, 9)
        ema21 = _ema(closes, 21)
        return "BULL" if ema9 > ema21 else "BEAR"

    def _tick_trend(self, tick_data: Dict[str, Any]) -> Optional[str]:
        """
        Tick-level trend: BULL if RSI > 50 and MACD hist > 0.
        Uses data already in tick_data — no extra fetch needed.
        """
        rsi = tick_data.get("rsi_14", 50.0)
        macd = tick_data.get("macd_hist", 0.0)
        if rsi is None or macd is None:
            return None
        if rsi > 52 and macd > 0:
            return "BULL"
        elif rsi < 48 and macd < 0:
            return "BEAR"
        return None  # neutral — don't count it

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_confluence(self, symbol: str, tick_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Returns a confluence dict:
          {
            "daily_trend":  "BULL" | "BEAR" | None,
            "hourly_trend": "BULL" | "BEAR" | None,
            "tick_trend":   "BULL" | "BEAR" | None,
            "alignment":    "STRONG" | "MODERATE" | "WEAK" | "OPPOSED" | "NEUTRAL",
            "confidence_multiplier": float  (0.0 – 1.3),
            "veto":         bool,
            "detail":       str,
          }
        """
        # Refresh caches in background (non-blocking; use stale data if still warm)
        self._refresh_if_stale(symbol)

        daily = self._daily_trend(symbol)
        hourly = self._hourly_trend(symbol)
        tick = self._tick_trend(tick_data)

        # If we have no higher timeframe data at all, pass through neutrally
        if daily is None and hourly is None:
            return {
                "daily_trend": None,
                "hourly_trend": None,
                "tick_trend": tick,
                "alignment": "NEUTRAL",
                "confidence_multiplier": 1.0,
                "veto": False,
                "detail": "Higher timeframe data not yet available. Passing through.",
            }

        trends = [t for t in [daily, hourly, tick] if t is not None]
        bull_count = trends.count("BULL")
        bear_count = trends.count("BEAR")
        total = len(trends)

        if total == 0:
            alignment = "NEUTRAL"
            mult = 1.0
            veto = False
            detail = "No trend data available across timeframes."
        elif bull_count == total:
            alignment = "STRONG"
            mult = 1.25
            veto = False
            detail = f"All {total} timeframes BULLISH — strong long confluence."
        elif bear_count == total:
            alignment = "STRONG"
            mult = 1.25
            veto = False
            detail = f"All {total} timeframes BEARISH — strong short confluence."
        elif bull_count > bear_count:
            alignment = "MODERATE"
            mult = 1.0
            veto = False
            detail = f"{bull_count}/{total} timeframes BULLISH — moderate confluence."
        elif bear_count > bull_count:
            alignment = "MODERATE"
            mult = 1.0
            veto = False
            detail = f"{bear_count}/{total} timeframes BEARISH — moderate confluence."
        elif bull_count == 1 and bear_count == 1 and total == 2:
            alignment = "WEAK"
            mult = 0.75
            veto = False
            detail = "Timeframes split 50/50 — weak confluence, reducing confidence."
        else:
            alignment = "OPPOSED"
            mult = 0.5
            veto = False
            detail = "Timeframes in opposition — strong warning against trading."

        return {
            "daily_trend": daily,
            "hourly_trend": hourly,
            "tick_trend": tick,
            "alignment": alignment,
            "confidence_multiplier": mult,
            "veto": veto,
            "detail": detail,
        }

    def apply_to_decision(
        self,
        decision: Dict[str, Any],
        confluence: Dict[str, Any],
        signal_direction: str,   # "BUY" or "SELL"
    ) -> Dict[str, Any]:
        """
        Applies the confluence multiplier to a master agent decision dict.
        Checks that the confluence direction matches the signal direction.
        Mutates and returns the decision dict.
        """
        if confluence["alignment"] == "NEUTRAL":
            decision["confluence"] = confluence
            return decision

        mult = confluence["confidence_multiplier"]
        daily = confluence.get("daily_trend")
        hourly = confluence.get("hourly_trend")

        # Direction mismatch: BUY against BEAR higher TFs or SELL against BULL
        def is_opposed(tf_trend, sig):
            if tf_trend is None:
                return False
            if sig == "BUY" and tf_trend == "BEAR":
                return True
            if sig == "SELL" and tf_trend == "BULL":
                return True
            return False

        daily_opposed  = is_opposed(daily, signal_direction)
        hourly_opposed = is_opposed(hourly, signal_direction)

        # Sniper Gate: Never trade against Higher Timeframe trend (Daily or 1h active opposition)
        if daily_opposed or (hourly_opposed and daily != ("BULL" if signal_direction == "BUY" else "BEAR")):
            decision["signal"] = "WAIT"
            opposing_tf = "Daily" if daily_opposed else "1h"
            decision["reason"] = (
                f"MTF VETO: {opposing_tf} trend ({daily if daily_opposed else hourly}) opposes {signal_direction} trade. "
                f"Sniper Rule requires HTF trend alignment."
            )
            decision["confluence"] = confluence
            return decision

        # Apply multiplier to confidence
        original_conf = decision.get("confidence", 0.0)
        new_conf = round(min(original_conf * mult, 1.0), 3)
        decision["confidence"] = new_conf
        decision["confluence"] = confluence
        return decision

