"""
Phase 2 — Meta-Labeling (scoped to BTC-USD).

Phase 1 result that justified this build: BTC-USD showed mean AUC 0.587 with
monotonically-improving folds (0.54/0.60/0.62, n=1816), driven by VIX term
structure and yield spread. All other symbols were coin flips, so this is
built for BTC ONLY. Selection-risk caveat: BTC was the best of 5 tested
symbols; Phase 3 (CPCV + Deflated Sharpe) must confirm before any live use.

What meta-labeling is here:
  * Primary signal: "a LONG entered at next bar's open" (the same trade the
    live engine takes when the committee says BUY).
  * Meta-model: RandomForest trained on the economic features to predict
    P(profit barrier is hit before stop barrier) — i.e. P(the primary trade
    wins). The gate then only allows trades whose predicted P(win) clears a
    threshold; sizing can also scale with P.

The evaluation that matters is NOT AUC — it is EXPECTANCY UPLIFT:
  E[R] of gated trades vs E[R] of all trades, out-of-sample, plus a
  calibration table (do predicted probabilities match realized win rates?).
"""
import os
from typing import Dict, Any

import numpy as np
import pandas as pd

from analytics.feature_lab import build_dataset, HORIZON

MODEL_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "models")
MODEL_PATH = os.path.join(MODEL_DIR, "meta_btc.joblib")


def get_model_path(symbol: str) -> str:
    """Returns the joblib artifact path for a given symbol."""
    clean = symbol.replace(".", "_").replace("-", "_").replace("^", "").lower()
    return os.path.join(MODEL_DIR, f"meta_{clean}.joblib")


TRAIN_FRAC = 0.70          # first 70% train, embargo, last ~30% test
THRESHOLDS = [0.50, 0.55, 0.60]


def _fit_model(X: pd.DataFrame, y: pd.Series):
    from sklearn.ensemble import RandomForestClassifier
    clf = RandomForestClassifier(
        n_estimators=400, max_depth=4, min_samples_leaf=50,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    clf.fit(X, y)
    return clf


def train_and_evaluate(symbol: str = "BTC-USD", period: str = "5y",
                       save_model: bool = True) -> Dict[str, Any]:
    """Train on the first 70% (with an embargo gap), evaluate expectancy
    uplift and probability calibration on the untouched last 30%."""
    from sklearn.metrics import roc_auc_score

    data = build_dataset(symbol, period)
    if data is None or len(data) < 500:
        return {"symbol": symbol, "error": "insufficient data"}

    y  = data["label"].astype(int)
    r  = data["realized_r"]
    X  = data.drop(columns=["label", "realized_r"])

    n        = len(data)
    tr_end   = int(TRAIN_FRAC * n)
    te_start = tr_end + HORIZON            # embargo: no label overlap
    Xtr, ytr = X.iloc[:tr_end], y.iloc[:tr_end]
    Xte, yte = X.iloc[te_start:], y.iloc[te_start:]
    rte      = r.iloc[te_start:]

    clf = _fit_model(Xtr, ytr)
    p   = pd.Series(clf.predict_proba(Xte)[:, 1], index=Xte.index)

    out: Dict[str, Any] = {
        "symbol": symbol, "rows": n,
        "train_rows": len(Xtr), "test_rows": len(Xte),
        "test_auc": round(float(roc_auc_score(yte, p)), 4) if yte.nunique() > 1 else None,
        "baseline": {
            "n_trades":  int(len(rte)),
            "win_rate":  round(float(yte.mean()), 3),
            "exp_R":     round(float(rte.mean()), 4),   # E[R] taking EVERY trade
        },
        "gates": {},
        "calibration": [],
    }

    # Gate evaluation: expectancy of only the trades the meta-model allows.
    for th in THRESHOLDS:
        mask = p >= th
        sel  = rte[mask]
        out["gates"][str(th)] = {
            "n_trades":  int(mask.sum()),
            "pct_taken": round(float(mask.mean() * 100), 1),
            "win_rate":  round(float(yte[mask].mean()), 3) if mask.sum() else None,
            "exp_R":     round(float(sel.mean()), 4) if mask.sum() else None,
        }

    # Calibration: within each predicted-probability quintile, does the
    # realized win rate rise accordingly? (If not, probabilities are fiction.)
    try:
        q = pd.qcut(p, 5, duplicates="drop")
        for interval, grp in yte.groupby(q, observed=True):
            out["calibration"].append({
                "p_range":  str(interval),
                "n":        int(len(grp)),
                "realized_win_rate": round(float(grp.mean()), 3),
                "exp_R":    round(float(rte[grp.index].mean()), 4),
            })
    except Exception:
        pass

    if save_model:
        try:
            import joblib
            os.makedirs(MODEL_DIR, exist_ok=True)
            target_path = get_model_path(symbol)
            joblib.dump({"model": clf, "features": list(X.columns),
                         "symbol": symbol, "trained_rows": len(Xtr)}, target_path)
            # Also maintain meta_btc.joblib as alias if BTC
            if symbol.upper() == "BTC-USD":
                joblib.dump({"model": clf, "features": list(X.columns),
                             "symbol": symbol, "trained_rows": len(Xtr)}, MODEL_PATH)
            out["model_saved"] = target_path
        except Exception as e:
            out["model_saved"] = f"FAILED: {e}"

    return out
