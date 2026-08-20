"""Write SYSTEM_CONTEXT.md — the deep technical context file for cross-AI sharing."""

CONTENT = """\
# AI Stock Trading Platform - Complete System Context

PURPOSE: Share this single file with any AI assistant (Claude, Gemini, ChatGPT) and it will have\
 full deep context about this entire system including real code logic, data flows, algorithm\
 implementations, file structure, API endpoints, constraints, and known issues.

---

## 1. System Identity

- Project Name: AI Stock (V3)
- Type: Autonomous Paper Trading Engine with Multi-Agent AI Committee (Upgraded: HMM, RFECV, Thompson Sampling)
- US Assets: Gold Futures (MGC=F / GC=F) and Nasdaq Micro Futures (MNQ=F / NQ=F)
- Indian Assets: NIFTYBEES.NS (proxy index ETF), WIPRO.NS, RELIANCE.NS, ONGC.NS
- Data Source: Yahoo Finance (yfinance) exclusively for both US and Indian markets. FII/DII institutional money flows are tracked in real-time using Yahoo Finance (real top institutional holders, option chain PCR ratios, and volume-weighted price proxies); no NSDL scraping or cached estimates. No mock data, no paid APIs.
- Mode: Paper Trading (virtual money). Real brokerage integration is a future step.
- Backend: Python 3.11, FastAPI, Uvicorn, Port 8080
- Frontend: React 19, Vite 6, Tailwind CSS v4, Port 5173
- Virtual Env: .venv at e:\\Ai Stock\\.venv
- State Persistence (US & Indian Modules):
  * backend/ai_stock.db (SQLite database) - Unified persistence for:
    - `portfolio` table: Stores cash and state_data (JSON for active_holdings, closed_trades, execution_logs)
    - `rl_weights` table: Stores agent weights by regime (Trending Bull, Sideways, Trending Bear, High Volatility)
    - `logs` table: System logging
    - `trade_journal` table: Committee breakdown, entry/exit reasons
  * Replaces legacy JSON files (portfolio_state.json, rl_state.json, journal.json).

---

## 2. Directory Structure

e:\\Ai Stock\\
  HELP.md                          - User-facing feature reference
  SYSTEM_CONTEXT.md                - THIS FILE: deep technical context for AI assistants
  QUANT_ARCHITECTURE.md            - Quantitative design decisions
  .env                             - Environment variables
  .venv/                           - Python virtual environment
  start_web.bat                    - Starts both backend and frontend

  backend/
    main.py                        - Entry point: port 8080 guard, starts Uvicorn
    ai_stock.db                    - Unified SQLite database (Portfolio, RLWeight, TradeJournal)
    api/
      server.py                    - FastAPI app + CORS config
      routes.py                    - ALL REST endpoints + global engine singletons
    agents/
      base_agent.py                - Abstract BaseAgent (evaluate() interface)
      committee.py                 - TechnicalAgent, FundamentalAgent, SentimentAgent, MacroAgent, RiskAgent, VolatilityAgent, LiquidityAgent, CorrelationAgent
      master.py                    - MasterAgent: committee orchestrator + Correlation Gate
      scanner_agent.py             - Background scanner for live opportunity feed
    data/
      ingestion.py                 - DataIngestionEngine: live Yahoo Finance 1-min tick fetcher
      regime_detector.py           - MarketRegimeDetector + MultiTimeframeAnalyzer
      event_awareness.py           - EventAwarenessEngine: FOMC/CPI/NFP blackout checker
                                     IndianEventAwarenessEngine: IST 9:15AM-3:30PM market hours enforcer
      pattern_matcher.py           - HistoricalPatternMatcher: RSI/MACD similarity search
      cot_client.py                - COTClient: CFTC Commitment of Traders API
      institutional.py             - InstitutionalTracker: FII/DII flow data
      provider.py                  - DataProviderFactory: Yahoo Finance abstraction
    execution/
      smart_execution.py           - SmartExecutionEngine: trade lifecycle + RL integration
      broker.py                    - SmartOrderRouter: VWAP/TWAP/Iceberg order routing
      shadow_trading.py            - ShadowTradingEngine: tracks outcomes of vetoed trades
    analytics/
      rl_engine.py                 - ReinforcementLearningEngine: regime-specific weights + persistence
      simulator.py                 - AITradeSimulator: Monte Carlo EV check (5000 paths)
      journal.py                   - AIJournal: persistent trade log with committee breakdowns
      probability_engine.py        - ProbabilityEngine: Win%, EV, Risk Score enrichment
      self_diagnosis.py            - SelfDiagnosingAI: end-of-day 360-degree report
    risk/
      position_sizing.py           - PositionSizer: Half-Kelly criterion
      adaptive_stops.py            - AdaptiveStopLoss: ATR-based stop and TP calculator
      portfolio_risk.py            - PortfolioRiskManager: 3% daily circuit breaker
    strategies/
      strategy_manager.py          - DynamicStrategyManager: 20+ strategy competition engine
      autonomous_builder.py        - AutonomousStrategyBuilder: AI strategy generator
    backtesting/
      engine.py                    - BacktestEngine: real walk-forward on Yahoo OHLCV + RL training
    scripts/
      cold_start_rl.py             - Generates rl_seed_trades.json on first boot
      rl_seed_trades.json          - 100 synthetic historical trades (pre-training seed)

  frontend/src/pages/
    Dashboard.tsx                  - Live Command Center + TradingView charts
    AutoTrader.tsx                 - Engine terminal: live log polling every 4s
    Backtesting.tsx                - Walk-Forward IDE: auto-continuous scan on page load
    Analytics.tsx                  - RL Weights, AI Journal, Strategy Builder
    MoneyTracker.tsx               - PnL Ledger, Active Holdings, Closed Trades
    Portfolio.tsx                  - Portfolio distribution + equity curve
    Scanner.tsx                    - Macro Dashboard (DXY, VIX, COT)
    News.tsx                       - VADER-scored news sentiment hub
    Watchlist.tsx                  - Gold vs NQ correlation monitor
    SandboxTrader.tsx              - Demo sandbox trader page (added 2026-07-02)
    IndianMarket.tsx               - Indian Market console (INR, NSE/BSE, tricolor theme)

---

## 3. Full Decision Pipeline (Every 4 Seconds)

STEP 1: DataIngestionEngine.get_latest_tick()
  - Fetches live 1-min OHLCV from Yahoo Finance for MGC=F or MNQ=F (alternates each tick)
  - Computes RSI-14, MACD histogram, VWAP, ATR live on the fetched data
  - Returns tick_data with: price, rsi_14, macd_hist, volume, atr, data_source

STEP 2: EventAwarenessEngine.check_today(tick_data)
  - Checks hardcoded calendar for FOMC / CPI / NFP / Earnings blackout dates
  - Normal/Safe mode: skip tick entirely with BLACKOUT log
  - Aggressive mode: log warning but continue

STEP 3: MarketRegimeDetector.detect(symbol, tick_data)
  - Uses GaussianHMM model trained on 60 days of historical hourly data to predict 1 of 10 market states
  - Maps predicted state to 1 of 10 HMM regimes, then consolidates it to 1 of 4 RL regimes (Trending Bull, Sideways, Trending Bear, High Volatility)
  - Falls back to rule-based classification (RSI, MACD, Volume, ATR) if HMM fails or is uninitialized
  - Result injected into tick_data["regime"]

STEP 4: RL Engine get_current_weights(regime)
  - Returns the 7-agent weight dict specific to the current regime
  - Injected into tick_data["agent_weights"]

STEP 5: MasterAgent.evaluate(symbol, tick_data)
  - 7 agents vote independently: Technical Analyst, Fundamental Analyst, News & Sentiment AI, Macro Economic AI, Volatility Agent, Liquidity Agent, Correlation Agent
  - Each vote (BUY/SELL/WAIT + confidence float) scaled by agent RL weight for this regime
  - buy_conviction = sum(confidence * weight for BUY votes) / total_weight_sum
  - sell_conviction = sum(confidence * weight for SELL votes) / total_weight_sum
  - Adaptive threshold: 0.75 (Bull) to 0.88 (Sideways), adjusted by mode and macro regime
  - Risk Manager veto check if signal passes
  - Correlation Gate check (20-bar rolling Gold/NQ correlation)
  - Returns: {signal, confidence, reason, recommendation, committee_breakdown, regime}

STEP 6: ProbabilityEngine.enrich(decision, tick_data)
  - Adds Win%, Expected Value, Risk Score to decision dict

STEP 7: MultiTimeframeAnalyzer.check_alignment(symbol, direction, tick_data)
  - Fetches REAL RSI from Yahoo Finance for 4 timeframes concurrently using ThreadPoolExecutor.
  - Intermediate timeframes are cached (Daily: 1h, 4H: 30m, 1H: 10m, 15m: 3m) to eliminate loop latency.
  - Cache is dynamically invalidated if the asset price has moved by >= 0.4% since the cache was created.
  - Daily (1d/3mo) = 3pts, 4H (4h/1mo) = 2pts, 1H (1h/5d) = 1pt, 15m (15m/2d) = 1pt
  - Score >= 5/7 required. Otherwise logs [MTF WAIT] and skips.

STEP 8: SmartExecutionEngine.execute_trade(symbol, price, decision)
  - BUY: If active SHORT holding exists, close it (Buy to Cover), calculate PnL, update RL weights, and save state to SQLite. Else, open a LONG position using Half-Kelly sizing, ATR stop/TP, Monte Carlo EV check, VWAP fill, and save state to SQLite.
  - SELL: If active LONG holding exists, liquidate it (Sell to Liquidate), calculate PnL, update RL weights, and save state to SQLite. Else, open a SHORT position using Half-Kelly sizing, ATR stop/TP, Monte Carlo EV check, VWAP fill, and save state to SQLite.
  - ScannerAgent concurrently scanning both symbols for opportunity feed

---

## 4. MasterAgent Adaptive Thresholds (backend/agents/master.py)

Base thresholds by regime:
  Trending Bull:   0.75   (easiest - trend is your friend)
  Sideways:        0.88   (strictest - high chop risk)
  Trending Bear:   0.82
  High Volatility: 0.85

Mode adjustments:
  Safe mode:       threshold += 0.07
  Aggressive mode: threshold -= 0.15

Macro regime adjustments:
  Risk-Off + MNQ=F:         +0.10  (higher bar to long Nasdaq in Risk-Off)
  Stagflation + MNQ=F:      +0.15  (very hostile for tech)
  Dislocation/Panic (any):  +0.20

Correlation Gate logic:
  correlation < -0.4 AND other_symbol in active_holdings = VETO (structurally opposed)
  correlation > 0.8  AND other_symbol in active_holdings = VETO (doubles portfolio risk)
  correlation < -0.4 AND other_symbol NOT held = reduce final_confidence by 0.25

---

## 5. ReinforcementLearningEngine (backend/analytics/rl_engine.py)

Architecture: 4 regimes x 7 agents = 28 independent weight slots
The 7 RL agents are:
  1. Technical Analyst (TechnicalAgent)
  2. Fundamental Analyst (FundamentalAgent)
  3. News & Sentiment AI (SentimentAgent)
  4. Macro Economic AI (MacroAgent)
  5. Volatility Agent (VolatilityAgent)
  6. Liquidity Agent (LiquidityAgent)
  7. Correlation Agent (CorrelationAgent)

REGIMES = ["Trending Bull", "Sideways", "Trending Bear", "High Volatility"]

HMM -> RL Regime Mapping Consolidation:
  Gold/NQ 10-state HMM is mapped to 4 RL regimes for committee voting:
  - Strong Trend Bull, Weak Trend Bull, Expansion => "Trending Bull"
  - Compression, Low Liquidity                 => "Sideways"
  - Strong Trend Bear, Weak Trend Bear         => "Trending Bear"
  - News Shock, High Liquidity, Gap Day         => "High Volatility"

Constants:
  RETRAIN_INTERVAL = 5       (weights updated after every 5 closed trades)
  learning_rate    = 0.005   (small, stable per-trade updates)
  decay_factor     = 0.95    (recency bias: older trades discounted exponentially)
  weight range     = [0.1, 2.0]  (agent can never be silenced or dominate excessively)

How a trade outcome updates weights:
  1. r_multiple = (pnl / capital_allocated * 100) / 2.0  (normalize to 2% risk baseline)
  2. Apply 0.95 decay to ALL regime batch deltas (not just this regime) for recency bias
  3. For each agent in committee_breakdown:
       agreed = (agent_signal == actual_action_taken)
       reward = r_multiple * 0.005 * (+1 if agreed, -1 if not agreed)
       batch_weight_deltas[trade_regime][agent_name] += reward
  4. Every 5 trades: cap each delta at [-0.25, +0.25], apply to weights, reset batch

Persistence (SQLite Database):
  - State persisted to SQLite database `ai_stock.db` in `rl_weights` table.
  - `rl_weights` table schema:
      - market (String: "US" or "INDIA")
      - regime (String: "Trending Bull", "Sideways", "Trending Bear", "High Volatility")
      - agent_name (String)
      - weight (Float)
      - alpha (Float)
      - beta (Float)
  - `portfolio` table schema:
      - market (String)
      - cash (Float)
      - state_data (JSON: active_holdings, closed_trades, execution_logs)

---

## 6. Backtesting Engine (backend/backtesting/engine.py)

Walk-Forward Split: 60% Train / 20% Validation / 20% Test (hardcoded, always enforced)

Indicators computed per bar:
  RSI-14, MACD (12/26/9 EMA), Bollinger Bands (20, 2 std), ATR-14, EMA-50, Volume Z-score

Strategies:
  AI Committee       - RSI + MACD + Volume + EMA50 filter (mirrors live engine exactly)
  RSI Mean Reversion - BUY RSI < 30, SELL RSI > 70
  MACD Crossover     - BUY when MACD crosses above signal line, SELL on cross below
  Bollinger Breakout - BUY above upper BB + volume spike, SELL below lower BB
  EMA Trend Follow   - BUY price > EMA50 AND RSI > 50, SELL when price < EMA50

Backtesting trains the RL engine: every simulated trade close calls
rl_engine.process_trade_outcome() updating regime-specific weights with historical data.

Continuous Scan Mode (Backtesting.tsx):
  Auto-starts 1 second after page load (default ON, persisted in localStorage)
  Randomly selects: symbol x strategy x period (6mo/1y/2y/5y)
  3 second cooldown between runs, then next run starts automatically
  Pulsing purple "Auto RL Training Active" badge shows completed session count this browser session
  Max period capped at 5y (10y/max removed from auto pool to prevent timeout)

---

## 7. SmartExecutionEngine (backend/execution/smart_execution.py)

BUY flow:
  1. PositionSizer.calculate_size() - Half-Kelly: f=(p*b-q)/b where b=avg_win/avg_loss
     Returns: shares, capital_allocated
  2. AdaptiveStopLoss.calculate():
     stop_loss   = price - 1.5 * ATR
     take_profit = price + 2.5 * ATR   (minimum 1:1.67 R:R ratio)
  3. AITradeSimulator.simulate():
     5000 Monte Carlo paths using live ATR as volatility parameter
     EV must clear 0.15% slippage hurdle or trade is VETOED
  4. SmartOrderRouter.execute() - VWAP mode:
     Slices order into 5 tranches across VWAP +/- 0.05% bands
     Returns: avg_fill_price, total_cost
  5. Record holding with entry_regime and direction="LONG"
  6. Save state to SQLite database `ai_stock.db` (`portfolio` table)
  7. Returns (True, fill_details) or (False, veto_reason)

SHORT flow:
  1. PositionSizer.calculate_size() - Half-Kelly: f=(p*b-q)/b where b=avg_win/avg_loss
     Returns: shares, capital_allocated
  2. AdaptiveStopLoss.calculate():
     stop_loss   = price + 1.5 * ATR
     take_profit = price - 2.5 * ATR   (minimum 1:1.67 R:R ratio)
  3. AITradeSimulator.simulate():
     5000 Monte Carlo paths using live ATR as volatility parameter
     EV must clear 0.15% slippage hurdle or trade is VETOED
  4. SmartOrderRouter.execute() - VWAP mode:
     Slices order into 5 tranches across VWAP +/- 0.05% bands
     Returns: avg_fill_price, total_cost
  5. Record holding with entry_regime and direction="SHORT"
  6. Save state to SQLite database `ai_stock.db` (`portfolio` table)
  7. Returns (True, fill_details) or (False, veto_reason)

SELL flow (Liquidate Long):
  1. Find matching holding by symbol in active_holdings[] with direction="LONG"
  2. revenue = shares * price
  3. profit_loss = revenue - holding["value"]
  4. rl_engine.process_trade_outcome(trade_result, committee_breakdown)
  5. Append to closed_trades[], save state to SQLite database `ai_stock.db` (`portfolio` and `rl_weights` tables)
  6. Returns (True, sell_details) or (False, error_reason)

COVER flow (Close Short):
  1. Find matching holding by symbol in active_holdings[] with direction="SHORT"
  2. profit_loss = shares * (holding["entry_price"] - price)
  3. revenue = holding["value"] + profit_loss
  4. portfolio_balance += revenue
  5. rl_engine.process_trade_outcome(trade_result, committee_breakdown)
  6. Append to closed_trades[], save state to SQLite database `ai_stock.db` (`portfolio` and `rl_weights` tables)
  7. Returns (True, cover_details) or (False, error_reason)

---

## 8. API Endpoints (http://localhost:8080/api/v1/)

POST /bot/start                   - Start autonomous trading loop + scanner background tasks
POST /bot/stop                    - Stop engine gracefully
GET  /bot/logs                    - Last 50 terminal log lines (polled every 4s by UI)
GET  /bot/status                  - {is_running, active_trades, uptime_seconds}
POST /backtest/run                - Run walk-forward backtest on historical data
                                    Body: {symbol, strategy, period, initial_capital}
                                    Returns: {equity_curve[], trades[], metrics, walk_forward, trained_weights}
GET  /opportunities               - Live scanner opportunity feed from ScannerAgent
GET  /portfolio/holdings          - {balance, holdings[]}
GET  /portfolio/money-tracker     - {closed_trades[], summary{total_pnl, win_rate, gross_profit, gross_loss}}
GET  /portfolio/risk              - {drawdown_pct, halt_trading_for_day, cash_pct}
GET  /portfolio/history           - Normalized equity curve benchmarked against MNQ=F
GET  /analytics/rl-stats          - {total_closed_trades, win_rate_pct, retrain_count, regime_agent_weights}
GET  /analytics/agent-weights     - Flat average weights across all regimes (backward compat for UI)
GET  /analytics/journal           - Full AI trade journal with committee breakdowns per trade
GET  /analytics/attribution       - Causal agent and feature P&L attribution and feature correlation analysis
GET  /analytics/report            - Daily self-diagnosis 360 report
GET  /analytics/missed-opportunities - Shadow trade virtual ledger (vetoed trades + their outcomes)
GET  /analytics/events            - Upcoming macro events + blackout status
GET  /data/regime                 - {regime, active_strategy} from DynamicStrategyManager
GET  /data/live/{symbol}          - Live real-time tick for any Yahoo Finance symbol
GET  /strategies/library          - All 20+ strategies with live competition PnL stats
GET  /strategies/builder          - Autonomous strategy builder pipeline status
POST /strategies/generate         - Manually trigger autonomous strategy generation
GET  /news/global                 - RSS financial news with VADER compound sentiment scores
GET  /news/{ticker}               - News for specific ticker with VADER scores
GET  /institutional/flows         - FII/DII institutional flow data
POST /chat/stream                 - AI assistant chat endpoint (streaming)

Indian Market Modules (INR / isolated):
POST /indian/bot/start            - Start Indian autonomous trading loop + scanner background tasks
POST /indian/bot/stop             - Stop Indian engine gracefully
GET  /indian/bot/status           - {is_running, active_trades, uptime_seconds} for India
GET  /indian/bot/logs             - Last 50 Indian terminal log lines (polled every 4s by UI)
GET  /indian/portfolio/money-tracker - Indian closed trades ledger and balance summary
GET  /indian/portfolio/holdings   - {balance, holdings[]} for Indian market
GET  /indian/portfolio/history    - INR normalized equity curve benchmarked to NIFTYBEES.NS
GET  /indian/portfolio/risk       - {drawdown_pct, halt_trading_for_day, cash_pct, circuit_breaker} for India
GET  /indian/analytics/gates      - Live Indian risk gates check status (correlation, blackout)
GET  /indian/data/regime          - Indian HMM regime and strategy details
GET  /indian/analytics/agent-weights - Flat average weights for Indian agents
GET  /indian/analytics/rl-stats   - Indian RL performance stats
GET  /indian/analytics/report     - Indian market daily self-diagnosis 360 report
GET  /indian/analytics/journal    - Complete Indian AI trade journal with breakdowns
GET  /indian/analytics/attribution - Indian causal agent and feature attribution
GET  /indian/execution/fills      - Order fill history for Indian market
POST /indian/execution/set-routing - Set order routing strategy (VWAP/TWAP/Iceberg) for India
GET  /indian/opportunities        - Live Indian opportunity feed from ScannerAgent
GET  /indian/data/live/{symbol}   - Live real-time tick for any Indian Yahoo Finance symbol
POST /indian/backtest/run         - Run walk-forward backtest on Indian historical data
GET  /indian/analytics/events     - Indian specific macro events + closed hours status
GET  /indian/strategies/library   - All Indian strategies with performance stats
POST /indian/strategies/generate  - Trigger autonomous strategy generator for India
GET  /indian/strategies/builder   - Indian strategy builder pipeline status
GET  /indian/analytics/missed-opportunities - Indian shadow trade virtual ledger
GET  /indian/analytics/pattern/{symbol} - Indian historical pattern similarity analysis
GET  /indian/portfolio/news       - News feeds for Indian portfolio symbols with VADER scores

---

## 9. Hard Design Rules (Never Violate)

1. NO MOCK DATA - If Yahoo Finance is unavailable, the engine pauses. It NEVER fabricates prices or signals.
2. NO PAID APIs - All data is free Yahoo Finance + CFTC public API (publicreporting.cftc.gov).
3. REGIME-AWARE RL ONLY - Wins in Bull markets update ONLY Bull weights. Cross-regime contamination is forbidden.
4. RL STATE NEVER RESETS - SQLite `rl_weights` table updated after closed trades (persistence via ai_stock.db), loaded on every boot. Seeds load only if total_closed_trades == 0.
5. WALK-FORWARD ENFORCED - 60/20/20 split hardcoded. Test set performance is always out-of-sample.
6. CORRELATION GATE ALWAYS ACTIVE - Cross-asset risk checked every tick via 20-bar rolling correlation of real returns.
7. 3 PERCENT DAILY CIRCUIT BREAKER - PortfolioRiskManager halts all trading if daily drawdown exceeds 3%.
8. US MODULE: MGC=F AND MNQ=F ONLY - No other US assets are traded, optimized for, or tested against.
9. INDIAN MODULE: NIFTYBEES.NS (benchmark), WIPRO.NS, RELIANCE.NS, ONGC.NS ONLY.
10. INDIAN MARKET HOURS ENFORCED - IndianEventAwarenessEngine halts Indian trading outside 9:15AM-3:30PM IST (03:45-10:00 UTC), Mon-Fri.
11. ISOLATED STATE - Indian and US portfolios are completely isolated. INR capital never mixes with USD capital.

---

## 10. Frontend Architecture

Framework: React 19 + Vite 6 + Tailwind CSS v4
State management: Pure component state + useEffect polling (no Redux, no Zustand, no Jotai)
All frontend files reference: const API_BASE = 'http://localhost:8080/api/v1'

Polling intervals:
  AutoTrader page:     /bot/logs, /analytics/rl-stats, /data/regime, /portfolio/holdings - every 4s
  IndianMarket page:   /indian/bot/logs, /indian/analytics/rl-stats, /indian/portfolio/money-tracker - every 3-5s
  Dashboard page:      /opportunities, /bot/logs - every 4s
  Shell (global):      /bot/logs OR /indian/bot/logs (switches based on active route) - every 3s
  Backtesting page:    POST /backtest/run auto-triggered on completion + 3s delay (continuous loop)

Key UI features:
  Custom React Toast alerts shown ONLY on BUY/SHORT signals (not WAIT/LIQUIDATE) to prevent alert fatigue
  ML Retrain Progress bar computed from real rl_engine.get_stats() (never hardcoded or faked)
  Agent Weights Radar shows live regime-specific RL weights for current active regime
  Walk-Forward results show 60/20/20 split returns + trained agent weights from that backtest run
  IndianMarket.tsx: Tricolor themed console with INR denominations, NSE stock tabs, isolated Indian gates and committee weights

---

## 11. Known Limitations

Short Selling Supported:
  The SmartExecutionEngine fully supports SHORT positions. It can execute SHORT trades when flat, track them in the portfolio, and COVER them later.

COT API HTTP 400 & Transient Outages (Mitigated):
  CFTC API rejects certain contract codes. Permanent errors (HTTP 400/404) are cached for 1 hour. Transient errors (timeouts, DNS, connection errors, HTTP 429, HTTP 5xx) are cached for only 2 minutes to allow rapid self-healing without blocking the ingestion loop.
  File: cot_client.py

TradingView console error:
  Non-blocking cosmetic "Cannot read properties of null (reading querySelector)" error.
  Comes from the TradingView widget iframe embed, not from our code.
  File: Dashboard.tsx

MTF analysis latency & Stale Data Risk (Optimized):
  MultiTimeframeAnalyzer fetches timeframes concurrently via thread pool and caches intermediate results (Daily: 1h, 4H: 30m, 1H: 10m, 15m: 3m), reducing latency to zero on cache hits. Cache invalidation triggers automatically if the current asset price moves >= 0.4% from the cached price.
  File: regime_detector.py

Long period backtesting timeout:
  10y and max periods removed from continuous auto-scan pool to prevent backend timeout.
  Still available for manual single runs.
  File: Backtesting.tsx

---

## 12. Launch Instructions

Backend (Port 8080):
  cd "e:\\Ai Stock\\backend"
  ..\\.venv\\Scripts\\python.exe main.py

Frontend (Port 5173):
  cd "e:\\Ai Stock\\frontend_v2"
  npm run dev

One-click (both): run start_web.bat from e:\\Ai Stock\\

---

## 13. System Diagnostics & Convergence Results (Gate 1 Baseline)

Date Generated: 2026-07-02

### RL Baseline Saturation (Gate 1)
- Total Backfilled Trades: 100
- Win Rate (Seed): 65.0%
- Avg PnL per Trade (Seed): $51.61

### Agent Committee Weights
The RL engine has converged on the following weights based on historical backtest success:
- Technical Analyst: 1.7595
- Fundamental Analyst: 0.9108
- News & Sentiment AI: 1.5993
- Macro Economic AI: 1.8242
- Volatility Agent: 1.0000
- Liquidity Agent: 1.0000
- Correlation Agent: 1.0000

### Shadow Trading & Forecast Accuracy
- Shadow veto tracking and Monte Carlo EV metrics populate dynamically after 24 hours of live paper trading.

### System Readiness
- Macro Regime Classifier: ACTIVE (Using DXY, VIX, Real Yields, and CFTC COT positioning)
- Correlation Block: ACTIVE (Blocking Inverse & Extreme Positive Correlation)
- Macro Event Blackouts: ACTIVE (Paused today: Non-Farm Payrolls on 2026-07-02)
- Execution Loop: READY FOR PAPER TRADING

---

Generated: 2026-07-04 | System Version: V3.2 (V2 UI + DB Integration) | Purpose: Cross-AI context sharing
"""

import os
out = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "SYSTEM_CONTEXT.md")
with open(out, "w", encoding="utf-8") as f:
    f.write(CONTENT)
print(f"Written {len(CONTENT)} bytes to {out}")
