import sys
import os
import json
import numpy as np

# Add backend directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from analytics.attribution import CausalAttributionEngine

def test_empty_or_missing_files():
    print("=== Testing with missing files ===")
    engine = CausalAttributionEngine(journal_path="nonexistent_j.json", portfolio_path="nonexistent_p.json")
    res = engine.analyze()
    print("Result:", res)
    assert res["agent_attribution"] == {}
    assert res["feature_correlation"] == {}

def test_actual_files():
    print("\n=== Testing with actual files ===")
    engine = CausalAttributionEngine()
    res = engine.analyze()
    print("Result status:", res.get("status"))
    print("Total analyzed trades:", res.get("total_analyzed_trades"))
    print("Agent attribution keys:", list(res.get("agent_attribution", {}).keys()))
    print("Feature correlation keys:", list(res.get("feature_correlation", {}).keys()))

def test_mocked_data_attribution():
    print("\n=== Testing with mocked trades and features ===")
    # Create temp files
    temp_journal = "temp_journal.json"
    temp_portfolio = "temp_portfolio.json"
    
    journal_data = [
        {
            "timestamp": 1000,
            "symbol": "AAPL",
            "action": "BUY",
            "committee_breakdown": [
                {"agent": "AgentA", "signal": "BUY"},
                {"agent": "AgentB", "signal": "SELL"},
                {"agent": "AgentC", "signal": "WAIT"}
            ],
            "entry_features": {
                "rsi_14": 30.0,
                "vix_level": 25.0
            }
        },
        {
            "timestamp": 2000,
            "symbol": "AAPL",
            "action": "BUY",
            "committee_breakdown": [
                {"agent": "AgentA", "signal": "BUY"},
                {"agent": "AgentB", "signal": "BUY"},
                {"agent": "AgentC", "signal": "WAIT"}
            ],
            "entry_features": {
                "rsi_14": 40.0,
                "vix_level": 20.0
            }
        },
        {
            "timestamp": 3000,
            "symbol": "AAPL",
            "action": "BUY",
            "committee_breakdown": [
                {"agent": "AgentA", "signal": "SELL"},
                {"agent": "AgentB", "signal": "BUY"},
                {"agent": "AgentC", "signal": "WAIT"}
            ],
            "entry_features": {
                "rsi_14": 70.0,
                "vix_level": 15.0
            }
        }
    ]
    
    portfolio_data = {
        "closed_trades": [
            {
                "symbol": "AAPL",
                "time": 1500,
                "profit_pct": 5.0,  # 5% profit
                "profit_loss": 500.0
            },
            {
                "symbol": "AAPL",
                "time": 2500,
                "profit_pct": 10.0,  # 10% profit
                "profit_loss": 1000.0
            },
            {
                "symbol": "AAPL",
                "time": 3500,
                "profit_pct": -2.0,  # -2% profit
                "profit_loss": -200.0
            }
        ]
    }
    
    base_dir = os.path.join(os.path.dirname(__file__), "..")
    j_path = os.path.join(base_dir, temp_journal)
    p_path = os.path.join(base_dir, temp_portfolio)
    
    try:
        with open(j_path, "w") as f:
            json.dump(journal_data, f)
        with open(p_path, "w") as f:
            json.dump(portfolio_data, f)
            
        engine = CausalAttributionEngine(journal_path=temp_journal, portfolio_path=temp_portfolio)
        res = engine.analyze()
        
        print("Success:", res["status"])
        print("Analyzed:", res["total_analyzed_trades"])
        print("Agent Attribution:")
        for agent, attr in res["agent_attribution"].items():
            print(f"  {agent}: {attr}")
            
        print("Feature Correlation:")
        for feat, corr in res["feature_correlation"].items():
            print(f"  {feat}: {corr}")
            
        # AgentA voted: BUY (+1) for +5% -> +5
        #               BUY (+1) for +10% -> +10
        #               SELL (-1) for -2% -> +2
        #               Total: 17.0, Avg: 5.667
        assert abs(res["agent_attribution"]["AgentA"]["total_attribution"] - 17.0) < 1e-5
        
        # AgentB voted: SELL (-1) for +5% -> -5
        #               BUY (+1) for +10% -> +10
        #               BUY (+1) for -2% -> -2
        #               Total: 3.0, Avg: 1.0
        assert abs(res["agent_attribution"]["AgentB"]["total_attribution"] - 3.0) < 1e-5
        
        # AgentC voted: WAIT (0) for all -> Total: 0.0
        assert abs(res["agent_attribution"]["AgentC"]["total_attribution"] - 0.0) < 1e-5
        
        # Let's verify Pearson correlation is computed
        # rsi_14: [30, 40, 70], returns: [5, 10, -2]
        # vix_level: [25, 20, 15], returns: [5, 10, -2]
        # np.corrcoef returns correct correlation
        expected_rsi_corr = np.corrcoef([30.0, 40.0, 70.0], [5.0, 10.0, -2.0])[0, 1]
        expected_vix_corr = np.corrcoef([25.0, 20.0, 15.0], [5.0, 10.0, -2.0])[0, 1]
        
        assert abs(res["feature_correlation"]["rsi_14"] - round(expected_rsi_corr, 3)) < 1e-5
        assert abs(res["feature_correlation"]["vix_level"] - round(expected_vix_corr, 3)) < 1e-5
        
    finally:
        if os.path.exists(j_path):
            os.remove(j_path)
        if os.path.exists(p_path):
            os.remove(p_path)
            
    print("Mock tests passed successfully!")

if __name__ == "__main__":
    test_empty_or_missing_files()
    test_actual_files()
    test_mocked_data_attribution()
    print("All tests passed.")
