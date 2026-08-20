# AI Stock Trading Platform (V3) - Complete Documentation

Welcome to the **AI Stock Trading Platform Version 3.0**. This system has been rebuilt from the ground up as an institutional-grade, multi-agent algorithmic trading ecosystem. It features a fully autonomous AI committee that debates every trade, a probability simulation engine, reinforcement learning, and a self-diagnosing AI — all wrapped in a beautiful, live-updating React dashboard.

---

## 1. System Overview

**Ai Stock** is a sophisticated, autonomous AI trading engine focused on **Gold & Nasdaq Futures (US Module)** and **NSE/BSE Indian stocks (Indian Module)**.
Unlike simple rule-based bots, this engine uses a **Multi-AI Committee** to synthesize technicals, fundamentals (CFTC COT positioning), macroeconomics (DXY, VIX, Real Yields), and news sentiment before taking any position.

> [!NOTE]
> The US module trades `MGC=F` and `MNQ=F` exclusively. The Indian module trades `NIFTYBEES.NS`, `WIPRO.NS`, `RELIANCE.NS`, and `ONGC.NS`. Both modules share the same AI committee architecture but maintain completely isolated portfolio state and RL weight histories.

V3.1 now runs **two parallel autonomous engines**: the US Futures Engine (MGC=F/MNQ=F) and the Indian Market Engine (NSE/BSE stocks). Each module has its own dashboard page, trading loop, RL state file, portfolio ledger, and journal. They can run simultaneously on the same machine since US futures (active 9:30 PM IST onwards) and Indian market hours (9:15 AM – 3:30 PM IST) have minimal overlap.

**Core Trading Principles:**
- **Never trade from one chart** — Multi-Timeframe Consensus required.
- **Never trade before major events** — Event Awareness Engine blocks blackouts.
- **Never trade in extreme chop** — ATR-based Volatility Filter blocks whipsaws.
- **Never trade a low-probability setup** — Monte Carlo Simulator filters bad Expected Value (EV).
- **Every trade is logged** — AI Journal and Money Tracker enable post-trade analysis.
- **The engine learns** — Reinforcement Learning adjusts agent weights dynamically based on the active **Market Regime**, applying recency bias to adapt to evolving conditions over time based on actual realized profit.

---

## 2. Architecture

```text
e:\Ai Stock/
├── HELP.md                          # This documentation file
├── backend/                         # Python FastAPI V3.1 Engine
│   ├── main.py                      # Entry point (Port 8080)
│   ├── api/
│   │   ├── server.py                # FastAPI app + CORS configuration
│   │   └── routes.py                # REST API endpoints (US + Indian modules)
│   ├── agents/
│   │   ├── base_agent.py            # Abstract BaseAgent interface
│   │   ├── committee.py             # Technical, Fundamental, Sentiment, Macro, Risk agents
│   │   └── master.py                # Master AI consensus engine
│   ├── data/
│   ├── ai_stock.db                  # Unified SQLite database (Portfolio, RLWeight, TradeJournal, Log)
│   │   ├── ingestion.py             # Live tick fetcher (parameterized symbols)
│   │   ├── regime_detector.py       # HMM Regime + Multi-Timeframe Analyzer
│   │   ├── event_awareness.py       # EventAwarenessEngine + IndianEventAwarenessEngine
│   │   ├── pattern_matcher.py       # Historical similarity search
│   │   └── cot_client.py            # CFTC Commitment of Traders (COT)
│   ├── execution/
│   │   └── smart_execution.py       # SmartExecutionEngine (parameterized per module)
│   ├── risk/
│   │   ├── position_sizing.py       # Kelly criterion & dynamic position sizing
│   │   ├── adaptive_stops.py        # ATR-based dynamic stop-loss calculator
│   │   └── portfolio_risk.py        # Portfolio-level risk management
│   ├── strategies/
│   │   ├── strategy_manager.py      # 20+ strategy library + regime selector
│   │   └── autonomous_builder.py    # AI strategy generator (parameterized per module)
│   └── analytics/
│       ├── simulator.py             # Monte Carlo trade simulator
│       ├── journal.py               # AIJournal (parameterized path per module)
│       ├── rl_engine.py             # Reinforcement Learning (Beta weights, blending, MAML)
│       ├── probability_engine.py    # Win%, EV, Risk score calculation
│       └── self_diagnosis.py        # Daily self-diagnosis AI report
└── frontend/                        # React 19 + Vite 6 + Tailwind v4 UI
    └── src/pages/
        ├── Dashboard.tsx            # Live Command Center + TradingView charts
        ├── Portfolio.tsx            # Live portfolio distribution & allocation
        ├── MoneyTracker.tsx         # Detailed PnL, Active Holdings, and Trade Ledger
        ├── AutoTrader.tsx           # AI engine terminal (US futures)
        ├── IndianMarket.tsx         # Indian Market console (INR, NSE/BSE, tricolor theme)
        ├── IndianBacktesting.tsx    # Walk-Forward Backtest IDE for Indian Market
        ├── Analytics.tsx            # AI Journal, Agent Weights, Strategy Builder
        ├── News.tsx                 # AI Sentiment news hub
        ├── Backtesting.tsx          # Walk-Forward Backtest IDE with Auto-mode
        ├── Scanner.tsx              # Macro Dashboard (DXY, VIX, yields, COT)
        └── Watchlist.tsx            # Correlation Monitor (Gold vs NQ, DXY, VIX)
```

---

## 3. Starting the Application

### Option A: One-Click Launch (Recommended)
Three `.bat` files are provided in the root `e:\Ai Stock\` directory:
| File | Purpose |
|---|---|
| `start_dashboard.bat` | Starts the React frontend (port 5173) |
| `start_daemon.bat` | Starts the Python backend engine (port 8080) |
| `start_web.bat` | Starts both simultaneously |

*Note: Always ensure the backend is running before testing the frontend to prevent connection errors.*

### Option B: Manual Launch
**Backend (FastAPI):**
```powershell
cd "e:\Ai Stock\backend"
python main.py
```
*(The backend script automatically prevents duplicate runs if port 8080 is in use).*

**Frontend (React/Vite):**
```powershell
cd "e:\Ai Stock\frontend"
npm run dev
```
Open **http://localhost:5173** in your browser.

---

## 4. Feature Reference

### Core AI Engine
- **Feature 1 — Multi-AI Decision Engine:** Seven specialized sub-agents (Technical Analyst, Fundamental Analyst, News & Sentiment AI, Macro Economic AI, Volatility Agent, Liquidity Agent, Correlation Agent) vote independently. The system uses a consensus model scaled by the active market regime's RL weights to dynamically evaluate sub-agent signals (scaled by confidence values) and macro states.
- **Feature 2 — HMM Regime Detection:** The engine classifies the market into 4 regimes (Trending Bull, Trending Bear, Range Bound, High Volatility) using a dynamically trained **Gaussian Hidden Markov Model (GaussianHMM)** instead of rigid static thresholds. This allows probabilistic state transitions based on 60-day historical returns and volatility.
- **Feature 3 — Strategy Competition Engine:** Runs 20+ built-in strategies in parallel, tracking their virtual PnL, and dynamically selects the current market leader.
- **Feature 4 — AI Confidence Engine:** Every decision outputs detailed metrics: `Confidence %`, `Win Probability`, `Expected Value`, `Risk Score`, and `Estimated Holding Time`.
- **Feature 5 — Adaptive Thresholds & Optuna Tuning:** The engine dynamically adjusts its confidence requirements based on the active market regime. These thresholds, along with RL learning rates and decay factors, are autonomously optimized via Bayesian Hyperparameter Tuning (`hyperopt.py`) using Optuna on actual live trade histories.
- **Feature 6 — AI Coach Insights:** The Master Agent provides explicit human-readable reasons and recommendations for every tick (e.g., "Wait for a confirmed breakout").
- **Feature 6.5 — LSTM Sequence Prediction:** An integrated PyTorch LSTM (`lstm_model.py`) constantly buffers 20-tick sequences of RSI, MACD, VWAP, and price action to generate deep-learning-based signal projections (`lstm_signal`, `lstm_confidence`) injected directly into the decision pipeline.

### Execution & Risk
- **Feature 7 — Dedicated Assets:** A background scanner that constantly streams live tick data for **Gold (XAUUSD)** and **Nasdaq (NQ)**, feeding a real-time opportunities feed to the UI.
- **Feature 8 — Monte Carlo Slippage Hurdle:** Before execution, the AI Simulator runs 5,000 rapid Monte Carlo simulations of the anticipated price path. If the Expected Value (EV) fails to clear a 0.15% slippage/cost hurdle, the trade is vetoed.
- **Feature 9 — Multi-Timeframe Consensus:** Analyzes structural alignment across **Daily (3 pts), 4H (2 pts), 1H (1 pt), and 15m (1 pt)** timeframes using a Weighted Scoring system. Since a total score >= 5/7 is required to execute, Daily timeframe alignment is mathematically required to pass.
- **Feature 10 — Fractional Kelly Position Sizing:** Dynamically calculates position size using the Half-Kelly criterion, inherently absorbing statistical estimation errors and preventing over-leveraging.
- **Feature 11 — Event Awareness:** Automatically detects FOMC meetings, CPI releases, and Earnings. All trading is paused during blackouts (`🚫 BLACKOUT`).
- **Feature 12 — Adaptive Stop Loss:** Stop losses are calculated using live ATR-proxy volatility bands, not fixed percentages.
- **Feature 13 — Portfolio-Level Risk:** Monitors Sector Exposure, Position Concentration, and Portfolio Beta to prevent catastrophic multi-asset drawdowns.

### Tracking & Analytics
- **Feature 14 — Persistent Money Tracker:** Fully automated live ledger. Tracks Available Cash, Invested Capital across Active Holdings, and computes Net Profit, Gross Profit, and Win Rate on all Closed Trades. State is permanently saved to the SQLite `Portfolio` table. Includes **Live Dollar P&L Tracking** and **Holdings CSV Export** functionality.
- **Feature 15 — Symmetrical Shadow Trading:** Tracks trades the AI rejected due to strict thresholds. If the trade hits its virtual target, it is logged as a missed opportunity (lowering strictness). If it hits its stop loss, it is logged as an avoided loss (reinforcing strictness).
- **Feature 16 — Advanced Reinforcement Learning:** After every closed trade, the RL Engine adjusts weights based on the raw R-multiple (`pnl_pct / 2.0`) reward signal. Features include:
  * **Thompson Sampling**: Weighs agent votes by drawing probabilistic samples from Beta distributions (`np.random.beta`) per regime to automatically balance exploration vs exploitation.
  * **Regime Blending**: Linear interpolation blends agent weights over a 5-tick window when regimes switch, preventing abrupt position-sizing shocks.
  * **TD-style Partial Updates**: 20% of accumulated deltas are applied immediately every 3 trades to prevent learning delay.
  * **Warm Restarts (SGDR) on Regime Switch**: Multiplies the learning rate by 5x (learning rate warmup) for the first 10 trades after a regime shift to rapidly adapt to structural breaks.
  * **Offline PPO Pre-training**: The Master Agent decision layer is backed by a Proximal Policy Optimization (PPO) neural network, trained offline on 1 year of historical market data via `train_ppo_offline.py` to bootstrap expert-level policy weights before live deployment.
- **Feature 17 — AI Trade Journal:** Every executed trade is logged with the full AI Committee Breakdown, Entry/Exit prices, and reasoning.
- **Feature 18 — Historical Pattern Search:** On every tick, the engine searches 1,000 historical setups for similar RSI/MACD configurations and outputs historical win probabilities.
- **Feature 19 — Self-Diagnosing AI (V3 360-Degree Reporting):** Generates end-of-day reports that analyze the entire macro ecosystem. Incorporates Portfolio Risk, Event Blackouts, Reinforcement Learning Shadow Trades (Veto Success Rates), and Agent Weight correlations to determine if the AI overtraded or is operating effectively.
- **Feature 20 — Dynamic News Sentiment Scoring:** Connects to Yahoo Finance global news to generate live VADER sentiment scores (e.g. Bullish +0.32), keeping the AI informed of immediate fundamental market shifts.
- **Feature 21 — Smart UI Alerting:** The React frontend utilizes a smart alerting stack that only issues critical Toast popups for actionable `[BUY]` or `[SHORT]` orders, silencing standard logs to avoid alert fatigue during heavy market chop.

- **Feature 26 — Short Selling:** The Smart Execution Engine fully supports shorting assets when the AI issues a high-conviction SELL signal, doubling the total market surface area by letting the engine profit in bear markets.

### Backtesting & Generation
- **Feature 22 — Real Walk-Forward Backtesting with RL Training:** Complete historical backtesting engine with an "Auto" mode that tests randomized parameters. Visualizes Equity Curves, Train/Test validation metrics, and historical trade logs. Runs the actual **Multi-Agent AI Committee** pipeline historically, feeding trade outcomes into the **Reinforcement Learning Engine** to generate accurate **Trained Agent Weights** that are displayed directly in the UI.
- **Feature 23 — Autonomous Strategy Builder:** The AI continuously generates new strategies from indicator combinations, advances them through a multi-stage pipeline, and flags them for deployment only if they survive a strict **Out-Of-Sample (OOS) validation gate**.
- **Feature 24 — Sandbox Trader (Demo Mode):** An interactive, risk-free sandbox interface allowing you to manually execute buy and sell orders on real live Yahoo Finance prices using a virtual $250,000 balance. Completely isolated from the main AI committee engine, letting you instantly verify platform logic, PnL tracking, win/loss stats, and visual feedback (confetti) without waiting for AI consensus.

---

## 5. API Reference (Key Endpoints)

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/bot/start` | Start the autonomous trading loop |
| POST | `/api/v1/bot/stop` | Stop the engine |
| POST | `/api/v1/backtest/run` | Execute walk-forward backtest on historical data |
| GET | `/api/v1/opportunities` | Live feed of broad-market scanned opportunities |
| GET | `/api/v1/bot/logs` | Fetch live AI committee terminal logs |
| GET | `/api/v1/portfolio/holdings` | Live executed portfolio (Cash & Active Holdings) |
| GET | `/api/v1/portfolio/money-tracker` | Complete trade ledger (Closed Trades & Summary KPIs) |
| GET | `/api/v1/portfolio/risk` | Portfolio-level risk profile metrics |
| GET | `/api/v1/analytics/journal` | Complete AI Trade Journal history |
| GET | `/api/v1/analytics/missed-opportunities` | Shadow Trading virtual ledger of missed trades |
| GET | `/api/v1/analytics/report` | Daily self-diagnosis insights |
| GET | `/api/v1/analytics/agent-weights` | Current RL-adjusted committee voting weights |
| GET | `/api/v1/strategies/library` | Full strategy library catalogue with live competition stats |

---

## 6. Database & Persistence

Currently, the AI operates in **Paper Trading Mode**.
- **Market Data Feed (Yahoo Finance):** The system connects strictly to `yfinance` to fetch live 1-minute tick aggregates and historical OHLCV data. No external API keys (such as Polygon.io) are required. The data provider implements a **Resilient Cache and Exponential Backoff** engine to gracefully handle Yahoo Finance rate limits or stale data without crashing the trading loops.
- **Portfolio Persistence:** Paper trading cash, holdings, and executed trades are saved automatically to the SQLite database (`ai_stock.db`). If the server restarts, this state is instantly rehydrated.
- **Database (SQLite):** The application relies on `ai_stock.db` using SQLAlchemy for persistent storage of Portfolio ledgers, RLWeights, TradeJournals, and System Logs.

---

## 7. Troubleshooting FAQ

**Q: The Money Tracker shows $0 invested and 0 trades, but my Cash Balance is $100000?**
**A:** This means the AI Engine has not yet found a high-probability setup to execute. The engine is waiting for a signal. Once a trade is executed, Cash will decrease and the "Active Holdings" table will populate. 

**Q: The Command Center terminal keeps showing `[MTF WAIT]` or `🚫 BLACKOUT`. Is it broken?**
**A:** No, this is the AI doing its job perfectly! It is actively vetoing low-conviction setups due to conflicting multi-timeframe trends or upcoming macroeconomic events. 

**Q: "Could not fetch news. Using fallback demo data."**
**A:** Ensure your backend server is running. If you are connected to the backend but still see this, the external News API may have reached its rate limit.

**Q: Why are all Agent Weights sitting at 1.0?**
**A:** Agent weights only adapt via Reinforcement Learning *after* a trade is completely closed (SELL). Once a few trades close, you will see the profitable agents' weights increase.

**Q: I tried to start the backend but it says "Port 8080 is already in use".**
**A:** You likely already have the backend running in another terminal window or a background task. The system detects this and gracefully prevents a second instance from crashing your database. Use the existing terminal window.

**Q: I see a `[EXECUTION VETO]` in the logs. What does it mean?**
**A:** This is the AI Execution Engine reporting exactly why a trade was blocked. The position sizing might have returned 0 shares due to low confidence (e.g., Kelly sizing rule), or the Monte Carlo simulator vetoed it because the projected trade path failed to clear the 0.15% slippage/cost expected-value hurdle. If you see "Liquidate failed", it means the AI issued a SELL signal but was trying to close a LONG position when none existed (though the engine does support going SHORT when appropriately confident).

**Q: Is the trading loop execution slow or laggy?**
**A:** No, latency is optimized. High-timeframe queries are fetched concurrently via a ThreadPoolExecutor and cached (Daily: 1 hour, 4H: 30 mins, 1H: 10 mins, 15m: 3 mins). Similarly, CFTC COT API fetch failures are cached for 1 hour, eliminating loop blocking from external rate limits or server down times.

## 8. Path to Live Trading (4 Gates)

Before you migrate this system to a live brokerage account, you must successfully pass the following 4 Validation Gates to ensure the system is stable, profitable, and risk-controlled in real-time market conditions. **These 4 gates are now tracked live in real-time on the Dashboard Command Center.**

### Gate 1: RL Baseline Saturation
Run the engine in paper trading mode until it records **100 closed trades**. Ensure that the Reinforcement Learning engine has naturally settled on stable agent weights (e.g. they stop wildly swinging day-by-day). This ensures your AI committee is properly calibrated.
*Tip: You can use the `backend/scripts/cold_start_rl.py` script to generate historical seed data if you don't want to wait for 100 live paper trades.*

### Gate 2: Shadow Trading Calibration
Monitor the **Shadow Trading Success Rate** in the Daily Diagnostics report. Your AI will veto hundreds of setups. You need the shadow trading success rate to remain >50% over a 2-week period. If it drops below 50%, it means your committee is too strict and is rejecting high-quality trades.

### Gate 3: Correlation & Drawdown Control
Validate that the **MGC and MNQ P&L Correlation** stays below 0.6 in the daily diagnostics. If they are highly correlated, your risk is effectively doubled. Also ensure the newly implemented **3% Daily Circuit Breaker** correctly halts trading in paper mode if drawn down.

### Gate 4: Forward-Tested EV Accuracy
Check the **Monte Carlo EV Forecast Accuracy** over 50 trades. If the AI consistently predicts a +1% Expected Value but the actual returns are -0.2%, your slippage modeling or ATR projections are fundamentally incorrect for current market conditions. Adjust them in `simulator.py` before touching real capital.

---

## 9. Indian Market Module

The **Indian Market Console** (`/indian-market`) runs a fully independent trading engine targeting NSE/BSE stocks.

### Setup
- Navigate to `http://localhost:5173/indian-market` in your browser
- The Indian engine uses **INR 4,150** virtual capital (paper trading mode)
- Click **Start Engine** on the Indian Market console

### Market Hours Enforcement
The `IndianEventAwarenessEngine` automatically enforces Indian market trading hours:
- **Allowed**: Mon–Fri, 9:15 AM – 3:30 PM IST (03:45 – 10:00 UTC)
- **Blocked**: All other hours — the engine will log a blackout and skip the tick

### Indian Assets
| Symbol | Description | Role |
|---|---|---|
| `NIFTYBEES.NS` | Nifty BeES ETF | Benchmark / Primary Index |
| `WIPRO.NS` | Wipro Ltd | Large-Cap IT |
| `RELIANCE.NS` | Reliance Industries | Large-Cap Conglomerate |
| `ONGC.NS` | ONGC Ltd | Large-Cap Energy |

### Correlation Gate (Indian)
- Stocks (`WIPRO`, `RELIANCE`, `ONGC`) are correlated against the `NIFTYBEES.NS` benchmark
- `correlation > 0.8` → VETO (doubles portfolio risk)
- `correlation < -0.4` → reduce confidence by 0.25

### State Files
| File | Contents |
|---|---|
| `ai_stock.db` (`Portfolio` table) | Indian portfolio (INR balance, holdings, closed trades) |
| `ai_stock.db` (`RLWeight` table) | Indian RL weights (Thompson Sampling per regime) |
| `ai_stock.db` (`TradeJournal` table)| Indian trade journal with committee breakdowns |

### Promotion Gates (Indian Module)
Apply the same 4 gates as the US module **independently**:
1. **RL Saturation**: 30+ closed Indian trades before considering real INR capital
2. **Shadow Rate**: Monitor vetoed trade outcomes for 2+ weeks
3. **Drawdown Control**: 3% daily circuit breaker applies independently
4. **EV Accuracy**: Track Monte Carlo prediction vs actual returns over 50 trades

> [!CAUTION]
> Do NOT promote the Indian module to real INR capital simply because the US module has passed its gates. Each module must independently satisfy all 4 gates. They track separate markets with different dynamics.

### Simultaneous Operation
US futures (CME, active from ~9:30 PM IST) and Indian markets (NSE, 9:15 AM – 3:30 PM IST) have minimal hour overlap. You can run both engines on the same machine 24/7 without resource contention.


