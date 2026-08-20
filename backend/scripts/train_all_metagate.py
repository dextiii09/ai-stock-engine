"""
Train and deploy MetaGate Veto Models for Multi-Asset universe:
  - Crypto: BTC-USD
  - Indian Equities / Index: NIFTYBEES.NS, RELIANCE.NS
  - US Equities / Index: SPY, NVDA
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analytics.meta_label import train_and_evaluate

SYMBOLS_TO_TRAIN = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "SPY",
    "NVDA",
    "AAPL",
    "MSFT",
    "MNQ=F",
    "MGC=F",
    "EURUSD=X",
    "GBPUSD=X",
    "NIFTYBEES.NS",
    "RELIANCE.NS",
    "HDFCBANK.NS",
]


def run_all_training():
    print("=== Starting MetaGate Multi-Asset Training ===")
    results = {}
    for sym in SYMBOLS_TO_TRAIN:
        print(f"\n--- Training MetaGate for {sym} ---")
        try:
            res = train_and_evaluate(symbol=sym, period="5y", save_model=True)
            if "error" in res:
                print(f"[{sym}] Skipped / Error: {res['error']}")
            else:
                auc = res.get("test_auc")
                base_wr = res.get("baseline", {}).get("win_rate")
                base_r = res.get("baseline", {}).get("exp_R")
                print(f"[{sym}] Trained rows: {res.get('train_rows')}, Test AUC: {auc}")
                print(f"[{sym}] Baseline Win Rate: {base_wr}, Baseline E[R]: {base_r}")
                print(f"[{sym}] Saved artifact -> {res.get('model_saved')}")
            results[sym] = res
        except Exception as e:
            print(f"[{sym}] Failed to train: {e}")
            results[sym] = {"error": str(e)}

    print("\n=== Training Complete ===")

if __name__ == "__main__":
    run_all_training()
