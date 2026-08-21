"""
GlobalRiskAggregator — cross-market circuit breaker.

Without this, the system can lose 15 % of total capital in a single day
while each of the five per-market PortfolioRiskManagers reports only a 3 %
drawdown — below every engine's individual halt threshold — so NO halt ever
fires.  This aggregator sums mark-to-market equity across all registered
SmartExecutionEngine instances and fires a system-wide halt flag when total
daily or weekly drawdown exceeds the thresholds below.

Usage (routes.py):
    global_risk = GlobalRiskAggregator(state_file=".../data/global_risk_state.json")
    global_risk.register_engines([
        execution_engine, execution_engine_in, execution_engine_st,
        execution_engine_cx, execution_engine_fx,
    ])

    # At the top of every tick loop:
    g = global_risk.check()
    if g["global_halt"]:
        continue   # skip this market's tick entirely
"""

import datetime
import json
import os
from typing import List, Dict, Any, Optional

GLOBAL_DAILY_HALT_PCT  = 3.5   # 3.5% combined daily drawdown -> halt all markets & protect capital
GLOBAL_WEEKLY_HALT_PCT = 7.0   # 7.0% combined weekly drawdown -> halt all markets


# FIX 2026-07-20: the Indian engine's equity is in INR; summing it raw with
# USD books distorts the combined drawdown (an INR crash is ~90x undercounted).
# Override with env INR_USD_RATE for accuracy; default is a coarse constant.
INR_USD_RATE = float(os.getenv("INR_USD_RATE", "0.0116"))


class GlobalRiskAggregator:
    """Singleton-style; create one instance shared across all route handlers."""

    def __init__(self, state_file: Optional[str] = None) -> None:
        self._engines: list = []
        self.global_halt:         bool  = False
        self.halt_reason:         str   = ""
        self.daily_start_equity:  float = 0.0
        self.weekly_start_equity: float = 0.0
        self._last_reset_date                   = None   # datetime.date
        self._last_reset_week: Optional[tuple]  = None   # (year, week_number)
        self._state_file = state_file
        self._load_state()

    # ------------------------------------------------------------------ #
    # Registration                                                         #
    # ------------------------------------------------------------------ #

    def register_engines(self, engines: list) -> None:
        """Register all SmartExecutionEngine instances (call once at startup)."""
        self._engines = engines

    # ------------------------------------------------------------------ #
    # Equity aggregation                                                   #
    # ------------------------------------------------------------------ #

    def total_equity(self) -> float:
        """Sum mark-to-market equity across all markets, normalized to USD."""
        total = 0.0
        for e in self._engines:
            eq = e.get_total_equity()
            if getattr(e, "market", "US") == "INDIA":
                eq *= INR_USD_RATE
            total += eq
        return total

    def total_initial_capital(self) -> float:
        """Sum initial capital baseline across all registered engines, normalized to USD."""
        total = 0.0
        for e in self._engines:
            init_bal = getattr(e, "_initial_balance", getattr(e, "portfolio_balance", 10000.0))
            if getattr(e, "market", "US") == "INDIA":
                init_bal *= INR_USD_RATE
            total += init_bal
        return total

    def equity_by_market(self) -> Dict[str, float]:
        return {e.market: round(e.get_total_equity(), 2) for e in self._engines}


    # ------------------------------------------------------------------ #
    # Circuit-breaker evaluation (call every tick — pure arithmetic)       #
    # ------------------------------------------------------------------ #

    def check(self) -> Dict[str, Any]:
        """
        Evaluate cross-market drawdown and update the global halt flag.
        Returns a snapshot dict; routes.py should check ['global_halt'] before
        entering any per-market loop body.
        """
        today    = datetime.date.today()
        iso_week = tuple(today.isocalendar()[:2])   # (year, week_number)
        total    = self.total_equity()

        # Day boundary reset
        if self._last_reset_date != today:
            self.daily_start_equity = total
            self._last_reset_date   = today
            # New day: clear the daily-triggered halt so trading can resume
            if self.global_halt and "daily" in self.halt_reason.lower():
                self.global_halt = False
                self.halt_reason = ""
            self._save_state()

        # Week boundary reset
        if self._last_reset_week != iso_week:
            self.weekly_start_equity = total
            self._last_reset_week    = iso_week
            self._save_state()

        daily_dd  = 0.0
        weekly_dd = 0.0
        if self.daily_start_equity > 0 and total < self.daily_start_equity:
            daily_dd = (self.daily_start_equity - total) / self.daily_start_equity * 100
        if self.weekly_start_equity > 0 and total < self.weekly_start_equity:
            weekly_dd = (self.weekly_start_equity - total) / self.weekly_start_equity * 100

        if not self.global_halt:
            if daily_dd >= GLOBAL_DAILY_HALT_PCT:
                self.global_halt = True
                self.halt_reason = (
                    f"GLOBAL HALT: combined daily drawdown {daily_dd:.2f}% "
                    f"exceeds {GLOBAL_DAILY_HALT_PCT}% limit across all markets."
                )
                print(f"[GlobalRisk] ⛔ {self.halt_reason}")
                self._save_state()

            elif weekly_dd >= GLOBAL_WEEKLY_HALT_PCT:
                self.global_halt = True
                self.halt_reason = (
                    f"GLOBAL HALT: combined weekly drawdown {weekly_dd:.2f}% "
                    f"exceeds {GLOBAL_WEEKLY_HALT_PCT}% limit."
                )
                print(f"[GlobalRisk] ⛔ {self.halt_reason}")
                self._save_state()

        return {
            "global_halt":           self.global_halt,
            "halt_reason":           self.halt_reason,
            "total_equity":          round(total, 2),
            "daily_start_equity":    round(self.daily_start_equity, 2),
            "weekly_start_equity":   round(self.weekly_start_equity, 2),
            "global_daily_dd_pct":   round(daily_dd, 2),
            "global_weekly_dd_pct":  round(weekly_dd, 2),
            "thresholds": {
                "daily_halt_pct":    GLOBAL_DAILY_HALT_PCT,
                "weekly_halt_pct":   GLOBAL_WEEKLY_HALT_PCT,
            },
            "equity_by_market":      self.equity_by_market(),
        }

    # ------------------------------------------------------------------ #
    # Manual baseline reset (for accounting changes, not trading losses)   #
    # ------------------------------------------------------------------ #

    def reset_baselines(self, reason: str = "manual reset") -> Dict[str, Any]:
        """
        Re-anchor daily/weekly drawdown baselines to CURRENT equity and clear
        any active halt. Use after accounting changes (balance migrations,
        currency-normalization fixes, book cleanups) that shift total equity
        without any real trading loss — otherwise the stale baseline reads
        the accounting delta as a crash and halts all markets.
        (Added 2026-07-20 after the cross-market cleanup tripped a 12.76%
        phantom weekly drawdown.)
        """
        total = self.total_equity()
        today = datetime.date.today()
        self.daily_start_equity  = total
        self.weekly_start_equity = total
        self._last_reset_date    = today
        self._last_reset_week    = tuple(today.isocalendar()[:2])
        was_halted = self.global_halt
        self.global_halt = False
        self.halt_reason = ""
        self._save_state()
        print(f"[GlobalRisk] Baselines reset to {total:.2f} ({reason}); "
              f"halt cleared: {was_halted}")
        return {"status": "reset", "new_baseline": round(total, 2),
                "halt_cleared": was_halted, "reason": reason}

    async def trigger_emergency_kill_switch(self, reason: str = "Manual Operator Emergency Trigger") -> Dict[str, Any]:
        """
        EMERGENCY KILL SWITCH: Immediately halts all market engines and liquidates
        all open active holdings across every market book.
        """
        self.global_halt = True
        self.halt_reason = f"EMERGENCY KILL-SWITCH: {reason}"
        self._save_state()
        print(f"[GlobalRisk] [EMERGENCY] {self.halt_reason}")



        liquidated_count = 0
        liquidation_details = []
        for eng in self._engines:
            holdings = list(getattr(eng, "active_holdings", []))
            for h in holdings:
                sym = h.get("symbol")
                price = h.get("current_price", h.get("entry_price", 0.0))
                try:
                    ok, msg = await eng.force_close(h, price, f"EMERGENCY_KILL_SWITCH_{reason}")
                    if ok:
                        liquidated_count += 1
                        liquidation_details.append(f"{sym} closed @ ${price:.2f}")
                except Exception as ex:
                    liquidation_details.append(f"Failed to close {sym}: {ex}")

        return {
            "status": "EMERGENCY_HALTED",
            "reason": self.halt_reason,
            "liquidated_positions_count": liquidated_count,
            "details": liquidation_details,
            "total_equity": round(self.total_equity(), 2),
        }

    def resume_trading(self, reason: str = "Operator Authorized Resume") -> Dict[str, Any]:
        """Resumes trading across all engines and resets drawdown baseline."""
        return self.reset_baselines(reason=reason)


    # ------------------------------------------------------------------ #
    # Persistence (survives server restarts)                               #
    # ------------------------------------------------------------------ #

    def _load_state(self) -> None:
        if not self._state_file or not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                s = json.load(f)

            today    = datetime.date.today()
            iso_week = tuple(today.isocalendar()[:2])

            saved_date = s.get("daily_reset_date")
            if saved_date == str(today):
                self.daily_start_equity = float(s.get("daily_start_equity", 0.0))
                self._last_reset_date   = today
                self.global_halt  = bool(s.get("global_halt", False))
                self.halt_reason  = s.get("halt_reason", "")

            saved_week = tuple(s.get("weekly_reset_week", []))
            if saved_week == iso_week:
                self.weekly_start_equity = float(s.get("weekly_start_equity", 0.0))
                self._last_reset_week    = iso_week
        except Exception as e:
            print(f"[GlobalRisk] State load failed: {e}")

    def _save_state(self) -> None:
        if not self._state_file:
            return
        try:
            payload = {
                "daily_start_equity":  self.daily_start_equity,
                "daily_reset_date":    str(self._last_reset_date) if self._last_reset_date else None,
                "weekly_start_equity": self.weekly_start_equity,
                "weekly_reset_week":   list(self._last_reset_week) if self._last_reset_week else [],
                "global_halt":         self.global_halt,
                "halt_reason":         self.halt_reason,
            }
            tmp = self._state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self._state_file)
        except Exception as e:
            print(f"[GlobalRisk] State save failed: {e}")
