import time
import random
from typing import Dict, Any, List, Optional, Tuple


MAX_ALLOWED_SPREAD_PCT = 0.0020  # 0.20% (20 bps max tolerance)


def _get_price_precision(symbol: str) -> int:
    """
    Returns the required decimal precision for execution pricing based on asset class.
    - Forex pairs (e.g. EURUSD=X, GBPUSD=X): 5 decimal places for pip/fractional-pip precision.
    - Crypto & Futures (e.g. BTC-USD, MNQ=F): 4 decimal places.
    - Equities (e.g. SPY, NVDA, RELIANCE.NS): 2 decimal places.
    """
    sym = symbol.upper()
    if "=X" in sym or "/" in sym:
        return 5
    elif sym.endswith("=F") or sym.startswith("^") or sym.endswith("-USD"):
        return 4
    return 2


class SmartOrderRouter:
    """
    Feature 19: Broker Intelligence
    Implements TWAP, VWAP, Iceberg order execution strategies,
    and pre-trade Spread & Slippage safety guards.
    
    Strategies:
    - MARKET: Immediate full fill at current price
    - TWAP:   Time-Weighted Average Price — splits order into N time slices
    - VWAP:   Volume-Weighted Average Price — sizes slices by volume profile
    - ICEBERG: Shows only a small portion of the order at a time
    """

    def __init__(self, strategy: str = "VWAP", slices: int = 5):
        self.strategy = strategy
        self.slices = slices
        self.execution_log: List[Dict[str, Any]] = []

    def check_spread(self, bid: float, ask: float) -> Tuple[bool, float, str]:
        """
        Validates that the current market bid-ask spread is within tolerable limits.
        Returns (is_acceptable, spread_pct, message).
        """
        if bid <= 0 or ask <= 0 or ask < bid:
            return True, 0.0, "Spread not available or crossed; proceeding with default execution."
        mid = (bid + ask) / 2.0
        spread = ask - bid
        spread_pct = spread / mid
        if spread_pct > MAX_ALLOWED_SPREAD_PCT:
            return False, spread_pct, (
                f"Spread {spread_pct*100:.3f}% exceeds max threshold "
                f"{MAX_ALLOWED_SPREAD_PCT*100:.2f}% (illiquid/volatile orderbook)"
            )
        return True, spread_pct, f"Spread {spread_pct*100:.3f}% is within normal limit."

    def execute(self, symbol: str, total_shares: float, current_price: float, volume: int = 50000, direction: str = "LONG") -> Dict[str, Any]:
        """
        Routes an order through the selected execution strategy.
        Returns the fill summary with average fill price and slippage estimate.
        """
        if self.strategy == "MARKET":
            return self._market_order(symbol, total_shares, current_price, direction=direction)
        elif self.strategy == "TWAP":
            return self._twap_order(symbol, total_shares, current_price, direction=direction)
        elif self.strategy == "VWAP":
            return self._vwap_order(symbol, total_shares, current_price, volume, direction=direction)
        elif self.strategy == "ICEBERG":
            return self._iceberg_order(symbol, total_shares, current_price, direction=direction)
        else:
            return self._market_order(symbol, total_shares, current_price, direction=direction)

    def _market_order(self, symbol: str, shares: float, price: float, direction: str = "LONG") -> Dict[str, Any]:
        """Immediate fill — highest adverse slippage."""
        prec = _get_price_precision(symbol)
        slippage = price * random.uniform(0.0001, 0.001)
        # Adverse slippage: higher price when buying (LONG), lower price when selling short (SHORT)
        fill_price = round(price + slippage, prec) if direction == "LONG" else round(price - slippage, prec)
        return self._fill_summary("MARKET", symbol, shares, fill_price, price, [[shares, fill_price]], direction=direction)

    def _twap_order(self, symbol: str, shares: float, price: float, direction: str = "LONG") -> Dict[str, Any]:
        """
        Splits order into N equal time slices.
        Each slice simulates small random walk from market impact.
        """
        prec = _get_price_precision(symbol)
        slice_size = max(1.0 if isinstance(shares, int) else shares / self.slices, shares / self.slices)
        fills = []
        running_price = price

        for i in range(self.slices):
            remaining = shares - sum(f[0] for f in fills)
            this_slice = min(slice_size, remaining)
            if this_slice <= 0:
                break
            # Each slice gets adverse drift
            drift = running_price * random.uniform(0.00005, 0.0004)
            fill_px = round(running_price + drift, prec) if direction == "LONG" else round(running_price - drift, prec)
            fills.append([this_slice, fill_px])
            running_price = fill_px

        avg_fill = round(sum(f[0] * f[1] for f in fills) / max(shares, 1e-9), prec)
        return self._fill_summary("TWAP", symbol, shares, avg_fill, price, fills, direction=direction)

    def _vwap_order(self, symbol: str, shares: float, price: float, volume: int, direction: str = "LONG") -> Dict[str, Any]:
        """
        Sizes each slice proportional to a simulated intraday volume profile.
        Heaviest at market open and close (U-shaped volume curve).
        """
        prec = _get_price_precision(symbol)
        weights = [0.20, 0.12, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.12]
        fills = []
        running_price = price
        total_filled = 0.0

        for w in weights:
            slice_shares = (shares * w) if not isinstance(shares, int) else int(shares * w)
            if total_filled + slice_shares > shares:
                slice_shares = shares - total_filled
            if slice_shares <= 0:
                break
            # Volume-proportional adverse impact: less slippage in high-volume slices
            impact = price * random.uniform(0.00005, 0.00035) * (1.0 - w)
            fill_px = round(running_price + impact, prec) if direction == "LONG" else round(running_price - impact, prec)
            fills.append([slice_shares, fill_px])
            total_filled += slice_shares
            running_price = fill_px

        # Fill any remainder at last price
        remainder = shares - total_filled
        if remainder > 0:
            fills.append([remainder, running_price])

        avg_fill = round(sum(f[0] * f[1] for f in fills) / max(shares, 1e-9), prec)
        return self._fill_summary("VWAP", symbol, shares, avg_fill, price, fills, direction=direction)

    def _iceberg_order(self, symbol: str, shares: float, price: float, direction: str = "LONG") -> Dict[str, Any]:
        """
        Hides order size — shows only a small 'tip' (10% visible at a time).
        Reduces market impact for large orders.
        """
        prec = _get_price_precision(symbol)
        visible_size = max(1.0 if isinstance(shares, int) else shares / 10.0, shares / 10.0)
        fills = []
        remaining = shares
        running_price = price

        while remaining > 0:
            this_slice = min(visible_size, remaining)
            drift = running_price * random.uniform(0.00005, 0.0003)
            fill_px = round(running_price + drift, prec) if direction == "LONG" else round(running_price - drift, prec)
            fills.append([this_slice, fill_px])
            remaining -= this_slice
            running_price = fill_px

        avg_fill = round(sum(f[0] * f[1] for f in fills) / max(shares, 1e-9), prec)
        return self._fill_summary("ICEBERG", symbol, shares, avg_fill, price, fills, direction=direction)

    def _fill_summary(self, strategy: str, symbol: str, shares: float,
                      avg_fill: float, market_price: float, fills: List, direction: str = "LONG") -> Dict[str, Any]:
        prec = _get_price_precision(symbol)
        diff = (avg_fill - market_price) if direction == "LONG" else (market_price - avg_fill)
        slippage_bps = round(diff / max(market_price, 1e-9) * 10000, 2)
        total_cost = round(avg_fill * shares, 2 if prec == 2 else 4)

        summary = {
            "strategy": strategy,
            "symbol": symbol,
            "direction": direction,
            "total_shares": shares,
            "avg_fill_price": round(avg_fill, prec),
            "market_price_at_entry": market_price,
            "slippage_bps": slippage_bps,
            "total_cost": total_cost,
            "fill_count": len(fills),
            "fills": fills,
            "timestamp": time.time()
        }
        self.execution_log.append(summary)
        return summary
