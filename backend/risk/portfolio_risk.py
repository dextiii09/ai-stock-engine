import datetime
import json
import os
from typing import Dict, Any, List, Optional

# Approximate betas vs S&P 500 / broad market for supported instruments
INSTRUMENT_BETAS = {
    # US Futures
    "MNQ=F": 1.05,   # Micro Nasdaq -- high beta tech-heavy
    "MGC=F": 0.02,   # Micro Gold -- near-zero market beta
    "MES=F": 1.00,   # Micro S&P 500
    "MCL=F": 0.40,   # Micro Crude Oil
    "M2K=F": 1.15,   # Micro Russell 2000 -- small caps, above-market beta
    # Indian ETFs / Equities (vs Nifty 50)
    "NIFTYBEES.NS": 1.00,
    "BANKBEES.NS":  1.05,
    "JUNIORBEES.NS": 1.10,
    "GOLDBEES.NS":  0.05,   # Gold ETF — near-zero equity beta
    "WIPRO.NS":     0.78,
    "RELIANCE.NS":  0.92,
    "ONGC.NS":      1.05,
    "TCS.NS":       0.85,
    "INFY.NS":      0.82,
    "HDFCBANK.NS":  0.95,
    "ICICIBANK.NS": 0.98,
}

RISK_LIMITS = {
    "max_daily_loss_pct": 3.0,
    "max_weekly_loss_pct": 6.0,
    "min_cash_reserve_pct": 10.0,
    "max_single_position_pct": 15.0,
    "max_concurrent_positions_per_instrument": 1,
}

# NSE dynamic price bands (Upper Circuit / Lower Circuit limits)
NSE_CIRCUIT_BANDS = {
    "NIFTYBEES.NS": 0.10,
    "JUNIORBEES.NS": 0.10,
    "WIPRO.NS":     0.20,
    "RELIANCE.NS":  0.20,
    "ONGC.NS":      0.20,
}


class PortfolioRiskManager:
    """
    Portfolio-level risk manager.
    Tracks correlation, dollar exposure, and enforces a daily circuit breaker.

    R-1 fix: daily_start_capital and weekly_start_capital are now persisted
    to disk so that a server crash/restart does not reset the circuit-breaker
    baseline to the post-loss capital level.  Without persistence a server
    that crashes after a 4 % loss restarts with daily_start_capital set to
    the *current* (lower) balance, making the breaker fire at 3 % of the
    already-reduced balance instead of 3 % of the true day-open balance.
    """

    def __init__(self, state_file: Optional[str] = None):
        self.daily_start_capital  = 0.0
        self._last_reset_date                  = None   # datetime.date
        self.weekly_start_capital = 0.0
        self._last_reset_week: Optional[tuple] = None   # (year, week_number)
        self._state_file = state_file
        self._load_risk_state()

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def _load_risk_state(self) -> None:
        """Restore baselines from disk after a restart."""
        if not self._state_file or not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                s = json.load(f)

            today    = datetime.date.today()
            iso_week = tuple(today.isocalendar()[:2])

            saved_date = s.get("daily_reset_date")
            if saved_date == str(today):
                self.daily_start_capital = float(s.get("daily_start_capital", 0.0))
                self._last_reset_date    = today

            saved_week = tuple(s.get("weekly_reset_week", []))
            if saved_week == iso_week:
                self.weekly_start_capital = float(s.get("weekly_start_capital", 0.0))
                self._last_reset_week     = iso_week
        except Exception as e:
            print(f"[PortfolioRisk] State load failed: {e}")

    def _save_risk_state(self) -> None:
        """Atomically persist baselines to disk."""
        if not self._state_file:
            return
        try:
            payload = {
                "daily_start_capital":  self.daily_start_capital,
                "daily_reset_date":     str(self._last_reset_date) if self._last_reset_date else None,
                "weekly_start_capital": self.weekly_start_capital,
                "weekly_reset_week":    list(self._last_reset_week) if self._last_reset_week else [],
            }
            tmp = self._state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self._state_file)
        except Exception as e:
            print(f"[PortfolioRisk] State save failed: {e}")

    # ------------------------------------------------------------------ #
    # Baseline reset (calendar-aware)                                      #
    # ------------------------------------------------------------------ #

    def _maybe_reset_daily(self, total_capital: float):

        """Reset daily/weekly baselines on calendar boundaries."""
        today    = datetime.date.today()
        iso_week = tuple(today.isocalendar()[:2])
        changed  = False
        if self._last_reset_date != today:
            self.daily_start_capital = total_capital
            self._last_reset_date    = today
            changed = True
        if self._last_reset_week != iso_week:
            self.weekly_start_capital = total_capital
            self._last_reset_week     = iso_week
            changed = True

        if changed:
            self._save_risk_state()   # R-1: persist immediately on reset

    def reset_baselines(self, total_capital: float) -> None:
        """Explicitly re-anchor baselines to current capital after intentional account operations."""
        today    = datetime.date.today()
        iso_week = tuple(today.isocalendar()[:2])
        self.daily_start_capital  = total_capital
        self.weekly_start_capital = total_capital
        self._last_reset_date     = today
        self._last_reset_week     = iso_week
        self._save_risk_state()

    def analyze(self, holdings: List[Dict[str, Any]], total_capital: float, correlation: float = 0.0) -> Dict[str, Any]:
        # C-5: Reset baseline on new calendar day, not on restart
        self._maybe_reset_daily(total_capital)

        if not holdings:
            return self._empty_profile(total_capital, correlation)

        total_value = sum(h.get("value", 0) for h in holdings)
        cash_value = total_capital - total_value
        cash_pct = (cash_value / total_capital * 100) if total_capital > 0 else 100.0

        current_daily_drawdown_pct = 0.0
        if self.daily_start_capital > 0 and total_capital < self.daily_start_capital:
            current_daily_drawdown_pct = (
                (self.daily_start_capital - total_capital) / self.daily_start_capital * 100
            )


        position_pcts = {}
        instrument_counts = {}
        for h in holdings:
            sym = h.get("symbol", "OTHER")
            val = h.get("value", 0)
            position_pcts[sym] = round(val / total_capital * 100, 1) if total_capital > 0 else 0
            instrument_counts[sym] = instrument_counts.get(sym, 0) + 1

        alerts = []
        halt_trading_for_day   = False
        halt_trading_for_week  = False
        max_daily  = RISK_LIMITS["max_daily_loss_pct"]
        max_weekly = RISK_LIMITS["max_weekly_loss_pct"]
        max_pos    = RISK_LIMITS["max_concurrent_positions_per_instrument"]
        min_cash   = RISK_LIMITS["min_cash_reserve_pct"]

        current_weekly_drawdown_pct = 0.0
        if self.weekly_start_capital > 0 and total_capital < self.weekly_start_capital:
            current_weekly_drawdown_pct = (
                (self.weekly_start_capital - total_capital) / self.weekly_start_capital * 100
            )

        if current_daily_drawdown_pct >= max_daily:
            msg = "Daily drawdown %.2f%% exceeds %.1f%% limit. HALTING." % (current_daily_drawdown_pct, max_daily)
            alerts.append({"level": "CRITICAL", "msg": msg})
            halt_trading_for_day = True

        if current_weekly_drawdown_pct >= max_weekly:
            msg = "Weekly drawdown %.2f%% exceeds %.1f%% limit. HALTING for week." % (current_weekly_drawdown_pct, max_weekly)
            alerts.append({"level": "CRITICAL", "msg": msg})
            halt_trading_for_week = True

        for sym, count in instrument_counts.items():
            if count > max_pos:
                msg = "%s has %d open positions. Max is %d." % (sym, count, max_pos)
                alerts.append({"level": "CRITICAL", "msg": msg})

        if cash_pct < min_cash:
            msg = "Cash reserve at %.1f%% -- below minimum %.1f%%." % (cash_pct, min_cash)
            alerts.append({"level": "WARNING", "msg": msg})

        overall_risk = "HIGH" if any(a["level"] == "CRITICAL" for a in alerts) else "MEDIUM" if alerts else "LOW"

        portfolio_beta = 0.0
        if total_capital > 0:
            portfolio_beta = round(
                sum(INSTRUMENT_BETAS.get(h.get("symbol", ""), 1.0) * h.get("value", 0) for h in holdings)
                / total_capital,
                3,
            )

        return {
            "total_positions": len(holdings),
            "total_invested": round(total_value, 2),
            "cash_value": round(cash_value, 2),
            "cash_pct": round(cash_pct, 1),
            "portfolio_beta": portfolio_beta,
            "correlation_gc_nq": correlation,
            "position_exposure_pct": position_pcts,
            "position_counts": instrument_counts,
            "daily_drawdown_pct":  round(current_daily_drawdown_pct, 2),
            "weekly_drawdown_pct": round(current_weekly_drawdown_pct, 2),
            "halt_trading_for_day":  halt_trading_for_day,
            "halt_trading_for_week": halt_trading_for_week,
            "overall_risk_level": overall_risk,
            "alerts": alerts,
            "limits": RISK_LIMITS,
        }

    def _empty_profile(self, capital: float, correlation: float) -> Dict[str, Any]:
        self._maybe_reset_daily(capital)
        current_daily_drawdown_pct = 0.0
        if capital < self.daily_start_capital and self.daily_start_capital > 0:
            current_daily_drawdown_pct = (
                (self.daily_start_capital - capital) / self.daily_start_capital * 100
            )

        max_daily = RISK_LIMITS["max_daily_loss_pct"]
        halt_trading_for_day = current_daily_drawdown_pct >= max_daily
        alerts = []
        if halt_trading_for_day:
            msg = "Daily drawdown %.2f%% exceeds %.1f%% limit. HALTING." % (current_daily_drawdown_pct, max_daily)
            alerts.append({"level": "CRITICAL", "msg": msg})

        current_weekly_drawdown_pct = 0.0
        if self.weekly_start_capital > 0 and capital < self.weekly_start_capital:
            current_weekly_drawdown_pct = (
                (self.weekly_start_capital - capital) / self.weekly_start_capital * 100
            )
        max_weekly = RISK_LIMITS["max_weekly_loss_pct"]
        halt_trading_for_week = current_weekly_drawdown_pct >= max_weekly
        if halt_trading_for_week:
            msg2 = "Weekly drawdown %.2f%% exceeds %.1f%% limit. HALTING for week." % (current_weekly_drawdown_pct, max_weekly)
            alerts.append({"level": "CRITICAL", "msg": msg2})

        overall_risk = "HIGH" if any(a["level"] == "CRITICAL" for a in alerts) else "LOW"

        return {
            "total_positions": 0,
            "total_invested": 0.0,
            "cash_value": round(capital, 2),
            "cash_pct": 100.0,
            "portfolio_beta": 0.0,
            "correlation_gc_nq": correlation,
            "position_exposure_pct": {},
            "position_counts": {},
            "daily_drawdown_pct":  round(current_daily_drawdown_pct, 2),
            "weekly_drawdown_pct": round(current_weekly_drawdown_pct, 2),
            "halt_trading_for_day":  halt_trading_for_day,
            "halt_trading_for_week": halt_trading_for_week,
            "overall_risk_level": overall_risk,
            "alerts": alerts,
            "limits": RISK_LIMITS,
        }
