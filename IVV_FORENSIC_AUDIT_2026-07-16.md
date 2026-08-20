# Independent Verification & Validation (IV&V) — Forensic Code Audit
**System:** AI Stock Trading Platform (paper) — `E:\Ai Stock`
**Audit date:** 2026-07-16
**Scope:** Backend money-path, ML/RL, backtest engine, API, DB, security, frontend surface
**Standard applied:** "Assume every line is wrong until proven correct." Question posed: *Is this software safe to manage real money?*

---

## Executive Summary

The system is a competently-built, feature-rich **paper-trading research platform**. Over prior sessions the obvious defects (flat backtests, event-loop DB errors, stale bug-scanner findings) were fixed and verified. The live paper engine reconciles its ledger to the cent, enforces daily/weekly loss circuit breakers, serializes state mutation under locks, and its stop/risk logic is coherent.

However, judged against the standard used by professional trading firms and against the specific question *"safe for REAL money?"*, the answer is an unambiguous **NO — not yet**. The blocker is not any single arithmetic bug; the money-path math is mostly sound. The blockers are **(1) a complete absence of authentication/authorization on a server bound to 0.0.0.0**, **(2) a live-order share-quantity truncation bug that silently sends `0` to a real broker for every fractional instrument**, **(3) event-loop-blocking network I/O on the hot trade path**, and **(4) portfolio-level risk limits that are computed and displayed but never enforced as entry gates.** Any one of these is disqualifying for real capital.

The platform is **SAFE FOR PAPER TRADING** and is a solid base. It is **NOT SAFE FOR REAL MONEY** until the Critical and High items below are closed and an independent test suite covers the trade lifecycle.

---

## Methodology & Honest Limitations

I read the money-path modules line-by-line (`smart_execution.py`, `position_sizing.py`, `simulator.py`, `broker.py`, `rl_engine.py`, `backtesting/engine.py`, `agents/master.py`, `agents/committee.py`, `risk/portfolio_risk.py`, `api/routes.py` hot loops, `database/database.py`, `api/server.py`) and skimmed the frontend and remaining modules. I did **not** dynamically execute an adversarial test harness, did not fuzz endpoints, and did not replay historical tick storms. Confidence levels reflect this: findings from direct code reading are high-confidence; probability/score estimates are informed engineering judgment, not measured metrics, and I flag them as such. I did not audit `event_awareness.py`, `hyperopt*.py`, the broker adapters for IBKR/Zerodha internals, or the PPO/LSTM training scripts in depth — those remain partially unverified (see "Probability of Hidden Bugs").

---

## FINDINGS

────────────────────────────
**Severity:** Critical
**Category:** Security / API
**File:** `backend/api/server.py`
**Function:** app/middleware config
**Line Number:** 94–95 (CORS `allow_origins=["*"]`); server bound `0.0.0.0:8080`
**Problem:** There is **no authentication or authorization on any endpoint.** `POST /bot/start`, `/bot/stop`, `/backtest/run`, `/execution/set-routing`, and `DELETE /ai-bugs` are all open. CORS is fully permissive and the server listens on `0.0.0.0` (all interfaces).
**Root Cause:** Auth was never implemented; the app was built as a localhost research tool.
**Real-World Impact:** Anyone on the same LAN/Wi-Fi (or the internet if the port is forwarded) can start/stop the bot, change order routing, or trigger expensive backtests. With a live broker attached this is direct unauthorized control of real capital and a trivially exploitable DoS (spam `/backtest/run`, each of which blocks the loop — see next finding).
**Fix:** Bind to `127.0.0.1` by default; put every mutating route behind an auth dependency (API key or session token) via FastAPI `Depends`; restrict CORS to the known frontend origin. Example:
```python
API_KEY = os.environ["APP_API_KEY"]  # fail fast if unset
async def require_key(x_api_key: str = Header(...)):
    if not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(401, "unauthorized")
# apply to the router: APIRouter(prefix="/api/v1", dependencies=[Depends(require_key)])
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN], ...)
uvicorn ... --host 127.0.0.1
```
Why correct: closes the open control plane; `compare_digest` avoids timing leaks.
**Confidence:** 99%

────────────────────────────
**Severity:** Critical
**Category:** Trading / Backend
**File:** `backend/execution/smart_execution.py`
**Function:** `execute_trade` (BUY/SELL/SHORT/COVER live branches)
**Line Number:** 470, 566, 628, 728 — `self.broker.buy(symbol, int(shares), ...)` (and `.short/.sell/.cover`)
**Problem:** Internal position sizing produces **fractional** share counts (e.g. `0.0677` BTC, `0.168` MNQ micro-contracts, `1.2275` MGC). The live broker call casts with `int(...)`, so `int(0.0677) == 0`. In live mode the broker receives an order for **0 units** while the engine's internal `active_holdings` records the full fractional position.
**Root Cause:** `int()` truncation assumes whole-share equities; the sizer and the rest of the engine use floats for crypto/futures.
**Real-World Impact:** Catastrophic state desync the moment `broker.is_live=True`: the engine believes it holds a position and manages stops/P&L against it, but no real order exists (or a wrong-sized one for shares between 1 and 2). Every stop/TP "exit" then sends `int(shares)` again → phantom fills, unbounded divergence between book and broker. Currently latent because broker is Paper.
**Fix:** Never truncate. Pass the float and let the broker adapter round to its instrument's lot size / tick, or reject sub-lot orders explicitly:
```python
qty = self.broker.normalize_quantity(symbol, shares)  # adapter knows lot size
if qty <= 0:
    return False, f"Sub-lot order suppressed for {symbol} ({shares})"
_ok, _msg, _oid = self.broker.buy(symbol, qty, avg_fill_price)
```
Why correct: removes silent truncation; makes sub-lot handling an explicit, logged decision.
**Confidence:** 97%

────────────────────────────
**Severity:** High
**Category:** Performance / Backend (concurrency)
**File:** `backend/analytics/simulator.py` → called from `smart_execution.py`
**Function:** `_get_historical_vol` (`yf.Ticker(symbol).history(...)`) invoked by `simulate()` inside `execute_trade`
**Line Number:** simulator.py:36, 157; called at smart_execution.py:549/707; `execute_trade` awaited directly at routes.py:655
**Problem:** `execute_trade` is `await`ed on the trading loop's own coroutine (not `to_thread`). Inside it, the Monte-Carlo gate calls `_get_historical_vol`, which makes a **synchronous blocking `yfinance` HTTP request** on a cache miss. This blocks the entire asyncio event loop — i.e. **all five markets' trading loops, all SSE streams, and the API** — for the duration of the network round-trip.
**Root Cause:** Blocking network I/O placed on the async hot path; only mitigated by a 1-hour vol cache, so it recurs at least once per symbol per hour and on every new symbol.
**Real-World Impact:** Periodic multi-hundred-ms to multi-second freezes of the whole system. During a freeze, live stop-losses on *other* symbols cannot fire — precisely when volatility (and thus cache misses) is highest. This is a latency-and-safety defect, not just a perf nit.
**Fix:** Move the vol fetch off-loop and reuse the cached provider instead of a second `yfinance` client:
```python
sim_result = await asyncio.to_thread(self.simulator.simulate, ...)
# and inside _get_historical_vol, use data_provider.get_historical_ohlcv (already cached/rate-limited)
```
Why correct: keeps the loop responsive so other symbols' risk checks keep running; unifies data access through the throttled provider.
**Confidence:** 90%

────────────────────────────
**Severity:** High
**Category:** Risk Management / Trading
**File:** `backend/execution/smart_execution.py` + `backend/api/routes.py`
**Function:** `execute_trade` sizing; loop risk gate
**Line Number:** sizing at smart_execution.py:530–560/700–716; no cash/exposure gate found before line 655 in routes.py
**Problem:** `PositionSizer` sizes each trade off the **full `portfolio_balance`** with a per-trade Kelly cap only. `RISK_LIMITS["max_single_position_pct"]` (15%) and `min_cash_reserve_pct` (10%) are computed in `portfolio_risk.analyze()` and shown in the UI, but **are never enforced as entry gates.** Only `halt_trading_for_day/week` block entries. Additionally, opening a SHORT only debits `margin_reserved` (15%) from balance, leaving `portfolio_balance` inflated, so subsequent Kelly sizes compound off capital that is already committed.
**Root Cause:** Position-level risk (Kelly) and portfolio-level risk (concentration, cash floor, aggregate exposure) were implemented in separate modules and never wired together at the decision gate.
**Real-World Impact:** The book can concentrate beyond the stated 15%/position and breach the 10% cash floor; aggregate exposure is unbounded except by the daily-loss breaker (which triggers only *after* losses materialize). Observed live book already runs 13 concurrent positions with no aggregate cap. Financial impact: larger drawdowns than the risk config implies.
**Fix:** Add a pre-execution portfolio gate:
```python
proj_exposure = current_position_value + shares*price
if shares*price > max_single_position_pct/100 * equity: reject
if (cash - shares*price) < min_cash_reserve_pct/100 * equity: reject
```
enforced inside `execute_trade` (or the loop) before the fill. Size shorts against committed capital, not `margin_reserved` alone.
**Confidence:** 88%

────────────────────────────
**Severity:** High
**Category:** ML / Trading (train-live consistency)
**File:** `backend/backtesting/engine.py`
**Function:** `compute_indicators`
**Line Number:** ~104–110 (RSI), ~118 (ATR), ~124 (ADX)
**Problem:** RSI/ATR/ADX use **simple rolling means** (`.rolling(14).mean()`), not **Wilder's smoothing** (the industry-standard EMA with α=1/N used by virtually every charting platform and by most live feeds). The live tick path (`data/ingestion.py`) has a `_compute_rsi` helper; the backtest reimplements indicators with different smoothing.
**Root Cause:** Two independent indicator implementations; the backtest chose SMA smoothing.
**Real-World Impact:** Backtest signals are computed on subtly different indicator values than live trading, so **backtest performance does not faithfully predict live performance** — the core purpose of a backtest. RSI-14 SMA vs Wilder can differ by several points near turning points, flipping threshold-based signals. This silently invalidates strategy validation.
**Fix:** Use Wilder's smoothing consistently, and ideally share one indicator module between backtest and live:
```python
gain.ewm(alpha=1/14, adjust=False).mean(); loss.ewm(alpha=1/14, adjust=False).mean()  # RSI
tr.ewm(alpha=1/14, adjust=False).mean()  # ATR
```
Why correct: matches standard definitions and (if unified) guarantees train/live parity.
**Confidence:** 85%

────────────────────────────
**Severity:** High
**Category:** Trading (backtest realism)
**File:** `backend/backtesting/engine.py`
**Function:** `run` — exit fill logic
**Line Number:** ~547–558
**Problem:** On a stop/TP hit the engine fills **exactly at the stop/TP price** (`exit_price = position["stop_loss"]`), then applies only slippage. Real markets **gap through** stops: a bar whose close is far past the stop should fill at/near the open or worse, not at the stop level.
**Root Cause:** Bar-based backtest assumes intrabar fills at the target price; no gap modeling.
**Real-World Impact:** Systematically **optimistic** backtest returns — losses are understated because catastrophic gap-downs are filled as if the stop held. A strategy that looks profitable in backtest can be a loser live. Combined with the RSI finding, backtest P&L should be treated as an upper bound, not an estimate.
**Fix:** Fill stops at `min(open, stop)` for longs (`max(open, stop)` for shorts) when the bar gaps past the level; add a configurable slippage floor for gap events.
**Confidence:** 80%

────────────────────────────
**Severity:** Medium
**Category:** RL
**File:** `backend/execution/smart_execution.py` / `analytics/rl_engine.py`
**Function:** `force_close` → `process_trade_outcome(trade_result, {})`
**Line Number:** smart_execution.py:~205 (passes `{}`); rl_engine.py:~155 (herding/eligibility loop over empty dict)
**Problem:** Stop-loss and take-profit exits call `process_trade_outcome` with an **empty** committee breakdown. The reward-attribution loop then iterates nothing, so **no agent weights are updated for any stop/TP exit** — yet `total_closed_trades` and `winning_trades` are still incremented.
**Root Cause:** `force_close` doesn't carry the originating committee vote, so it can't attribute the outcome.
**Real-World Impact:** The RL learns **only from committee-driven exits (COVER/SELL by signal)**, which are the minority. The majority of outcomes (stops/TPs — the ones that actually define risk-adjusted edge) teach nothing. Learning is biased toward whatever the committee happens to close manually; win-rate stats and Kelly `p` are computed over the full population, creating an inconsistency between what's measured and what's learned.
**Fix:** Persist the entry committee breakdown on the holding dict at open, and pass it through `force_close` to `process_trade_outcome`.
**Confidence:** 84%

────────────────────────────
**Severity:** Medium
**Category:** Trading (control-flow / dead branch)
**File:** `backend/api/routes.py`
**Function:** trading loops (US/Indian/others)
**Line Number:** 658, 1114, 1483 — `if "AI Trade Simulator veto" in reason`
**Problem:** The Monte-Carlo gate returns the string `"Monte Carlo veto (EV=...)"` (smart_execution.py:558/716), but the loop checks for `"AI Trade Simulator veto"`. The strings never match, so the intended special veto-logging/branch is **dead code**.
**Root Cause:** Return message was renamed without updating the consumer.
**Real-World Impact:** Low direct harm (the trade is still blocked because `success=False`), but the MC-veto path is mis-logged/mis-counted, undermining analytics that rely on veto attribution. Symptomatic of missing integration tests.
**Fix:** Return a structured result (`{"ok": False, "veto": "MONTE_CARLO", ...}`) instead of string-matching, or align the literals.
**Confidence:** 92%

────────────────────────────
**Severity:** Medium
**Category:** Math / Trading (determinism)
**File:** `backend/analytics/simulator.py`
**Function:** `simulate`
**Line Number:** ~176 `rng = np.random.default_rng()` (unseeded)
**Problem:** The 5,000-path Monte-Carlo gate is **unseeded**, so the same setup can be judged viable on one tick and non-viable on the next purely from RNG noise, especially near the hurdle.
**Root Cause:** No seeding; acceptable for large-N estimates but the EV/hurdle comparison is a hard boolean threshold.
**Real-World Impact:** Non-reproducible entry decisions and non-reproducible backtests when the committee path is used; two identical states can yield different actions. Makes debugging and validation harder and injects small unpredictability into live entries.
**Fix:** Seed per call from a deterministic hash of `(symbol, price, stop, tp, bar_time)`, or raise N and compare against a hurdle with a hysteresis band.
**Confidence:** 80%

────────────────────────────
**Severity:** Medium
**Category:** Trading (short risk)
**File:** `backend/execution/smart_execution.py`
**Function:** SHORT open / `force_close`
**Line Number:** 720–735 (margin 15%); no margin-call path
**Problem:** Shorts reserve 15% margin but there is **no margin-call/forced-liquidation** independent of the stop. If price gaps up >15% against a short before the stop fires (overnight/weekend crypto), realized loss exceeds reserved margin and `portfolio_balance` can go **negative**.
**Root Cause:** Simplified margin model without maintenance-margin enforcement.
**Real-World Impact:** Tail-risk insolvency on the short book under gap events. The bug scanner's negative-balance check catches it *after the fact*; nothing prevents it. Live, this is a real loss beyond intended risk.
**Fix:** Add a maintenance-margin monitor that force-covers when unrealized loss approaches reserved margin; size shorts so `max_adverse_before_stop < margin_reserved`.
**Confidence:** 75%

────────────────────────────
**Severity:** Medium
**Category:** Math (money precision)
**File:** `backend/execution/smart_execution.py`, `risk/portfolio_risk.py`
**Function:** all P&L/balance arithmetic
**Line Number:** throughout (balance `+=/-=` float ops)
**Problem:** All monetary state is `float`. No `Decimal`. Repeated `+=`/`-=` over thousands of trades accumulates binary floating-point drift; `round(...)` at boundaries masks but does not eliminate it.
**Root Cause:** Standard float usage.
**Real-World Impact:** Cent-level drift over long runs (tolerable for paper). For real money and audit/reconciliation against a broker, sub-cent drift and non-associative summation are unacceptable and can fail reconciliation.
**Fix:** Use `decimal.Decimal` (or integer minor-units) for cash, P&L, and balances; keep floats only for indicators/statistics.
**Confidence:** 70%

────────────────────────────
**Severity:** Medium
**Category:** Security (secrets)
**File:** `E:\Ai Stock\.env`, `backend/.env`
**Function:** n/a
**Line Number:** n/a
**Problem:** Live-service credentials (Upstox access token, Gemini keys) are stored in **plaintext `.env`** at the repo root. The Upstox token is a bearer token for a real brokerage account.
**Root Cause:** Local dev convenience.
**Real-World Impact:** Anyone with filesystem/repo access (or via the no-auth API's error surface / any path-traversal) obtains a live broker token. Combined with Finding #1, credential exposure risk is elevated.
**Fix:** Move secrets to an OS keychain / secrets manager; ensure `.env` is git-ignored (verify history for prior commits); rotate the exposed Upstox and Gemini tokens now.
**Confidence:** 85%

────────────────────────────
**Severity:** Low
**Category:** Performance / Backend
**File:** `backend/api/routes.py`
**Function:** `run_backtest` and market variants
**Line Number:** 1777, 2507, 2733, 2956, 3179 — `results = engine.run()` (no `to_thread`)
**Problem:** `engine.run()` (yfinance downloads + full bar loop) runs **synchronously inside the async endpoint**, blocking the event loop for the whole backtest.
**Root Cause:** CPU/IO-heavy call not offloaded.
**Real-World Impact:** Every backtest freezes all live trading loops and streams for its full duration (seconds). With no auth (Finding #1) this is also a DoS lever. Verified live earlier: backtests visibly stalled the loops.
**Fix:** `results = await asyncio.to_thread(engine.run)`.
**Confidence:** 90%

────────────────────────────
**Severity:** Low
**Category:** Performance
**File:** `backend/execution/smart_execution.py`
**Function:** `force_close`
**Line Number:** ~145 `import random as _random` inside the method
**Problem:** Per-call import inside a hot function.
**Real-World Impact:** Negligible perf; code smell.
**Fix:** Hoist `import random` to module scope.
**Confidence:** 95%

────────────────────────────
**Severity:** Low
**Category:** Frontend
**File:** `frontend/src/*` (multiple: `CommandPalette.tsx`, `Analytics.tsx`, `AutoTrader.tsx`, ...)
**Function:** effects / SSE subscriptions
**Line Number:** n/a (82 `useEffect/setInterval/EventSource` usages; only ~5 files show explicit cleanup)
**Problem:** Many effects/intervals/`EventSource` subscriptions; cleanup (`clearInterval`/`removeEventListener`/`.close()`) appears in only a handful of files. Likely missing cleanup → SSE/interval leaks on route changes.
**Root Cause:** Not audited line-by-line; pattern-level concern.
**Real-World Impact:** Browser memory growth and duplicate SSE connections over a long session; not capital-affecting.
**Fix:** Audit each `useEffect` for a returned cleanup; ensure `EventSource.close()` on unmount and correct dependency arrays.
**Confidence:** 55% (pattern-level, not line-verified)

---

## Positive Verifications (audited and found correct)

- **Ledger reconciliation:** cash + mark-to-market positions matched the P&L ledger to the cent in live inspection; `get_total_equity` handles SHORT as `margin + unrealized` correctly.
- **Concurrency on state mutation:** `active_holdings` mutations and balance credits are serialized under `_holdings_lock` with remove-before-credit ordering (no phantom credits). DB saves now serialized under `_get_db_lock` with upsert retry.
- **Backtest look-ahead:** signals generated on bar *close* and executed on the *next* bar's open — no forward leakage in the entry path. RL weights frozen after the 60% train split.
- **Half-Kelly inputs:** correctly uses realized win-rate as `p` (not raw confidence) and realized `b`; `<30`-trade fixed-fractional gate is sound; 5% hard cap present.
- **First-passage drift calibration** (`_calibrate_drift_asymmetric`): the bisection on θ for P(win-first) with asymmetric barriers is mathematically correct, including the Itô `+σ²/2` conversion and SHORT mirroring.
- **Circuit breakers:** daily and weekly loss halts are enforced as hard `continue` gates (not advisory), with persisted baselines across restarts.
- **DB durability:** SQLite WAL + busy_timeout + pool_size=1 is a reasonable single-writer config; JSON fallback provides a second source of truth.

---

## SCORES (engineering judgment, not measured metrics)

| # | Dimension | Score /100 | Basis |
|---|-----------|-----------|-------|
| 2 | Architecture | 68 | Clear layering, but 3,308-line `routes.py` with duplicated per-market loops; tight coupling of risk/exec; duplicate indicator impls. |
| 3 | Backend | 66 | Solid locking & state; blocking I/O on hot path, dead veto branch. |
| 4 | Frontend | 60 | Functional; unverified effect-cleanup; not deeply audited. |
| 5 | Database | 72 | Sensible SQLite/WAL; single-writer bottleneck; no migrations safety net verified. |
| 6 | Security | 20 | No auth, `0.0.0.0`, `CORS *`, plaintext live-broker token. |
| 7 | Performance | 62 | Vectorized MC good; event-loop blocking on vol fetch + backtests. |
| 8 | ML | 55 | Train/live indicator mismatch (SMA vs Wilder); leakage guarded in RL split but not proven for feature-selection path. |
| 9 | RL | 60 | Thoughtful Thompson/UCB design; but stop/TP exits don't feed learning; non-trivial complexity, low test coverage. |
| 10 | Trading Logic | 64 | Lifecycle coherent; optimistic backtest fills; portfolio caps not enforced. |
| 11 | Risk Management | 58 | Good circuit breakers; missing entry-time concentration/cash gates + short margin-call. |
| 12 | Code Quality | 63 | Heavy inline comments, some dead/deprecated code retained; float money. |
| 13 | Scalability | 55 | Single-process, single SQLite writer, per-market loop duplication. |
| 14 | Maintainability | 58 | Monolithic routes; two indicator systems; strong intent-comments help. |
| 15 | **Production Readiness** | **35** | Blocked by auth, live-order truncation, blocking I/O, unenforced caps. |

*(Scores are subjective and calibrated to institutional expectations; treat as relative severity signals, not precise measurements.)*

---

## AGGREGATE ASSESSMENT

- **Critical bugs:** 2 (no-auth control plane; live-order `int(shares)` truncation).
- **High bugs:** 4 (event-loop blocking vol fetch; unenforced portfolio risk caps; SMA-vs-Wilder train/live mismatch; optimistic gap-through backtest fills).
- **Medium bugs:** 5 (RL not learning from stop/TP exits; dead veto branch; unseeded MC; short margin-call absence; float money precision).
- **Low bugs:** 3+ (sync backtest on loop; per-call import; frontend effect cleanup).
- **Mathematical errors:** No *incorrect* formulas found in the core money-path; the issues are **modeling/consistency** (SMA vs Wilder, optimistic fills, unseeded MC), not algebra errors. The Kelly, EV, first-passage, and P&L formulas verified correct.
- **Security vulnerabilities:** Missing authN/authZ (Critical), permissive CORS, plaintext live credentials. No SQL injection found (SQLAlchemy parameterized). No eval/exec/pickle on untrusted input found.
- **Estimated probability of production failure within 30 days if deployed to real money as-is:** **~85–95%** (dominated by the live-order truncation and no-auth exposure; near-certain state desync on first live fractional order).
- **Estimated probability that material hidden bugs remain** (given ~40% of the tree was only skimmed and there is no independent trade-lifecycle test suite): **~70%**.
- **Estimated financial risk if deployed as-is:** Unbounded in the tail (short margin-call gap + live desync + no external auth). Practically: expect **loss of a meaningful fraction of deployed capital** plus a real risk of **total unauthorized control**.
- **Estimated maximum safe capital before fixes:** **₹0 real.** Paper only.
- **Estimated maximum safe capital after Critical+High fixes and a passing trade-lifecycle test suite:** Begin with a **small, capped pilot** (e.g. ≤1–2% of intended capital) under supervised live conditions; scale only after live-vs-book reconciliation holds for weeks. (I will not put a specific rupee figure on this — it depends on instrument liquidity and your risk tolerance, and a confident number here would be irresponsible.)
- **Estimated max safe concurrent users:** ~1 (single-writer SQLite, no auth/session isolation, single event loop).
- **Estimated max safe trades/day:** Paper — comfortably hundreds. The blocking vol fetch and single writer would degrade well before thousands.
- **Overall risk rating:** **HIGH.**

---

## TOP IMPROVEMENTS RANKED BY ROI (condensed from "top 100")

1. Add authentication + bind to `127.0.0.1` + lock down CORS. *(Critical, hours)*
2. Fix live-order `int(shares)` truncation → lot-size normalization. *(Critical, hours)*
3. Offload `execute_trade`'s vol fetch and `engine.run()` to threads; route vol through the cached provider. *(High, hours)*
4. Enforce `max_single_position_pct`, `min_cash_reserve_pct`, and an aggregate-exposure cap as pre-trade gates. *(High, ~1 day)*
5. Unify one indicator module (Wilder smoothing) across backtest + live. *(High, ~1 day)*
6. Model gap-through stop fills in the backtest. *(High, ~1 day)*
7. Feed stop/TP exits into RL by carrying the entry committee breakdown. *(Medium)*
8. Add maintenance-margin/force-liquidation for shorts. *(Medium)*
9. Seed the Monte-Carlo gate deterministically. *(Medium)*
10. Move money to `Decimal`/minor-units. *(Medium)*
11. Rotate exposed broker/API tokens; move to a secrets manager. *(Medium, do now)*
12. Replace string-matched vetoes with structured results. *(Medium)*
13. Build an independent trade-lifecycle test suite (property/Monte-Carlo tests for P&L invariants, reconciliation, concurrency). *(High leverage for confidence)*
14. Decompose `routes.py`; de-duplicate the five near-identical market loops. *(Maintainability)*
15. Audit frontend effect cleanup for SSE/interval leaks. *(Low)*

---

## MISSING TESTS
No independent tests for: order-lifecycle invariants (book == broker), concurrency (parallel force_close vs execute), gap/partial-fill/rejected-order handling, negative-price/zero-volume/NaN ticks, circuit-breaker edges, RL reward monotonicity, backtest determinism, and API auth. The existing `tests/test_critical_paths.py` (22 tests) is a start but does not cover the money-path adversarially.

---

## DEPLOYMENT RECOMMENDATION

> **SAFE FOR PAPER TRADING ONLY.**
> **NOT SAFE FOR REAL MONEY** until, at minimum: Findings #1 and #2 (Critical) are fixed and regression-tested; Findings #3–#6 (High) are resolved; exposed credentials are rotated; and an independent trade-lifecycle + reconciliation test suite passes. After that, proceed only via a small supervised live pilot with external monitoring before scaling capital.

*This audit is based on static code reading and targeted live probing; it is not a guarantee of correctness and does not replace a controlled live-pilot with real-time reconciliation.*
