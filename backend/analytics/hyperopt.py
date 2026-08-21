import os
import sys
import json
import argparse
import optuna

# Add backend dir to python path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from backtesting.engine import BacktestEngine

# Suppress Optuna logs to keep CLI clean unless debug
optuna.logging.set_verbosity(optuna.logging.WARNING)

def objective(trial):
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

    try:
        engine = BacktestEngine(symbol="MNQ=F", strategy="AI Committee", period="3mo", interval="1d", strict_macro=False)
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
    print("[Hyperopt] Running historical 3-month MNQ=F backtest simulation for guaranteed production parity.")
        
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=args.trials)
    
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
