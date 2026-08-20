"""
Adaptive Stop Loss Engine.
Supports both fixed ATR-based stops and trailing ATR stops that
move with price to lock in profits as trades go in favour.
"""
from typing import Dict, Any

# Multipliers for Asymmetric 2-Stage Scale-Out Engine
STOP_ATR_MULT   = 2.5   # How many ATRs below price to place the initial stop
TRAIL_ATR_MULT  = 2.5   # How many ATRs to trail behind the best price seen
TP1_RISK_REWARD = 1.5   # 1st Target (1.5R): Scale out 50% & move SL to Breakeven
TP2_RISK_REWARD = 3.0   # 2nd Target (3.0R): Final target / trailing runner
TP_RISK_REWARD  = 3.0   # Take-profit for backward compatibility

# Minimum stop distance as a fraction of price (0.5% floor to clear trading fees & slippage)
MIN_STOP_PCT    = 0.005

# Regime-specific multiplier profiles for 2-stage execution
REGIME_STOP_CONFIG: Dict[str, Dict[str, float]] = {
    "Trending Bull":   {"stop_mult": 2.5, "trail_mult": 2.8, "tp1_rr": 1.5, "tp2_rr": 3.5, "ratchet_thresh": 0.8},
    "Trending Bear":   {"stop_mult": 2.5, "trail_mult": 2.8, "tp1_rr": 1.5, "tp2_rr": 3.5, "ratchet_thresh": 0.8},
    "Sideways":        {"stop_mult": 2.0, "trail_mult": 1.8, "tp1_rr": 1.2, "tp2_rr": 2.0, "ratchet_thresh": 0.6},
    "High Volatility": {"stop_mult": 2.2, "trail_mult": 1.6, "tp1_rr": 1.2, "tp2_rr": 2.0, "ratchet_thresh": 0.5},
}
_DEFAULT_CONFIG = {
    "stop_mult": STOP_ATR_MULT,
    "trail_mult": TRAIL_ATR_MULT,
    "tp1_rr": TP1_RISK_REWARD,
    "tp2_rr": TP2_RISK_REWARD,
    "ratchet_thresh": 0.8,
}


class AdaptiveStopLoss:
    """
    Calculates dynamic stop-losses and asymmetric 2-stage take-profit targets
    using volatility (ATR proxy) and HMM market regimes.
    """

    def calculate(self, current_price: float, signal: str,
                  volatility_proxy: float = 0.02,
                  regime: str = None) -> Dict[str, Any]:
        """
        Returns initial stop_loss and 2-stage take_profit targets (TP1=1.5R, TP2=3.0R)
        for a new trade, modulating distances based on market regime.
        """
        cfg = REGIME_STOP_CONFIG.get(regime, _DEFAULT_CONFIG)
        stop_mult = cfg["stop_mult"]
        tp1_rr    = cfg.get("tp1_rr", TP1_RISK_REWARD)
        tp2_rr    = cfg.get("tp2_rr", TP2_RISK_REWARD)

        distance = current_price * max(volatility_proxy * stop_mult, MIN_STOP_PCT)

        if signal == "BUY":
            stop_loss          = current_price - distance
            tp1_target         = current_price + (distance * tp1_rr)
            tp2_target         = current_price + (distance * tp2_rr)
            breakeven_trigger  = current_price + (distance * 1.0)
        else:
            stop_loss          = current_price + distance
            tp1_target         = current_price - (distance * tp1_rr)
            tp2_target         = current_price - (distance * tp2_rr)
            breakeven_trigger  = current_price - (distance * 1.0)

        return {
            "stop_loss":          round(stop_loss, 4),
            "take_profit":        round(tp2_target, 4),
            "tp1_target":         round(tp1_target, 4),
            "tp2_target":         round(tp2_target, 4),
            "breakeven_trigger":  round(breakeven_trigger, 4),
            "atr_distance":       round(distance, 4),
            "regime_used":        regime or "Default",
        }

    def update_trailing(self, current_price: float, signal: str,
                        current_stop: float,
                        best_price: float,
                        volatility_proxy: float = 0.02,
                        entry_price: float = None,
                        regime: str = None,
                        tp1_hit: bool = False) -> Dict[str, Any]:
        """
        Advances a trailing stop when price moves favourably and ratchets
        to breakeven once price moves into profit or TP1 is reached.
        """
        cfg = REGIME_STOP_CONFIG.get(regime, _DEFAULT_CONFIG)
        trail_mult     = cfg["trail_mult"]
        ratchet_thresh = cfg["ratchet_thresh"]

        _trail_frac = max(volatility_proxy * trail_mult, MIN_STOP_PCT)
        if signal == "BUY":
            best_price = max(best_price, current_price)
            proposed   = best_price - (best_price * _trail_frac)
            if entry_price is not None and entry_price > 0:
                # If TP1 was hit or price passed ratchet threshold, guarantee Breakeven stop floor
                if tp1_hit or best_price >= entry_price + (entry_price * _trail_frac * ratchet_thresh):
                    proposed = max(proposed, entry_price)
            new_stop = max(current_stop, proposed)   # Only move stop UP
        else:
            best_price = min(best_price, current_price)
            proposed   = best_price + (best_price * _trail_frac)
            if entry_price is not None and entry_price > 0:
                if tp1_hit or best_price <= entry_price - (entry_price * _trail_frac * ratchet_thresh):
                    proposed = min(proposed, entry_price)
            new_stop = min(current_stop, proposed)   # Only move stop DOWN

        trail_distance = best_price * _trail_frac
        stop_moved = abs(new_stop - current_stop) > 0.0001

        return {
            "new_stop":       round(new_stop, 4),
            "best_price":     round(best_price, 4),
            "stop_moved":     stop_moved,
            "trail_distance": round(trail_distance, 4),
            "regime_used":    regime or "Default",
        }

    def is_stop_hit(self, current_price: float, signal: str,
                    stop_loss: float) -> bool:
        """Returns True when price has crossed the stop level."""
        if signal == "BUY":
            return current_price <= stop_loss
        return current_price >= stop_loss

    def is_tp1_hit(self, current_price: float, signal: str,
                   tp1_target: float) -> bool:
        """Returns True when price reaches TP1 target (1.5R)."""
        if not tp1_target:
            return False
        if signal == "BUY":
            return current_price >= tp1_target
        return current_price <= tp1_target

    def is_tp2_hit(self, current_price: float, signal: str,
                   tp2_target: float) -> bool:
        """Returns True when price reaches TP2 target (3.0R+)."""
        if not tp2_target:
            return False
        if signal == "BUY":
            return current_price >= tp2_target
        return current_price <= tp2_target

