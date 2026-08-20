import time
from typing import Dict, Any, List

class ShadowTradingEngine:
    """
    Feature: Trade Simulation & Missed Opportunities Tracker
    Tracks trades that the AI *rejected* due to confidence thresholds.
    Evaluates them virtually over time to see if they would have won,
    providing data to the RL engine to adjust overly strict thresholds.
    """
    def __init__(self):
        self.shadow_portfolio: List[Dict[str, Any]] = []
        self.missed_opportunities: List[Dict[str, Any]] = []

    def record_rejected_trade(self, symbol: str, price: float, decision: Dict[str, Any]):
        """Records a trade that was evaluated but rejected."""
        # Only track trades with decent conviction (e.g. > 60% confidence but < threshold)
        if decision.get("confidence", 0) > 0.60:
            self.shadow_portfolio.append({
                "symbol": symbol,
                "entry_price": price,
                "signal": decision.get("signal", "WAIT"),
                "confidence": decision.get("confidence", 0),
                "timestamp": time.time(),
                "target_price": price * 1.05 if decision.get("signal") == "BUY" else price * 0.95,
                "stop_price": price * 0.98 if decision.get("signal") == "BUY" else price * 1.02,
                # Preserved for RL feedback on outcome
                "committee_breakdown": decision.get("committee_breakdown", {}),
                "regime": decision.get("regime", "Sideways"),
            })

    def evaluate_shadow_trades(self, symbol: str, current_price: float, rl_engine=None, regime: str = "Sideways"):
        """Called on every tick to evaluate the performance of shadow trades."""
        active_shadows = []
        
        for trade in self.shadow_portfolio:
            if trade["symbol"] != symbol:
                active_shadows.append(trade)
                continue
                
            elapsed_time = time.time() - trade["timestamp"]
            
            # Simulated 3-hour expiration (for fast demo purposes, 3 mins = 180s)
            if elapsed_time > 10800: # 3 hours
                continue
                
            win = False
            if trade["signal"] == "BUY" and current_price >= trade["target_price"]:
                win = True
            elif trade["signal"] == "SELL" and current_price <= trade["target_price"]:
                win = True
                
            loss = False
            if trade["signal"] == "BUY" and current_price <= trade["stop_price"]:
                loss = True
            elif trade["signal"] == "SELL" and current_price >= trade["stop_price"]:
                loss = True
                
            if win:
                pnl_pct = 5.0  # target hit
                self.missed_opportunities.append({
                    "symbol": symbol,
                    "signal": trade["signal"],
                    "confidence": round(trade["confidence"] * 100, 1),
                    "outcome": "Missed Profit",
                    "pnl_pct": pnl_pct,
                    "timestamp": time.time(),
                    "reason": "AI confidence threshold was too strict."
                })
                if len(self.missed_opportunities) > 200: self.missed_opportunities = self.missed_opportunities[-200:]
                # Feed dampened signal into RL so it learns from missed setups
                if rl_engine is not None:
                    rl_engine.process_shadow_outcome({
                        "pnl_pct": pnl_pct,
                        "action": trade["signal"],
                        "regime": trade.get("regime", regime),
                        "committee_breakdown": trade.get("committee_breakdown", {})
                    })
            elif loss:
                pnl_pct = -2.0  # stop hit
                self.missed_opportunities.append({
                    "symbol": symbol,
                    "signal": trade["signal"],
                    "confidence": round(trade["confidence"] * 100, 1),
                    "outcome": "Avoided Loss",
                    "pnl_pct": pnl_pct,
                    "timestamp": time.time(),
                    "reason": "AI correctly vetoed a losing setup."
                })
                if len(self.missed_opportunities) > 200: self.missed_opportunities = self.missed_opportunities[-200:]
                # Feed dampened signal into RL so it reinforces the veto correctly
                if rl_engine is not None:
                    rl_engine.process_shadow_outcome({
                        "pnl_pct": pnl_pct,
                        "action": trade["signal"],
                        "regime": trade.get("regime", regime),
                        "committee_breakdown": trade.get("committee_breakdown", {})
                    })
            else:
                active_shadows.append(trade)
                
        self.shadow_portfolio = active_shadows

    def get_missed_opportunities(self) -> List[Dict[str, Any]]:
        return self.missed_opportunities
