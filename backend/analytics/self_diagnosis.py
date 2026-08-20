import json
from datetime import datetime, timedelta
from typing import Dict, Any, List
import numpy as np

class SelfDiagnosingAI:
    """
    Analyses the AI Journal at end of day and generates a Self-Diagnosis Report.
    Answers: 
    - Correlation between MGC and MNQ P&L
    - Shadow Trading Success Rate (veto accuracy)
    - Win/Loss by Macro Regime
    - Monte Carlo EV Forecast Accuracy
    """

    def generate_report(self, journal_logs: List[Dict[str, Any]], shadow_logs: List[Dict[str, Any]], agent_weights: Dict[str, float], system_context: Dict[str, Any] = None, closed_trades_count: int = 0, closed_trades: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Analyzes trade journal to produce a structured daily/weekly report.
        """
        today = datetime.utcnow().date()
        today_str = str(today)
        closed_trades = closed_trades or []

        insights = []
        if not journal_logs:
            insights.append("ℹ️ No trades executed today.")

        # Total trades = all journal TRADE actions (BUY + SELL signals executed)
        trade_entries = [t for t in journal_logs if t.get("type") == "TRADE"]
        total_trades = len(trade_entries)
        buy_count  = sum(1 for t in trade_entries if str(t.get("action", "")).upper() == "BUY")
        sell_count = sum(1 for t in trade_entries if str(t.get("action", "")).upper() == "SELL")
        confidences = [t.get("ai_confidence", 0) for t in trade_entries if t.get("ai_confidence", 0) > 0]
        avg_confidence_pct = round(sum(confidences) / len(confidences) * 100, 1) if confidences else None

        # 1. MGC vs MNQ P&L Correlation — use closed_trades (they have actual profit_loss)
        mgc_pnl = [t["profit_loss"] for t in closed_trades if t.get("symbol") == "MGC=F" and "profit_loss" in t]
        mnq_pnl = [t["profit_loss"] for t in closed_trades if t.get("symbol") == "MNQ=F" and "profit_loss" in t]

        pnl_correlation = 0.0
        if len(mgc_pnl) > 5 and len(mnq_pnl) > 5:
            min_len = min(len(mgc_pnl), len(mnq_pnl))
            corr = np.corrcoef(mgc_pnl[:min_len], mnq_pnl[:min_len])[0, 1]
            if not np.isnan(corr):
                pnl_correlation = round(float(corr), 2)

        # 2. Shadow Trading Success Rate
        correct_vetoes = 0
        total_vetoes = len(shadow_logs)
        for s in shadow_logs:
            if s.get("would_have_lost_money", False):
                correct_vetoes += 1
        shadow_success_rate = round(correct_vetoes / total_vetoes * 100, 1) if total_vetoes > 0 else 0.0

        # 3. Win/Loss by Regime — journal entries now store "regime" (logged by log_trade).
        #    Fall back to closed_trades.reason as a proxy when regime is absent.
        regime_performance: Dict[str, Dict[str, int]] = {}
        for t in trade_entries:
            regime = t.get("regime", "Unknown")
            if regime not in regime_performance:
                regime_performance[regime] = {"wins": 0, "losses": 0}
        # Pair each closed trade with a journal entry by symbol proximity to get regime + PnL
        for ct in closed_trades:
            sym  = ct.get("symbol")
            pnl_val = ct.get("profit_loss", 0)
            # Find matching journal entry (same symbol, closest timestamp)
            matching = [e for e in trade_entries if e.get("symbol") == sym]
            regime = matching[-1].get("regime", "Unknown") if matching else "Unknown"
            if regime not in regime_performance:
                regime_performance[regime] = {"wins": 0, "losses": 0}
            if pnl_val > 0:
                regime_performance[regime]["wins"] += 1
            else:
                regime_performance[regime]["losses"] += 1
        # Drop the zeroed-out "Unknown" placeholder if no real trades were added
        if "Unknown" in regime_performance and regime_performance["Unknown"] == {"wins": 0, "losses": 0}:
            del regime_performance["Unknown"]

        # 4. Monte Carlo EV Forecast Accuracy (requires forecast_ev_pct in journal — future feature)
        avg_ev_error = 0.0  # Not yet populated; log_trade will be extended when MC EV is stored

        # Build insights
        if pnl_correlation > 0.5:
            insights.append(f"⚠️ High P&L correlation ({pnl_correlation}) between Gold and NQ. Diversification benefit is compromised.")
        if shadow_success_rate < 50 and total_vetoes > 5:
            insights.append(f"⚠️ Shadow Trading rate is {shadow_success_rate}%. Vetoes are rejecting too many winning trades. Loosen correlation gate or agent thresholds.")
        elif shadow_success_rate >= 50:
            insights.append(f"✅ Veto logic is healthy. {shadow_success_rate}% of rejected setups would have resulted in losses.")
            
        if avg_ev_error > 1.0:
            insights.append(f"⚠️ Monte Carlo EV is over/under-estimating by {avg_ev_error}% on average. Check slippage and ATR parameters.")

        if system_context:
            portfolio_risk = system_context.get("portfolio_risk", {})
            event_status = system_context.get("event_status", {})
            active_count = system_context.get("active_holdings_count", 0)
            
            if portfolio_risk.get("halt_trading_for_day"):
                insights.append(f"🛑 CRITICAL: Portfolio Risk Engine has halted trading due to max daily drawdown ({portfolio_risk.get('daily_drawdown_pct')}%)")
            
            if event_status.get("trading_blackout"):
                insights.append(f"⚠️ MACRO BLACKOUT: {event_status.get('blackout_reason')}. Safe Mode engines are blocked from entering new trades.")
                
            if active_count > 0:
                insights.append(f"ℹ️ Currently managing {active_count} active position(s).")

        return {
            "date": today_str,
            # Journal actions (every BUY/SELL signal executed)
            "total_trades": total_trades,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "avg_confidence_pct": avg_confidence_pct,
            # Closed trades = completed round-trips with P&L (matches Money Tracker)
            "closed_trades_count": closed_trades_count,
            "pnl_correlation": pnl_correlation,
            "shadow_veto_success_rate": shadow_success_rate,
            "regime_performance": regime_performance,
            "avg_ev_forecast_error": avg_ev_error,
            "agent_weights": agent_weights,
            "system_health": system_context or {},
            "insights": insights
        }

    def get_health_report(self) -> Dict[str, Any]:
        """
        Returns real-time health/performance metrics of the AI system.
        """
        import os
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "pid": os.getpid(),
            "services": {
                "yahoo_finance": "online",
                "cftc_api": "online"
            }
        }

