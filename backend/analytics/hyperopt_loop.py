"""
Hyperparameter Auto-Reoptimization Loop
Walk-forward Bayesian optimization that re-tunes:
  - Regime thresholds (4 params)
  - RL learning rate and decay factor (2 params)

Strategy: use closed_trades from rl_state.json as the evaluation set.
For each candidate hyperparameter set, simulate which trades would have
been accepted (based on the RL conviction that produced them) and compute:
  - Profit Factor = gross_profit / abs(gross_loss)
  - Sharpe-like score = mean_pnl / std_pnl * sqrt(N)

Optuna (Bayesian) is used when available, falling back to random search.

API:
  run_hyperopt(trades, rl_state, n_trials=80) -> best_params dict
  apply_and_save(best_params)                 -> writes hyperparams.json
"""

import os
import json
import math
import random
import threading
import time
from typing import Dict, List, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
HYPERPARAMS_PATH = os.path.join(BASE_DIR, "data", "hyperparams.json")
RL_STATE_PATH    = os.path.join(BASE_DIR, "data", "rl_state.json")

# Bounds for optimization, centered on the values master.py's own comments
# derive from the committee math (e.g. "3 agents at 0.63 avg -> 0.378 ~ just
# fires"): Trending Bull 0.38, Sideways 0.45, Trending Bear 0.41,
# High Volatility 0.49. Previously these floors sat AT OR ABOVE that
# calibrated baseline (0.45/0.52/0.40/0.45), so the optimizer could only ever
# push thresholds higher than what actually works, never back down to it —
# confirmed live: it drifted to 0.45/0.52/0.48/0.56 and AI Committee stopped
# generating trades in both backtests and live Normal-mode trading. Bounds
# now span calibrated-baseline minus headroom to calibrated-baseline plus
# headroom, so re-optimization can explore in both directions instead of
# only ratcheting upward. Upper end still caps well short of "never trades".
PARAM_BOUNDS = {
    "trending_bull_threshold":  (0.28, 0.50),
    "sideways_threshold":       (0.35, 0.58),
    "trending_bear_threshold":  (0.31, 0.53),
    "high_volatility_threshold":(0.39, 0.62),
    "learning_rate":            (0.0001, 0.005),
    "decay_factor":             (0.88, 0.999),
}

# Module-level status for polling
_status: Dict[str, Any] = {
    "running": False,
    "last_run": None,
    "last_result": None,
    "progress": 0,
    "total_trials": 0,
    "best_score": None,
    "error": None,
}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Score function
# ---------------------------------------------------------------------------

def _score_params(
    params: Dict[str, float],
    trades: List[Dict],
    rl_history: List[Dict],
) -> float:
    """
    Given a candidate threshold set, simulate filtering past trades.

    Each trade in rl_history has:
      {regime, conviction, outcome_pnl}   (conviction = weighted score at entry)

    We filter to trades where conviction > regime threshold.
    Then compute profit_factor * sqrt(n_trades) as the objective.
    Returns -inf if no trades pass the filter.
    """
    thresholds = {
        "Trending Bull":   params["trending_bull_threshold"],
        "Sideways":        params["sideways_threshold"],
        "Trending Bear":   params["trending_bear_threshold"],
        "High Volatility": params["high_volatility_threshold"],
    }

    accepted_pnl = []
    for entry in rl_history:
        regime    = entry.get("regime", "Sideways")
        conviction = entry.get("conviction", 0.0)
        pnl       = entry.get("outcome_pnl", 0.0)
        thresh    = thresholds.get(regime, 0.75)
        if conviction >= thresh:
            accepted_pnl.append(pnl)

    if len(accepted_pnl) < 5:
        return -float("inf")

    gross_profit = sum(p for p in accepted_pnl if p > 0)
    gross_loss   = abs(sum(p for p in accepted_pnl if p < 0))
    pf = gross_profit / max(gross_loss, 1e-9)

    mean_pnl = sum(accepted_pnl) / len(accepted_pnl)
    var_pnl  = sum((p - mean_pnl) ** 2 for p in accepted_pnl) / max(len(accepted_pnl) - 1, 1)
    if var_pnl < 1e-12:
        return 0.01  # all trades identical — no useful signal
    std_pnl  = math.sqrt(var_pnl) if var_pnl > 0 else 1e-9
    sharpe   = mean_pnl / std_pnl * math.sqrt(len(accepted_pnl))

    return pf * max(sharpe, 0.01)


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def _load_rl_history() -> List[Dict]:
    """
    Loads trade history from rl_state.json.
    Each entry needs {regime, conviction, outcome_pnl}.
    If not present, we use the raw _trade_history list.
    """
    if not os.path.exists(RL_STATE_PATH):
        return []
    try:
        with open(RL_STATE_PATH) as f:
            state = json.load(f)
        raw = state.get("_trade_history", [])
        result = []
        for t in raw:
            if isinstance(t, dict):
                result.append({
                    "regime":      t.get("regime", "Sideways"),
                    "conviction":  float(t.get("conviction", t.get("confidence", 0.0))),
                    "outcome_pnl": float(t.get("outcome_pnl", t.get("pnl", 0.0))),
                })
        return result
    except Exception:
        return []


def _load_current_params() -> Dict[str, float]:
    # Safe defaults — MUST match master.py's actual calibrated baseline
    # (regime_thresholds in MasterAgent.__init__), not an arbitrarily higher
    # guess. These previously were 0.68/0.62/0.55/0.65, well above the
    # calibrated 0.38/0.45/0.41/0.49 baseline, so any fallback to "defaults"
    # (e.g. missing/corrupt hyperparams.json) silently made the bot far more
    # conservative than intended. Used when hyperparams.json is missing/corrupt.
    defaults = {
        "trending_bull_threshold":   0.38,
        "sideways_threshold":        0.45,
        "trending_bear_threshold":   0.41,
        "high_volatility_threshold": 0.49,
        "learning_rate":             0.003,
        "decay_factor":              0.945,
    }
    if not os.path.exists(HYPERPARAMS_PATH):
        return defaults
    try:
        with open(HYPERPARAMS_PATH) as f:
            data = json.load(f)
        defaults.update(data)
        return defaults
    except Exception:
        return defaults


# ---------------------------------------------------------------------------
# Optimization engines
# ---------------------------------------------------------------------------

def _random_params() -> Dict[str, float]:
    return {
        k: random.uniform(lo, hi)
        for k, (lo, hi) in PARAM_BOUNDS.items()
    }


def _run_optuna(rl_history: List[Dict], n_trials: int) -> Dict[str, float]:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            k: trial.suggest_float(k, lo, hi)
            for k, (lo, hi) in PARAM_BOUNDS.items()
        }
        return _score_params(params, [], rl_history)

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, n_jobs=1)
    return study.best_params


def _run_random_search(rl_history: List[Dict], n_trials: int) -> Dict[str, float]:
    best_score = -float("inf")
    best_params = _load_current_params()

    for i in range(n_trials):
        params = _random_params()
        score  = _score_params(params, [], rl_history)
        if score > best_score:
            best_score = score
            best_params = params

        with _lock:
            _status["progress"] = i + 1
            _status["best_score"] = best_score

    return best_params


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_hyperopt(n_trials: int = 80) -> Dict[str, float]:
    """
    Synchronous optimization. Returns the best params dict.
    Tries Optuna first; falls back to random search.
    """
    rl_history = _load_rl_history()
    if len(rl_history) < 10:
        return _load_current_params()

    with _lock:
        _status["running"] = True
        _status["progress"] = 0
        _status["total_trials"] = n_trials
        _status["error"] = None

    try:
        try:
            import optuna  # noqa: F401
            best = _run_optuna(rl_history, n_trials)
        except ImportError:
            best = _run_random_search(rl_history, n_trials)

        with _lock:
            _status["running"] = False
            _status["last_run"] = time.time()
            _status["last_result"] = best
            _status["best_score"] = _score_params(best, [], rl_history)

        return best

    except Exception as e:
        with _lock:
            _status["running"] = False
            _status["error"] = str(e)
        raise


def apply_and_save(params: Dict[str, float]) -> None:
    """Write best_params to hyperparams.json."""
    current = _load_current_params()
    current.update(params)
    with open(HYPERPARAMS_PATH, "w") as f:
        json.dump(current, f, indent=4)
    print(f"[HyperOpt] Saved new hyperparams: {params}")


def run_and_save(n_trials: int = 80) -> Dict[str, float]:
    """Convenience: optimize + save in one call."""
    best = run_hyperopt(n_trials)
    apply_and_save(best)
    return best


def get_status() -> Dict[str, Any]:
    with _lock:
        return dict(_status)


# ---------------------------------------------------------------------------
# Background scheduler — runs monthly
# ---------------------------------------------------------------------------

_scheduler_thread: Optional[threading.Thread] = None
_INTERVAL_SECONDS = 30 * 24 * 3600   # 30 days


def start_scheduler(interval_seconds: int = _INTERVAL_SECONDS) -> None:
    """
    Starts a background daemon thread that re-optimizes hyperparams monthly.
    Safe to call multiple times — only one thread runs.
    """
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        return

    def _loop():
        # Wait 10 min after boot before first auto-run (don't slow startup)
        time.sleep(600)
        while True:
            try:
                print("[HyperOpt] Starting scheduled walk-forward optimization...")
                run_and_save(n_trials=80)
                print("[HyperOpt] Optimization complete. Sleeping for next cycle.")
            except Exception as e:
                print(f"[HyperOpt] Scheduled run failed: {e}")
            time.sleep(interval_seconds)

    _scheduler_thread = threading.Thread(target=_loop, daemon=True, name="hyperopt-scheduler")
    _scheduler_thread.start()
    print(f"[HyperOpt] Scheduler started. Interval: {interval_seconds // 86400} days.")
