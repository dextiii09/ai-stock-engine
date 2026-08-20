import sys
import os
import math

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.rl_engine import ReinforcementLearningEngine

# Current engine semantics (kept in sync with rl_engine.process_trade_outcome):
#   sharpe_reward = clip(pnl_pct / std_pnl, -5, +5)      (std fallback 1.0 when <5 trades)
#   reward_base   = sharpe_reward - max_dd*0.3, floored at 0 for wins
#   delta         = reward_base * lr * herding_mult * confidence * (+1 if agreed else -1)
#   confidence defaults to 0.5 when the committee breakdown omits it
#   herding_mult  = 0.5 when >= 85% of agents agree with the executed action
#   adaptive lr   = base * 2.0 if recent win rate < 40% (1.5 if < 50%)
#   TD partial: every 3rd trade, 20% of accumulated delta is applied and deducted


def _fresh_engine():
    rl = ReinforcementLearningEngine()
    rl.learning_rate = 0.005
    rl.active_regime = "Trending Bull"
    rl.trades_in_active_regime = 10
    rl._last_regime = "Trending Bull"
    rl._trades_in_new_regime = 10   # past the 10-trade warmup window
    return rl


def test_tier1_rl():
    print("=== Testing ReinforcementLearningEngine Tier 1 Upgrades ===")

    rl = _fresh_engine()

    # 1. Verify RETRAIN_INTERVAL is 5
    print(f"Checking RETRAIN_INTERVAL... Expected: 5, Got: {rl.trades_till_retrain}")
    assert rl.trades_till_retrain == 5, "RETRAIN_INTERVAL must be 5"
    print("[OK] RETRAIN_INTERVAL check passed.")

    # Committee breakdown for 100% agreement (4 BUY votes)
    all_buy_breakdown = [
        {"agent": "Technical Analyst", "signal": "BUY"},
        {"agent": "Fundamental Analyst", "signal": "BUY"},
        {"agent": "News & Sentiment AI", "signal": "BUY"},
        {"agent": "Macro Economic AI", "signal": "BUY"},
    ]

    # Committee breakdown for diverse signals (2 BUY, 2 SELL) -> 50% agreement
    diverse_breakdown = [
        {"agent": "Technical Analyst", "signal": "BUY"},
        {"agent": "Fundamental Analyst", "signal": "SELL"},
        {"agent": "News & Sentiment AI", "signal": "BUY"},
        {"agent": "Macro Economic AI", "signal": "SELL"},
    ]

    # 2. First trade: std fallback 1.0 → sharpe = clip(10/1, ±5) = 5.0
    # Trade 1: Win of $100 on $1000 capital (pnl_pct = 10%)
    t1_result = {"profit_loss": 100.0, "capital_allocated": 1000.0, "action": "BUY", "regime": "Trending Bull"}
    rl.process_trade_outcome(t1_result, diverse_breakdown)

    assert len(rl._trade_history) == 1, "Trade history should contain 1 trade"
    assert rl._trade_history[0]["pnl_pct"] == 10.0, "pnl_pct should be 10%"

    # Expected delta for Technical Analyst (agreed with BUY):
    #   reward_base = 5.0 (clipped sharpe, no drawdown yet)
    #   lr = 0.005 (recent win rate 100% → 1.0x), herding = 1.0 (50% agreement)
    #   confidence = 0.5 (default when breakdown omits confidence)
    #   delta = 5.0 * 0.005 * 1.0 * 0.5 = 0.0125
    expected_t1 = 5.0 * 0.005 * 1.0 * 0.5
    t_analyst_delta = rl._batch_weight_deltas["Trending Bull"]["Technical Analyst"]
    print(f"T1 delta for Technical Analyst: {t_analyst_delta:.4f} (Expected: {expected_t1:.4f})")
    assert abs(t_analyst_delta - expected_t1) < 1e-6, "Sharpe reward or base reward logic failed on Trade 1"

    # Disagreeing agent must receive the mirrored negative delta
    f_analyst_delta = rl._batch_weight_deltas["Trending Bull"]["Fundamental Analyst"]
    assert abs(f_analyst_delta + expected_t1) < 1e-6, "Disagreeing agent should get symmetric negative delta"
    print("[OK] Sharpe clip, confidence default, and symmetric updates passed.")

    # 3. Diversity Guard (agreement >= 85% → herding multiplier 0.5)
    rl = _fresh_engine()
    rl.process_trade_outcome(t1_result, all_buy_breakdown)
    expected_herded = expected_t1 * 0.5   # only difference is herding_mult
    t_analyst_delta = rl._batch_weight_deltas["Trending Bull"]["Technical Analyst"]
    print(f"T1 herded delta for Technical Analyst: {t_analyst_delta:.4f} (Expected: {expected_herded:.4f})")
    assert abs(t_analyst_delta - expected_herded) < 1e-6, "Diversity guard herding penalty failed to apply"
    print("[OK] Diversity Guard check passed.")

    # 4. Drawdown Penalty clamp: a WIN during a drawdown must never produce a
    #    negative contribution (reward floored at 0 for wins).
    rl = _fresh_engine()
    rl.process_trade_outcome(t1_result, diverse_breakdown)                       # +10%
    t2_result = {"profit_loss": -200.0, "capital_allocated": 1000.0, "action": "BUY", "regime": "Trending Bull"}
    rl.process_trade_outcome(t2_result, diverse_breakdown)                       # -20%
    # Isolate trade 3's contribution
    rl._batch_weight_deltas["Trending Bull"]["Technical Analyst"] = 0.0
    t3_result = {"profit_loss": 10.0, "capital_allocated": 1000.0, "action": "BUY", "regime": "Trending Bull"}
    rl.process_trade_outcome(t3_result, diverse_breakdown)                       # +1% win inside a drawdown
    t_analyst_delta = rl._batch_weight_deltas["Trending Bull"]["Technical Analyst"]
    print(f"Technical Analyst isolated T3 delta: {t_analyst_delta:.6f} (must be >= 0)")
    assert t_analyst_delta >= 0.0, "Drawdown penalty sign-flipped a win reward!"
    print("[OK] Drawdown penalty clamp protection check passed.")

    # 5. Adaptive Learning Rate: 4 straight losses → recent win rate 0% → lr x2
    rl = _fresh_engine()
    loss_result = {"profit_loss": -100.0, "capital_allocated": 1000.0, "action": "BUY", "regime": "Trending Bull"}
    rl.process_trade_outcome(loss_result, diverse_breakdown)  # T1 (loss)
    rl.process_trade_outcome(loss_result, diverse_breakdown)  # T2 (loss)
    rl.process_trade_outcome(loss_result, diverse_breakdown)  # T3 (loss, TD flush fires here)
    # Isolate trade 4's update
    rl._batch_weight_deltas["Trending Bull"]["Technical Analyst"] = 0.0
    rl.process_trade_outcome(loss_result, diverse_breakdown)  # T4 (loss)
    t_analyst_delta_t4 = rl._batch_weight_deltas["Trending Bull"]["Technical Analyst"]
    # Expected: sharpe = clip(-10/1, ±5) = -5; equity walk 100→90→80→70→60 (peak 100)
    #   max_dd = 40% → penalty 12.0 → reward_base = -17.0
    #   lr = 0.005 * 2.0 (win rate 0% < 40%) = 0.01
    #   delta = -17.0 * 0.01 * 1.0 * 0.5 = -0.085 (agreed with losing BUY)
    expected_t4 = -17.0 * 0.01 * 1.0 * 0.5
    print(f"Technical Analyst delta on T4 (isolated): {t_analyst_delta_t4:.4f} (Expected: {expected_t4:.4f})")
    assert abs(t_analyst_delta_t4 - expected_t4) < 0.02, "Adaptive learning rate boost not applied correctly"
    print("[OK] Adaptive learning rate boost check passed.")

    # 6. Retraining Trigger Frequency (every 5 trades)
    rl = ReinforcementLearningEngine()
    assert rl.retrain_count == 0, "Initial retrain count must be 0"
    t1_result = {"profit_loss": 100.0, "capital_allocated": 1000.0, "action": "BUY", "regime": "Trending Bull"}
    for _ in range(5):
        rl.process_trade_outcome(t1_result, diverse_breakdown)
    print(f"Retrain count after 5 trades: {rl.retrain_count} (Expected: 1)")
    assert rl.retrain_count == 1, "Should trigger retrain after 5 trades"
    print("[OK] Retraining trigger frequency check passed.")

    print("\nALL TIER 1 RL UPGRADES TESTED AND VERIFIED SUCCESSFULLY!")


if __name__ == "__main__":
    test_tier1_rl()
