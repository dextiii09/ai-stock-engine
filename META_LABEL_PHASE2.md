# Phase 2 — Meta-Labeling Evaluation (BTC-USD)
_Generated 2026-07-17 17:02_

- rows: 1816 (train 1271, test 525, embargoed)
- out-of-sample AUC: **0.591**

## Baseline (take every trade)
- trades 525, win rate 0.4, **E[R] -0.073**

## Gated by meta-model P(win)
- p ≥ 0.5: takes 56.2% of trades (n=295), win rate 0.464, **E[R] 0.0936**
- p ≥ 0.55: takes 27.0% of trades (n=142), win rate 0.43, **E[R] -0.0062**
- p ≥ 0.6: takes 7.0% of trades (n=37), win rate 0.432, **E[R] -0.0832**

## Calibration (predicted P vs realized win rate)
- (0.28, 0.428]: n=105, realized win 0.219, E[R] -0.4127
- (0.428, 0.493]: n=105, realized win 0.4, E[R] -0.2
- (0.493, 0.524]: n=105, realized win 0.486, E[R] 0.1728
- (0.524, 0.565]: n=105, realized win 0.438, E[R] 0.06
- (0.565, 0.702]: n=105, realized win 0.457, E[R] 0.0148

## Verdict (criteria fixed before running)
- **PROMISING**: gate p≥0.5 improves out-of-sample expectancy from -0.073 to 0.0936 R/trade while keeping 56.2% of trades.
- NOT live-ready yet: requires Phase 3 validation (CPCV + Deflated Sharpe, multiple periods) — a single split can flatter a regime.
- Model saved: E:\Ai Stock\backend\data\models\meta_btc.joblib

_Paper trading only. This measures; it does not promise._