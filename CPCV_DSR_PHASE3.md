# Phase 3 — CPCV + Deflated Sharpe (BTC-USD, p>=0.50 gate)
_Generated 2026-07-17 17:21_

- rows: 1816, splits: 15, gate p>=0.5, cost model 0.25% round trip
- splits net-positive (gated): **100.0%**
- splits with positive UPLIFT (gate beats no-gate): **100.0%** | mean uplift 0.1661 R
- aggregate OOS gated trades: 4640
- aggregate OOS expectancy (net): **0.2014 R/trade**
- per-trade Sharpe: 0.188 | null-max Sharpe (16 trials): 0.0264
- **Deflated Sharpe Ratio: 1.0** (probability the edge is real after luck adjustment)

## Per-split detail

- groups [0, 1]: AUC 0.5794, gated 58.2% of 605, E[R] all -0.0907 vs gated **0.0568**
- groups [0, 2]: AUC 0.6559, gated 38.0% of 605, E[R] all 0.0335 vs gated **0.3054**
- groups [0, 3]: AUC 0.6229, gated 63.9% of 604, E[R] all 0.0827 vs gated **0.3162**
- groups [0, 4]: AUC 0.6187, gated 30.7% of 605, E[R] all -0.066 vs gated **0.1971**
- groups [0, 5]: AUC 0.6557, gated 22.0% of 605, E[R] all -0.201 vs gated **0.0623**
- groups [1, 2]: AUC 0.5711, gated 58.9% of 606, E[R] all 0.1115 vs gated **0.1687**
- groups [1, 3]: AUC 0.5387, gated 88.4% of 605, E[R] all 0.1607 vs gated **0.1845**
- groups [1, 4]: AUC 0.5697, gated 66.3% of 606, E[R] all 0.0121 vs gated **0.0874**
- groups [1, 5]: AUC 0.5863, gated 46.2% of 606, E[R] all -0.1226 vs gated **0.0236**
- groups [2, 3]: AUC 0.5742, gated 62.6% of 605, E[R] all 0.2849 vs gated **0.3317**
- groups [2, 4]: AUC 0.6377, gated 39.1% of 606, E[R] all 0.1361 vs gated **0.3143**
- groups [2, 5]: AUC 0.6382, gated 30.9% of 606, E[R] all 0.0014 vs gated **0.2737**
- groups [3, 4]: AUC 0.5571, gated 63.3% of 605, E[R] all 0.1853 vs gated **0.2874**
- groups [3, 5]: AUC 0.6371, gated 54.2% of 605, E[R] all 0.0504 vs gated **0.2974**
- groups [4, 5]: AUC 0.6054, gated 43.7% of 606, E[R] all -0.098 vs gated **0.0656**

## VERDICT: **CONFIRMED**

Next step: wire the gate into the live crypto loop as a BTC-only entry veto (paper), monitored weekly.

_Criteria were fixed before running. Paper trading only._