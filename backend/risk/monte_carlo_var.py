import numpy as np
from typing import Dict, Any, List, Optional


class MonteCarloVaREngine:
    """
    Institutional Monte Carlo Value-at-Risk (VaR) & Macro Stress-Testing Engine.
    
    Simulates 10,000 randomized forward paths across active multi-asset holdings
    (US Equities/Futures, Indian Equities, Tech, Crypto, Forex) to compute:
    - 95% & 99% 1-Day Value at Risk (VaR)
    - 99% Conditional Value at Risk (CVaR / Expected Shortfall)
    - Historical Macro Stress-Test Scenarios (2020 Covid Crash, 2022 Tech Selloff, Crypto Flash Crash)
    """

    _instance: Optional["MonteCarloVaREngine"] = None

    # Base daily asset class volatilities (sigma)
    DEFAULT_VOLATILITIES = {
        "CRYPTO": 0.045,   # 4.5% daily sigma
        "STOCKS": 0.020,   # 2.0% daily sigma (Tech)
        "US": 0.014,       # 1.4% daily sigma (Index Futures)
        "INDIA": 0.015,    # 1.5% daily sigma (NSE)
        "FOREX": 0.006,    # 0.6% daily sigma
    }

    # Historical Macro Shock Scenarios
    STRESS_SCENARIOS = {
        "2020 Covid Liquidity Shock": {"US": -0.075, "INDIA": -0.080, "STOCKS": -0.090, "CRYPTO": -0.180, "FOREX": -0.018},
        "2022 Fed Rate Hike Selloff": {"US": -0.035, "INDIA": -0.025, "STOCKS": -0.055, "CRYPTO": -0.090, "FOREX": 0.012},
        "Crypto Flash Crash / Depeg": {"US": -0.005, "INDIA": -0.005, "STOCKS": -0.010, "CRYPTO": -0.220, "FOREX": 0.002},
        "Global Geopolitical Escalation": {"US": -0.040, "INDIA": -0.035, "STOCKS": -0.045, "CRYPTO": -0.060, "FOREX": -0.015},
    }

    @classmethod
    def instance(cls) -> "MonteCarloVaREngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_market_type(self, symbol: str) -> str:
        sym = symbol.upper()
        if sym.endswith(".NS") or sym.endswith(".BO"):
            return "INDIA"
        elif "-USD" in sym or "BTC" in sym or "ETH" in sym:
            return "CRYPTO"
        elif "=X" in sym or "/" in sym:
            return "FOREX"
        elif sym in ("AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META", "GOOGL"):
            return "STOCKS"
        return "US"

    def calculate_portfolio_var(
        self,
        holdings: List[Dict[str, Any]],
        total_equity: float,
        iterations: int = 10000,
        inr_usd_rate: float = 0.012
    ) -> Dict[str, Any]:
        """
        Calculates 10,000-path Monte Carlo VaR and stress scenarios for open holdings.
        """
        if not holdings or total_equity <= 0:
            return {
                "total_equity": total_equity,
                "open_positions": 0,
                "total_exposure_usd": 0.0,
                "var_95_usd": 0.0,
                "var_99_usd": 0.0,
                "cvar_99_usd": 0.0,
                "var_95_pct": 0.0,
                "var_99_pct": 0.0,
                "cvar_99_pct": 0.0,
                "status": "ALL_CASH",
                "stress_tests": {}
            }

        position_exposures = []
        position_vols = []
        position_dirs = []
        position_markets = []

        total_exposure = 0.0

        for h in holdings:
            sym = h.get("symbol", "UNKNOWN")
            mkt = self._get_market_type(sym)
            shares = float(h.get("shares", 0.0))
            price = float(h.get("current_price", h.get("entry_price", 0.0)))
            direction = 1.0 if h.get("direction", "LONG") == "LONG" else -1.0
            
            notional = shares * price
            # Convert INR to USD for Indian stocks
            if mkt == "INDIA":
                notional = notional * inr_usd_rate

            vol = self.DEFAULT_VOLATILITIES.get(mkt, 0.015)
            
            position_exposures.append(notional)
            position_vols.append(vol)
            position_dirs.append(direction)
            position_markets.append(mkt)
            total_exposure += notional

        exposures_arr = np.array(position_exposures)
        vols_arr = np.array(position_vols)
        dirs_arr = np.array(position_dirs)

        n_pos = len(exposures_arr)
        # Generate correlated return matrix (assumes average cross-asset correlation of 0.25)
        corr_matrix = np.full((n_pos, n_pos), 0.25)
        np.fill_diagonal(corr_matrix, 1.0)
        
        # Cholesky decomposition for correlated random draws
        try:
            L = np.linalg.cholesky(corr_matrix)
        except Exception:
            L = np.eye(n_pos)

        # Standard normal random draws: (iterations, n_pos)
        z = np.random.normal(0, 1, size=(iterations, n_pos))
        correlated_z = z @ L.T

        # Simulated returns = direction * volatility * correlated_z
        sim_returns = dirs_arr * vols_arr * correlated_z
        # Simulated dollar P&L per path = sum over all positions
        sim_pnl = sim_returns @ exposures_arr

        # VaR is the negative of the corresponding percentile of P&L
        var_95_usd = float(-np.percentile(sim_pnl, 5))
        var_99_usd = float(-np.percentile(sim_pnl, 1))
        
        # CVaR (Expected Shortfall) is the mean of all losses exceeding 99% VaR
        tail_losses = -sim_pnl[sim_pnl <= -var_99_usd]
        cvar_99_usd = float(np.mean(tail_losses)) if len(tail_losses) > 0 else var_99_usd

        # Floor at zero
        var_95_usd = max(0.0, var_95_usd)
        var_99_usd = max(0.0, var_99_usd)
        cvar_99_usd = max(0.0, cvar_99_usd)

        var_95_pct = round(var_95_usd / total_equity * 100, 2)
        var_99_pct = round(var_99_usd / total_equity * 100, 2)
        cvar_99_pct = round(cvar_99_usd / total_equity * 100, 2)

        # Historical Stress Tests
        stress_results = {}
        for scenario_name, shocks in self.STRESS_SCENARIOS.items():
            scenario_loss = 0.0
            for i, mkt in enumerate(position_markets):
                shock = shocks.get(mkt, -0.02)
                # Directional impact: Long loses on negative shock, Short gains on negative shock
                pos_pnl = exposures_arr[i] * dirs_arr[i] * shock
                scenario_loss += pos_pnl
            
            loss_usd = max(0.0, float(-scenario_loss))
            loss_pct = round(float(loss_usd / total_equity * 100), 2)
            stress_results[scenario_name] = {
                "loss_usd": round(float(loss_usd), 2),
                "loss_pct": float(loss_pct),
                "survives_circuit_breaker": bool(loss_pct < 3.5)
            }

        return {
            "total_equity": float(round(total_equity, 2)),
            "open_positions": int(n_pos),
            "total_exposure_usd": float(round(total_exposure, 2)),
            "exposure_ratio_pct": float(round(total_exposure / max(total_equity, 1.0) * 100, 1)),
            "var_95_usd": float(round(var_95_usd, 2)),
            "var_99_usd": float(round(var_99_usd, 2)),
            "cvar_99_usd": float(round(cvar_99_usd, 2)),
            "var_95_pct": float(var_95_pct),
            "var_99_pct": float(var_99_pct),
            "cvar_99_pct": float(cvar_99_pct),
            "status": "OPTIMAL" if var_99_pct < 2.0 else "ELEVATED" if var_99_pct < 3.5 else "CRITICAL",
            "stress_tests": stress_results
        }


    def format_var_report(self, res: Dict[str, Any]) -> str:
        """Formats the VaR calculation results into a sleek Telegram message."""
        status_emoji = "🟢" if res["status"] == "OPTIMAL" else "🟡" if res["status"] == "ELEVATED" else "🔴"
        
        if res.get("status") == "ALL_CASH":
            return (
                "🎲 *Monte Carlo Portfolio Risk & VaR (10,000 Paths)*\n\n"
                "• *Status*: 🟢 `100% SAFE CASH`\n"
                "• *Open Positions*: `0`\n"
                "• *1-Day 99% VaR*: `$0.00 (0.0%)`\n"
                "• *Tail Risk (CVaR)*: `$0.00`\n"
                "Zero market risk. Capital is 100% protected."
            )

        lines = [
            "🎲 *Monte Carlo Value-at-Risk (10,000 Paths)*",
            f"• *Risk Status*: {status_emoji} `{res['status']}`",
            f"• *Open Positions*: `{res['open_positions']}` (Exposure: `${res['total_exposure_usd']:,.2f}` | `{res['exposure_ratio_pct']}%`)",
            f"• *Total Portfolio Equity*: `${res['total_equity']:,.2f}`\n",
            f"📊 *1-Day Tail Risk Projections:*",
            f"   • *95% VaR (1-Day)*: `${res['var_95_usd']:,.2f}` (`{res['var_95_pct']}%`)",
            f"   • *99% VaR (1-Day)*: `${res['var_99_usd']:,.2f}` (`{res['var_99_pct']}%`)",
            f"   • *99% Expected Shortfall (CVaR)*: `${res['cvar_99_usd']:,.2f}` (`{res['cvar_99_pct']}%`)\n",
            "🌪️ *Historical Macro Shock Stress-Tests:*",
        ]
        
        for name, data in res.get("stress_tests", {}).items():
            breaker = "✅ Safe" if data["survives_circuit_breaker"] else "⚠️ Breaker Trigger"
            lines.append(f"   • *{name}*: `${data['loss_usd']:,.2f}` (`{data['loss_pct']}%`) — {breaker}")

        lines.append(f"\n_99% confidence that daily loss will not exceed ${res['var_99_usd']:,.2f}._")
        return "\n".join(lines)
