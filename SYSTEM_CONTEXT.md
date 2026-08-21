# AI Stock Trading Platform - Complete System Context

PURPOSE: Share this single file with any AI assistant (Claude, Gemini, ChatGPT) and it will have full deep context about this entire system including real code logic, data flows, algorithm implementations, file structure, API endpoints, constraints, and known issues.

---

## 1. System Identity

- Project Name: AI Stock Engine (V3.0 Institutional Quant Edition)
- Type: 24/7 Autonomous Multi-Asset Algorithmic Trading & Risk Engine
- Markets Supported (5 Simultaneous Autonomous Loops):
  1. US Futures: Gold Micro Futures (`MGC=F`) and Nasdaq Micro Futures (`MNQ=F`, `MES=F`)
  2. Indian Equities & Index ETFs (NSE/BSE in INR): `NIFTYBEES.NS`, `BANKBEES.NS`, `RELIANCE.NS`, `HDFCBANK.NS`
  3. US Tech Stocks & Indices: `SPY`, `NVDA`, `AAPL`, `MSFT`
  4. 24/7 Global Cryptocurrency: `BTC-USD`, `ETH-USD`, `SOL-USD`, `BNB-USD` (Live 0-Delay Binance WebSocket Streamer)
  5. Global Forex: `EURUSD=X`, `GBPUSD=X`, `USDJPY=X`
- Production Deployment: Oracle Cloud Ubuntu 24.04 VPS (`140.245.210.188`), port 8080 (backend) & port 5173 (frontend)
- Official Git Repository: `https://github.com/dextiii09/ai-stock-engine` (`main` branch)
- Quant Perfection Stack:
  * Sniper Gate: Multi-Timeframe Trend Alignment (Daily & 1-Hour trend confluence)
  * MetaGate ML: 14 multi-asset CatBoost/LightGBM model artifacts with probability threshold >= 0.65
  * 2-Stage Asymmetric Scale-Out: 50% scale-out at TP1 (1.5R) with instant Breakeven stop ratcheting + trailing runner at TP2 (3.0R+)
  * Directional Regime Gating: HMM-based bull/bear directional vetoes
  * Cross-Market Circuit Breaker: Global 3.5% Daily Drawdown Hard Stop
  * Automated Weekly Retraining: Linux cron every Sunday 00:00 UTC
- Backend: Python 3.11, FastAPI, Uvicorn, SQLAlchemy (Async SQLite WAL)
- Frontend: React 19, Vite 6, Tailwind CSS v4, Lucide Icons, TradingView LightWeight Charts

---

## 2. Directory Structure

e:\Ai Stock\
  HELP.md                          - User-facing feature reference
  SYSTEM_CONTEXT.md                - THIS FILE: deep technical context for AI assistants
  SYSTEM_VERIFICATION_REPORT.md    - Live diagnostic and telemetry proof report for Claude/Auditor
  QUANT_ARCHITECTURE.md            - Quantitative design decisions
  .env                             - Environment variables
  .venv/                           - Python virtual environment

  backend/
    main.py                        - Entry point: port 8080 guard, starts Uvicorn
    ai_stock.db                    - Unified SQLite database (Portfolio, RLWeight, TradeJournal)
    api/
      server.py                    - FastAPI app + CORS config
      routes.py                    - ALL REST endpoints + global engine singletons + 5 market trading loops
    agents/
      base_agent.py                - Abstract BaseAgent (evaluate() interface)
      committee.py                 - TechnicalAgent, FundamentalAgent, SentimentAgent, MacroAgent, RiskAgent, VolatilityAgent, LiquidityAgent, CorrelationAgent
      master.py                    - MasterAgent: committee orchestrator + Directional Regime Gate + Correlation Gate
      scanner_agent.py             - Background scanner for live opportunity feed
    data/
      ingestion.py                 - DataIngestionEngine: live Yahoo Finance 1-min tick fetcher
      websocket_streamer.py        - CryptoWebSocketStreamer: Real-time 0-delay Binance WebSocket client
      timeframe_confluence.py      - TimeframeConfluenceEngine: Higher-Timeframe (Daily/1h) trend confluence gate
      regime_detector.py           - MarketRegimeDetector + MultiTimeframeAnalyzer (4-state HMM)
      event_awareness.py           - EventAwarenessEngine: FOMC/CPI/NFP blackout checker
      institutional.py             - InstitutionalTracker: FII/DII flow data
      provider.py                  - DataProviderFactory: Yahoo Finance abstraction
      models/                      - 14 Multi-Asset MetaGate ML model files (.joblib)
    execution/
      smart_execution.py           - SmartExecutionEngine: trade lifecycle + partial_close() (2-stage scale out)
      broker.py                    - SmartOrderRouter: VWAP/TWAP/Iceberg order routing + Broker abstractions
      shadow_trading.py            - ShadowTradingEngine: tracks outcomes of vetoed trades
    analytics/
      meta_gate.py                 - MetaGate: Secondary ML classification filter (>= 0.65 probability threshold)
      meta_label.py                - MetaLabelingEngine: Feature engineering & labeling pipeline
      performance_metrics.py       - Institutional performance metrics (Sharpe, Sortino, Realized R:R, Expectancy E[R])
      rl_engine.py                 - ReinforcementLearningEngine: regime-specific weights + persistence
      hyperopt.py                  - Bayesian Optimization via Optuna for learning rates and thresholds
      simulator.py                 - AITradeSimulator: Monte Carlo EV check (5000 paths)
      journal.py                   - AIJournal: persistent trade log with committee breakdowns
    risk/
      position_sizing.py           - PositionSizer: Half-Kelly criterion
      adaptive_stops.py            - AdaptiveStopLoss: Asymmetric 2-stage TP1 (1.5R) / TP2 (3.0R) & Breakeven stops
      portfolio_risk.py            - PortfolioRiskManager: per-market risk budgeting
      global_risk.py               - GlobalRiskAggregator: 3.5% cross-market daily circuit breaker + kill switch
    strategies/
      strategy_manager.py          - DynamicStrategyManager: 20+ strategy competition engine
    backtesting/
      engine.py                    - BacktestEngine: walk-forward backtesting with 2-stage scale-out simulation
    scripts/
      train_all_metagate.py        - Retrains all 14 multi-asset MetaGate machine learning models
      audit_quant_integrity.py     - 7-suite mathematical and algorithmic integrity audit
      generate_system_verification_report.py - Auto-generates SYSTEM_VERIFICATION_REPORT.md with live telemetry
      auto_upstox_login.py         - Headless TOTP 2FA access token generator for Upstox (NSE/BSE)
  frontend/src/pages/
    Dashboard.tsx                  - Live Command Center + TradingView charts
    AutoTrader.tsx                 - Engine terminal: live log polling every 4s
    Backtesting.tsx                - Walk-Forward IDE: auto-continuous scan on page load
    Analytics.tsx                  - RL Weights, AI Journal, Strategy Builder
    MoneyTracker.tsx               - PnL Ledger, Active Holdings, Closed Trades
    Portfolio.tsx                  - Portfolio distribution + equity curve
    IndianMarket.tsx               - Indian Market console (INR, NSE/BSE, tricolor theme)


---

## 3. Full Decision Pipeline (Every 4 Seconds)

STEP 1: DataIngestionEngine.get_latest_tick()
  - Fetches live 1-min OHLCV from Yahoo Finance (uses resilient provider with exponential backoff and caching)
  - Computes RSI-14, MACD histogram, VWAP, ATR live on the fetched data
  - Returns tick_data with: price, rsi_14, macd_hist, volume, atr, data_source

STEP 1.5: LSTMSignalEngine.update_tick() / get_signal()
  - Buffers tick_data into 20-tick sequences.
  - Generates RNN-based lstm_signal and lstm_confidence using a PyTorch LSTM model.
  - Injected into tick_data["lstm_signal"] and tick_data["lstm_confidence"].

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
  - Thresholds are dynamically loaded from hyperparams.json (tuned via Optuna)
  - PPOMasterAgent loads offline weights (ppo_policy.pth) to enhance the decision layer
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
  learning_rate    = dynamically loaded from hyperparams.json (default 0.005)
  decay_factor     = dynamically loaded from hyperparams.json (default 0.95)
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

## 6. Backtesting Engine (backend/backtesting/engine.py) — v2 (upgraded 2026-07-04)

Walk-Forward Split: 60% Train / 20% Validation / 20% Test (hardcoded, always enforced)

Indicators computed per bar:
  RSI-14, MACD (12/26/9 EMA), Bollinger Bands (20, 2 std), ATR-14, ADX-14 + DI+/DI−,
  Rolling VWAP (20-bar), Supertrend (3×ATR sequential), EMA-50, Volume Z-score

Strategies (8 total):
  AI Committee        - RSI + MACD + Volume + EMA50 filter (mirrors live engine exactly)
  RSI Mean Reversion  - BUY RSI < 30, SELL RSI > 70
  MACD Crossover      - BUY when MACD crosses above signal line, SELL on cross below
  Bollinger Breakout  - BUY above upper BB + volume spike, SELL below lower BB
  EMA Trend Follow    - BUY price > EMA50 AND RSI > 50, SELL when price < EMA50
  Supertrend          - ATR-based trend bands; signal fires on direction flip (-1↔+1)
  VWAP Reversion      - BUY close < VWAP*0.99 AND RSI < 40; SELL close > VWAP*1.01 AND RSI > 60
  ADX Trend Strength  - BUY when ADX > 25 AND DI+ > DI−; SELL when DI− > DI+; HOLD when ADX < 20

Short Selling:
  SELL signals open real SHORT positions (not just exits). Capital uses symmetric margin model:
    LONG entry:  capital -= (entry_price * shares) + commission
    SHORT entry: capital -= (entry_price * shares) + commission  (margin reserved)
    Equity while open: capital + (2*entry_price − close) * shares  (for both sides)
    SHORT close: capital += (2*entry_price − exit_price) * shares − commission
    Net PnL SHORT = (entry_price − exit_price) * shares − 2*commissions

Indian market charges:
  Commission: ₹2/share (vs $0.50 for US)
  STT: 0.1% on sell-side value (auto-detected via symbol.endswith(".NS" or ".BO"))

Output metrics (v2 — all returned in every backtest):
  total_return_pct, sharpe_ratio, sortino_ratio, max_drawdown_pct, calmar_ratio,
  var_95_pct, cvar_95_pct, profit_factor, win_rate_pct,
  total_trades, winning_trades, losing_trades, long_trades, short_trades,
  avg_win_usd, avg_loss_usd, avg_hold_bars, max_hold_bars,
  max_win_streak, max_lose_streak,
  walk_forward {train_60pct, validation_20pct, test_20pct},
  monthly_returns {YYYY-MM: pct},  ← heatmap data
  benchmark {symbol, return_pct, sharpe},  ← SPY (US) or NIFTYBEES.NS (India) buy-and-hold
  monte_carlo {p5, p50, p95, expected_final},  ← 200 bootstrapped paths
  trained_weights,  equity_curve[], trades[-50:], all_trades[]

Slippage model: 5% of ATR applied at entry and exit (unfavourable direction for trader)
Commission model: US $0.50/share fixed; India ₹2/share + 0.1% STT on sell-side

Backtesting trains the RL engine: every simulated trade close calls
rl_engine.process_trade_outcome() updating regime-specific weights with historical data.

Continuous Scan Mode (Backtesting.tsx):
  Auto-starts 1 second after page load (default ON, persisted in localStorage)
  Pool: 5 symbols × 8 strategies × 3 periods (6mo/1y/2y)
  3 second cooldown between runs, then next run starts automatically
  Pulsing purple "Auto RL Training Active" badge shows completed session count this browser session

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

Core Global & System Endpoints:
GET  /health                      - Global health check + status of all 5 market loops (US, INDIA, STOCKS, CRYPTO, FOREX)
GET  /analytics/performance-breakdown - Institutional performance breakdown (Expectancy E[R], Realized R:R, Sharpe, Sortino, Rolling 30d, Per-Market stats)
POST /risk/emergency-kill-switch   - Emergency Kill Switch: immediately halts all 5 engines & liquidates 100% active positions
POST /risk/resume                 - Clears circuit breaker halt & resets mark-to-market baseline equity
POST /models/retrain-all          - Triggers asynchronous background retraining for all 14 MetaGate models

US Futures Market (/api/v1/):
POST /bot/start                   - Start US autonomous trading loop + scanner background tasks
POST /bot/stop                    - Stop US engine gracefully
GET  /bot/logs                    - Last 50 US terminal log lines (polled every 4s by UI)
GET  /bot/status                  - {is_running, active_trades, uptime_seconds}
POST /backtest/run                - Run walk-forward backtest on historical data
GET  /portfolio/holdings          - {balance, holdings[]}
GET  /portfolio/money-tracker     - {closed_trades[], summary{total_pnl, win_rate, gross_profit, gross_loss}}
GET  /portfolio/risk              - {drawdown_pct, halt_trading_for_day, cash_pct}
GET  /data/regime                 - {regime, active_strategy} from DynamicStrategyManager
GET  /data/live/{symbol}          - Live real-time tick for any symbol

Indian Equities Market (/api/v1/indian/):
POST /indian/bot/start            - Start Indian autonomous trading loop (NSE/BSE in INR)
POST /indian/bot/stop             - Stop Indian engine gracefully
GET  /indian/bot/status           - {is_running, active_trades, uptime_seconds}
GET  /indian/portfolio/holdings   - {balance, holdings[]} in INR
GET  /indian/portfolio/money-tracker - Indian closed trades ledger and balance summary
GET  /indian/portfolio/risk       - {drawdown_pct, halt_trading_for_day, cash_pct}
GET  /indian/data/regime          - Indian HMM regime and strategy details

US Tech Stocks Market (/api/v1/stocks/):
POST /stocks/bot/start            - Start US Tech Stocks trading loop (SPY, NVDA, AAPL, MSFT)
POST /stocks/bot/stop             - Stop Tech Stocks engine gracefully
GET  /stocks/bot/status           - {is_running, active_trades, uptime_seconds}
GET  /stocks/portfolio/holdings   - {balance, holdings[]}
GET  /stocks/portfolio/money-tracker - Stocks closed trades ledger

Cryptocurrency Market (/api/v1/crypto/):
POST /crypto/bot/start            - Start 24/7 Crypto trading loop (BTC, ETH, SOL, BNB)
POST /crypto/bot/stop             - Stop Crypto engine gracefully
GET  /crypto/bot/status           - {is_running, active_trades, uptime_seconds}
GET  /crypto/portfolio/holdings   - {balance, holdings[]}
GET  /crypto/portfolio/money-tracker - Crypto closed trades ledger

Forex Market (/api/v1/forex/):
POST /forex/bot/start             - Start Global Forex trading loop (EURUSD=X, GBPUSD=X, USDJPY=X)
POST /forex/bot/stop              - Stop Forex engine gracefully
GET  /forex/bot/status            - {is_running, active_trades, uptime_seconds}
GET  /forex/portfolio/holdings    - {balance, holdings[]}
GET  /forex/portfolio/money-tracker - Forex closed trades ledger

---

## 9. Hard Design Rules (Never Violate)

1. NO MOCK DATA - Real Binance WebSockets and Yahoo Finance feeds only. If data is unavailable, the engine pauses safely.
2. NO PAID APIs - All feeds use public endpoints (Binance WS, Yahoo Finance, CFTC public reporting).
3. HIGHER-TIMEFRAME CONFLUENCE (SNIPER GATE) - 5-minute entries MUST align with 1-Hour and Daily EMA(50)/EMA(200) trend; counter-trend trades are strictly VETOED.
4. METAGATE ML PROBABILITY >= 0.65 - Only signals that pass the secondary macro CatBoost/LightGBM model with >= 65% probability proceed to order execution.
5. 2-STAGE ASYMMETRIC SCALE-OUT - 50% partial exit at TP1 (1.5R) with instant Breakeven stop ratchet, leaving remaining 50% as a risk-free trend runner towards TP2 (3.0R+).
6. DIRECTIONAL REGIME GATING - Bearish regimes block Long entries; Bullish regimes block Short entries.
7. GLOBAL 3.5% DAILY DRAWDOWN CIRCUIT BREAKER - GlobalRiskAggregator halts all 5 markets if aggregate mark-to-market drawdown exceeds 3.5% from day open.
8. ISOLATED MARKET BOOKS - US, India, Tech Stocks, Crypto, and Forex run independent cash books, margin ledgers, and RL weight matrices.
9. WEEKLY AUTOMATED MODEL RETRAINING - Oracle VPS cron executes `train_all_metagate.py` every Sunday at 00:00 UTC.


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
  Backtesting.tsx (v2): 8-strategy dropdown, Sortino+VaR+CVaR metrics row, Long/Short breakdown panel,
    monthly returns heatmap (green/red intensity grid), Monte Carlo confidence card (p5/p50/p95),
    Benchmark comparison card (alpha vs SPY or NIFTYBEES.NS), LONG/SHORT badge + hold-bars in trade log
  Shell.tsx: SSE-based real-time log streaming (EventSource → /bot/stream or /indian/bot/stream)
  Analytics.tsx: Institutional Performance Metrics section with 6 cards (Sharpe, Sortino, Calmar, Max DD, VaR 95%, CVaR 95%)
  Watchlist.tsx: Live 30-day Pearson correlation data from /analytics/correlation + real gate status from /analytics/gates

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

One-click (backend + frontend): run start_web.bat from e:\Ai Stock\
  → Launches start_trading_bot.bat in a separate window (uvicorn + auto-restart + log capture)
  → Launches npm run dev for frontend in a separate window

Backend only (Port 8080): run start_trading_bot.bat
  → PowerShell Tee-Object captures all stdout + stderr to backend\logs\server.log
  → Auto-restarts if server crashes (10 second delay before restart)
  → Both US and Indian bots start automatically on every server launch (no bot_state.json dependency)

Frontend only (Port 5173): run start_dashboard.bat

Log monitor (separate terminal): run start_log_monitor.bat
  → Polls /api/v1/health, /bot/status, /indian/bot/status every 30s
  → Scans server.log for ERROR / WARNING patterns
  → Displays terminal dashboard with last 12 issues

Stop all services: run stop_servers.bat

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
- News & Sentiment AI: **0.0 (FORCED — ghost agent)** ← RL α/β params exist but weight is
  overridden to 0.0 in both backtest (engine.py) and live loop (routes.py). No point-in-time
  news archive → always current RSS → lookahead bias in backtest. RL update loop also skips
  this agent (rl_engine.py `_GHOST_AGENTS` set). The stored 1.5993 is historical artifact only.
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

---

## 16. Bug Fixes & Upgrades Applied (2026-07-07 Session)

### 1. SQLite WAL Mode — Eliminated "database is locked" Errors

**File**: `backend/database/database.py`

**Problem**: US and Indian trading loops write to `ai_stock.db` simultaneously (every 4s). SQLite's default journal mode serialises writers with an exclusive lock, causing `(sqlite3.OperationalError) database is locked` errors that aborted individual tick cycles.

**Fix**: WAL (Write-Ahead Logging) mode + 30-second busy timeout enabled at connection time via SQLAlchemy event hook:
```python
@_event.listens_for(engine.sync_engine, "connect")
def _enable_wal(dbapi_conn, connection_record):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA busy_timeout=30000")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")
```
WAL allows concurrent readers and one writer without blocking — correct for the dual-loop architecture.

---

### 2. Always-On Auto-Trader

**File**: `backend/api/routes.py` — `auto_resume_bots()`

**Problem**: `auto_resume_bots()` was conditioned on `bot_state.json` showing `us_running: true` / `india_running: true`. After laptop sleep, fresh boot, or file deletion, both bots silently never started.

**Fix**: Both US and Indian bots now start unconditionally on every server launch. Risk mode is still read from `bot_state.json` if present (falls back to "Normal" if file is missing or corrupt).

---

### 3. Log Monitoring System

**New files**:
- `backend/log_monitor.py` — Terminal dashboard that polls `/api/v1/health`, `/bot/status`, `/indian/bot/status` and scans `backend/logs/server.log` for ERROR/WARNING patterns. Refreshes every 30 seconds. Tracks last 25 issues in a deque.
- `start_log_monitor.bat` — Launcher. Run in a separate terminal alongside the bot.

**Modified**:
- `start_trading_bot.bat` — Uses PowerShell `Tee-Object` to write all stdout + stderr to both console and `backend/logs/server.log` simultaneously.
- `backend/api/server.py` — Added `RotatingFileHandler` (5 MB × 3 backups) wired to uvicorn/fastapi loggers so structured exceptions also appear in `server.log`.

---

### 4. RSI=0 / MACD=0 — Bot Never Trading Bug (Critical)

**File**: `backend/data/ingestion.py` — Line 509

**Problem**: After Boruta/RFECV feature selection, only selected features plus a small hardcoded set were stored in `active_features[symbol]`. The hardcoded set did **not** include `rsi_14` or `macd_hist`. The `_filter_features()` function then stripped those keys from every tick dict.

Root cause trace for WIPRO.NS:
1. RFECV selects `['atr_14', 'High', 'Volume']` → mapped to `['atr_14', 'high', 'volume']`
2. `active_features['WIPRO.NS']` = `['atr_14', 'high', 'volume', 'price', 'vwap', ...]` — no RSI, no MACD
3. `_filter_features()` strips any key not in `features_list` or `essential`; neither list contained `rsi_14` or `macd_hist`
4. Every agent calling `tick.get('rsi_14', 0)` received **0.0**
5. TechnicalAnalyst → 6–21% conviction → below 30% Aggressive floor → zero trades executed

**Fix** (line 509):
```python
# BEFORE:
self.active_features[symbol] = list(set(mapped_selected + [
    "price", "vwap", "dxy_momentum", "dxy_value", "real_yield_10y_trend", "vix_level"
]))

# AFTER:
self.active_features[symbol] = list(set(mapped_selected + [
    "price", "open", "high", "low", "volume", "vwap",
    "rsi_14", "macd_hist", "atr_14",       # core technical indicators — always needed by agents
    "dxy_momentum", "dxy_value", "real_yield_10y_trend", "vix_level",
]))
```

`rsi_14`, `macd_hist`, and `atr_14` are now always present in the tick dict regardless of Boruta's selection. Boruta still runs and its selected features still augment the set — this only adds a floor, not a ceiling.

---

Generated: 2026-07-07 | System Version: V3.7 (Always-On + Log Monitor + RSI Fix) | Purpose: Cross-AI context sharing — share this single file for complete system context

---

## 14. Bug Fixes & Upgrades Applied (2026-07-04 Session)

### Critical Bug Fixes

| File | Bug | Fix Applied |
|------|-----|-------------|
| backend/analytics/rl_engine.py | `KeyError: 'is_win'` in `get_stats()` | Added `is_win: pnl > 0` to trade dicts in `_trade_history` |
| backend/analytics/rl_engine.py | `load_hyperparams()` method cut off constructor initializations | Fixed indentation — method placed correctly inside `__init__` |
| backend/agents/master.py | Same indentation issue with `load_hyperparams()` | Fixed indentation |
| backend/api/routes.py | Blocking `yfinance`, `feedparser`, `COTClient` calls on FastAPI event loop → UI polling timeouts | All blocking calls wrapped in `asyncio.to_thread()` |
| frontend/src/pages/Dashboard.tsx | Indian dashboard hit `/api/v1/indian/news/global` (404) | Fixed: India uses `/api/v1/indian/portfolio/news` |
| backend/scripts/test_cot_endpoint.py | `test_url` function caused pytest to attempt fixture collection | Renamed to `check_url` |
| start_web.bat, start_dashboard.bat | Pointed to empty `frontend_v2/` directory → npm ENOENT error | Fixed to point to `frontend/` |

### Tier 1–3 ML Restorations

| Component | Description |
|-----------|-------------|
| backend/data/provider.py | Yahoo Finance resilient provider: exponential backoff (3 retries), last-known-good price cache |
| backend/api/routes.py | LSTM `LSTMSignalEngine` re-integrated into both US and Indian trading loops |
| backend/agents/master.py | Dynamic `regime_thresholds` loaded from `backend/data/hyperparams.json` via `load_hyperparams()` |
| backend/analytics/rl_engine.py | Dynamic LR and decay loaded from `hyperparams.json` at init |
| backend/analytics/hyperopt.py | Optuna-based Bayesian optimization: tunes LR, decay, thresholds. Runs on live trades or MNQ=F backtest fallback |
| backend/scripts/train_ppo_offline.py | PPO offline pre-training harness: 1 year of MNQ=F rollouts, saves `ppo_policy.pth` |
| backend/agents/ppo_master.py | Automatically loads `ppo_policy.pth` on init if it exists |

### Known Remaining Issues
- **CORS origins**: `server.py` only allows `http://localhost:5173`. If Vite binds to `::1` instead of `localhost`, add `http://[::1]:5173` to allow_origins.
- **Orphaned processes**: If backend is killed with Ctrl+C, use `taskkill /F /IM python.exe` to clear all child processes before restarting.
- **Weekend Indian market**: The `IndianEventAwarenessEngine` blocks trades outside IST 09:15–15:30 and on weekends. This is correct behaviour — the Event Blackout gate will show `BLOCKED: Indian Market Closed (Weekend)` on Saturdays and Sundays.
- **TradingView widget**: Console error `Cannot read properties of null (reading 'querySelector')` is from TradingView's embed script — it is benign and does not affect any functionality.

### Integrity Fixes Applied (Session 3 — 2026-07-04)

These fix the five data-integrity issues identified in deep review. Three items were investigated and confirmed already correct — no change needed.

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `backtesting/engine.py` | RL engine trained continuously through val/test splits → reported test-set returns were NOT out-of-sample | Added `rl_train_cutoff = int(n_rows * 0.60)`; `process_trade_outcome()` now guarded by `i < rl_train_cutoff` — val/test bars never update weights |
| 2 | `backtesting/engine.py` | SentimentAgent uses live RSS at backtest time (looks-ahead into current news) | Force `weights["News & Sentiment AI"] = 0.0` in every backtest bar before `MasterAgent.evaluate()` |
| 3 | `risk/position_sizing.py` | Kelly sizing with < 30 trades has std-error > 9 pp on `p̂` — produces wildly oversized positions | Added `n_closed_trades` param; `n < 30` → 1% fixed-fractional fallback with `kelly_gate: "fixed_fractional_lt30"` in return dict |
| 4 | `execution/smart_execution.py` | Both LONG and SHORT `calculate_size()` calls lacked `n_closed_trades` | Added `n_closed_trades=self.rl_engine.total_closed_trades` to both call sites |
| 5 | `data/institutional.py` | Docstring claimed "real-time FII/DII flows" — data is 13F (45–135 days stale) | Replaced module docstring with honest data-quality warning; updated `SYSTEM_CONTEXT.md` description |

**Confirmed correct (no changes made):**
- **HMM label switching** (`data/regime_detector.py`): States mapped by learned characteristics (return → vol → volume sort), not by raw index. Label-switching bug already fixed.
- **Monte Carlo EV gate** (`backtesting/simulator.py`): Uses `mu = 0.0` zero-drift GBM. Not circular (doesn't use the signal). Not a no-op (checks first-hit geometry). Valid conservative filter.

### Backtesting Engine Upgrades (Session 2 — 2026-07-04)

| Feature | Details |
|---------|---------|
| **Short selling** | SELL signals open SHORT positions with symmetric margin accounting. Net PnL = (entry−exit)×shares − 2×commissions |
| **3 new strategies** | Supertrend (ATR flip), VWAP Reversion (20-bar rolling VWAP), ADX Trend Strength (ADX>25 filter) |
| **New indicators** | ADX-14, DI+/DI−, rolling VWAP (20-bar), Supertrend line with sequential numpy pass |
| **Sortino ratio** | Computed from downside deviation only (returns < risk-free rate); included in all backtest results |
| **VaR-95% + CVaR-95%** | Daily 5th-percentile return and average tail loss beyond VaR |
| **Benchmark comparison** | Downloads SPY (US) or NIFTYBEES.NS (India) for same period; returns buy-and-hold return, Sharpe, and alpha |
| **Monthly returns matrix** | `{YYYY-MM: pct}` dict in every result; rendered as colour-intensity heatmap in UI |
| **Monte Carlo** | 200 bootstrapped trade orderings → p5/p50/p95/expected confidence band on final equity |
| **Trade duration + streaks** | avg_hold_bars, max_hold_bars, max_win_streak, max_lose_streak per run |
| **Long/Short breakdown** | long_trades and short_trades counts returned separately |
| **Indian STT charges** | 0.1% STT on sell-side value auto-applied for .NS/.BO symbols; commission ₹2/share (vs $0.50 US) |
| **Files changed** | `backend/backtesting/engine.py` (full rewrite), `frontend/src/pages/Backtesting.tsx` (full rewrite) |

### Previous Session Upgrades (Session 1 — 2026-07-04)

| Component | Upgrade |
|-----------|---------|
| `analytics/performance_metrics.py` | New file: Sharpe, Sortino, Calmar, VaR-95%, CVaR-95%, Max DD computation module |
| `risk/portfolio_risk.py` | Added `INSTRUMENT_BETAS` dict (14 instruments) + weighted portfolio beta in `analyze()` |
| `risk/adaptive_stops.py` | Added `update_trailing()` method for trailing ATR stops; `TRAIL_ATR_MULT = 1.2` |
| `api/routes.py` | `/portfolio/risk` and `/indian/portfolio/risk` now include `performance` block from `performance_metrics.compute()` |
| `api/routes.py` | `/bot/stream` and `/indian/bot/stream` SSE endpoints (EventSource streaming) |
| `api/routes.py` | `/analytics/correlation` endpoint: live 60-day Pearson Gold/NQ/DXY correlations from Yahoo Finance |
| `frontend/Analytics.tsx` | Institutional Performance Metrics section: 6 cards (Sharpe, Sortino, Calmar, Max DD, VaR, CVaR) |
| `frontend/Shell.tsx` | SSE-based real-time log streaming replaces 3-second polling; stale closure fixed via useRef |
| `frontend/Watchlist.tsx` | Live correlation and gate status data from backend endpoints |
| `frontend/Portfolio.tsx` | Fixed `riskData?.sector_exposure` → `riskData?.position_exposure_pct` key mismatch |

### Test Suite Status
- All 16 backend tests pass: `backend/scripts/test_attribution.py`, `test_fixes.py`, `test_indian_engine.py`, `test_tier1_rl.py`, `test_tier3.py`
- Run with: `.venv\Scripts\pytest backend --tb=short -q`
- Legacy tests in `legacy_archive/scratch/` are excluded — they import from removed `src/` module.
  To exclude: `pytest backend` (not project root)

### Statistical / Integrity Fixes (Session 4 — 2026-07-04)

| # | Issue | File(s) | Fix |
|---|-------|---------|-----|
| 1 | Sharpe/Sortino/Calmar computed from per-trade dollar PnL (scales with position size; assumes one trade = one day; backtest and live ratios disagreed) | `analytics/performance_metrics.py`, `backtesting/engine.py` | New `from_equity_curve(equity_curve)` is the single authoritative ratio function. `compute()` reconstructs a chronological equity curve from closed trades then calls it. `engine.py._compute_metrics()` also calls it. All three ratio sources now use identical daily-return methodology. |
| 2 | Thompson Sampling (`np.random.beta()`) made backtest results non-deterministic — run twice, get different Sharpe | `analytics/rl_engine.py`, `backtesting/engine.py` | `get_current_weights(deterministic=True)` returns Beta distribution MEAN `2α/(α+β)` with no RNG. Backtest calls use `deterministic=True`; live loop keeps `deterministic=False` (Thompson Sampling = exploration). |
| 3 | Monte Carlo gate used `mu=0.0` (zero-drift GBM) → P(TP first) = 0.375 analytically, EV ≈ 0 minus slippage → gate could not distinguish good setups from bad | `analytics/simulator.py`, `execution/smart_execution.py` | `simulate()` now accepts `p_win` (realized win-rate fraction). `mu_daily = sigma_daily × logit(p_win) / steps`. Gate tightens in losing streaks, loosens with edge. Caller now passes `rl_engine.regime_win_rate(regime)` (Session 5 upgrade: regime-conditional, shrunk toward global, cold-start bypass via None). |
| 4 | Kelly fed raw committee `confidence` as p (not a calibrated win probability). `b=2.0` was target R:R not realized. `recent_win_rate` passed as percentage (65.0) but code compared to 0.5 → win_rate_scalar massively inflated | `risk/position_sizing.py`, `execution/smart_execution.py` | `calculate_size()` now uses `recent_win_rate` (fraction 0–1) as Kelly's p. Accepts `realized_b` (avg_win/avg_loss from trade history) for Kelly's b. `_get_realized_b()` helper added to SmartExecutionEngine. `smart_execution.py` now divides `rl_engine.win_rate / 100.0` before passing. |
| 5 | SentimentAgent weighted 1.60 in live loop, zeroed in backtest → deploying unvalidated agent (distribution shift) | `api/routes.py` | Both US and Indian live loops now zero `weights["News & Sentiment AI"] = 0.0` before `MasterAgent.evaluate()`. System now validates what it deploys. |
| 6 | RL reward: std computed from <5 samples could be unreliable; clipped sharpe_reward avoids blowup | `analytics/rl_engine.py` | Require ≥5 samples before using real std; clip `sharpe_reward` to [−5, +5]; clip TD partial update to [−0.05, +0.05] per step. |

---

## 15. Full Source Code of Key Modules (AI Reference)

This section contains the complete or near-complete source of every module an AI needs to understand the system deeply without access to the files. Paste this entire SYSTEM_CONTEXT.md to any AI assistant and it will have full coding context.

---

### 15.1 `backend/risk/position_sizing.py` — Kelly Criterion + Sample Gate

Three bugs fixed vs. the original (Session 4):
1. `p` was `confidence` (uncalibrated score ≠ win probability). Now uses `recent_win_rate` (measured p̂).
2. `b` was hardcoded 2.0 (target R:R). Now accepts `realized_b` (trailing avg_win/avg_loss).
3. `recent_win_rate` expected as **fraction 0–1**. Callers must pass `rl_engine.win_rate / 100.0`.

```python
class PositionSizer:
    def __init__(self, max_risk_per_trade: float = 0.05):
        self.max_risk_per_trade = max_risk_per_trade   # 5% hard cap

    def calculate_size(
        self,
        confidence: float,          # Committee score (0–1); fallback p only when n<30
        current_capital: float,
        current_price: float,
        regime: str = "Sideways",
        recent_win_rate: float = 0.50,   # FRACTION (0–1). Pass rl_engine.win_rate / 100.
        atr_pct: float = 0.0,
        n_closed_trades: int = 0,        # pass rl_engine.total_closed_trades
        realized_b: float = None,        # trailing avg_win / avg_loss; None → 2.0
    ) -> dict:
        # ── Minimum-sample gate (n<30 → SE(p̂) > 9pp → Kelly over-sizes) ──────
        if n_closed_trades < 30:
            risk_pct = 0.01
            shares = round(current_capital * risk_pct / current_price, 4)
            return {"shares": shares,
                    "capital_allocated": round(shares * current_price, 4),
                    "risk_pct": round(risk_pct * 100, 2),
                    "scalars": {"regime": 1.0, "win_rate": 1.0, "volatility": 1.0},
                    "kelly_gate": "fixed_fractional_lt30"}

        # ── Calibrated Kelly inputs ───────────────────────────────────────────
        # p: realized win rate (fraction). Guard edges; fall back to confidence only when 0.
        p = float(max(0.05, min(0.95, recent_win_rate))) if recent_win_rate > 0 else confidence
        q = 1.0 - p
        # b: realized avg_win / avg_loss. Fall back to target R:R when history is thin.
        b = float(realized_b) if (realized_b is not None and realized_b > 0.1) else 2.0

        kelly_fraction = (p * b - q) / b
        half_kelly     = kelly_fraction / 2.0

        # ── Adaptive scalers ─────────────────────────────────────────────────
        # regime_scalars uses 4-name RL vocab — what detect() actually emits.
        # The old 10-name dict was dead: detect() pre-converts via HMM_TO_RL.
        # Collapsed values are conservative blends of constituent HMM scalars.
        regime_scalars = {
            "Trending Bull":   1.1,   # Strong(1.2)+Weak(1.0)+Expansion(1.0) blend
            "Trending Bear":   1.0,   # Strong(1.2)+Weak(1.0) blend, bear = neutral risk
            "Sideways":        0.5,   # Compression(0.5)+Low Liquidity(0.6), take min
            "High Volatility": 0.4,   # Gap Day(0.5)+News Shock(0.2)+High Liq(1.1): tail risk
        }
        regime_scalar = regime_scalars.get(regime, 1.0)

        # win_rate_scalar REMOVED (Session 5): p already carries win-rate via Kelly's formula.
        # Applying a separate scalar on top double-counts the same signal and is pro-cyclical.
        # Regime + volatility scalars are sufficient non-redundant adjustments.
        volatility_scalar = 1.0
        if atr_pct > 1.0:   volatility_scalar = 0.5
        elif atr_pct > 0.5: volatility_scalar = 0.8

        adjusted_kelly = half_kelly * regime_scalar * volatility_scalar
        risk_pct = min(max(0.0, adjusted_kelly), self.max_risk_per_trade)

        shares = round(current_capital * risk_pct / current_price, 4)
        return {"shares": shares,
                "capital_allocated": round(shares * current_price, 4),
                "risk_pct": round(risk_pct * 100, 2),
                "scalars": {"regime": regime_scalar, "win_rate": win_rate_scalar,
                            "volatility": volatility_scalar},
                "kelly_inputs": {"p": round(p, 4), "b": round(b, 4),
                                 "half_kelly": round(half_kelly, 4)}}
```

Call sites in `smart_execution.py` (LONG open and SHORT open — identical pattern):
```python
realized_b = self._get_realized_b()   # trailing avg_win/avg_loss from _trade_history
# win_rate stored as PERCENTAGE → divide by 100 before passing to Kelly
size_data = self.sizer.calculate_size(
    confidence, self.portfolio_balance, price,
    regime=regime,
    recent_win_rate=self.rl_engine.win_rate / 100.0,   # ← /100 critical
    n_closed_trades=self.rl_engine.total_closed_trades,
    realized_b=realized_b,
)
# Monte Carlo gate uses REGIME-CONDITIONAL win rate (Session 5).
# regime_win_rate() normalizes to 4-RL vocab internally, returns fraction [0.05,0.95],
# returns None when n<30 (cold-start bypass — veto skipped, Kelly holds at 1% flat).
p_win_frac = self.rl_engine.regime_win_rate(regime)
sim_result = self.simulator.simulate(..., p_win=p_win_frac)
...
if p_win_frac is not None and not sim_result["is_viable"]:
    return False, f"AI Trade Simulator veto ..."
```

`rl_engine.win_rate` property returns **percentage** (e.g. 65.0):
```python
@property
def win_rate(self) -> float:
    if self.total_closed_trades == 0: return 0.0
    return round(self.winning_trades / self.total_closed_trades * 100, 1)
```

---

### 15.2 `backend/risk/adaptive_stops.py` — Trailing ATR Stop

```python
STOP_ATR_MULT  = 1.5   # Initial stop: price ± 1.5×ATR
TRAIL_ATR_MULT = 1.2   # Trailing stop trails best price by 1.2×ATR
TP_RISK_REWARD = 2.0   # Take-profit = stop_distance × 2.0

class AdaptiveStopLoss:

    def calculate(self, current_price, signal, volatility_proxy=0.02):
        """Returns initial stop_loss and take_profit at trade entry."""
        distance = current_price * (volatility_proxy * STOP_ATR_MULT)
        if signal == "BUY":
            return {"stop_loss": current_price - distance,
                    "take_profit": current_price + distance * TP_RISK_REWARD,
                    "atr_distance": distance}
        else:  # SHORT
            return {"stop_loss": current_price + distance,
                    "take_profit": current_price - distance * TP_RISK_REWARD,
                    "atr_distance": distance}

    def update_trailing(self, current_price, signal, current_stop, best_price, volatility_proxy=0.02):
        """Advances trailing stop as price moves in our favour. Never moves against the trade."""
        if signal == "BUY":
            best_price = max(best_price, current_price)
            proposed   = best_price - (best_price * volatility_proxy * TRAIL_ATR_MULT)
            new_stop   = max(current_stop, proposed)   # Only move UP
        else:
            best_price = min(best_price, current_price)
            proposed   = best_price + (best_price * volatility_proxy * TRAIL_ATR_MULT)
            new_stop   = min(current_stop, proposed)   # Only move DOWN
        return {"new_stop": new_stop, "best_price": best_price,
                "stop_moved": abs(new_stop - current_stop) > 0.0001}

    def is_stop_hit(self, current_price, signal, stop_loss):
        if signal == "BUY": return current_price <= stop_loss
        return current_price >= stop_loss
```

---

### 15.3 `backend/analytics/performance_metrics.py` — Institutional Metrics

**KEY DESIGN RULE (Session 4 rewrite):** All risk ratios work on daily equity-curve *returns*, never
per-trade dollar PnL. Per-trade PnL scales with position size and implicitly assumes 1 trade = 1 day
(off by √N). One shared function (`from_equity_curve`) used by both the backtest engine and the live API.

```python
RISK_FREE_RATE_ANNUAL = 0.05        # 5% T-Bill proxy
TRADING_DAYS_PER_YEAR = 252

def from_equity_curve(equity_curve: List[Dict]) -> Dict[str, Any]:
    """
    Compute Sharpe/Sortino/Calmar/VaR/CVaR from a daily equity curve.
    Args: equity_curve — list of {date: str, equity: float} dicts.
    Methodology:
        daily return: r_i = (e_i − e_{i-1}) / e_{i-1}
        excess:       x_i = r_i − rf_daily  (rf_daily = 5% / 252)
        Sharpe:       mean(x) / std(x, ddof=1) × sqrt(252)
        Sortino:      mean(x) / downside_std(x) × sqrt(252)  [only x_i < 0]
        Calmar:       annualised_return_pct / max_drawdown_pct
                      annualised = ((1 + total_ret) ^ (252/n) − 1) × 100
        VaR-95%:      5th-percentile of daily returns × 100
        CVaR-95%:     mean of returns at or below VaR × 100
    Returns: sharpe_ratio, sortino_ratio, calmar_ratio, max_drawdown,
             var_95, cvar_95, annualized_return_pct, n_periods
    """
    # Collapse duplicate dates (last value wins), sort chronologically
    by_date = {str(pt["date"])[:10]: float(pt["equity"]) for pt in equity_curve if pt.get("equity", 0) > 0}
    equities = [by_date[d] for d in sorted(by_date)]
    returns  = np.array([(equities[i] - equities[i-1]) / max(equities[i-1], 1e-9)
                         for i in range(1, len(equities))])
    rf_daily = RISK_FREE_RATE_ANNUAL / TRADING_DAYS_PER_YEAR
    excess   = returns - rf_daily
    std_exc  = max(np.std(excess, ddof=1), 1e-9)
    ann      = math.sqrt(252)
    sharpe   = np.mean(excess) / std_exc * ann
    down     = excess[excess < 0]
    down_std = max(np.std(down, ddof=1) if len(down) >= 2 else std_exc, 1e-9)
    sortino  = np.mean(excess) / down_std * ann
    # Max drawdown (peak-to-trough on equity, not returns)
    peak = equities[0]; max_dd = 0.0
    for eq in equities[1:]:
        if eq > peak: peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd: max_dd = dd
    total_ret = equities[-1] / equities[0] - 1
    ann_ret   = ((1 + total_ret) ** (252 / len(returns)) - 1) * 100
    calmar    = ann_ret / max_dd if max_dd > 0 else 0.0
    var_95    = float(np.percentile(returns, 5)) * 100
    cvar_95   = float(returns[returns <= np.percentile(returns, 5)].mean()) * 100
    return {"sharpe_ratio": round(sharpe, 3), "sortino_ratio": round(sortino, 3),
            "calmar_ratio": round(calmar, 3), "max_drawdown": round(max_dd, 2),
            "var_95": round(var_95, 3), "cvar_95": round(cvar_95, 3),
            "annualized_return_pct": round(ann_ret, 2), "n_periods": len(returns)}

def compute(closed_trades, initial_capital=100_000.0) -> dict:
    """
    For /portfolio/risk. Per-trade statistics + equity-curve ratios.
    Rebuilds a chronological equity curve from closed_trades, then calls
    from_equity_curve() — same methodology as the backtest engine.
    """
    # Per-trade stats (win-rate, PF, expectancy) use raw PnL list
    # Ratio metrics (Sharpe etc.) use the reconstructed daily equity curve
    sorted_trades = sorted(closed_trades, key=lambda t: t.get("exit_date") or t.get("date") or "")
    equity = initial_capital
    equity_curve = []
    for t in sorted_trades:
        equity += float(t.get("pnl") or t.get("realized_pnl") or t.get("profit_loss") or 0)
        date = (t.get("exit_date") or t.get("date") or "")[:10]
        if date:
            equity_curve.append({"date": date, "equity": equity})
    ratios = from_equity_curve(equity_curve) if len(equity_curve) >= 2 else _empty_ratio_metrics()
    return {"trade_count": n, "total_pnl": ..., "win_rate_pct": ..., **ratios}
```

---

### 15.4 `backend/analytics/rl_engine.py` — Key Functions

#### `process_trade_outcome()` — Weight Update Algorithm
```python
def process_trade_outcome(self, trade_result, committee_breakdown):
    """
    Called after every closed trade. Updates regime-specific agent weights.
    IMPORTANT: In backtests this is ONLY called for i < rl_train_cutoff (first 60% of bars).
    """
    # 1. Sharpe-adjusted reward — guarded against small-std blow-up
    pnl_pct = (pnl / capital) * 100 if capital > 0 else 0.0
    recent_pnls = [t["pnl_pct"] for t in _trade_history[-30:]]
    std_pnl = np.std(recent_pnls) if len(recent_pnls) >= 5 else 1.0   # ≥5 sample gate
    if std_pnl < 1e-4: std_pnl = 1.0
    sharpe_reward = float(np.clip(pnl_pct / std_pnl, -5.0, 5.0))      # clipped ±5

    # 2. Drawdown penalty on last 20 trades (×0.3 of peak-to-trough dd)
    reward_base = sharpe_reward - (max_dd * 0.3)
    if sharpe_reward >= 0: reward_base = max(reward_base, 0.0)  # no sign flip on wins

    # 3. Adaptive LR: 2× if recent win-rate < 40%, 1.5× if < 50%, 1× otherwise
    lr = self.learning_rate * (2.0 if recent_wr < 0.40 else 1.5 if recent_wr < 0.50 else 1.0)

    # 4. LR warmup: 5× for first 10 trades in a new regime
    if trades_in_new_regime <= 10: lr *= 5.0

    # 5. Herding guard: if > 85% agents agree, halve the reward signal
    herding_mult = 0.5 if (agreed_count / total_agents) >= 0.85 else 1.0

    # 6. Accumulate batch deltas — "News & Sentiment AI" skipped (_GHOST_AGENTS set)
    #    Weight forced to 0 everywhere; updating its α/β wastes state and misleads RL.
    for agent_name in committee_breakdown:
        if agent_name in _GHOST_AGENTS: continue
        delta = reward_base * lr * herding_mult * (1 if agreed else -1)
        batch_weight_deltas[regime][agent_name] += delta

    # 7. TD partial update every 3 trades — clipped to ±0.05 per step
    if trades_since_td >= 3:
        partial = float(np.clip(delta * 0.20, -0.05, 0.05))   # max 0.05 per TD step
        weight = clip(weight + partial, 0.1, 2.0)

    # 8. Full batch update every 5 trades (RETRAIN_INTERVAL)
    if trades_since_last_retrain >= 5:
        for each agent: capped = clip(delta, -0.25, +0.25)
                        weight = clip(weight + capped, 0.1, 2.0)
        reset batch; retrain_count += 1
```

#### `get_current_weights(regime, deterministic)` — Thompson Sampling (Session 4 update)
```python
def get_current_weights(self, regime=None, deterministic=False):
    """
    Returns dict of {agent_name: weight} for the given regime.

    deterministic=True  → returns Beta distribution MEAN (2α / (α+β)), no RNG.
                          Used in backtests so the result is bit-reproducible.
                          Run twice, get the same Sharpe.
    deterministic=False → samples from Beta(alpha, beta) * 2.0 (Thompson Sampling).
                          Used in the live loop for exploration.
                          Applies regime blending over 5 ticks after a regime switch.
    """
    if deterministic:
        for agent in all_agents:
            a = alpha[regime][agent]
            b = beta[regime][agent]
            weight = 2.0 * a / (a + b)   # Beta mean, scaled to [0, 2]
            sampled_weights[agent] = clip(weight, 0.1, 2.0)
    else:
        for agent in all_agents:
            weight = np.random.beta(alpha[regime][agent], beta[regime][agent]) * 2.0
            # Regime blending: smooth transition over 5 ticks after a regime switch
            if ticks_since_switch < 5 and previous_regime:
                blend_factor = ticks_since_switch / 5.0
                weight = prev_weight * (1 - blend_factor) + weight * blend_factor
            sampled_weights[agent] = clip(weight, 0.1, 2.0)
    return sampled_weights  # ALL 7 agents always returned
```

Weight range: [0.1, 2.0]. Seven agents tracked per regime × 4 regimes = 28 independent weight slots.

#### `_adjust_weight()` — Beta params update
```python
def _adjust_weight(self, regime, agent_name, adjustment):
    if adjustment > 0:
        alpha[regime][agent] += adjustment * 5.0   # Reward → increase alpha
    else:
        beta[regime][agent]  -= adjustment * 5.0   # Punish → increase beta
    weight = clip(weight + adjustment, 0.1, 2.0)   # Deterministic weight also updated
```

---

### 15.5 `backend/backtesting/engine.py` — Key Sections

#### Supertrend (sequential, not vectorised)
```python
def _add_supertrend(df, mult=3.0):
    """Must be computed after dropna() — requires sequential numpy loop."""
    hl2 = (High + Low) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    direction = np.ones(n, dtype=int)
    for i in range(1, n):
        if close[i] > upper[i-1]:   direction[i] = 1
        elif close[i] < lower[i-1]: direction[i] = -1
        else:
            direction[i] = direction[i-1]
            if direction[i] == 1  and lower[i] < lower[i-1]: lower[i] = lower[i-1]  # only tighten
            if direction[i] == -1 and upper[i] > upper[i-1]: upper[i] = upper[i-1]
    df["supertrend_dir"] = direction   # +1 bullish, -1 bearish
```

#### Strategy Signal Logic (`get_signal()`)
```python
"AI Committee":       RSI < 35 AND MACD_hist > 0 AND close > EMA50*0.995 → BUY
                      RSI > 65 AND MACD_hist < 0 AND close < EMA50*1.005 → SELL
                      RSI < 30 → BUY (fallback);  RSI > 70 → SELL (fallback)

"RSI Mean Reversion": RSI < 30 → BUY;  RSI > 70 → SELL

"MACD Crossover":     MACD_hist > 0 AND macd > signal → BUY
                      MACD_hist < 0 → SELL

"Bollinger Breakout": close > bb_upper AND vol_zscore > 1.0 → BUY
                      close < bb_lower → SELL

"EMA Trend Follow":   close > EMA50 AND RSI > 50 AND MACD_hist > 0 → BUY
                      close < EMA50 AND RSI < 50 → SELL

"Supertrend":         direction flips -1→+1 → BUY;  +1→-1 → SELL

"VWAP Reversion":     close < VWAP*0.99 AND RSI < 40 → BUY
                      close > VWAP*1.01 AND RSI > 60 → SELL

"ADX Trend Strength": ADX > 25 AND DI+ > DI- AND RSI > 45 → BUY
                      ADX > 25 AND DI- > DI+ AND RSI < 55 → SELL
                      ADX < 20 → HOLD (ranging market, skip)
```

#### run() Loop — Capital Accounting & RL Integrity
```python
rl_train_cutoff = int(n_rows * 0.60)   # bar index boundary for RL training

# ENTRY (identical for LONG and SHORT — symmetric margin model):
capital -= (entry_price * shares) + commission

# EQUITY while open (works for both LONG and SHORT):
total_equity = capital + (2 * entry_price - close) * shares

# LONG EXIT:
capital += (2 * entry_price - exit_price) * shares - commission
gross_pnl = (exit_price - entry_price) * shares

# SHORT EXIT (buy back):
capital += (2 * entry_price - exit_price) * shares - commission
gross_pnl = (entry_price - exit_price) * shares

# RL update guard — only train on first 60% of bars:
in_train_split = (i < rl_train_cutoff)
if strategy == "AI Committee" and committee and in_train_split:
    rl_engine.process_trade_outcome(...)

# Sentiment zero (no point-in-time news in backtest):
# deterministic=True → Beta mean, no RNG → same Sharpe on every run
weights = rl_engine.get_current_weights(regime=regime, deterministic=True)
weights["News & Sentiment AI"] = 0.0   # lookahead bias: current RSS ≠ past news
data_dict["agent_weights"] = weights
```

#### Commission Model
```python
def _commission(self, price, shares, is_sell):
    if self.is_indian:
        comm = shares * 2.0                                # ₹2/share
        stt  = (price * shares * 0.001) if is_sell else 0  # 0.1% STT on sell-side
        return round(comm + stt, 4)
    return round(shares * 0.50, 4)                         # $0.50/share (US)
```

#### Full Output Shape of `_compute_metrics()`
```python
{
  # Identification
  "symbol", "strategy", "period", "currency", "is_indian",
  "initial_capital", "final_equity", "total_return_pct",

  # Risk-adjusted
  "sharpe_ratio",   # (avg_daily_return - rf_daily) / std * sqrt(252)
  "sortino_ratio",  # same but std = downside-only
  "max_drawdown_pct",
  "calmar_ratio",   # total_return / max_drawdown
  "var_95_pct",     # 5th percentile daily return × 100
  "cvar_95_pct",    # mean of returns below VaR threshold × 100
  "profit_factor",  # gross_wins / gross_losses

  # Trade counts
  "total_trades", "winning_trades", "losing_trades",
  "long_trades", "short_trades", "win_rate_pct",
  "avg_win_usd", "avg_loss_usd",

  # Duration / streaks
  "avg_hold_bars", "max_hold_bars",
  "max_win_streak", "max_lose_streak",

  # Walk-forward (60/20/20)
  "walk_forward": {"train_60pct", "validation_20pct", "test_20pct"},

  # Advanced outputs
  "monthly_returns": {"YYYY-MM": pct, ...},          # heatmap data
  "benchmark": {"symbol", "return_pct", "sharpe"},   # SPY or NIFTYBEES.NS
  "monte_carlo": {"p5", "p50", "p95", "expected_final"},  # 200 bootstrap paths

  # Raw data
  "trained_weights",    # agent weights after RL training
  "equity_curve": [],   # [{date, equity, drawdown, in_position, position_side}]
  "trades": [],         # last 50 (with side, hold_bars, exit_reason, won)
  "all_trades": [],
}
```

---

### 15.5b `backend/analytics/simulator.py` — GBM Monte Carlo Gate

GBM Monte Carlo pre-trade gate. Key fix (Session 4): `mu=0` (zero-drift) made the EV always ≈0 —
the gate couldn't distinguish good setups from bad. Fix: parameterise drift from realized win rate
so the gate tightens on losing streaks and loosens on winning runs.

```python
def _win_rate_to_daily_drift(p_win: float, daily_vol: float, steps: int) -> float:
    """
    Maps realized win-rate (0–1) → GBM daily drift mu_daily.
    Formula: mu_daily = sigma_daily × logit(p_win) / steps
    At p_win = 0.5:  mu = 0  (no edge, symmetric barrier)
    At p_win = 0.65: mu > 0  (positive edge → sim inflates win prob)
    At p_win = 0.35: mu < 0  (negative edge → gate tightens)
    p_win is CLAMPED to [0.05, 0.95] — logit explodes at 0 or 1.
    """
    p = float(np.clip(p_win, 0.05, 0.95))   # CRITICAL: guard before log
    return daily_vol * math.log(p / (1.0 - p)) / max(steps, 1)

class AITradeSimulator:
    def simulate(self, current_price, stop_loss, take_profit,
                 symbol="MNQ=F", steps=20, session_quality="NORMAL",
                 direction="LONG", p_win=None):
        annual_vol = _get_historical_vol(symbol)    # real 30-day Yahoo vol
        daily_vol  = annual_vol / sqrt(252)
        # Drift from realized edge (or zero-drift if no history yet)
        if p_win is not None and p_win > 0.02:
            mu = _win_rate_to_daily_drift(p_win, daily_vol, steps)
        else:
            mu = 0.0   # conservative default when n<30

        # 5000 GBM paths; each path checks first-passage to TP or SL
        # Works for both LONG (price ↑ → TP, price ↓ → SL) and SHORT (reversed)
        win_prob = success_count / self.simulations
        expected_value = (win_prob × reward) - ((1 - win_prob) × risk)

        # Hurdle rate = slippage cost (symbol + session quality dependent)
        # Asian thin session: 0.35%,  MNQ=F: 0.08%,  MGC=F: 0.12%,  default: 0.15%
        is_viable = expected_value > current_price * hurdle_pct
        return {"is_viable": is_viable, "win_probability": win_prob*100,
                "expected_value": expected_value, "reason": f"GBM Monte Carlo ...|{drift_note}"}
```

Call site (smart_execution.py) — regime-conditional + cold-start bypass (Session 5):
```python
# regime_win_rate() returns None when global n<30 → cold-start bypass.
# Returns a fraction [0.05, 0.95] already — no /100 needed.
# Decoupled from Kelly's p: MC gate uses regime bucket, Kelly uses global rate.
p_win_frac = self.rl_engine.regime_win_rate(regime)
sim_result = self.simulator.simulate(..., p_win=p_win_frac)
self.latest_sim_result = sim_result   # always saved for UI display

# Veto only when regime_win_rate returned a real estimate (n≥30).
# None (cold start) falls through — Kelly is already 1% flat.
if p_win_frac is not None and not sim_result["is_viable"]:
    return False, f"AI Trade Simulator veto ..."
```

`regime_win_rate(regime, k=20)` in `rl_engine.py`:
- Returns `None` when `total_closed_trades < 30` (cold-start signal to caller)
- Computes `p_regime` from `_trade_history` entries with matching `regime` key
- Shrinks toward `p_global`: `w = n_r / (n_r + k)` — at `k=20` trades need 20 regime-specific
  trades to reach 50/50 blend; thin buckets lean on global to suppress noise
- Clamps output to [0.05, 0.95] before returning (logit safety for MC drift function)
- Requires each `_trade_history` entry to carry `"regime"` key — stamped in
  `process_trade_outcome` since Session 5

---

### 15.6 Data Integrity Rules (Hard Constraints for Any AI Working on This Codebase)

1. **RL train/val/test isolation**: `process_trade_outcome()` is ONLY called when `i < rl_train_cutoff` (first 60% of bars). Never call it in val or test splits.
2. **Sentiment agent = 0 everywhere**: Force `weights["News & Sentiment AI"] = 0.0` before any `MasterAgent.evaluate()` call — in both backtests (`engine.py`) and the live loop (`routes.py`). No point-in-time news archive exists. Validate what you deploy; deploy what you validated.
3. **Kelly minimum gate + calibrated inputs**: Always pass `n_closed_trades` to `calculate_size()` (falls back to 1% if n<30). Pass `recent_win_rate` as a FRACTION (0–1), not a percentage — divide `rl_engine.win_rate` by 100. Pass `realized_b = avg_win/avg_loss` from `_get_realized_b()`. Never pass raw committee `confidence` as Kelly's p.
4. **No cross-backtest RL contamination**: `BacktestEngine` creates its own `ReinforcementLearningEngine()` — never calls `load_state()` or `save_state()`. Each backtest run starts with fresh weights.
5. **Symmetric margin model**: Entry deducts `(price×shares + commission)` for both LONG and SHORT. Equity formula `capital + (2×entry − close)×shares` works for both. SHORT close credits the same formula. Net PnL for SHORT = (entry − exit)×shares − 2×commissions.
6. **Institutional data is quarterly stale**: `institutional.py` returns 13F holders (45–135 days old). Only the PCR ratio and volume proxy are real-time. Do not describe this as "real-time FII/DII flow" anywhere.
7. **HMM label stability**: `regime_detector.py` maps HMM states by learned characteristics (sort by return, vol, volume) — NOT by raw state index. Label-switching is already fixed. Do not re-index by raw state ID.
8. **Monte Carlo drift from regime-conditional edge**: `simulator.py` accepts `p_win` (fraction [0.05,0.95]). Pass `self.rl_engine.regime_win_rate(regime)` — NOT `win_rate / 100.0`. `regime_win_rate` normalizes the HMM-vocab regime to 4-RL vocab internally, shrinks toward global via James-Stein (k=20), and returns `None` at cold start (n<30). Veto guard: `if p_win_frac is not None and not is_viable`. Do NOT pass raw `win_rate / 100.0` to the MC gate — that's Kelly's input, not the simulator's.
9. **All ratios from equity-curve returns**: Sharpe, Sortino, Calmar, VaR, CVaR must be computed via `from_equity_curve()` from `analytics/performance_metrics.py`. Never compute them from per-trade dollar PnL. Never annualize with `sqrt(252)` applied to per-trade returns.
10. **Backtest weights are deterministic**: All `get_current_weights()` calls inside `BacktestEngine` must pass `deterministic=True`.
11. **Single regime vocabulary everywhere**: `MarketRegimeDetector.detect()` always returns one of 4 RL names (`"Trending Bull"`, `"Sideways"`, `"Trending Bear"`, `"High Volatility"`) via `HMM_TO_RL`. Every downstream consumer — `position_sizing.regime_scalars`, `regime_win_rate`, `get_current_weights`, `_trade_history` stamps — must be keyed on this 4-name vocab. Do NOT key any dict on the 10-name HMM strings (`"Strong Trend Bull"`, `"News Shock"`, etc.) — `detect()` has already collapsed them and those strings will never arrive. To recover sub-regime granularity at the sizer (e.g. High Liquidity 1.1 vs News Shock 0.2), the raw HMM name would need to be carried alongside the RL name into `calculate_size` — not possible at the current 4-name boundary.
12. **Evaluation baseline reset (Session 5)**: All paper-trading P&L and risk-adjusted numbers collected before Session 5 were generated with `regime_scalar` silently fixed at `1.0` (dead 10-name dict). Post-fix, High Volatility trades size at 0.4×, Sideways at 0.5×. Do not compare pre-fix and post-fix results — treat the first 30+ trades per regime after this session as the new clean baseline.
13. **Dynamic Initial Capital Invariant**: Never pass arbitrary hardcoded `initial_capital` magic numbers into performance metrics or risk endpoints. Individual engines must pass their true configured `engine._initial_balance`, and combined cross-market breakdown must pass `GlobalRiskAggregator.total_initial_capital()`.
14. **Exact Boundary Test Verification**: Global and per-market circuit breakers must always be validated against precise sub-threshold and super-threshold boundary conditions (Daily: 3.4% -> NO halt, 3.6% -> HALT; Weekly: 6.9% -> NO halt, 7.1% -> HALT).


---

## 16. Telegram Bot, Scheduled Multi-Universe Automation & Real-Time Monitoring

### 16.1 Interactive Telegram Bot Controller (`backend/utils/telegram_bot.py`)
The engine features a native asynchronous Telegram Bot controller running directly on the production VPS, communicating over the official Telegram Bot REST API without heavy external dependencies.

* **Security & Authorization**: Inbound updates are strictly validated against `TELEGRAM_CHAT_ID` (`7016835190`). Any unauthorized access attempts receive instant rejection alerts.
* **Persistent 1-Tap Quick Action Keyboard**:
  ```text
  ┌───────────────┬───────────────┬────────────────┐
  │   📊 Status   │    💰 PnL     │  📈 Positions  │
  ├───────────────┼───────────────┼────────────────┤
  │   🖥️ System   │   👻 Shadow   │    🌐 Regime   │
  ├───────────────┼───────────────┼────────────────┤
  │ 📬 EOD Digest │  🔄 Retrain   │    🚨 Halt     │
  └───────────────┴───────────────┴────────────────┘
  ```
* **Supported Commands**:
  - `/status`: Real-time health, open positions count, and tick latencies across all 5 market loops.
  - `/system` (or `/cpu`, `/ram`, `/server`): Real-time VPS CPU %, RAM Memory (Used/Free GB), Disk (Used/Free GB), and Python process RSS memory & uptime.
  - `/pnl`: Complete quantitative performance breakdown (Win Rate %, Net Realized PnL, Profit Factor, Expectancy, Sharpe, Sortino, Max Drawdown).
  - `/positions`: Live open holdings across US, India, Stocks, Crypto, and Forex markets with entry price, current price, unrealized PnL, and TP1 ratchet status.
  - `/shadow`: Real-time Shadow Trading intelligence, active virtual setups, avoided losses count, and AI gate veto accuracy %.
  - `/regime`: Current HMM volatility regimes across SPY, Nifty, QQQ, BTC, and EUR/USD.
  - `/digest` (or `/eod`): Today's End-of-Day PnL recap, wins vs losses, best trade, worst trade, and overnight open book.
  - `/backtest <symbol>`: Instant 1-Year walk-forward backtest on historical Yahoo Finance data (e.g. `/backtest AAPL` or `/backtest RELIANCE.NS`).
  - `/halt`: Emergency Kill-Switch that halts all 5 trading loops and liquidates all open positions.
  - `/resume`: Re-activates trading loops and recalibrates portfolio equity baselines.
  - `/retrain`: Launches background AutoML retraining of all MetaGate classifiers.

### 16.2 Automated Background Automation Schedule (Oracle VPS)
```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. DAILY 18:00 UTC (23:30 IST): Automated EOD Performance Recap              │
│    • Module: TelegramBotController._daily_eod_loop()                        │
│    • Pushes complete daily PnL, win/loss breakdown, and overnight holdings   │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. SATURDAY 02:00 UTC (07:30 IST): Multi-Universe Walk-Forward Backtesting   │
│    • Script: backend/scripts/scheduled_universe_backtest.py                 │
│    • Tests 15 core assets across 3 strategies                               │
│    • Generates 'data/backtest_leaderboard.json' & sends Telegram report      │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. SUNDAY 00:00 UTC (05:30 IST): MetaGate Model AutoML Retraining            │
│    • Script: backend/scripts/train_all_metagate.py                          │
│    • Re-fits classifiers on newly closed trade samples                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 16.3 Macroeconomic Event Auto-Blackout Scanner
`EventAwarenessEngine` continuously monitors economic calendars:
- High-impact events (FOMC, CPI, NFP, RBI MPC, US/Indian market holidays) trigger automatic trade entry blackout 15 minutes before the event.
- Delivers instant high-priority Telegram push alerts upon blackout entry and clear.
- Existing open positions maintain active mathematical Stop-Loss and Trailing Breakeven protection.

### 16.4 Dynamic Regime-Adaptive ATR Multipliers (`backend/risk/adaptive_stops.py`)
ATR multipliers are calibrated to HMM volatility regimes:
- **Trending Bull**: SL = $1.2 \times ATR$, Trailing = $1.5 \times ATR$ (tight stops, strong directional momentum, higher Kelly position sizing).
- **Trending Bear**: SL = $1.3 \times ATR$, Trailing = $1.6 \times ATR$ (disciplined trailing on short trades).
- **Sideways**: SL = $1.5 \times ATR$, Trailing = $1.8 \times ATR$ (standard mean-reversion buffer).
- **High Volatility**: SL = $2.2 \times ATR$, Trailing = $2.5 \times ATR$ (wide buffer to absorb noise and prevent premature whipsaws).

