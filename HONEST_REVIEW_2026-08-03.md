# Honest Project Review — AI Stock Platform
### 2026-08-03 (final session)

## What you built

A five-market paper-trading system (US futures, stocks, crypto, forex, Indian equities) with a multi-agent decision committee, regime detection, RL-based agent reweighting with Thompson sampling, LSTM signals, MTF confluence, Monte Carlo EV gating, per-market and global circuit breakers, a watchdog, SSE log streaming, a React dashboard, and a measurement pipeline with weekly expectancy tracking. For a personal project, the engineering ambition and the discipline of the fix history (six audit/fix sessions, each documented in code comments) are far beyond typical.

## The engineering — honest grade: 7/10

Strong: atomic writes everywhere, per-engine locks, the A-3 remove-before-credit pattern, INR normalization in global risk, the IV&V habit of writing the *why* into comments, and — rarest of all — a culture of measuring instead of believing.

The recurring weakness is **state persistence**. Nearly every serious bug found across six sessions was some form of "state silently wasn't saved or loaded": the shared-DB-row aliasing, the rl_metadata wipe, the fire-and-forget shutdown save, today's restart-wipes-RL-counters bug. The DB+JSON dual-persistence design with different code paths for each is the root of most of it. If you refactor one thing, make it this: a single, synchronous, versioned save/load path per engine, tested by an automated "restart and compare" script.

Second weakness: routes.py is ~3,300 lines with the US and India loops as hand-copied variants of the generic loop. Divergence between copies has already caused bugs (the India loop's missing session-quality check, the differing heartbeat placement). Fold all five into `_run_market_loop`.

## The trading performance — honest grade: 3/10 today, undetermined tomorrow

The numbers since the clean 2026-07-20 baseline: 394 trades, 26.4% win rate, realized RR 1.56, expectancy −$2.44/trade (USD-only −$3.39), total −$962. The arithmetic is unforgiving: at RR 1.56 you need a 39% win rate to break even; at a 26% win rate you need RR 2.85. You are not close on either axis, and 81% of resolved exits are stops. The system currently loses money slowly and consistently.

The one bright spot is the Indian book: 48% win rate this week, expectancy ≈ ₹0 — the only book near breakeven. Worth studying why (slower symbols? different session dynamics? the extra India Flow Agent?).

## The RL experiment — status: effectively restarting today

Hard truth: weeks 1–2 of the experiment were compromised. The persistence bug meant RL counters and the Sharpe-normalization history reset on every server restart, so the system was learning nearly from scratch each boot. Weight movement you saw was real but shallow — the learning never compounded. With today's fix, the experiment starts clean. Treat 2026-08-03 as the true baseline and give it the full 12 weeks from here.

Also be realistic about the ceiling: RL here re-weights 5–7 committee agents. If the agents' underlying signals have no edge at a 4-second Yahoo-Finance cadence, the best possible weighting still loses. If expectancy is still ≈ −$2 to −$7/trade by week 8, the answer is not more RL — it is better entries: fewer trades, higher timeframes, stricter confidence thresholds. Trade count is currently ~150/week; cutting that by two-thirds and keeping only the highest-conviction setups is the single most promising lever, and it is testable with the same weekly script.

## Known weak points to watch (nothing broken today, but fragile)

Data source: yfinance is delayed, rate-limited, and hangs (cause of the 14h INDIA stall — now guarded by fetch timeouts plus a 30s global socket timeout, but the data quality itself is a ceiling on everything). Thread pool: hung fetch threads now leak workers into a 12-worker pool; repeated hangs over days could exhaust it — a restart clears it. Mixed currency: aggregate dollars are INR+USD; always read the split stats. RL DB metadata: can lag one trade behind the JSON under a save race — harmless while the JSON-fresher load rule exists; don't remove it.

## What to do without Claude

Run `python weekly_report.py` every Monday with the backend up — it computes everything the scheduled report did, appends to performance_log.json, warns if the aliasing or RL-persistence bugs regress, and prints the trend verdict. The old scheduled task will stop running when the subscription ends.

After your next graceful restart (Ctrl+C), check `/api/v1/analytics/rl-stats`: total_closed_trades must continue from its pre-restart value. Then restart once more and check again — that second check is the real proof the persistence fix holds.

Judge the experiment at week 12 by the agreed criterion: monthly expectancy improving toward ≥ $0/trade. Flat around −$2 to −$7 means the answer is negative — and that is a successful experiment too, because it tells you where the real work is: entry signal quality, not learning machinery.

## Bottom line

You built a real system with real engineering, and — more valuable — a measurement pipeline that will tell you the truth. The strategy doesn't work yet, and the experiment that would prove whether RL can fix it only starts today with sound persistence. This is paper trading; nothing was lost but time, and the infrastructure you built is exactly what would be needed to iterate toward something that works. Do not put real money on this until the weekly log shows sustained positive expectancy for at least two months.
