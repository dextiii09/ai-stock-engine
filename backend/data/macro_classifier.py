from typing import Dict, Any

class MacroRegimeClassifier:
    """
    Feature 12: High-Level Macro Regime Classifier.
    Outputs one of five states based on DXY, VIX, Yields, and COT:
    - Risk-On: NQ bullish, Gold muted
    - Risk-Off: Gold bullish, NQ defensive
    - Stagflation: Gold bullish, NQ bearish (rates rising)
    - Reflationary: Both can trend (dollar dropping, yields dropping)
    - Dislocation/Panic: Both sell (liquidity crisis, dollar cash dash)
    """

    def classify(self, macro_data: Dict[str, Any]) -> str:
        dxy_momentum = macro_data.get("dxy_momentum", 0.0)
        vix_level = macro_data.get("vix_level", 15.0)
        real_yield_trend = macro_data.get("real_yield_10y_trend", 0.0)
        
        # Extract COT Positioning
        cot = macro_data.get("cot_positioning", {})
        gold_cot = cot.get("MGC=F", "NEUTRAL")
        nq_cot = cot.get("MNQ=F", "NEUTRAL")
        
        # 1. Dislocation / Panic (VIX > 30, Cash Dash)
        if vix_level > 30 and (dxy_momentum > 0.5 or "BEARISH" in gold_cot):
            return "Dislocation/Panic"

        # 2. Reflationary (Dollar dropping, yields dropping, Funds piling into both)
        if dxy_momentum < -0.1 and real_yield_trend < -0.02:
            if "BULLISH" in gold_cot or "BULLISH" in nq_cot:
                return "Reflationary"
            if vix_level < 20:
                return "Risk-On"
            return "Reflationary"

        # 3. Stagflation (Dollar rising/flat, yields rising, Gold bought as inflation hedge)
        if real_yield_trend > 0.02 and "BULLISH" in gold_cot:
            if vix_level > 20 or dxy_momentum > 0.1:
                return "Stagflation"

        # 4. Risk-Off (Fear rising, Gold safe haven, NQ sold)
        if vix_level > 25 and "BEARISH" in nq_cot:
            return "Risk-Off"

        # 5. Risk-On (VIX low, NQ bought)
        return "Risk-On"
