import os
import sys
import json
import argparse
import numpy as np
import optuna

# Add backend dir to python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

try:
    from database.database import AsyncSessionLocal
    from database.models import Portfolio
except ImportError:
    pass

from backtesting.engine import BacktestEngine
from analytics.rl_engine import ReinforcementLearningEngine
from agents.master import MasterAgent

# Suppress Optuna logs to keep CLI clean unless debug
optuna.logging.set_verbosity(optuna.logging.WARNING)

def load_live_trades_and_journal() -> tuple[list, list]:
    """Attempts to load closed trades and matching journal entries from JSON/SQLite."""
    base_dir = os.path.join(os.path.dirname(__file__), "..")
    portfolio_path = os.path.join(base_dir, "data", "portfolio_state.json")
    journal_path = os.path.join(base_dir, "journal.json")
    
    closed_trades = []
    journal = []
    
    # 1. Load closed trades
    if os.path.exists(portfolio_path):
        try:
            with open(portfolio_path, "r") as f:
                state = json.load(f)
                closed_trades = state.get("closed_trades", [])
        except Exception as e:
            print(f"[Hyperopt] Error loading portfolio state JSON: {e}")
            
    # 2. Load journal
    if os.path.exists(journal_path):
        try:
            with open(journal_path, "r") as f:
                journal = json.load(f)
        except Exception as e:
            print(f"[Hyperopt] Error loading journal JSON: {e}")
            
    return closed_trades, journal

def objective(trial, closed_trades, journal):
    # Suggest hyperparameters
    learning_rate = trial.suggest_float("learning_rate", 1e-4, 1e-1, log=True)
    decay_factor = trial.suggest_float("decay_factor", 0.80, 0.999)
    
    # Thresholds capped at 0.75 — above this the bot effectively never trades
    tb_th    = trial.suggest_float("trending_bull_threshold",   0.52, 0.72)
    s_th     = trial.suggest_float("sideways_threshold",        0.52, 0.68)
    tbear_th = trial.suggest_float("trending_bear_threshold",   0.50, 0.65)
    hv_th    = trial.suggest_float("high_volatility_threshold", 0.52, 0.70)
    
    thresholds = {
        "Trending Bull": tb_th,
        "Sideways": s_th,
        "Trending Bear": tbear_th,
        "High Volatility": hv_th
    }
    
    # If we have enough live trades, simulate on live trade history
    if len(closed_trades) >= 5:
        # Match trades with journal entries
        matched = []
        buy_logs = [log for log in journal if log.get("action") == "BUY"]
        
        for trade in closed_trades:
            symbol = trade.get("symbol")
            trade_time = trade.get("time", 0)
            
            # Find closest BUY log before close
            best_match = None
            min_diff = float("inf")
            for log in buy_logs:
                log_time = log.get("timestamp", 0)
                if log.get("symbol") == symbol and log_time < trade_time:
                    diff = trade_time - log_time
                    if diff < min_diff:
                        min_diff = diff
                        best_match = log
            if best_match:
                matched.append((trade, best_match))
                
        if len(matched) >= 5:
            # Simulate RL weights and threshold checks sequentially
            rl_engine = ReinforcementLearningEngine()
            rl_engine.learning_rate = learning_rate
            rl_engine.decay_factor = decay_factor
            
            # Simulated equity curve starting at $100,000
            balance = 100000.0
            equity_curve = [balance]
            
            for trade, entry_log in matched:
                regime = entry_log.get("regime", "Sideways")
                th = thresholds.get(regime, 0.80)
                
                # Check if decision would have cleared the simulated thresholds
                # Calculate conviction using simulated RL weights
                breakdown = entry_log.get("committee_breakdown", [])
                agent_weights = rl_engine.get_current_weights(regime)
                
                buy_weight = 0.0
                sell_weight = 0.0
                for vote in breakdown:
                    agent = vote.get("agent")
                    sig = vote.get("signal", "WAIT")
                    conf = vote.get("confidence", 0.0)
                    weight = agent_weights.get(agent, 1.0)
                    
                    if sig == "BUY":
                        buy_weight += conf * weight
                    elif sig == "SELL":
                        sell_weight += conf * weight
                        
                total_weight = sum(agent_weights.get(v.get("agent"), 1.0) for v in breakdown)
                if total_weight <= 0:
                    total_weight = len(breakdown) if breakdown else 1.0
                    
                buy_conv = buy_weight / total_weight
                sell_conv = sell_weight / total_weight
                
                # Was this a buy trade?
                is_buy = trade.get("net_pnl", 0) >= 0 or True # assume matched is taken
                clears_th = buy_conv > th if is_buy else sell_conv > th
                
                if clears_th:
                    # Trade is taken, apply actual returns
                    ret = trade.get("profit_pct", 0.0) / 100.0
                    pnl = balance * 0.1 * ret  # assume 10% sizing
                    balance += pnl
                    
                    # Update weights
                    rl_outcome = {
                        "profit_loss": pnl,
                        "capital_allocated": balance * 0.1,
                        "action": "BUY" if is_buy else "SELL",
                        "regime": regime
                    }
                    rl_engine.process_trade_outcome(rl_outcome, breakdown)
                else:
                    # Skipped trade, balance stays flat
                    pass
                equity_curve.append(balance)
                
            # Compute Sharpe Ratio of equity curve returns
            returns = [(equity_curve[j] - equity_curve[j-1]) / equity_curve[j-1] for j in range(1, len(equity_curve))]
            avg_ret = np.mean(returns) if returns else 0.0
            std_ret = np.std(returns) if returns else 1.0
            sharpe = (avg_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0
            return sharpe

    # Fallback: run simulated backtest on Nasdaq Micro Futures (MNQ=F)
    try:
        engine = BacktestEngine(symbol="MNQ=F", strategy="AI Committee", period="3mo", interval="1d")
        # Overwrite defaults
        engine.rl_engine.learning_rate = learning_rate
        engine.rl_engine.decay_factor = decay_factor
        engine.master_agent.regime_thresholds = thresholds
        
        res = engine.run()
        if "error" in res:
            return -100.0
            
        # Target Sharpe Ratio
        return res.get("sharpe_ratio", 0.0)
    except Exception as e:
        print(f"[Hyperopt] Trial exception: {e}")
        return -100.0

def main():
    parser = argparse.ArgumentParser(description="Optuna-based Bayesian parameter tuning.")
    parser.add_argument("--trials", type=int, default=50, help="Number of trials to run.")
    args = parser.parse_args()
    
    print(f"=== Starting Bayesian Parameter Tuning ({args.trials} trials) ===")
    
    # Load data
    closed_trades, journal = load_live_trades_and_journal()
    if len(closed_trades) >= 5:
        print(f"[Hyperopt] Found {len(closed_trades)} closed trades. Running optimization against live trade history.")
    else:
        print("[Hyperopt] Insufficient live trades. Falling back to historical 3-month MNQ=F backtest simulation.")
        
    study = optuna.create_study(direction="maximize")
    study.optimize(lambda t: objective(t, closed_trades, journal), n_trials=args.trials)
    
    best_params = study.best_params
    best_value = study.best_value
    
    print(f"\nOptimization complete!")
    print(f"Best Trial Value (Sharpe): {best_value:.4f}")
    print("Optimal Parameters:")
    for k, v in best_params.items():
        print(f"  {k}: {v}")
        
    # Save parameters to hyperparams.json
    base_dir = os.path.join(os.path.dirname(__file__), "..")
    out_dir = os.path.join(base_dir, "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "hyperparams.json")
    
    with open(out_path, "w") as f:
        json.dump(best_params, f, indent=4)
        
    print(f"\nSaved optimal parameters to {os.path.abspath(out_path)}")

if __name__ == "__main__":
    main()
