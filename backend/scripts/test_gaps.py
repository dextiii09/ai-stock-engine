import sys
import os
import asyncio
import numpy as np
import pandas as pd

# Reconfigure stdout to use UTF-8 to prevent encoding crashes on Windows console when printing greek symbols (e.g. sigma)
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.ingestion import run_boruta_feature_selection
from analytics.simulator import AITradeSimulator
from execution.smart_execution import SmartExecutionEngine
from data.cot_client import COTClient

async def run_tests():
    print("=== Testing Core Architectural Gaps ===")

    # ----------------------------------------------------
    # 1. Test Boruta Feature Selection
    # ----------------------------------------------------
    print("\n--- 1. Testing Boruta Feature Selection ---")
    np.random.seed(42)
    # Generate synthetic dataset: 100 samples, 6 features
    # f1 and f2 are highly correlated with target, others are noise
    X_data = np.random.randn(100, 6)
    y_data = X_data[:, 0] * 3.0 + X_data[:, 1] * 2.0 + np.random.randn(100) * 0.1
    
    feature_names = [f"feat_{i}" for i in range(6)]
    X = pd.DataFrame(X_data, columns=feature_names)
    y = pd.Series(y_data)
    
    selected_features = run_boruta_feature_selection(X, y, max_iter=10, random_state=42)
    print(f"Boruta Selected Features: {selected_features}")
    # Check that it returns a list and doesn't crash
    assert isinstance(selected_features, list), "Boruta must return a list of selected features"
    assert "feat_0" in selected_features, "Boruta failed to select the most significant feature"
    print("[OK] Boruta Feature Selection passed.")

    # ----------------------------------------------------
    # 2. Test AITradeSimulator Short Setup EV Inversion
    # ----------------------------------------------------
    print("\n--- 2. Testing AITradeSimulator Short Setup ---")
    sim = AITradeSimulator(simulations=500)
    
    # In a SHORT position:
    # entry = 100.0, take_profit = 90.0 (below entry), stop_loss = 105.0 (above entry)
    # expected reward = entry - TP = 10.0
    # expected risk = SL - entry = 5.0
    res = sim.simulate(
        current_price=100.0,
        stop_loss=105.0,
        take_profit=90.0,
        symbol="MNQ=F",
        direction="SHORT"
    )
    print(f"Short Simulation Result: {res}")
    assert "is_viable" in res, "Simulation result must contain is_viable flag"
    assert "expected_value" in res, "Simulation result must contain expected_value metric"
    print("[OK] AITradeSimulator Short Setup passed.")

    # ----------------------------------------------------
    # 3. Test SmartExecutionEngine Long and Short Lifecycles
    # ----------------------------------------------------
    print("\n--- 3. Testing SmartExecutionEngine ---")
    engine = SmartExecutionEngine()
    
    # Mock simulator inside engine to always pass and return static values
    engine.simulator.simulate = lambda **kwargs: {
        "is_viable": True,
        "expected_value": 15.0,
        "win_probability": 65.0,
        "annual_volatility_used": 20.0,
        "simulations": 100,
        "reason": "Mocked simulator"
    }
    
    # Start clean: clear existing active holdings to isolate the test
    engine.active_holdings = []
    engine.portfolio_balance = 100000.0
    initial_balance = engine.portfolio_balance
    
    print(f"Initial Balance: ${initial_balance:.2f}")
    
    # 3a. Open a SHORT position
    decision_sell = {
        "signal": "SELL",
        "confidence": 0.85,
        "reason": "Test short open",
        "regime": "Trending Bear",
        "session_quality": "NORMAL"
    }
    
    success, reason = await engine.execute_trade("MNQ=F", 20000.0, decision_sell)
    print(f"Open SHORT: Success={success}, Reason={reason}")
    assert success, "Failed to execute SHORT trade"
    assert len(engine.active_holdings) == 1, "Should have 1 active holding"
    
    short_holding = engine.active_holdings[0]
    assert short_holding["direction"] == "SHORT", "Holding direction should be SHORT"
    print(f"Opened SHORT Position: {short_holding}")
    
    # Verify portfolio balance decreased (allocated collateral/margin)
    post_short_balance = engine.portfolio_balance
    print(f"Balance after SHORT open: ${post_short_balance:.2f}")
    assert post_short_balance < initial_balance, "Balance should decrease after opening short position"

    # 3b. Close SHORT position (Buy to Cover) at a profit (price dropped from 20000 to 19500)
    decision_buy = {
        "signal": "BUY",
        "confidence": 0.85,
        "reason": "Test cover profit",
        "regime": "Trending Bear",
        "session_quality": "NORMAL"
    }
    
    success, reason = await engine.execute_trade("MNQ=F", 19500.0, decision_buy)
    print(f"Buy to Cover (Profit): Success={success}, Reason={reason}")
    assert success, "Failed to execute BUY to COVER trade"
    assert len(engine.active_holdings) == 0, "Holdings list should be empty"
    
    # Verify profit is credited to the balance
    final_balance = engine.portfolio_balance
    print(f"Balance after Cover: ${final_balance:.2f}")
    assert final_balance > initial_balance, f"Cover at profit should increase balance (Final: {final_balance}, Initial: {initial_balance})"
    
    # Check closed trade records
    assert len(engine.closed_trades) > 0, "Closed trades should not be empty"
    last_closed = engine.closed_trades[-1]
    assert last_closed["direction"] == "SHORT", "Closed trade direction should be SHORT"
    assert last_closed["profit_loss"] > 0, "Closed trade profit should be positive"
    print(f"Closed Trade Record: {last_closed}")

    # ----------------------------------------------------
    # 4. Test CFTC COT Client Robustness
    # ----------------------------------------------------
    print("\n--- 4. Testing CFTC COT API Client ---")
    cot = COTClient()
    # Fetch positioning - should succeed or fallback gracefully without raising an exception
    nq_pos = cot.get_nq_positioning()
    print(f"NQ COT Positioning: {nq_pos}")
    assert "positioning" in nq_pos, "COT response should contain positioning flag"
    
    gold_pos = cot.get_gold_positioning()
    print(f"Gold COT Positioning: {gold_pos}")
    assert "positioning" in gold_pos, "COT response should contain positioning flag"
    
    print("[OK] CFTC COT Client check passed.")

if __name__ == "__main__":
    asyncio.run(run_tests())
