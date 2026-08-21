"""
Regression test for a LOW/MEDIUM finding in the 2026-08-21 audit (Finding #13):

`ReinforcementLearningEngine.process_trade_outcome()` excludes both
"News & Sentiment AI" and "Correlation Agent" from RL weight updates via a
`_GHOST_AGENTS` set — both are forced to weight 0.0 in every live trading
loop (neither can be point-in-time backtested), so updating their alpha/beta
from real outcomes would be wasted cycles creating stale, misleading state.

`process_shadow_outcome()` (the parallel path for shadow/simulated trade
outcomes) had its own separate `_GHOST_AGENTS` set that only excluded
"News & Sentiment AI" — missing "Correlation Agent". This meant shadow-trade
learning kept nudging Correlation Agent's weight even though its live weight
never moves, the same class of "un-tuned agent silently accumulates state"
bug as Finding #2 (the un-excluded Indian Gemini agent).
"""

from analytics.rl_engine import ReinforcementLearningEngine


def test_process_shadow_outcome_excludes_correlation_agent():
    """
    Every agent (including ghosts) is pre-seeded with a 0.0 delta at
    __init__ for every regime — so presence of the key alone proves
    nothing. The real bug is whether process_shadow_outcome() *changes*
    a ghost agent's delta away from 0.0; a real, non-ghost agent's delta
    must change.
    """
    engine = ReinforcementLearningEngine()

    trade_result = {
        "pnl_pct": 2.0,
        "regime": "Sideways",
        "action": "BUY",
        "committee_breakdown": {
            "Correlation Agent": {"signal": "WAIT", "confidence": 0.5},
            "News & Sentiment AI": {"signal": "WAIT", "confidence": 0.5},
            "Technical Analyst": {"signal": "BUY", "confidence": 0.8},
        },
    }

    engine.process_shadow_outcome(trade_result)

    matched_regime = engine._match_regime("Sideways")
    deltas = engine._batch_weight_deltas[matched_regime]

    assert deltas["Correlation Agent"] == 0.0, (
        "process_shadow_outcome() moved Correlation Agent's weight delta away "
        "from 0.0 — it is forced to 0.0 in every live loop and must be "
        "excluded from shadow-trade learning too, matching "
        "process_trade_outcome()'s _GHOST_AGENTS set."
    )
    assert deltas["News & Sentiment AI"] == 0.0
    assert deltas["Technical Analyst"] != 0.0, (
        "A real, non-ghost agent should still learn from shadow outcomes."
    )
