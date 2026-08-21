from typing import Dict, Any, List
from .base_agent import BaseAgent
from .committee import TechnicalAgent, FundamentalAgent, SentimentAgent, MacroAgent, RiskAgent, VolatilityAgent, LiquidityAgent, CorrelationAgent, IndianInstitutionalFlowAgent

class MasterAgent(BaseAgent):
    """
    The Master AI Decision Engine.
    It orchestrates the entire committee, collects their votes,
    and formulates a singular, high-conviction decision.
    """
    def __init__(self):
        super().__init__("Master AI Decision Engine")
        self.committee: List[BaseAgent] = [
            TechnicalAgent(),
            FundamentalAgent(),
            SentimentAgent(),
            MacroAgent(),
            VolatilityAgent(),
            LiquidityAgent(),
            CorrelationAgent()
        ]
        self.risk_manager = RiskAgent()
        
        # Track 20 bars of price history for correlation gate dynamically
        self._price_history = {}
        
        # Base thresholds by regime — calibrated for 5 effective agents
        # (SentimentAgent and CorrelationAgent are zeroed in routes.py).
        # total_weight_sum = 5.0.
        #
        # Previous thresholds (0.45/0.52/0.48/0.56) were too strict in practice:
        # • For crypto/tech, FundamentalAgent COT data is NEUTRAL → only 4 agents vote.
        #   3 agreeing at avg 0.65 → buy_conv=0.39, missed even Trending Bull at 0.45.
        # • For US futures, 4 agents at avg 0.65 → 0.52, exactly at Sideways — never fires
        #   because `>` (strict) is used, not `>=`.
        # Calibrated thresholds to filter noise and enforce high-conviction agreement:
        # Requires at least 4 agents in solid agreement or 3 agents in very strong agreement.
        self.regime_thresholds = {
            "Trending Bull":  0.45,
            "Sideways":       0.52,
            "Trending Bear":  0.48,
            "High Volatility": 0.55,
        }
        self.load_hyperparams()

    def load_hyperparams(self):
        import os
        import json
        base_dir = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(base_dir, "data", "hyperparams.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    params = json.load(f)
                # Load thresholds
                for regime in self.regime_thresholds:
                    key = f"{regime.lower().replace(' ', '_')}_threshold"
                    if key in params:
                        self.regime_thresholds[regime] = params[key]
                print(f"[MasterAgent] Loaded optimized thresholds from hyperparams.json: {self.regime_thresholds}")
            except Exception as e:
                print(f"[MasterAgent] Error loading hyperparams.json: {e}")

    def _update_history_and_get_correlation(self, symbol: str, price: float) -> float:
        # Update price history
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        self._price_history[symbol].append(price)
        if len(self._price_history[symbol]) > 20:
            self._price_history[symbol].pop(0)
            
        # Determine the other symbol we want to correlate against
        if symbol == "MGC=F":
            other_symbol = "MNQ=F"
        elif symbol == "MNQ=F":
            other_symbol = "MGC=F"
        elif symbol in ("MES=F", "M2K=F"):
            other_symbol = "MNQ=F"    # broad equity index - correlate to NQ
        elif symbol == "MCL=F":
            other_symbol = "MGC=F"    # commodities - correlate to Gold
        elif symbol == "NIFTYBEES.NS":
            other_symbol = "RELIANCE.NS"
        elif symbol.endswith(".NS"):
            other_symbol = "NIFTYBEES.NS"
        # US Tech Stocks — correlate to AAPL as market bellwether
        elif symbol in ("AAPL", "MSFT"):
            other_symbol = "NVDA"
        elif symbol in ("NVDA", "TSLA", "AMZN", "META"):
            other_symbol = "AAPL"
        # Crypto — BTC as anchor
        elif symbol == "BTC-USD":
            other_symbol = "ETH-USD"
        elif symbol in ("ETH-USD", "SOL-USD", "BNB-USD"):
            other_symbol = "BTC-USD"
        # Forex — EURUSD as DXY proxy anchor
        elif symbol == "EURUSD=X":
            other_symbol = "GBPUSD=X"
        elif symbol in ("GBPUSD=X", "AUDUSD=X"):
            other_symbol = "EURUSD=X"
        elif symbol == "USDJPY=X":
            other_symbol = "EURUSD=X"
        else:
            other_symbol = "MGC=F"    # safe fallback within US market
            
        hist_a = self._price_history.get(symbol, [])
        hist_b = self._price_history.get(other_symbol, [])
        
        if len(hist_a) == 20 and len(hist_b) == 20:
            import numpy as np
            # Convert prices to returns
            ret_a = np.diff(hist_a) / hist_a[:-1]
            ret_b = np.diff(hist_b) / hist_b[:-1]
            # Standard deviation check to prevent division by zero
            if np.std(ret_a) == 0 or np.std(ret_b) == 0:
                return 0.0
            return float(np.corrcoef(ret_a, ret_b)[0, 1])
            
        return 0.0

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        results = []
        buy_weight = 0.0
        sell_weight = 0.0
        
        # 1. Collect votes from the committee
        agent_weights = data.get("agent_weights", {})
        
        for agent in self.committee:
            vote = agent.evaluate(symbol, data)
            weight = agent_weights.get(agent.name, 1.0)
            
            # Compute contribution: BUY is +, SELL is -, WAIT is 0
            sig_val = 1.0 if vote["signal"] == "BUY" else -1.0 if vote["signal"] == "SELL" else 0.0
            contribution = round(sig_val * vote["confidence"] * weight, 3)
            
            results.append({
                "agent": agent.name,
                "signal": vote["signal"],
                "confidence": vote["confidence"],
                "reason": vote["reason"],
                "weight": round(weight, 3),
                "contribution": contribution
            })
            
            if vote["signal"] == "BUY":
                buy_weight += vote["confidence"] * weight
            elif vote["signal"] == "SELL":
                sell_weight += vote["confidence"] * weight

        total_weight_sum = sum(agent_weights.get(agent.name, 1.0) for agent in self.committee)
        if total_weight_sum <= 0:
            total_weight_sum = len(self.committee)
            
        buy_conviction = buy_weight / total_weight_sum
        sell_conviction = sell_weight / total_weight_sum
        
        # 2. Adaptive Confidence Thresholds
        regime = data.get("regime", "Sideways")
        mode = data.get("trading_mode", "Normal") # Safe, Normal, Aggressive
        
        # Base thresholds by regime
        thresholds = self.regime_thresholds
        base_threshold = thresholds.get(regime, 0.55)
        
        # Adjust by mode
        if mode == "Safe":
            base_threshold += 0.07
        elif mode == "Aggressive":
            # Drastically reduced threshold for testing weak signals
            base_threshold -= 0.70
        # Floor raised 0.35 → 0.42 to prevent low-conviction noise churn
        base_threshold = max(base_threshold, 0.42)

        # Adjust by High-Level Macro Regime
        macro_regime = data.get("macro_regime", "Risk-On")
        if macro_regime == "Risk-Off" and symbol == "MNQ=F":
            # Require higher confidence to long NQ in Risk-Off
            base_threshold += 0.10
        elif macro_regime == "Stagflation" and symbol == "MNQ=F":
            # Very hostile for NQ
            base_threshold += 0.15
        elif macro_regime == "Dislocation/Panic":
            # Hostile for almost all longs except extreme oversold
            base_threshold += 0.20
            
        final_signal = "WAIT"
        # WAIT confidence = max committee conviction so the log shows meaningful %
        final_confidence = max(buy_conviction, sell_conviction)
        reason = "Lack of strong agreement among AI agents."
        recommendation = "Wait for better setup."

        # 3. Formulate preliminary decision
        if buy_conviction > base_threshold and buy_conviction > sell_conviction:
            final_signal = "BUY"
            final_confidence = buy_conviction
        elif sell_conviction > base_threshold and sell_conviction > buy_conviction:
            final_signal = "SELL"
            final_confidence = sell_conviction
        else:
            # AI Coach Diagnostics for WAIT
            if buy_conviction > 0.5:
                reason = "Bullish momentum detected, but confidence is below the strict threshold."
                recommendation = f"Wait for a confirmed breakout or volume spike to push confidence past {base_threshold*100:.1f}%."
            elif sell_conviction > 0.5:
                reason = "Bearish pressure detected, but lacking full committee consensus."
                recommendation = "Monitor support levels. If broken with high volume, consider shorting."
            else:
                reason = "The market is currently range-bound with low momentum."
                recommendation = "Avoid trading in chop. Wait for a clear trend to establish."
            
        # 4. Consult Risk Manager before finalizing
        if final_signal != "WAIT":
            risk_vote = self.risk_manager.evaluate(symbol, data)
            if risk_vote["signal"] == "VETO":
                return {
                    "signal": "WAIT",
                    "confidence": final_confidence,
                    "reason": f"Trade vetoed by Risk Manager: {risk_vote['reason']}",
                    "recommendation": "Capital preservation active. Wait for risk conditions to improve.",
                    "committee_breakdown": results
                }
            reason = f"Committee consensus reached with {final_confidence*100:.1f}% confidence."
            recommendation = "Execute trade according to dynamic position sizing."


        # 4.1. Sniper Rule: Regime-Adaptive Directional Filter
        if final_signal == "BUY" and regime == "Trending Bear":
            return {
                "signal": "WAIT",
                "confidence": final_confidence,
                "reason": "Regime VETO: Long entries blocked during Trending Bear regime (Sniper Rule: Never buy into downtrend).",
                "recommendation": "Wait for trend reversal or short setup.",
                "committee_breakdown": results
            }
        elif final_signal == "SELL" and regime == "Trending Bull":
            return {
                "signal": "WAIT",
                "confidence": final_confidence,
                "reason": "Regime VETO: Short entries blocked during Trending Bull regime (Sniper Rule: Never short a strong uptrend).",
                "recommendation": "Wait for trend pullback or long setup.",
                "committee_breakdown": results
            }
        elif regime == "High Volatility" and mode != "Aggressive" and final_signal != "WAIT":
            if final_confidence < 0.70:
                return {
                    "signal": "WAIT",
                    "confidence": final_confidence,
                    "reason": f"Regime VETO: High Volatility Shock requires >= 70% conviction (got {final_confidence*100:.1f}%). Cash is preferred.",
                    "recommendation": "Protect capital in high volatility noise.",
                    "committee_breakdown": results
                }

        # 4.2 Real-Time News Headline Sentiment Veto
        if final_signal == "BUY" and mode != "Aggressive":
            try:
                from data.news_sentiment_scanner import NewsSentimentScanner
                is_news_veto, news_score, news_reason = NewsSentimentScanner.instance().check_news_veto(symbol)
                if is_news_veto:
                    return {
                        "signal": "WAIT",
                        "confidence": final_confidence,
                        "reason": f"News Sentiment VETO: {news_reason} (Score: {news_score:+.2f})",
                        "recommendation": "Capital preservation active. High-risk adverse breaking news in progress.",
                        "committee_breakdown": results
                    }
            except Exception:
                pass

        # 5. Correlation Gate

        correlation = self._update_history_and_get_correlation(symbol, data.get("price", 0))
        active_holdings = data.get("active_holdings", [])
        
        if final_signal != "WAIT":
            if symbol == "MGC=F":
                other_symbol = "MNQ=F"
            elif symbol == "MNQ=F":
                other_symbol = "MGC=F"
            elif symbol in ("MES=F", "M2K=F"):
                other_symbol = "MNQ=F"
            elif symbol == "MCL=F":
                other_symbol = "MGC=F"
            elif symbol == "NIFTYBEES.NS":
                other_symbol = "RELIANCE.NS"
            elif symbol.endswith(".NS"):
                other_symbol = "NIFTYBEES.NS"
            elif symbol in ("AAPL", "MSFT"):
                other_symbol = "NVDA"
            elif symbol in ("NVDA", "TSLA", "AMZN", "META"):
                other_symbol = "AAPL"
            elif symbol == "BTC-USD":
                other_symbol = "ETH-USD"
            elif symbol in ("ETH-USD", "SOL-USD", "BNB-USD"):
                other_symbol = "BTC-USD"
            elif symbol == "EURUSD=X":
                other_symbol = "GBPUSD=X"
            elif symbol in ("GBPUSD=X", "AUDUSD=X"):
                other_symbol = "EURUSD=X"
            elif symbol == "USDJPY=X":
                other_symbol = "EURUSD=X"
            else:
                other_symbol = "MGC=F"
            
            # Check for Inverse Correlation Block
            if correlation < -0.4 and any(h.get("symbol") == other_symbol for h in active_holdings):
                return {
                    "signal": "WAIT",
                    "confidence": final_confidence,
                    "reason": f"Correlation Gate VETO: {symbol}/{other_symbol} correlation is {correlation:.2f}. Holding {other_symbol} while taking new position is structurally opposed.",
                    "recommendation": "Wait for correlation regime to neutralize.",
                    "committee_breakdown": results
                }

            # Check for High Positive Correlation Block (Doubling Risk)
            if correlation > 0.8 and any(h.get("symbol") == other_symbol for h in active_holdings):
                return {
                    "signal": "WAIT",
                    "confidence": final_confidence,
                    "reason": f"Correlation Gate VETO: Extreme positive correlation ({correlation:.2f}). Taking this trade doubles portfolio risk without diversification benefit.",
                    "recommendation": "Maintain existing position. Wait for correlation to drop below 0.8.",
                    "committee_breakdown": results
                }

            # Not holding the other, but if fractured macro regime, reduce confidence
            if correlation < -0.4 and not any(h.get("symbol") == other_symbol for h in active_holdings):
                final_confidence = max(0.1, final_confidence - 0.25)
                reason += f" (Note: Fractured macro regime, GC/NQ correlation is {correlation:.2f})"
        
        return {
            "signal": final_signal,
            "confidence": round(final_confidence, 2),
            "buy_conviction": round(buy_conviction, 3),
            "sell_conviction": round(sell_conviction, 3),
            "threshold": round(base_threshold, 3),
            "reason": reason,
            "recommendation": recommendation,
            "committee_breakdown": results,
            "regime": data.get("regime", "Sideways"),
            "correlation": round(correlation, 4)
        }


class IndianMasterAgent(MasterAgent):
    """
    Indian Market Master Agent -- extends MasterAgent with India-specific
    committee (adds IndianInstitutionalFlowAgent) and lower regime thresholds
    calibrated for the 8-agent committee structure.
    """
    def __init__(self):
        super().__init__()
        from .committee import IndianInstitutionalFlowAgent
        from .gemini_agent import IndianGeminiAgent
        self.committee.append(IndianInstitutionalFlowAgent())
        self.committee.append(IndianGeminiAgent())
        # Thresholds calibrated for 6 effective agents after zeroing Sentiment
        # and Correlation. total_weight_sum = 6.0.
        self.regime_thresholds = {
            "Trending Bull":  0.42,
            "Sideways":       0.48,
            "Trending Bear":  0.45,
            "High Volatility": 0.52,
        }
