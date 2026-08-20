"""
Phase 3 — Combinatorial Purged Cross-Validation (CPCV) + Deflated Sharpe
Ratio (DSR) for the BTC-USD meta-labeling gate.

Why this exists: Phase 2's single 70/30 split showed the p>=0.50 gate lifting
out-of-sample expectancy from -0.073R to +0.094R. One split can flatter one
regime, and this research program has already made selection choices
(5 symbols tested, 3 thresholds). CPCV tests the gate on MANY train/test
combinations with strict purging; DSR then asks: given how many things we
tried, how likely is a Sharpe this good under pure luck?

Method (Lopez de Prado, Advances in Financial ML, ch. 7 & 12 — simplified but
faithful on the two properties that matter: purging and combinatorics):
  * Split the series into N_GROUPS contiguous groups. Every C(N_GROUPS, 2)
    pair of groups serves once as the test set; the model trains on the rest.
  * PURGING: any training bar whose triple-barrier label window overlaps a
    test group (± an embargo of HORIZON bars) is dropped — no leakage.
  * Per split: train RF, gate test trades at p >= GATE, record net-of-cost
    E[R] and per-trade Sharpe.
  * DSR: probability that the aggregate out-of-sample Sharpe exceeds the
    expected-maximum Sharpe of N_TRIALS null strategies (accounts for
    non-normality via skew/kurtosis).

Costs: realized_r from feature_lab is gross. We subtract a round-trip cost of
COST_PCT of notional converted to R units per trade (cost_R = COST_PCT /
stop_distance_pct). This is the honest number a live gate must beat.

Verdict criteria (fixed BEFORE running):
  * CONFIRMED   : >=70% of splits net-positive AND DSR >= 0.95
  * INCONCLUSIVE: mixed evidence — do NOT wire live; gather more data
  * REJECTED    : <50% of splits net-positive or DSR < 0.50
"""
from itertools import combinations
from typing import Dict, Any, List

import numpy as np
import pandas as pd

from analytics.feature_lab import build_dataset, HORIZON, ATR_MULT, MIN_STOP

N_GROUPS = 6
GATE     = 0.50          # the only gate Phase 2 supported (veto filter)
COST_PCT = 0.0025        # 0.1% commission x2 + ~5bps slippage, of notional
N_TRIALS = 16            # honest count of configurations tried in this
                         # program: 5 symbols (phase 1) + 3 thresholds +
                         # ~8 informal backtest sweeps. Used by DSR.


def _cost_in_r(atr_pct: pd.Series) -> pd.Series:
    """Round-trip cost expressed in R units (R = stop distance)."""
    stop_frac = np.maximum(ATR_MULT * atr_pct, MIN_STOP)
    return COST_PCT / stop_frac


def run_cpcv(symbol: str = "BTC-USD", period: str = "5y") -> Dict[str, Any]:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score

    data = build_dataset(symbol, period)
    if data is None or len(data) < 600:
        return {"symbol": symbol, "error": "insufficient data"}

    y = data["label"].astype(int).values
    r_gross = data["realized_r"].values
    cost_r = _cost_in_r(data["atr_pct"]).values
    r_net = r_gross - cost_r
    X = data.drop(columns=["label", "realized_r"]).values
    n = len(data)

    # Contiguous groups
    edges = np.linspace(0, n, N_GROUPS + 1).astype(int)
    groups = [(edges[i], edges[i + 1]) for i in range(N_GROUPS)]

    splits: List[Dict[str, Any]] = []
    oos_returns: List[float] = []   # net R of every gated OOS trade
    for test_pair in combinations(range(N_GROUPS), 2):
        test_mask = np.zeros(n, dtype=bool)
        for g in test_pair:
            test_mask[groups[g][0]:groups[g][1]] = True

        # PURGE: drop train bars whose label window [i, i+HORIZON+1] overlaps
        # any test region expanded by the embargo.
        train_mask = ~test_mask
        for g in test_pair:
            lo = max(0, groups[g][0] - (HORIZON + 1))     # labels reaching in
            hi = min(n, groups[g][1] + HORIZON)           # embargo after
            train_mask[lo:hi] = False

        if train_mask.sum() < 200 or test_mask.sum() < 60:
            continue
        ytr = y[train_mask]
        if len(np.unique(ytr)) < 2:
            continue

        clf = RandomForestClassifier(n_estimators=300, max_depth=4,
                                     min_samples_leaf=50,
                                     class_weight="balanced",
                                     random_state=42, n_jobs=-1)
        clf.fit(X[train_mask], ytr)
        p = clf.predict_proba(X[test_mask])[:, 1]

        yte, rte = y[test_mask], r_net[test_mask]
        gated = p >= GATE
        try:
            auc = round(float(roc_auc_score(yte, p)), 4)
        except Exception:
            auc = None
        g_r = rte[gated]
        _gated_er = round(float(g_r.mean()), 4) if gated.sum() else None
        _all_er   = round(float(rte.mean()), 4)
        splits.append({
            "test_groups": list(test_pair),
            "auc": auc,
            "n_test": int(test_mask.sum()),
            "pct_gated": round(float(gated.mean() * 100), 1),
            "exp_R_all_net": _all_er,
            "exp_R_gated_net": _gated_er,
            # uplift = the gate's OWN contribution, separated from the asset's
            # drift. A random gate on a drifting asset shows gated>0 but
            # uplift~0 — verified with a stub-RF test that fooled the first
            # version of these criteria.
            "uplift_R": round(_gated_er - _all_er, 4) if _gated_er is not None else None,
        })
        oos_returns.extend(g_r.tolist())

    # ── Aggregate + Deflated Sharpe ──────────────────────────────────────────
    res: Dict[str, Any] = {"symbol": symbol, "rows": n,
                           "n_splits": len(splits), "gate": GATE,
                           "cost_model_pct": COST_PCT, "splits": splits}
    pos = [s for s in splits if s["exp_R_gated_net"] is not None
           and s["exp_R_gated_net"] > 0]
    res["pct_splits_net_positive"] = round(100 * len(pos) / max(len(splits), 1), 1)
    up = [s for s in splits if s.get("uplift_R") is not None and s["uplift_R"] > 0]
    res["pct_splits_uplift_positive"] = round(100 * len(up) / max(len(splits), 1), 1)
    _uplifts = [s["uplift_R"] for s in splits if s.get("uplift_R") is not None]
    res["mean_uplift_R"] = round(float(np.mean(_uplifts)), 4) if _uplifts else None

    r = np.array(oos_returns)
    if len(r) > 30 and r.std() > 0:
        sr = float(r.mean() / r.std())                     # per-trade Sharpe
        res["oos_trades"] = int(len(r))
        res["oos_exp_R_net"] = round(float(r.mean()), 4)
        res["oos_sharpe_per_trade"] = round(sr, 4)

        # Deflated Sharpe (Bailey & Lopez de Prado 2014)
        from scipy.stats import norm, skew, kurtosis
        T = len(r)
        g3, g4 = float(skew(r)), float(kurtosis(r, fisher=False))
        # Expected max Sharpe of N_TRIALS null strategies (variance of SR ~ 1/T)
        e = np.e
        sr_star = np.sqrt(1.0 / T) * ((1 - np.euler_gamma) *
                  norm.ppf(1 - 1.0 / N_TRIALS) +
                  np.euler_gamma * norm.ppf(1 - 1.0 / (N_TRIALS * e)))
        denom = np.sqrt(max(1e-12, (1 - g3 * sr + (g4 - 1) / 4.0 * sr ** 2) / (T - 1)))
        dsr = float(norm.cdf((sr - sr_star) / denom))
        res["sr_star_null_max"] = round(float(sr_star), 4)
        res["deflated_sharpe"] = round(dsr, 4)

        # CONFIRMED requires the gate to ADD value (uplift), not merely ride
        # the asset's drift: >=70% of splits net-positive AND >=70% of splits
        # uplift-positive AND DSR >= 0.95.
        if (res["pct_splits_net_positive"] >= 70
                and res["pct_splits_uplift_positive"] >= 70
                and dsr >= 0.95):
            res["verdict"] = "CONFIRMED"
        elif (res["pct_splits_net_positive"] < 50
                or res["pct_splits_uplift_positive"] < 50
                or dsr < 0.50):
            res["verdict"] = "REJECTED"
        else:
            res["verdict"] = "INCONCLUSIVE"
    else:
        res["verdict"] = "INSUFFICIENT_OOS_TRADES"
    return res
