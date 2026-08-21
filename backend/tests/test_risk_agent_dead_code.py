"""
Regression test for a MEDIUM finding in the 2026-08-21 audit (Finding #17):

`RiskAgent.evaluate()` previously also vetoed on `daily_pnl_pct < -3.0` and
`max_drawdown_pct < -8.0`, but `routes.py` never populates either key in
`tick_data` for any of the 5 markets — confirmed via grep, those branches
were permanently dead code that misleadingly implied this agent enforced a
daily/drawdown circuit breaker (the real one lives in GlobalRiskAggregator).
Removed per an explicit decision (this agent's real job is cash/concentration,
not duplicating the global breaker) rather than wiring in unused inputs.

This guards against those dead branches reappearing, and confirms the real
cash/concentration checks still work.
"""

from agents.committee import RiskAgent


def test_risk_agent_no_longer_checks_dead_pnl_drawdown_inputs():
    agent = RiskAgent()
    # These inputs are never populated by routes.py in real use — if the
    # agent still reads them, this proves the dead branches came back.
    result = agent.evaluate("AAPL", {
        "cash_pct": 50.0,
        "open_trade_count": 1,
        "daily_pnl_pct": -50.0,       # would have vetoed under the old code
        "max_drawdown_pct": -90.0,    # would have vetoed under the old code
    })
    assert result["signal"] == "OK", (
        "RiskAgent vetoed based on daily_pnl_pct/max_drawdown_pct — these "
        "dead-code branches (routes.py never populates either key) were "
        "removed in the 2026-08-21 audit and must not reappear."
    )


def test_risk_agent_still_vetoes_on_low_cash():
    agent = RiskAgent()
    result = agent.evaluate("AAPL", {"cash_pct": 10.0, "open_trade_count": 1})
    assert result["signal"] == "VETO"


def test_risk_agent_still_vetoes_on_position_concentration():
    agent = RiskAgent()
    result = agent.evaluate("AAPL", {"cash_pct": 50.0, "open_trade_count": 5})
    assert result["signal"] == "VETO"


def test_risk_agent_ok_within_limits():
    agent = RiskAgent()
    result = agent.evaluate("AAPL", {"cash_pct": 50.0, "open_trade_count": 2})
    assert result["signal"] == "OK"
