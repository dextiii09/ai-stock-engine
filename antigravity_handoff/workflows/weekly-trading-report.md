---
description: >
  Generate the weekly AI Stock paper-trading performance report AND audit it for
  bugs/glitches. Invoke with /weekly-trading-report. Pairs with the
  "trading-report-audit" rule (apply its ten smell-tests throughout).
---

# Workflow: /weekly-trading-report

Produce the weekly report for the AI Stock paper-trading system and actively hunt
for bugs. Read the **trading-report-audit** rule first — every step below assumes
its smell-tests are running. Backend: FastAPI at `http://localhost:8080`, repo
`E:\Ai Stock`. Paper trading only. Execute autonomously; note any assumptions.

## Step 1 — Reach the backend
The sandbox shell CANNOT reach localhost. Query via the browser tools (open a tab,
`fetch(...)` in the page context, or navigate + read text).
- GET `/api/v1/health` — engines status + `global_halt`.
- If connection refused: state the server is down and STOP. Do not fabricate.
- Note any engine flagged `slow` or `stopped`.

## Step 2 — Fetch all books + RL + health
GET these and keep the JSON:
- `/api/v1/portfolio/money-tracker` (US)
- `/api/v1/stocks/portfolio/money-tracker`
- `/api/v1/crypto/portfolio/money-tracker`
- `/api/v1/forex/portfolio/money-tracker`
- `/api/v1/indian/portfolio/money-tracker`
- `/api/v1/analytics/rl-stats` (agent + regime weights, win rate)
Each book returns `closed_trades[]`, `summary`, `active_holdings`. Trade fields:
`symbol, shares, direction, entry_price, exit_price, profit_loss, profit_pct, time, reason`.
(If a JS result is truncated/blocked, store it on `window.__D` and extract small
summaries rather than dumping whole arrays.)

## Step 3 — Merge, dedupe, split by currency
- Merge all five `closed_trades[]`.
- **Dedupe by `(symbol, time, profit_loss)`.** If a nontrivial count is removed →
  FLAG as possible aliasing-bug regression (audit smell-test #6).
- Tag Indian book as **INR**, all others **USD**. You will report Indian
  separately and caveat every mixed aggregate.

## Step 4 — Read history
Read `E:\Ai Stock\performance_log.json`. Get the previous run's cumulative stats
and `max_trade_time`. New/this-week trades = those with `time > last max_trade_time`.
Trend baseline is the 2026-07-20 "baseline v2" record — never compare earlier.

## Step 5 — Compute stats
For (a) ALL deduped trades, (b) USD-only, (c) INR-only, and (d) this-week
(new since last run, same three cuts):
- `n`, wins (`pnl>0`), losses (`pnl<0`), breakeven (`pnl==0`)
- `win_rate% = wins / n * 100`
- `avg_win` = mean of winning pnl; `avg_loss` = mean of losing pnl
- `realized_rr = |avg_win / avg_loss|`
- `expectancy = total_pnl / n`
- `total_pnl`
Also for NEW trades: **stop:target exit ratio** — count `reason` containing
"STOP" vs "PROFIT"/"TARGET" (everything else = committee/other closes). Compare to
the pre-fix 82:26 to judge whether the trailing-stop fix is helping.

## Step 6 — Run the bug audit (the point of this workflow)
Apply the audit rule's smell-tests, especially:
- **API vs disk:** for each book compare live money-tracker (balance / open
  positions / closed count) against `backend/data/portfolio_state_<m>.json`.
  Divergence = stale state → flag.
- **Impossible halts:** any DAILY_HALT/WEEKLY_HALT on a ~zero-trade book → stale
  risk baseline. Check `backend/data/risk_state_<m>.json` vs live equity.
- **Stuck/under-trading engine:** load `backend/journal_<m>.json`; tally by
  `type`, `gate`, `reason`; time-window the dominant gate (first/last timestamp,
  and last-3-days mix) to tell ongoing from historical; compare to a healthy book.
  Separate legitimate weekend/session closures from real macro-event gating.
- **Config drift:** watch for hardcoded overrides contradicting global defaults
  (e.g. blackout windows in `backend/data/event_awareness.py`).
Map paths: `E:\Ai Stock` → shell mount for reading; but verify disk reads against
the API (mount can be stale).

## Step 7 — Append to the log
Append one record to `performance_log.json`:
```
{
  "run_date": "<ISO date>",
  "dedupe": {"raw": N, "deduped": N, "removed": N},
  "cumulative": {...}, "cumulative_usd_only": {...}, "cumulative_inr_only": {...},
  "this_week": {...}, "this_week_usd_only": {...}, "this_week_inr_only": {...},
  "exit_ratio_this_week": {"stop": N, "target": N, "other": N},
  "max_trade_time": <max epoch time seen>,
  "rl_snapshot": {top 3 most-changed agent weights per regime vs default 1.0}
}
```

## Step 8 — Report to the user (concise, plain language)
- This week: trade count, win rate, expectancy/trade (USD split + INR split).
- Cumulative: same.
- **THE TREND (headline):** compare this week's expectancy to prior weeks from the
  log — improving / flat / worsening. Note it starts at baseline v2, and that
  swings under ~30 trades are mostly noise. Never oversell.
- Stop:target ratio vs 82:26 — is the trailing-stop fix working?
- RL evidence: which agent/regime weights moved most since last week.
- **Any bugs/glitches found in Step 6**, with the specific file/endpoint evidence
  and a suggested fix — but do NOT delete or rewrite state without confirmation.
- Honest verdict line + paper-trading reminder.
