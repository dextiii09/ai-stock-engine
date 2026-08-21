# 1-Week Log Review Cheat Sheet

Run these commands from the server terminal (adjusting `/path/to/logs/backend.log` to your actual log location) to empirically validate the structural fixes applied during the audit.

### 1. Meta-Gate Macro Feed Reliability
**Question:** How often does the Meta-Gate abstain entirely due to missing VIX or Yield Curve data?
```bash
grep -c "Failing open" /path/to/logs/backend.log
```
*If this number is high, we're losing the CPCV-validated edge on too many trades and need to build a more robust macro-data fetcher.*

### 2. In-Flight TOCTOU Race Condition Lock
**Question:** Did the new lock mechanism actually prevent any double-entry attempts?
```bash
grep -c "is already in-flight" /path/to/logs/backend.log
```
*If this returns >0, the fix prevented a race that would have otherwise caused a duplicate entry.*

### 3. HMM Regime Detector Sanity Checks
**Question:** Did the heuristic clustering fail the Bull/Bear return spread sanity check on a Sunday retrain?
```bash
grep -c "HMM Sanity Check Failed" /path/to/logs/backend.log
```
*If >0, the detector hallucinated a bad mapping and safely kept the old model.*

### 4. Forex Spread-Gate Evaluation
**Question:** Does the Spread & Slippage Filter ever actually run for FOREX, or is it perpetually skipping due to missing bid/ask depth in the feed?
```bash
grep "\[SpreadGate\]" /path/to/logs/backend.log | grep "=X"
```
*Look at the output: if they all say `skipped (bid/ask depth unavailable)`, then the spread gate is a complete illusion for Forex and we are flying blind on slippage.*

### 5. Reinforcement Learning Persistence
**Question:** Are the RL weights silently failing to save to SQLite or JSON during production operation?
```bash
grep -c -E "\[RL Engine\].*(Failed to save|async save failed)" /path/to/logs/backend.log
```
*If this returns >0, the learning engine is dropping its state and reverting to stale weights on restart, crippling long-term adaptation.*
