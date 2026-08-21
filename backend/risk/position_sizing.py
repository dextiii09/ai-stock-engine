class PositionSizer:
    """
    Half-Kelly position sizer with calibrated inputs.

    Two distinct issues fixed vs. original:

    1. Kelly's p was fed raw committee `confidence` — an uncalibrated score,
       NOT a win probability. confidence=0.75 does not mean 75% of such trades
       win. Fix: use `recent_win_rate` (actual realized win fraction 0–1) as p.

    2. Kelly's b was hard-coded to 2.0 (target R:R). Fix: accept `realized_b`
       (trailing avg_win / avg_loss from real closed trades). Falls back to 2.0
       only when history is too thin.

    3. `recent_win_rate` is now expected as a FRACTION (0.0–1.0), NOT a
       percentage. Callers must divide rl_engine.win_rate by 100.
    """

    def __init__(self, max_risk_per_trade: float = 0.05):
        self.max_risk_per_trade = max_risk_per_trade   # 5% hard cap

    def calculate_size(
        self,
        confidence: float,
        current_capital: float,
        current_price: float,
        regime: str = "Sideways",
        recent_win_rate: float = 0.50,   # fraction (0–1), NOT percentage
        atr_pct: float = 0.0,
        n_closed_trades: int = 0,
        realized_b: float = None,        # realized avg_win / avg_loss
    ) -> dict:
        """
        Args:
            confidence:       Committee conviction score (0–1). Retained for caller
                              signature compatibility; sizing uses calibrated win rate.
            recent_win_rate:  FRACTION (0–1). Pass rl_engine.win_rate / 100.
            n_closed_trades:  rl_engine.total_closed_trades.
            realized_b:       avg_win / avg_loss from trade history. None → 2.0.
        """
        # ── Zero / negative price & capital safety guard ──
        if current_price <= 0 or current_capital <= 0:
            return {
                "shares": 0.0,
                "capital_allocated": 0.0,
                "risk_pct": 0.0,
                "scalars": {"regime": 1.0, "volatility": 1.0},
                "kelly_gate": "invalid_price_or_capital",
            }

        # ── Minimum-sample gate ────────────────────────────────────────────────
        # With < 30 trades, SE(p̂) > 9 pp — Kelly will massively over-size.
        if n_closed_trades < 30:
            risk_pct = 0.01
            capital_to_allocate = current_capital * risk_pct
            shares = round(capital_to_allocate / max(current_price, 1e-6), 4)
            return {
                "shares":            shares,
                "capital_allocated": round(shares * current_price, 4),
                "risk_pct":          round(risk_pct * 100, 2),
                "scalars":           {"regime": 1.0, "win_rate": 1.0, "volatility": 1.0},
                "kelly_gate":        "fixed_fractional_lt30",
            }

        # ── Calibrated Kelly inputs ────────────────────────────────────────────
        # p: use realized win rate (the actual measured p̂), NOT raw confidence.
        #    recent_win_rate is a fraction (0–1); guard against edge cases.
        p = float(max(0.05, min(0.95, recent_win_rate)))
        q = 1.0 - p

        # b: realized avg_win / avg_loss (trailing). Use 1e-4 floor for zero-div safety.
        b = max(1e-4, float(realized_b)) if realized_b is not None else 2.0

        # Half-Kelly: f* = (p·b − q) / b, halved to absorb estimation error
        kelly_fraction = (p * b - q) / b
        half_kelly     = kelly_fraction / 2.0

        # ── Adaptive scalers ──────────────────────────────────────────────────
        # Map raw HMM state names to the 4 canonical names if unmapped
        _HMM_FALLBACK = {
            "Strong Bull": "Trending Bull", "Weak Bull": "Trending Bull", "Bull Expansion": "Trending Bull",
            "Strong Bear": "Trending Bear", "Weak Bear": "Trending Bear",
            "Compression": "Sideways", "Low Liquidity": "Sideways",
            "Gap Day": "High Volatility", "News Shock": "High Volatility", "High Liquidity": "High Volatility"
        }
        canonical_regime = _HMM_FALLBACK.get(regime, regime)
        regime_scalars = {
            "Trending Bull":   1.1,
            "Trending Bear":   1.0,
            "Sideways":        0.5,
            "High Volatility": 0.4,
        }
        regime_scalar = regime_scalars.get(canonical_regime, 1.0)

        # 2. Volatility penalty
        volatility_scalar = 1.0
        if atr_pct > 1.0:    volatility_scalar = 0.5
        elif atr_pct > 0.5:  volatility_scalar = 0.8

        adjusted_kelly = half_kelly * regime_scalar * volatility_scalar

        # ── Negative edge safety gate ──
        if adjusted_kelly <= 0.0:
            return {
                "shares":            0.0,
                "capital_allocated": 0.0,
                "risk_pct":          0.0,
                "scalars": {
                    "regime":     regime_scalar,
                    "volatility": volatility_scalar,
                },
                "kelly_inputs": {
                    "p":          round(p, 4),
                    "b":          round(b, 4),
                    "half_kelly": round(half_kelly, 4),
                },
                "kelly_gate": "negative_edge",
            }

        risk_pct = min(adjusted_kelly, self.max_risk_per_trade)
        capital_to_allocate = current_capital * risk_pct
        shares = round(capital_to_allocate / max(current_price, 1e-6), 4)

        return {
            "shares":            shares,
            "capital_allocated": round(shares * current_price, 4),
            "risk_pct":          round(risk_pct * 100, 2),
            "scalars": {
                "regime":     regime_scalar,
                "volatility": volatility_scalar,
            },
            "kelly_inputs": {
                "p":          round(p, 4),
                "b":          round(b, 4),
                "half_kelly": round(half_kelly, 4),
            },
            "kelly_gate": "half_kelly_optimal",
        }

