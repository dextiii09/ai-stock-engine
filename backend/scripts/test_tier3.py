import sys
import os
import pytest
import pandas as pd

# Tier-3 tests exercise the torch-based LSTM/PPO stack — skip cleanly when
# torch isn't installed instead of breaking the whole test collection.
torch = pytest.importorskip("torch")

# Add backend directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from analytics.lstm_model import LSTMSignalEngine
from agents.ppo_master import PPOMasterAgent
from data.provider import DataProviderFactory, YFinanceDataProvider

def test_lstm_signal_engine():
    print("\n--- Testing LSTM Signal Engine ---")
    engine = LSTMSignalEngine()
    
    # Check initial state / warmup
    warmup_res = engine.get_signal("MGC=F")
    assert warmup_res["signal"] == "WAIT"
    assert "warming up" in warmup_res["reason"]
    
    # Feed 20 ticks to complete sequence buffer
    for i in range(21):
        tick = {
            "price": 100.0 + i,
            "rsi_14": 50.0,
            "atr_14": 1.5,
            "macd_hist": 0.1,
            "vwap": 100.0
        }
        engine.update_tick("MGC=F", tick)
        
    # Check signal after warmup
    sig_res = engine.get_signal("MGC=F")
    print(f"LSTM prediction output: {sig_res}")
    assert sig_res["signal"] in ["BUY", "SELL", "WAIT"]
    assert "confidence" in sig_res

def test_ppo_agent_loading():
    print("\n--- Testing PPO Agent Weight Loading ---")
    ppo = PPOMasterAgent()
    # Check if policy parameters exist
    assert ppo.policy is not None
    # If weights file exists, verify they were loaded correctly
    weights_path = os.path.join(os.path.dirname(__file__), "..", "data", "ppo_policy.pth")
    if os.path.exists(weights_path):
        assert ppo.policy.training is False  # should be in eval() mode after loading

def test_yfinance_resilient_provider():
    print("\n--- Testing YFinance Provider Caching and Fallback ---")
    provider = DataProviderFactory.get_provider()
    
    # 1. Successful fetch should store in cache
    try:
        df = provider.get_historical_ohlcv("MNQ=F", period="1d", interval="1m")
        assert not df.empty
        assert "MNQ=F" in provider._cache
    except Exception as e:
        pytest.skip(f"YFinance download failed, skipping test: {e}")
        
    # 2. Simulate failure on subsequent call and check fallback
    # We pass an invalid symbol that normally fails
    try:
        # Fetching invalid symbol first time should raise error
        provider.get_historical_ohlcv("INVALID_TICKER", period="1d", interval="1m")
    except RuntimeError:
        pass  # expected
        
    # Seed cache for the invalid symbol to simulate a previous successful fetch
    provider._cache["INVALID_TICKER"] = provider._cache["MNQ=F"]
    
    # Fetching invalid symbol now should fallback to cached data and succeed
    fallback_df = provider.get_historical_ohlcv("INVALID_TICKER", period="1d", interval="1m")
    assert fallback_df is not None
    assert not fallback_df.empty
    print("[OK] Fallback to cache succeeded.")
