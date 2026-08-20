from typing import Dict, Any

class ProbabilityEngine:
    """
    Augments every MasterAgent decision with a rich probability profile.
    Instead of just "BUY", returns:
      - Chance of Success (%)
      - Chance of Stop Loss (%)
      - Expected Profit (%)
      - Expected Loss (%)
      - Expected Holding Time
      - Uncertainty Score
      - Risk Score
      - Volatility Score
    """

    def enrich(self, decision: Dict[str, Any], tick_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes a raw MasterAgent decision and enriches it with probability estimates.
        """
        confidence = decision.get("confidence", 0.5)
        signal = decision.get("signal", "WAIT")

        if signal == "WAIT":
            return {**decision, "probability_profile": None}

        # Win probability based on confidence + regime alignment
        win_prob = confidence * 100

        # Expected profit/loss using 1:2 risk:reward ratio
        atr_14 = tick_data.get("atr_14", 0.0) or 0.0
        price = max(tick_data.get("price", 1.0), 1.0)
        volatility = min(float(atr_14) / price, 0.05) / 0.05  # normalize ATR% to 0-1 range (5% ATR = max)
        volatility = max(0.1, min(1.0, volatility))  # clamp to reasonable range
        expected_profit_pct = round(confidence * 2.6, 2)
        expected_loss_pct = round((1 - confidence) * 0.9, 2)

        # Scores
        uncertainty_score = round((1 - confidence) * 100, 1)
        risk_score = round((1 - confidence) * 80, 1)
        volatility_score = round(volatility * 100, 1)

        # Estimated holding time based on timeframe and volatility
        if volatility > 0.70:
            holding_time = "30 Minutes"
        elif volatility > 0.50:
            holding_time = "2 Hours"
        else:
            holding_time = "4-8 Hours"

        probability_profile = {
            "chance_of_success": round(win_prob, 1),
            "chance_of_stop_loss": round(100 - win_prob, 1),
            "expected_profit_pct": expected_profit_pct,
            "expected_loss_pct": expected_loss_pct,
            "expected_holding_time": holding_time,
            "uncertainty_score": uncertainty_score,
            "risk_score": risk_score,
            "volatility_score": volatility_score,
        }

        return {**decision, "probability_profile": probability_profile}
