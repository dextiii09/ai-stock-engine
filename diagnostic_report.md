# Autonomous Trading Engine - Diagnostic Report
**Date Generated:** 2026-07-02

## RL Baseline Saturation (Gate 1)
- **Total Backfilled Trades:** 100
- **Win Rate (Seed):** 65.0%
- **Avg PnL per Trade (Seed):** $51.61

## Agent Committee Weights
The RL engine has converged on the following weights based on historical backtest success. The baseline of 1.0 has been successfully broken, meaning the engine has learned which agents to trust for Gold and NQ.
- **Technical Analyst:** 1.7595
- **Fundamental Analyst:** 0.9108
- **News & Sentiment AI:** 1.5993
- **Macro Economic AI:** 1.8242

## Shadow Trading & Forecast Accuracy
*Since the engine just booted with cold start, shadow veto tracking and Monte Carlo EV metrics will populate after the first 24 hours of live paper trading.*

## System Readiness
- **Macro Regime Classifier:** ACTIVE (Using DXY, VIX, Real Yields, and CFTC COT positioning)
- **Correlation Block:** ACTIVE (Blocking Inverse & Extreme Positive Correlation)
- **Macro Event Blackouts:** ACTIVE (Paused today: Non-Farm Payrolls on 2026-07-02)
- **Execution Loop:** READY FOR PAPER TRADING

