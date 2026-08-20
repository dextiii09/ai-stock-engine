---
trigger: model_decision
description: >
  Audit heuristics and known failure patterns for the AI Stock paper-trading
  system. Apply whenever generating or reviewing the weekly trading performance
  report, or investigating why a market/engine behaves oddly (not trading,
  halted, wrong stats). Set activation to "Always On" or "Model Decision".
---

# Trading-Report Audit Heuristics & Known Glitches

Persistent context for auditing the AI Stock paper-trading backend
(`E:\Ai Stock`, FastAPI on `http://localhost:8080`). Goal: find bugs and
glitches — not just print numbers. This is paper trading; no real money at risk.

## Source-of-truth hierarchy (memorize this)
1. **The live API** (`localhost:8080/api/v1/...`) is authoritative for current state.
2. The SQLite DB (`backend/ai_stock.db` — NOT the stale root `ai_stock.db`) backs it.
3. **JSON state files** (`backend/data/portfolio_state_*.json`, `risk_state_*.json`)
   are seeds/fallbacks and drift easily. Treat them as suspects, never as truth.
- The sandbox shell CANNOT reach localhost — query the API through the browser
  tools. The file mount can serve STALE copies, so anything read off disk must be
  cross-checked against the API before you trust it.

## The ten audit smell-tests
Run these every report. Any one firing is a finding to flag, not to silently fix.

1. **API vs. persisted-state disagreement.** Compare each book's live
   money-tracker (balance, open positions, closed-trade count) against its
   `portfolio_state_<m>.json`. Divergence = stale/orphaned state (a landmine that
   re-seeds phantom data if the DB is ever emptied). This is how the forex
   phantom ($50k/0 live vs $78.5k/5/26 on disk) was caught.

2. **A ~zero-trade book cannot have a loss-based halt.** If a market with no
   positions/trades shows DAILY_HALT or WEEKLY_HALT, the halt is impossible from
   real losses → corrupt/stale risk baseline. Every halt must be explainable by
   actual drawdown.

3. **Journal gate analysis.** When a market under-trades, load
   `backend/journal_<m>.json` and tally entries by `type` (VETO vs TRADE), by
   `gate` (EVENT_BLACKOUT, WEEKLY_HALT, DAILY_HALT, MONTE_CARLO, MTF_VETO,
   CORRELATION…), and by `reason`. Compare to a book that IS trading. The gate
   that dominates the stuck book but not the healthy one is the culprit.

4. **Break down EVENT_BLACKOUT reasons.** Weekend closures (Saturday / Sunday /
   Friday-late) are legitimate and typically ~80%+ of forex blackouts — not a
   bug. The real gating is the macro calendar (FOMC / CPI / NFP). Separate the two
   before concluding anything.

5. **Time-window every blocking gate.** Check first/last timestamps of the
   dominant gate. Historical (already reset) ≠ ongoing. Only gates active in the
   current period explain current behavior. (Ex: a WEEKLY_HALT confined to one
   past ISO week self-clears on the next week's baseline reset.)

6. **Dedupe as an aliasing tripwire.** Always dedupe trades by
   `(symbol, time, profit_loss)`. If a NONTRIVIAL number is removed, the
   shared-DB-row aliasing bug ("_st" substring bug) may have regressed — FLAG it.
   0 removed = healthy.

7. **Config-consistency checks.** Look for hardcoded overrides that contradict a
   global/default constant. Real example: FOMC gate used `window=1` while global
   `BLACKOUT_WINDOW_DAYS=0` and CPI used `window=0`; combined with FOMC dates
   stored as consecutive pairs, that silently produced a 3-day forex blackout.

8. **Currency mixing.** Indian book is INR; all others USD. Any aggregate dollar
   figure that blends them is misleading — always compute per-currency splits and
   state the mixed-currency caveat.

9. **Baseline plausibility guard.** A persisted weekly/daily baseline sitting
   >~25% above live equity cannot be a genuine loss (breakers halt at 3%/6% first)
   → it is stale state. The runtime guard for this lives in
   `risk/portfolio_risk.py` (`PortfolioRiskManager.STALE_BASELINE_DD`).

10. **Reconcile after every reset.** A book reset must clear ALL artifacts — DB,
    `portfolio_state_*.json`, `risk_state_*.json`, `rl_state_*.json` — not just the
    DB. Missed JSONs are the classic post-reset landmine. Use
    `backend/scripts/reset_market_state.py --market <M>` (server stopped).

## Known failure-pattern catalog
- **Shared-DB-row aliasing** — one DB row aliased to multiple engines; caught by
  the dedupe tripwire (#6).
- **Stale JSON state after reset** — phantom trades/balance re-seed the DB if it's
  ever emptied (#1, #10).
- **Stale weekly baseline within the same ISO week** — reset zeroes live equity but
  not `risk_state_<m>.json`; a restart later that week reloads the old baseline →
  phantom WEEKLY_HALT for the whole week (#2, #9).
- **FOMC window=1 + paired dates** → unintended 3-day blackout (#7).
- **Mixed-currency aggregates** → misleading expectancy/PnL (#8).
- **Event-loop starvation / blocking I/O** — import-time backtests, sync calls in
  async loops; symptom is engines flagged "slow" in `/health`.

## Reporting discipline
- If the server is unreachable (connection refused), say so briefly and STOP.
  Never fabricate numbers.
- Trend is the headline, but week-to-week expectancy swings under ~30 trades are
  mostly noise — say so; never oversell noise as signal.
- Compare only against the post-2026-07-20 "baseline v2" (earlier data was
  contaminated and purged).
- Always end with the paper-trading / no-real-money reminder.
- Report findings honestly; for anything destructive (deleting/rewriting state),
  surface it and get confirmation rather than acting silently.
