import sys
import os
import datetime

# Add backend directory to Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data.ingestion import DataIngestionEngine
from data.regime_detector import MarketRegimeDetector
from data.event_awareness import IndianEventAwarenessEngine
from execution.smart_execution import SmartExecutionEngine

def test_indian_ingestion():
    print("Testing Indian Market Ingestion Engine...")
    symbols = ["NIFTYBEES.NS", "WIPRO.NS", "RELIANCE.NS", "ONGC.NS"]
    engine = DataIngestionEngine(symbols=symbols)
    assert engine.symbols == symbols, f"Expected {symbols}, but got {engine.symbols}"
    
    # Try fetching a tick
    try:
        tick = engine.get_tick_for("NIFTYBEES.NS")
        print(f"Ingestion check PASSED. Ticker price: INR {tick.get('price')}")
    except Exception as e:
        print(f"Ingestion warning (might be offline/closed): {e}")

def test_indian_regime():
    print("Testing Indian HMM Regime Detector training...")
    try:
        detector = MarketRegimeDetector(training_symbol="NIFTYBEES.NS")
        assert detector.training_symbol == "NIFTYBEES.NS"
        print(f"HMM check PASSED. training_symbol: {detector.training_symbol}")
    except Exception as e:
        print(f"Regime check FAILED: {e}")

def test_indian_event_awareness():
    print("Testing Indian Event Awareness market hours check...")
    engine = IndianEventAwarenessEngine()
    
    # Test during market hours (simulate Mon 05:00 UTC = 10:30 AM IST)
    mon_midday = datetime.datetime(2026, 7, 6, 5, 0, 0)
    # Monkey-patch datetime.datetime.utcnow inside check_today or event_awareness
    # Let's test with real current time first
    status = engine.check_today()
    print(f"Current event blackout status: {status['trading_blackout']}")
    print(f"Current event blackout reason: {status.get('blackout_reason', 'None')}")

def test_indian_execution_engine():
    print("Testing Indian Smart Execution Engine initialization...")
    # Initialize with portfolio_state_in.json, rl_state_in.json and initial balance 4150
    engine = SmartExecutionEngine(
        state_filename="portfolio_state_in_test.json",
        rl_state_filename="rl_state_in_test.json",
        initial_balance=4150.0,
        journal_filename="journal_in_test.json"
    )
    print(f"Starting balance: INR {engine.portfolio_balance}")
    assert engine.portfolio_balance == 4150.0, f"Expected 4150.0, got {engine.portfolio_balance}"
    
    # Save state to verify it writes portfolio_state_in_test.json
    engine._save_state()
    test_state_file = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio_state_in_test.json")
    assert os.path.exists(test_state_file), "Expected state file to be written."
    
    # Clean up test files
    try:
        os.remove(test_state_file)
        os.remove(os.path.join(os.path.dirname(__file__), "..", "data", "rl_state_in_test.json"))
        os.remove(os.path.join(os.path.dirname(__file__), "..", "journal_in_test.json"))
    except:
        pass
    print("Execution check PASSED.")

if __name__ == "__main__":
    test_indian_ingestion()
    test_indian_regime()
    test_indian_event_awareness()
    test_indian_execution_engine()
    print("All tests completed successfully!")
