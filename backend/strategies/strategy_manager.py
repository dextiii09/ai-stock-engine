from typing import Dict, Any, List
from data.regime_detector import MarketRegimeDetector

# ─────────────────────────────────────────────
# 20+ Strategy Library
# Each strategy is mapped to one or more market regimes.
# In production, each strategy would be a full signal-generation function.
# ─────────────────────────────────────────────
STRATEGY_LIBRARY = {
    "Trending Bull": [
        {"id": "trend_follow_ema",    "name": "EMA Trend Following",         "timeframe": "1H",  "leverage": 1.0},
        {"id": "momentum_breakout",   "name": "Momentum Breakout",           "timeframe": "4H",  "leverage": 1.5},
        {"id": "smc_displacement",    "name": "SMC Displacement Entry",      "timeframe": "15m", "leverage": 1.0},
        {"id": "vwap_pullback",       "name": "VWAP Pullback Long",          "timeframe": "5m",  "leverage": 1.0},
        {"id": "fib_extension",       "name": "Fibonacci Extension Target",  "timeframe": "Daily", "leverage": 1.0},
    ],
    "Trending Bear": [
        {"id": "short_ema_cross",     "name": "EMA Bearish Cross Short",     "timeframe": "1H",  "leverage": 1.0},
        {"id": "supply_zone_short",   "name": "Supply Zone Reversal",        "timeframe": "4H",  "leverage": 1.0},
        {"id": "put_flow_follow",     "name": "Options Put Flow Following",  "timeframe": "Daily","leverage": 1.0},
    ],
    "Range Bound": [
        {"id": "mean_reversion",      "name": "Mean Reversion (Bollinger)",  "timeframe": "1H",  "leverage": 1.0},
        {"id": "rsi_overextended",    "name": "RSI Overbought/Oversold",     "timeframe": "30m", "leverage": 1.0},
        {"id": "range_scalp",         "name": "Support/Resistance Scalp",   "timeframe": "5m",  "leverage": 1.0},
    ],
    "High Volatility": [
        {"id": "vol_breakout",        "name": "Volatility Breakout (ATR)",   "timeframe": "15m", "leverage": 0.5},
        {"id": "news_spike_fade",     "name": "News Spike Fade",             "timeframe": "5m",  "leverage": 0.5},
        {"id": "iv_crush_play",       "name": "IV Crush Options Play",       "timeframe": "Daily","leverage": 1.0},
    ],
    "Low Volatility": [
        {"id": "theta_decay",         "name": "Options Theta Decay Play",    "timeframe": "Daily","leverage": 1.0},
        {"id": "tight_range_ping",    "name": "Tight Range Ping-Pong",       "timeframe": "1H",  "leverage": 1.0},
    ],
    "News Event": [
        {"id": "news_momentum",       "name": "Post-News Momentum Ride",     "timeframe": "5m",  "leverage": 0.75},
        {"id": "sentiment_reversal",  "name": "Sentiment Exhaustion Reversal","timeframe": "15m","leverage": 0.5},
    ],
    "Earnings Week": [
        {"id": "earnings_straddle",   "name": "Pre-Earnings Straddle",       "timeframe": "Daily","leverage": 1.0},
        {"id": "post_earnings_gap",   "name": "Post-Earnings Gap Fill",      "timeframe": "1H",  "leverage": 0.75},
    ],
    "Holiday Session": [],  # No trading in low-liquidity windows
}


class DynamicStrategyManager:
    """
    Feature 3: Dynamically selects the optimal strategy from 20+ 
    options based on the current Market Regime.
    """
    def __init__(self):
        self.regime_detector = MarketRegimeDetector()
        self.active_strategy = None
        self.current_regime = None
        
        # Strategy Competition Tracker
        # Initialize virtual PnLs for all strategies
        self.strategy_performance = {}
        for regime, strats in STRATEGY_LIBRARY.items():
            for strat in strats:
                self.strategy_performance[strat["id"]] = 0.0

    def select_strategy(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detects the current regime, runs competition tracking, and picks the best-fit strategy.
        """
        regime = self.regime_detector.detect(symbol, data)
        self.current_regime = regime

        candidates = STRATEGY_LIBRARY.get(regime, [])

        # Indian symbols (.NS) don't have US options flow/IV data — remove options-dependent strategies
        if symbol.endswith(".NS"):
            _INDIA_OPTIONS_BLACKLIST = {"put_flow_follow", "iv_crush_play", "theta_decay", "earnings_straddle"}
            candidates = [s for s in candidates if s["id"] not in _INDIA_OPTIONS_BLACKLIST]

        if not candidates:
            self.active_strategy = None
            return {
                "regime": regime,
                "strategy": None,
                "reason": f"No strategies available for '{regime}' on {symbol}. Sitting out."
            }

        # Pick the strategy with the highest virtual PnL in the current regime
        # (updated via record_outcome() after each closed trade)
        best_strategy = max(candidates, key=lambda s: self.strategy_performance[s["id"]])
        self.active_strategy = best_strategy

        # Format competition stats for AI Coach / UI
        competition_stats = []
        for strat in candidates:
            competition_stats.append({
                "name": strat["name"],
                "pnl": round(self.strategy_performance[strat["id"]], 2)
            })

        return {
            "regime": regime,
            "strategy": best_strategy,
            "available_count": len(candidates),
            "competition": competition_stats,
            "reason": f"Regime '{regime}' → Selected '{best_strategy['name']}' (Leader: {self.strategy_performance[best_strategy['id']]:+.2f}%)"
        }

    def record_outcome(self, strategy_id: str, pnl: float) -> None:
        """
        Update the virtual PnL for a strategy after a closed trade.
        Call this from the execution engine with the realized P&L so the
        competition reflects actual performance rather than remaining at 0.0.
        """
        if strategy_id in self.strategy_performance:
            self.strategy_performance[strategy_id] += pnl

    def get_all_strategies(self) -> Dict[str, Any]:
        """Returns the full strategy library for UI display."""
        total = sum(len(v) for v in STRATEGY_LIBRARY.values())
        return {
            "total": total,
            "by_regime": STRATEGY_LIBRARY,
            "active_regime": self.current_regime,
            "active_strategy": self.active_strategy
        }
