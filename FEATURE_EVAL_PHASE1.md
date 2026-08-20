# Phase 1 — Feature Predictive-Power Evaluation
_Generated 2026-07-17 16:43_

**Question:** do the new economically-motivated features (VIX term
structure, yield-curve spread, COT positioning momentum) — or the old
technicals — predict Triple-Barrier trade outcomes out-of-sample?

**How to read this:** AUC 0.50 = coin flip (no signal). AUC 0.52-0.55
held across folds AND symbols = weak-but-interesting, worth Phase 2
(meta-labeling) and Phase 3 (CPCV + Deflated Sharpe) validation.
Single-fold spikes are noise. |IC| < 0.03 is noise.

## MNQ=F
- rows: 1247  |  label balance (profit-first): 0.526
- **fold AUCs: [0.4555, 0.4992, 0.4665]  →  mean 0.4737**
- top |IC| features: [('yield_spread', -0.2292), ('vix_ts', -0.1247), ('rsi', 0.0788), ('yield_spread_mom5', -0.0697), ('atr_pct', -0.0524)]
- top RF importance: [('yield_spread', 0.3163), ('atr_pct', 0.1457), ('vix_ts', 0.1265), ('yield_spread_mom5', 0.1101), ('vix_lvl', 0.0689)]

## MGC=F
- rows: 1248  |  label balance (profit-first): 0.56
- **fold AUCs: [0.459, 0.4854, 0.5321]  →  mean 0.4922**
- top |IC| features: [('yield_spread', -0.1184), ('macd_hist', -0.1049), ('vix_lvl', -0.0917), ('vol_z', -0.0775), ('cot_net_mom', -0.0688)]
- top RF importance: [('yield_spread', 0.2363), ('cot_net_mom', 0.1511), ('vix_ts', 0.1422), ('vix_lvl', 0.1006), ('vol_z', 0.0973)]

## BTC-USD
- rows: 1816  |  label balance (profit-first): 0.454
- **fold AUCs: [0.5408, 0.5985, 0.6219]  →  mean 0.5871**
- top |IC| features: [('vix_ts', -0.2145), ('yield_spread', -0.0974), ('macd_hist', 0.0832), ('yield_spread_mom5', -0.0547), ('vix_lvl', 0.0471)]
- top RF importance: [('yield_spread', 0.2587), ('vix_ts', 0.2439), ('atr_pct', 0.1442), ('rsi', 0.131), ('vix_lvl', 0.0759)]

## NVDA
- rows: 1245  |  label balance (profit-first): 0.551
- **fold AUCs: [0.3394, 0.7103, 0.5418]  →  mean 0.5305**
- top |IC| features: [('yield_spread', -0.221), ('atr_pct', -0.1419), ('macd_hist', 0.0984), ('vix_ts', -0.0765), ('rsi', 0.0586)]
- top RF importance: [('yield_spread', 0.3442), ('atr_pct', 0.1735), ('vix_ts', 0.1105), ('vix_lvl', 0.0997), ('rsi', 0.0884)]

## EURUSD=X
- rows: 1289  |  label balance (profit-first): 0.449
- **fold AUCs: [0.4485, 0.432, 0.4478]  →  mean 0.4428**
- top |IC| features: [('vix_ts', -0.1864), ('yield_spread', -0.1318), ('atr_pct', 0.1313), ('yield_spread_mom5', -0.0799), ('vix_lvl', 0.0629)]
- top RF importance: [('yield_spread', 0.3911), ('atr_pct', 0.1636), ('vix_ts', 0.1481), ('rsi', 0.0797), ('vix_lvl', 0.0779)]

## Overall verdict
- mean AUC across symbols: **0.5053**
- Verdict: **no exploitable signal detected** in these features at daily resolution. Phase 2 (meta-labeling) would be building on sand — not recommended until a feature shows AUC ≥ 0.52 consistently.

_This evaluation reduces self-deception; it cannot create signal. Paper trading only._