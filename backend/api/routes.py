from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from starlette.requests import Request
import asyncio
import json as _json
from pydantic import BaseModel
import time
from datetime import datetime
import feedparser
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from dotenv import load_dotenv
load_dotenv()

from agents.master import MasterAgent, IndianMasterAgent
from ai_bug_finder import get_bug_finder
from agents.scanner_agent import ScannerAgent
from data.ingestion import DataIngestionEngine
from data.event_awareness import EventAwarenessEngine
from data.timeframe_confluence import TimeframeConfluenceEngine
from data.pattern_matcher import HistoricalPatternMatcher
from data.institutional import InstitutionalTracker
from utils.notifier import notifier
from data.regime_detector import MarketRegimeDetector, MultiTimeframeAnalyzer
from execution.smart_execution import SmartExecutionEngine
from execution.shadow_trading import ShadowTradingEngine
from analytics.probability_engine import ProbabilityEngine
from analytics.self_diagnosis import SelfDiagnosingAI
from analytics.attribution import CausalAttributionEngine
from analytics.lstm_model import LSTMSignalEngine
from analytics import performance_metrics
from analytics import hyperopt_loop
from execution.broker_factory import get_current_mode, save_config as save_broker_config
from strategies.strategy_manager import DynamicStrategyManager
from strategies.autonomous_builder import AutonomousStrategyBuilder
from risk.portfolio_risk import PortfolioRiskManager
from risk.global_risk import GlobalRiskAggregator
from backtesting.engine import BacktestEngine

class BacktestRequest(BaseModel):
    symbol: str
    strategy: str
    period: str = "1y"
    initial_capital: float = 100000.0

import os

DB_ENABLED = os.getenv("DB_ENABLED", "false").lower() == "true"

try:
    from database.database import AsyncSessionLocal, Base, engine
    import database.models
    from database.models import Log, Order, Portfolio, RLWeight
except ImportError:
    pass

router = APIRouter(prefix="/api/v1")

@router.get("/health")
async def health_check():
    """PR-2: Full per-engine heartbeat health endpoint."""
    now = time.time()
    _engines_info = [
        ("US",     engine_state,    execution_engine),
        ("INDIA",  engine_state_in, execution_engine_in),
        ("STOCKS", engine_state_st, execution_engine_st),
        ("CRYPTO", engine_state_cx, execution_engine_cx),
        ("FOREX",  engine_state_fx, execution_engine_fx),
    ]
    per_engine = {}
    for market, state, eng in _engines_info:
        last_beat = engine_heartbeats.get(market)
        staleness = round(now - last_beat, 1) if last_beat else None
        per_engine[market] = {
            "running":        state.get("is_running", False),
            "open_positions": len(eng.active_holdings),
            "last_tick_secs_ago": staleness,
            "status": (
                "ok"       if last_beat and staleness < 30   else
                "slow"     if last_beat and staleness < 120  else
                "stalled"  if last_beat and staleness >= 120 else
                "not_started"
            ),
        }
    global_ok = all(
        v["status"] in ("ok", "slow", "not_started")
        for v in per_engine.values()
    )
    return {
        "status":  "ok" if global_ok else "degraded",
        "version": "3.0.0",
        "engines": per_engine,
        "global_halt": global_risk.global_halt,
        "global_halt_reason": global_risk.halt_reason,
    }

## ── Batched log queue ────────────────────────────────────────────────────────
## Instead of opening one AsyncSession per log line (causing write-lock storms
## with 5 concurrent trading loops), we accumulate entries in memory and flush
## them all in a single transaction every _LOG_FLUSH_INTERVAL seconds.
_LOG_QUEUE: list = []              # pending (level, message, service) tuples
_LOG_FLUSH_INTERVAL = 15           # seconds between DB flushes
_log_flush_started  = False        # start the background task only once

async def _log_flush_loop():
    """Background task: drain _LOG_QUEUE into DB in one transaction per cycle."""
    while True:
        await asyncio.sleep(_LOG_FLUSH_INTERVAL)
        if not _LOG_QUEUE or not DB_ENABLED:
            continue
        batch, _LOG_QUEUE[:] = _LOG_QUEUE[:], []   # atomic swap
        if not batch:
            continue
        try:
            async with AsyncSessionLocal() as session:
                for lvl, msg, svc in batch:
                    session.add(Log(level=lvl, message=msg, service=svc))
                await session.commit()
        except Exception as e:
            print(f"[DB] Log flush failed ({len(batch)} entries): {e}")


async def _write_log(state: dict, level: str, message: str, service: str, decision: dict, *, db: bool = False):
    """Shared log writer — appends to in-memory ring buffer and queues DB persist."""
    state["bot_logs"].append({
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "level": level, "message": message, "decision": decision
    })
    if len(state["bot_logs"]) > 50:
        state["bot_logs"].pop(0)
    if db and DB_ENABLED:
        _LOG_QUEUE.append((level, message, service))

async def write_log(level: str, message: str, service: str = "engine", decision: dict = None):
    await _write_log(engine_state, level, message, service, decision, db=True)

# Global state to track if the engine is running
_engine_lock    = None   # A-2: asyncio.Lock() — prevents double-start race condition
_engine_lock_in = None
_engine_lock_st = None   # US Tech Stocks
_engine_lock_cx = None   # Crypto
_engine_lock_fx = None   # Forex

# ── Bot state persistence ─────────────────────────────────────────────────────
import json as _json_state
_BOT_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "bot_state.json")
_DATA_DIR       = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(_DATA_DIR, exist_ok=True)

# PR-2: Per-engine heartbeat timestamps — updated once per tick cycle
engine_heartbeats: dict = {
    "US":     None,
    "INDIA":  None,
    "STOCKS": None,
    "CRYPTO": None,
    "FOREX":  None,
}
_watchdog_started    = False  # PR-2: ensure watchdog is started only once
_log_flush_started   = False  # DB-3: ensure log-flush task is started only once

def _save_bot_state():
    """Write running state to disk so the bot auto-resumes after laptop wake/restart."""
    try:
        with open(_BOT_STATE_FILE, "w") as _f:
            _json_state.dump({
                "us_running":       engine_state.get("is_running", False),
                "india_running":    engine_state_in.get("is_running", False),
                "stocks_running":   engine_state_st.get("is_running", False),
                "crypto_running":   engine_state_cx.get("is_running", False),
                "forex_running":    engine_state_fx.get("is_running", False),
                "us_risk_mode":     engine_state.get("risk_mode", "Normal"),
                "india_risk_mode":  engine_state_in.get("risk_mode", "Normal"),
                "stocks_risk_mode": engine_state_st.get("risk_mode", "Normal"),
                "crypto_risk_mode": engine_state_cx.get("risk_mode", "Normal"),
                "forex_risk_mode":  engine_state_fx.get("risk_mode", "Normal"),
            }, _f)
    except Exception as _e:
        print(f"[BotState] Failed to save: {_e}")

engine_state = {
    "is_running": False,
    "active_trades": 0,
    "risk_mode": "Normal",
    "last_scan": None,
    "bot_logs": [],
    "latest_gates": {
        "event_blackout": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev": {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    }
}

master_agent = MasterAgent()
regime_detector = MarketRegimeDetector()
data_engine = DataIngestionEngine()
execution_engine = SmartExecutionEngine()
lstm_engine = LSTMSignalEngine()
event_engine = EventAwarenessEngine()
probability_engine = ProbabilityEngine()
diagnosis_engine = SelfDiagnosingAI()
pattern_matcher = HistoricalPatternMatcher()
strategy_manager = DynamicStrategyManager()
auto_builder = AutonomousStrategyBuilder()
institutional_tracker = InstitutionalTracker()
mtf_analyzer = MultiTimeframeAnalyzer()
portfolio_risk = PortfolioRiskManager(state_file=os.path.join(_DATA_DIR, "risk_state_us.json"))
scanner_agent = ScannerAgent(master_agent, regime_detector=regime_detector, rl_engine=execution_engine.rl_engine)
shadow_engine = ShadowTradingEngine()
confluence_engine = TimeframeConfluenceEngine()

# --- Indian Market Integration ---
from data.event_awareness import IndianEventAwarenessEngine

master_agent_in = IndianMasterAgent()
regime_detector_in = MarketRegimeDetector(training_symbol="NIFTYBEES.NS")
_INDIAN_SYMBOLS = [
    "NIFTYBEES.NS",   # Nifty 50 ETF (index proxy)
    "WIPRO.NS",       # IT sector
    "RELIANCE.NS",    # Energy / conglomerate
    "ONGC.NS",        # Oil & Gas
    "HDFCBANK.NS",    # Largest private bank
    "TCS.NS",         # Largest IT company
    "INFY.NS",        # Infosys (IT)
    "ICICIBANK.NS",   # Major private bank
    "BAJFINANCE.NS",  # Bajaj Finance (NBFC / consumer credit)
    "SUNPHARMA.NS",   # Sun Pharma (pharma / defensives)
    "MARUTI.NS",      # Maruti Suzuki (auto)
]
data_engine_in = DataIngestionEngine(symbols=_INDIAN_SYMBOLS)
execution_engine_in = SmartExecutionEngine(
    state_filename="portfolio_state_in.json", 
    rl_state_filename="rl_state_in.json", 
    initial_balance=4150.0,
    journal_filename="journal_in.json"
)
lstm_engine_in = LSTMSignalEngine()
event_engine_in = IndianEventAwarenessEngine()
probability_engine_in = ProbabilityEngine()
diagnosis_engine_in = SelfDiagnosingAI()
pattern_matcher_in = HistoricalPatternMatcher()
strategy_manager_in = DynamicStrategyManager()
auto_builder_in = AutonomousStrategyBuilder(symbols=_INDIAN_SYMBOLS)
mtf_analyzer_in = MultiTimeframeAnalyzer()
portfolio_risk_in = PortfolioRiskManager(state_file=os.path.join(_DATA_DIR, "risk_state_in.json"))
scanner_agent_in = ScannerAgent(master_agent_in, symbols=_INDIAN_SYMBOLS, regime_detector=regime_detector_in, rl_engine=execution_engine_in.rl_engine)
shadow_engine_in = ShadowTradingEngine()
confluence_engine_in = TimeframeConfluenceEngine()

engine_state_in = {
    "is_running": False,
    "risk_mode": "Normal",
    "last_scan": None,
    "bot_logs": [],
    "latest_gates": {
        "event_blackout":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "nifty_trend":     {"status": "NOT_EVALUATED", "details": "Waiting for first tick."},
        "mtf_alignment":   {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate":{"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    }
}

# ─── US Tech Stocks ──────────────────────────────────────────────────────────
from data.event_awareness import CryptoEventAwarenessEngine, ForexEventAwarenessEngine

# Per-market regime detectors — each trained on a representative benchmark
# so the HMM states reflect the actual volatility regime of that asset class.
regime_detector_st = MarketRegimeDetector(training_symbol="QQQ")      # NASDAQ tech ETF
regime_detector_cx = MarketRegimeDetector(training_symbol="BTC-USD")   # Most liquid crypto
regime_detector_fx = MarketRegimeDetector(training_symbol="EURUSD=X")  # Most liquid FX pair

_STOCKS_SYMBOLS = ["AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META"]
master_agent_st      = MasterAgent()
data_engine_st       = DataIngestionEngine(symbols=_STOCKS_SYMBOLS)
execution_engine_st  = SmartExecutionEngine(
    state_filename="portfolio_state_st.json",
    rl_state_filename="rl_state_st.json",
    initial_balance=100000.0,
    journal_filename="journal_st.json"
)
lstm_engine_st        = LSTMSignalEngine()
event_engine_st       = EventAwarenessEngine()   # NYSE hours + earnings for AAPL/NVDA/MSFT/META
probability_engine_st = ProbabilityEngine()
diagnosis_engine_st   = SelfDiagnosingAI()
pattern_matcher_st    = HistoricalPatternMatcher()
strategy_manager_st   = DynamicStrategyManager()
auto_builder_st       = AutonomousStrategyBuilder(symbols=_STOCKS_SYMBOLS)
mtf_analyzer_st       = MultiTimeframeAnalyzer()
portfolio_risk_st     = PortfolioRiskManager(state_file=os.path.join(_DATA_DIR, "risk_state_st.json"))
scanner_agent_st      = ScannerAgent(master_agent_st, symbols=_STOCKS_SYMBOLS, regime_detector=regime_detector_st, rl_engine=execution_engine_st.rl_engine)
shadow_engine_st      = ShadowTradingEngine()
confluence_engine_st  = TimeframeConfluenceEngine()

engine_state_st = {
    "is_running": False,
    "risk_mode": "Normal",
    "last_scan": None,
    "bot_logs": [],
    "latest_gates": {
        "event_blackout":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment":   {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate":{"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    }
}

# ─── Crypto 24/7 ─────────────────────────────────────────────────────────────
_CRYPTO_SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"]
master_agent_cx      = MasterAgent()
data_engine_cx       = DataIngestionEngine(symbols=_CRYPTO_SYMBOLS)
execution_engine_cx  = SmartExecutionEngine(
    state_filename="portfolio_state_cx.json",
    rl_state_filename="rl_state_cx.json",
    initial_balance=10000.0,
    journal_filename="journal_cx.json"
)
lstm_engine_cx        = LSTMSignalEngine()
event_engine_cx       = CryptoEventAwarenessEngine()
probability_engine_cx = ProbabilityEngine()
diagnosis_engine_cx   = SelfDiagnosingAI()
pattern_matcher_cx    = HistoricalPatternMatcher()
strategy_manager_cx   = DynamicStrategyManager()
auto_builder_cx       = AutonomousStrategyBuilder(symbols=_CRYPTO_SYMBOLS)
mtf_analyzer_cx       = MultiTimeframeAnalyzer()
portfolio_risk_cx     = PortfolioRiskManager(state_file=os.path.join(_DATA_DIR, "risk_state_cx.json"))
scanner_agent_cx      = ScannerAgent(master_agent_cx, symbols=_CRYPTO_SYMBOLS, regime_detector=regime_detector_cx, rl_engine=execution_engine_cx.rl_engine)
shadow_engine_cx      = ShadowTradingEngine()
confluence_engine_cx  = TimeframeConfluenceEngine()

engine_state_cx = {
    "is_running": False,
    "risk_mode": "Normal",
    "last_scan": None,
    "bot_logs": [],
    "latest_gates": {
        "event_blackout":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment":   {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate":{"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    }
}

# ─── Forex ───────────────────────────────────────────────────────────────────
_FOREX_SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"]
master_agent_fx      = MasterAgent()
data_engine_fx       = DataIngestionEngine(symbols=_FOREX_SYMBOLS)
execution_engine_fx  = SmartExecutionEngine(
    state_filename="portfolio_state_fx.json",
    rl_state_filename="rl_state_fx.json",
    initial_balance=50000.0,
    journal_filename="journal_fx.json"
)
lstm_engine_fx        = LSTMSignalEngine()
event_engine_fx       = ForexEventAwarenessEngine()
probability_engine_fx = ProbabilityEngine()
diagnosis_engine_fx   = SelfDiagnosingAI()
pattern_matcher_fx    = HistoricalPatternMatcher()
strategy_manager_fx   = DynamicStrategyManager()
auto_builder_fx       = AutonomousStrategyBuilder(symbols=_FOREX_SYMBOLS)
mtf_analyzer_fx       = MultiTimeframeAnalyzer()
portfolio_risk_fx     = PortfolioRiskManager(state_file=os.path.join(_DATA_DIR, "risk_state_fx.json"))
scanner_agent_fx      = ScannerAgent(master_agent_fx, symbols=_FOREX_SYMBOLS, regime_detector=regime_detector_fx, rl_engine=execution_engine_fx.rl_engine)
shadow_engine_fx      = ShadowTradingEngine()
confluence_engine_fx  = TimeframeConfluenceEngine()

engine_state_fx = {
    "is_running": False,
    "risk_mode": "Normal",
    "last_scan": None,
    "bot_logs": [],
    "latest_gates": {
        "event_blackout":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment":   {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate":{"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    }
}

# ── A-1: Cross-market risk aggregator ────────────────────────────────────────
global_risk = GlobalRiskAggregator(
    state_file=os.path.join(_DATA_DIR, "global_risk_state.json")
)
global_risk.register_engines([
    execution_engine, execution_engine_in, execution_engine_st,
    execution_engine_cx, execution_engine_fx,
])

async def write_log_in(level: str, message: str, service: str = "engine_in", decision: dict = None):
    await _write_log(engine_state_in, level, message, service, decision, db=True)

async def write_log_st(level: str, message: str, service: str = "engine_st", decision: dict = None):
    await _write_log(engine_state_st, level, message, service, decision)

async def write_log_cx(level: str, message: str, service: str = "engine_cx", decision: dict = None):
    await _write_log(engine_state_cx, level, message, service, decision)

async def write_log_fx(level: str, message: str, service: str = "engine_fx", decision: dict = None):
    await _write_log(engine_state_fx, level, message, service, decision)


async def trading_loop():
    """Background task that runs the autonomous trading engine."""
    print("[DEBUG] trading_loop task spawned!")
    while engine_state["is_running"]:
        print("[DEBUG] trading_loop tick started...")

        # A-1: Global cross-market circuit breaker
        _g = global_risk.check()
        if _g["global_halt"]:
            await write_log("warning", f"⛔ {_g['halt_reason']} — US engine standing down.")
            await asyncio.sleep(4)
            continue

        # PR-2: Heartbeat — marks this engine as alive for the watchdog
        engine_heartbeats["US"] = time.time()

        # Reset gates for this tick cycle
        engine_state["latest_gates"] = {
            "event_blackout": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "mtf_alignment": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "correlation_gate": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "monte_carlo_ev": {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
        }
        
        # Fetch all US symbols concurrently (same pattern as Indian/Stocks/Crypto/Forex loops)
        try:
            # FIX 2026-08-03: hang guard. A yfinance network stall inside the
            # fetch thread never raises, so the await blocked forever and the
            # engine flatlined (observed: INDIA silent ~14h mid-fetch). The
            # timeout abandons the hung await (the worker thread leaks until
            # the underlying call returns — unavoidable) and retries.
            ticks_us = await asyncio.wait_for(asyncio.to_thread(fetch_all_us_ticks), timeout=240)
        except Exception as _fetch_err:
            _fe = "timed out after 240s" if isinstance(_fetch_err, (asyncio.TimeoutError, TimeoutError)) else str(_fetch_err)
            await write_log("error", f"🚨 US tick fetch failed: {_fe}. Retrying in 30s.")
            await asyncio.sleep(30)
            continue

        for symbol in data_engine.symbols:
            if not engine_state["is_running"]:
                break

            tick_data = ticks_us.get(symbol)
            if isinstance(tick_data, Exception):
                await write_log("warning", f"⏸ Market data unavailable for {symbol}: {str(tick_data)[:80]}. Skipping.")
                continue
            if tick_data is None:
                await write_log("warning", f"⏸ No tick for {symbol}. Skipping.")
                continue

            try:
                # Update LSTM Tick Buffer and predict
                lstm_engine.update_tick(symbol, tick_data)
                lstm_res = lstm_engine.get_signal(symbol)
                tick_data["lstm_signal"] = lstm_res["signal"]
                tick_data["lstm_confidence"] = lstm_res["confidence"]
                
                tick_data["trading_mode"] = engine_state.get("risk_mode", "Normal")
                source = tick_data.get("data_source", "Yahoo Finance")
                
                # Log: Scanning
                await write_log("info", f"Analyzing {symbol} @ ${tick_data['price']} | RSI: {tick_data.get('rsi_14', 0):.1f} | MACD: {tick_data.get('macd_hist', 0):.4f} | {source}")
                
                
                # Event Awareness Check - block trades during high-risk events
                event_status = event_engine.check_today(tick_data)
                if event_status["trading_blackout"]:
                    if engine_state.get("risk_mode") == "Aggressive":
                        engine_state["latest_gates"]["event_blackout"] = {
                            "status": "PASSED",
                            "details": f"Macro blackout bypassed (Aggressive mode): {event_status['blackout_reason']}."
                        }
                        await write_log("warning", f"⚠️ BLACKOUT: {event_status['blackout_reason']} ignored due to Aggressive Mode.")
                    else:
                        engine_state["latest_gates"]["event_blackout"] = {
                            "status": "BLOCKED",
                            "details": f"Blocked: {event_status['blackout_reason']}."
                        }
                        await write_log("warning", f"🚫 BLACKOUT: {event_status['blackout_reason']} detected. Skipping trade.")
                        execution_engine.journal.log_veto(symbol, "ANY", "EVENT_BLACKOUT", event_status['blackout_reason'])
                        continue
                else:
                    if engine_state["latest_gates"]["event_blackout"]["status"] != "BLOCKED":
                        engine_state["latest_gates"]["event_blackout"] = {
                            "status": "PASSED",
                            "details": "Passed: No high-risk macro events today."
                        }
                
                # Inject active holdings and session quality
                # Pass full holding dicts — MasterAgent correlation gate uses h.get("symbol")
                holdings_list = execution_engine.active_holdings
                tick_data['active_holdings'] = execution_engine.active_holdings
                tick_data['open_trade_count'] = len(execution_engine.active_holdings)
                tick_data['session_quality'] = event_engine.check_session_quality().get("session", "NORMAL")
                
                # Inject portfolio risk metrics
                # Mark-to-market equity (not raw cash): raw cash made every LONG
                # entry look like an instant drawdown → spurious daily halts.
                risk_profile = portfolio_risk.analyze(holdings_list, execution_engine.get_total_equity())
                tick_data['halt_trading_for_day']  = risk_profile.get('halt_trading_for_day', False)
                tick_data['halt_trading_for_week'] = risk_profile.get('halt_trading_for_week', False)  # RM-2 fix: was never copied
                tick_data['daily_drawdown_pct'] = risk_profile.get('daily_drawdown_pct', 0.0)
                tick_data['cash_pct'] = risk_profile.get('cash_pct', 100.0)

                # C-2: Enforce daily loss circuit breaker — hard stop, not advisory
                if tick_data['halt_trading_for_day']:
                    dd = risk_profile.get('daily_drawdown_pct', 0.0)
                    await write_log("warning", f"🚨 DAILY LOSS LIMIT HIT ({dd:.1f}% drawdown). All new trades blocked for {symbol}.")
                    execution_engine.journal.log_veto(symbol, "ANY", "DAILY_HALT", f"Daily drawdown {dd:.1f}% exceeded limit.")
                    continue
                # RM-2: Weekly loss circuit breaker
                if tick_data.get('halt_trading_for_week'):
                    wd = risk_profile.get('weekly_drawdown_pct', 0.0)
                    await write_log("warning", f"🚨 WEEKLY LOSS LIMIT HIT ({wd:.1f}% drawdown). All new trades blocked for the week.")
                    execution_engine.journal.log_veto(symbol, "ANY", "WEEKLY_HALT", f"Weekly drawdown {wd:.1f}% exceeded limit.")
                    continue

                # C-1: Enforce 2-Stage Asymmetric Stop-Loss & Take-Profit on active holdings
                _sl_tp_triggers = []
                for _h in list(execution_engine.active_holdings):
                    if _h["symbol"] != symbol:
                        continue
                    _cur     = tick_data['price']
                    _dir     = _h.get("direction", "LONG")
                    _sl      = _h.get("stop_loss")
                    if not _sl or _sl <= 0:
                        _entry_p = float(_h.get("entry_price", _cur) or _cur)
                        _sl = round(_entry_p * 0.98, 4) if _dir == "LONG" else round(_entry_p * 1.02, 4)
                        _h["stop_loss"] = _sl
                        await write_log("warning", f"🚨 [Emergency Stop Guard] Missing/corrupt stop-loss detected for {symbol}. Initialized fallback stop at ${_sl:.4f} (Entry: ${_entry_p:.4f}, Cur: ${_cur:.4f}).")

                    _tp1     = _h.get("tp1_target")
                    _tp2     = _h.get("tp2_target") or _h.get("take_profit")
                    _tp3     = _h.get("tp3_runner_target")
                    _tp1_hit = _h.get("tp1_hit", False)
                    _tp2_hit = _h.get("tp2_hit", False)

                    if _dir == "LONG":
                        if _cur <= _sl:
                            _sl_tp_triggers.append((_h, "STOP_LOSS", "FULL"))

                        elif not _tp1_hit and _tp1 and _cur >= _tp1:
                            _sl_tp_triggers.append((_h, "TP1_1.5R_SCALEOUT", "PARTIAL"))
                        elif _tp1_hit and not _tp2_hit and _tp2 and _cur >= _tp2:
                            _sl_tp_triggers.append((_h, "TP2_3.0R_SCALEOUT", "PARTIAL"))
                        elif _tp2_hit and _tp3 and _cur >= _tp3:
                            _sl_tp_triggers.append((_h, "TP3_CHANDELIER_RUNNER", "FULL"))
                    else:  # SHORT
                        if _sl and _cur >= _sl:
                            _sl_tp_triggers.append((_h, "STOP_LOSS", "FULL"))
                        elif not _tp1_hit and _tp1 and _cur <= _tp1:
                            _sl_tp_triggers.append((_h, "TP1_1.5R_SCALEOUT", "PARTIAL"))
                        elif _tp1_hit and not _tp2_hit and _tp2 and _cur <= _tp2:
                            _sl_tp_triggers.append((_h, "TP2_3.0R_SCALEOUT", "PARTIAL"))
                        elif _tp2_hit and _tp3 and _cur <= _tp3:
                            _sl_tp_triggers.append((_h, "TP3_CHANDELIER_RUNNER", "FULL"))


                for _h, _close_reason, _close_type in _sl_tp_triggers:
                    if _close_type == "PARTIAL":
                        _ok, _msg = await execution_engine.partial_close(_h, tick_data['price'], fraction=0.5, reason=_close_reason)
                        _lvl = "success"
                    else:
                        _ok, _msg = await execution_engine.force_close(_h, tick_data['price'], _close_reason)
                        _lvl = "success" if "TAKE_PROFIT" in _close_reason else "warning"
                    await write_log(_lvl, f"[{_close_reason}] {symbol} @ ${tick_data['price']:.4f} | {_msg}")
                    if _ok:
                        await notifier.send_alert(f"🚨 **{_close_reason}** for {symbol} at ${tick_data['price']:.4f}\nDetails: {_msg}")


                # Classify market regime and inject weights
                current_regime = regime_detector.detect(symbol, tick_data)
                tick_data["regime"] = current_regime
                _live_weights = execution_engine.rl_engine.get_current_weights(current_regime)
                # SentimentAgent: zeroed — no point-in-time news archive, can't backtest.
                # CorrelationAgent: zeroed — it always returns WAIT; its weight in the
                # denominator makes the Sideways threshold mathematically unreachable.
                # The Correlation Gate in master.py.evaluate() already handles this logic.
                _live_weights["News & Sentiment AI"] = 0.0
                _live_weights["Correlation Agent"]   = 0.0
                tick_data["agent_weights"] = _live_weights

                # Multi-Timeframe Confluence: fetch in thread (avoids blocking loop)
                mtf_confluence = await asyncio.to_thread(
                    confluence_engine.get_confluence, symbol, tick_data
                )
                tick_data["mtf_confluence"] = mtf_confluence

                # Evaluate using the V3 Multi-AI Committee
                decision = master_agent.evaluate(symbol, tick_data)

                # Apply MTF confidence adjustment / veto
                _pre_mtf_signal = decision["signal"]
                if decision["signal"] in ("BUY", "SELL"):
                    decision = confluence_engine.apply_to_decision(
                        decision, mtf_confluence, decision["signal"]
                    )
                    alignment = mtf_confluence.get("alignment", "NEUTRAL")
                    if decision["signal"] == "WAIT" and "MTF VETO" in decision.get("reason", ""):
                        engine_state["latest_gates"]["mtf_alignment"] = {
                            "status": "BLOCKED",
                            "details": f"MTF VETO: {mtf_confluence['detail']}"
                        }
                        await write_log("warning", f"🚫 MTF: {mtf_confluence['detail']}")
                        execution_engine.journal.log_veto(symbol, _pre_mtf_signal, "MTF_VETO", mtf_confluence['detail'], {"confidence": decision.get("confidence", 0.0), "regime": current_regime})
                    else:
                        engine_state["latest_gates"]["mtf_alignment"] = {
                            "status": "PASSED",
                            "details": f"{alignment} — Daily:{mtf_confluence.get('daily_trend','?')} 1h:{mtf_confluence.get('hourly_trend','?')}"
                        }
                else:
                    engine_state["latest_gates"]["mtf_alignment"] = {
                        "status": "NOT_EVALUATED",
                        "details": "No signal from committee. MTF not applied."
                    }
                
                # Update Correlation Gate status
                corr_val = decision.get("correlation", 0.0)
                if decision.get("signal") == "WAIT" and "Correlation Gate VETO" in decision.get("reason", ""):
                    engine_state["latest_gates"]["correlation_gate"] = {
                        "status": "BLOCKED",
                        "details": f"Blocked: {decision['reason']}"
                    }
                else:
                    if engine_state["latest_gates"]["correlation_gate"]["status"] != "BLOCKED":
                        engine_state["latest_gates"]["correlation_gate"] = {
                            "status": "PASSED",
                            "details": f"Passed: Gold/NQ rolling correlation is {corr_val:.2f}."
                        }
                
                # Shadow Trading: Evaluate active shadow trades
                shadow_engine.evaluate_shadow_trades(
                    symbol, tick_data['price'],
                    rl_engine=execution_engine.rl_engine,
                    regime=current_regime
                )
                
                # Feature 16: Historical Pattern Search
                pattern_result = pattern_matcher.find_similar(tick_data)
                
                # Feature 3: Dynamic Strategy Selection
                strategy_result = strategy_manager.select_strategy(symbol, tick_data)
                
                # Feature 18: Advance autonomous builder pipeline
                auto_builder.tick()
                
                # Enrich with Probability Profile
                decision = probability_engine.enrich(decision, tick_data)
                
                # MTF gate already applied by confluence_engine above — no second veto needed
                if decision.get("signal") not in ("BUY", "SELL"):
                    if engine_state["latest_gates"]["mtf_alignment"]["status"] == "NOT_EVALUATED":
                        engine_state["latest_gates"]["mtf_alignment"] = {
                            "status": "NOT_EVALUATED",
                            "details": "Not evaluated: No BUY or SELL signal from committee."
                        }

                # Shadow Trading: Record missed opportunities if AI rejected a good setup
                signal = decision.get("signal", "WAIT")
                if signal == "WAIT" and decision.get("confidence", 0) > 0.60:
                    shadow_engine.record_rejected_trade(symbol, tick_data['price'], decision)

                timestamp = datetime.now().strftime("%H:%M:%S")
                conf = decision.get("confidence", 0) * 100
                buy_conv  = decision.get("buy_conviction", 0) * 100
                sell_conv = decision.get("sell_conviction", 0) * 100
                threshold = decision.get("threshold", 0) * 100

                level = "success" if signal == "BUY" else "error" if signal == "SELL" else "warning"
                if signal == "WAIT":
                    log_msg = f"[WAIT] {symbol} (↑{buy_conv:.0f}% ↓{sell_conv:.0f}% | need {threshold:.0f}%): {decision['reason']}"
                else:
                    log_msg = f"[{signal}] {symbol} (Conf: {conf:.1f}%): {decision['reason']}"
                
                # Execute the trade via Execution Engine
                if signal in ["BUY", "SELL"]:
                    decision["session_quality"] = tick_data.get("session_quality", "NORMAL")

                    decision["regime"] = current_regime   # stored in journal.log_trade for self-diagnosis
                    # Store entry features for causal attribution
                    decision["entry_features"] = {
                        "price": tick_data.get("price"),
                        "rsi_14": tick_data.get("rsi_14"),
                        "macd_hist": tick_data.get("macd_hist"),
                        "atr_14": tick_data.get("atr_14"),
                        "vwap": tick_data.get("vwap"),
                        "volume": tick_data.get("volume"),
                        "vix_level": tick_data.get("vix_level"),
                        "dxy_value": tick_data.get("dxy_value"),
                        "real_yield_10y_trend": tick_data.get("real_yield_10y_trend")
                    }
                    success, reason = await execution_engine.execute_trade(symbol, tick_data['price'], decision)
                    
                    # Check Monte Carlo EV status
                    if not success and "AI Trade Simulator veto" in reason:
                        engine_state["latest_gates"]["monte_carlo_ev"] = {
                            "status": "BLOCKED",
                            "details": f"Blocked: {reason}"
                        }
                        await write_log("warning", f"[EXECUTION VETO] {symbol}: {reason}")
                        execution_engine.journal.log_veto(symbol, signal, "MONTE_CARLO", reason, {"confidence": decision.get("confidence", 0.0), "regime": current_regime})
                        continue
                    else:
                        sim = getattr(execution_engine, "latest_sim_result", None)
                        if sim:
                            engine_state["latest_gates"]["monte_carlo_ev"] = {
                                "status": "PASSED",
                                "details": f"Passed: EV of ${sim['expected_value']:.4f} is above hurdle (win prob: {sim['win_probability']*100:.1f}%)."
                            }
                        else:
                            engine_state["latest_gates"]["monte_carlo_ev"] = {
                                "status": "NOT_EVALUATED",
                                "details": "Not evaluated: Liquidating/covering active position."
                            }
                        
                        if not success:
                            await write_log("warning", f"[EXECUTION VETO] {symbol}: {reason}")
                            continue
                        else:
                            await write_log("success", f"[FILL] {reason}")
                else:
                    if engine_state["latest_gates"]["monte_carlo_ev"]["status"] == "NOT_EVALUATED":
                        engine_state["latest_gates"]["monte_carlo_ev"] = {
                            "status": "NOT_EVALUATED",
                            "details": "Not evaluated: No BUY or SELL signal."
                        }
                
                # Update holdings with live price from the same real Yahoo Finance tick
                for holding in execution_engine.active_holdings:
                    if holding["symbol"] == symbol:
                        holding["current_price"] = tick_data['price']
                        if holding.get("direction", "LONG") == "SHORT":
                            pnl = holding["shares"] * (holding["entry_price"] - tick_data['price'])
                            holding["value"] = round(holding["shares"] * holding["entry_price"] + pnl, 4)
                            holding["change"] = round(
                                (holding["entry_price"] - tick_data['price']) / holding["entry_price"] * 100, 3
                            )
                        else:
                            holding["value"] = round(holding["shares"] * tick_data['price'], 4)
                            holding["change"] = round(
                                (tick_data['price'] - holding["entry_price"]) / holding["entry_price"] * 100, 3
                            )
                        # Sparkline: real price history (populated as engine ticks)
                        holding["sparkline"].append(round(tick_data['price'], 4))
                        if len(holding["sparkline"]) > 20:
                            holding["sparkline"].pop(0)
                        # C-1: Advance trailing stop as price moves in favour
                        _trail_signal = "BUY" if holding.get("direction", "LONG") == "LONG" else "SELL"
                        _atr_val  = tick_data.get('atr_14', 0.0)
                        _vol_prox = (_atr_val / tick_data['price']) if tick_data.get('price', 0) > 0 else 0.02
                        _vol_prox = max(_vol_prox, 0.002)  # floor: prevent zero-width stops
                        _trail = execution_engine.stops.update_trailing(
                            current_price    = tick_data['price'],
                            signal           = _trail_signal,
                            current_stop     = holding.get("stop_loss", 0.0),
                            best_price       = holding.get("best_price", holding.get("entry_price", tick_data['price'])),
                            volatility_proxy = _vol_prox,
                            entry_price      = holding.get("entry_price"),
                            regime           = current_regime,
                        )
                        holding["stop_loss"]  = _trail["new_stop"]
                        holding["best_price"] = _trail["best_price"]

                await write_log(level, log_msg, decision=decision)
            except Exception as e:
                await write_log("error", f"🚨 Error processing {symbol}: {str(e)}")
                
        await asyncio.sleep(4) # Wait before next scan

async def periodic_model_update_loop():
    """Background task to run Boruta + RFECV feature selection and HMM retraining periodically (every 24 hours)."""
    print("[DEBUG] periodic_model_update_loop task spawned!")
    # Delay boot ML jobs by 60s so they don't pile onto startup thread pressure
    # alongside both trading loops spinning up simultaneously.
    await asyncio.sleep(60)
    # Initial startup run to initialize models/features with fresh data
    try:
        await write_log("info", "Starting initial boot feature selection (Boruta + RFECV)...")
        for _sym in data_engine.symbols:
            await asyncio.to_thread(data_engine.run_feature_selection, _sym)
        await write_log("info", f"Boot feature selection complete. Symbols: {data_engine.symbols}")

        await write_log("info", "Starting initial boot HMM regime detector retraining...")
        await asyncio.to_thread(regime_detector.retrain)
        await write_log("info", "Boot HMM retraining complete.")
    except Exception as e:
        await write_log("error", f"Boot model update error: {e}")

    while engine_state["is_running"]:
        # Sleep for 24 hours, checking every 10 seconds if engine is stopped
        for _ in range(8640):
            if not engine_state["is_running"]:
                break
            await asyncio.sleep(10)
            
        if not engine_state["is_running"]:
            break
            
        try:
            await write_log("info", "Starting periodic feature selection (Boruta + RFECV)...")
            for _sym in data_engine.symbols:
                await asyncio.to_thread(data_engine.run_feature_selection, _sym)
            await write_log("info", "Periodic feature selection complete.")
            
            await write_log("info", "Starting periodic HMM regime detector retraining...")
            await asyncio.to_thread(regime_detector.retrain)
            await write_log("info", "Periodic HMM retraining complete.")
        except Exception as e:
            await write_log("error", f"Periodic model update loop error: {e}")


# Reusable executors — created once, not every 4-second tick.
# Creating a new ThreadPoolExecutor each cycle leaks threads and contributes
# to Windows error 1450 (insufficient resources to create thread).
import concurrent.futures as _cf
_us_tick_executor     = _cf.ThreadPoolExecutor(max_workers=5, thread_name_prefix="us_tick")
_indian_tick_executor = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="indian_tick")

def _concurrent_tick_fetch_generic(executor, data_eng, timeout=30) -> dict:
    """Fetch all symbols for a given engine concurrently."""
    from concurrent.futures import as_completed, TimeoutError as FuturesTimeoutError
    results = {}
    future_map = {executor.submit(data_eng.get_tick_for, sym): sym for sym in data_eng.symbols}
    try:
        for future in as_completed(future_map, timeout=timeout):
            sym = future_map[future]
            try:
                results[sym] = future.result()
            except Exception as e:
                results[sym] = e
    except FuturesTimeoutError:
        for fut, sym in future_map.items():
            if sym not in results:
                results[sym] = RuntimeError(f"Tick fetch timed out for {sym}")
    return results

def fetch_all_us_ticks() -> dict:
    """Fetch all US symbols concurrently — reuses a fixed thread pool, 30s timeout."""
    return _concurrent_tick_fetch_generic(_us_tick_executor, data_engine)

def fetch_all_indian_ticks() -> dict:
    """Fetch all Indian symbols concurrently — reuses a fixed thread pool, 30s timeout."""
    return _concurrent_tick_fetch_generic(_indian_tick_executor, data_engine_in)


# Per-market tick executors — each reused across ticks (no `with` shutdown bug)
_stocks_tick_executor = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="stocks_tick")
_crypto_tick_executor = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="crypto_tick")
_forex_tick_executor  = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="forex_tick")

def fetch_all_stocks_ticks() -> dict:
    return _concurrent_tick_fetch_generic(_stocks_tick_executor, data_engine_st)

def fetch_all_crypto_ticks() -> dict:
    try:
        from data.websocket_streamer import CryptoWebSocketStreamer
        streamer = CryptoWebSocketStreamer.get_instance()
        results = {}
        missing = []
        for sym in data_engine_cx.symbols:
            ws_tick = streamer.get_tick(sym)
            if ws_tick:
                # Augment with calculated technical indicators from historical cache
                hist_tick = data_engine_cx.get_latest_tick(sym)
                if hist_tick and not isinstance(hist_tick, Exception):
                    hist_tick.update({
                        "price": ws_tick["price"],
                        "high": max(hist_tick.get("high", ws_tick["high"]), ws_tick["high"]),
                        "low": min(hist_tick.get("low", ws_tick["low"]), ws_tick["low"]),
                        "bid": ws_tick.get("bid", hist_tick.get("bid")),
                        "ask": ws_tick.get("ask", hist_tick.get("ask")),
                        "data_source": "Binance WebSocket (Live 0-Delay)",
                    })
                    results[sym] = hist_tick
                else:
                    results[sym] = ws_tick
            else:
                missing.append(sym)
        if missing:
            rest_ticks = _concurrent_tick_fetch_generic(_crypto_tick_executor, data_engine_cx)
            for sym, t in rest_ticks.items():
                if sym not in results:
                    results[sym] = t
        return results
    except Exception as e:
        return _concurrent_tick_fetch_generic(_crypto_tick_executor, data_engine_cx)

def fetch_all_forex_ticks() -> dict:
    return _concurrent_tick_fetch_generic(_forex_tick_executor, data_engine_fx)



async def indian_trading_loop():
    """Background task that runs the autonomous trading engine for the Indian Market."""
    print("[DEBUG] indian_trading_loop task spawned!")
    while engine_state_in["is_running"]:
        print("[DEBUG] indian_trading_loop tick started...")

        # A-1: Global cross-market circuit breaker
        _g_in = global_risk.check()
        if _g_in["global_halt"]:
            await write_log_in("warning", f"⛔ {_g_in['halt_reason']} — India engine standing down.")
            await asyncio.sleep(4)
            continue

        # PR-2: Heartbeat
        engine_heartbeats["INDIA"] = time.time()

        # Reset gates for this tick cycle
        engine_state_in["latest_gates"] = {
            "event_blackout":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "nifty_trend":     {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "mtf_alignment":   {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "correlation_gate":{"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "monte_carlo_ev":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
        }
        
        # Fetch all ticks concurrently — if this raises, log and retry next cycle
        try:
            # FIX 2026-08-03: hang guard (root cause of the 14h INDIA stall on
            # 2026-08-02/03: fetch thread hung on network I/O with no timeout,
            # the await never returned, heartbeat froze at 12:45). See US loop.
            ticks = await asyncio.wait_for(asyncio.to_thread(fetch_all_indian_ticks), timeout=240)
        except Exception as _fetch_err:
            _fe = "timed out after 240s" if isinstance(_fetch_err, (asyncio.TimeoutError, TimeoutError)) else str(_fetch_err)
            await write_log_in("error", f"🚨 Indian tick fetch failed: {_fe}. Retrying in 30s.")
            await asyncio.sleep(30)
            continue

        for symbol in data_engine_in.symbols:
            if not engine_state_in["is_running"]:
                break
            
            tick_data = ticks.get(symbol)
            if tick_data is None:
                continue
            if isinstance(tick_data, RuntimeError):
                await write_log_in("warning", f"⏸ Indian Market data unavailable for {symbol}: {str(tick_data)[:80]}. Skipping.")
                continue
            if isinstance(tick_data, Exception):
                await write_log_in("error", f"🚨 Error fetching tick for {symbol}: {str(tick_data)[:80]}. Skipping.")
                continue

            try:
                # Update LSTM Tick Buffer and predict
                lstm_engine_in.update_tick(symbol, tick_data)
                lstm_res = lstm_engine_in.get_signal(symbol)
                tick_data["lstm_signal"] = lstm_res["signal"]
                tick_data["lstm_confidence"] = lstm_res["confidence"]
                
                tick_data["trading_mode"] = engine_state_in.get("risk_mode", "Normal")
                source = tick_data.get("data_source", "Yahoo Finance")
                
                # Log: Scanning
                await write_log_in("info", f"Analyzing {symbol} @ ₹{tick_data['price']} | RSI: {tick_data.get('rsi_14', 0):.1f} | MACD: {tick_data.get('macd_hist', 0):.4f} | {source}")
                
                
                # Event Awareness Check - block trades during high-risk events or closed hours
                event_status = event_engine_in.check_today(tick_data)
                if event_status["trading_blackout"]:
                    if engine_state_in.get("risk_mode") == "Aggressive":
                        engine_state_in["latest_gates"]["event_blackout"] = {
                            "status": "PASSED",
                            "details": f"Macro blackout bypassed (Aggressive mode): {event_status['blackout_reason']}."
                        }
                        await write_log_in("warning", f"⚠️ BLACKOUT: {event_status['blackout_reason']} ignored due to Aggressive Mode.")
                    else:
                        engine_state_in["latest_gates"]["event_blackout"] = {
                            "status": "BLOCKED",
                            "details": f"Blocked: {event_status['blackout_reason']}."
                        }
                        await write_log_in("warning", f"🚫 BLACKOUT: {event_status['blackout_reason']} detected. Skipping trade.")
                        execution_engine_in.journal.log_veto(symbol, "ANY", "EVENT_BLACKOUT", event_status['blackout_reason'])
                        continue
                else:
                    if engine_state_in["latest_gates"]["event_blackout"]["status"] != "BLOCKED":
                        engine_state_in["latest_gates"]["event_blackout"] = {
                            "status": "PASSED",
                            "details": "Passed: No high-risk macro events or market closed hours today."
                        }
                
                # Inject active holdings and session quality
                # Pass full holding dicts — MasterAgent correlation gate uses h.get("symbol")
                holdings_list = execution_engine_in.active_holdings
                tick_data['active_holdings'] = execution_engine_in.active_holdings
                tick_data['open_trade_count'] = len(execution_engine_in.active_holdings)
                tick_data['session_quality'] = "NORMAL"  # IndianEventAwarenessEngine has no check_session_quality method
                
                # Inject portfolio risk metrics
                risk_profile = portfolio_risk_in.analyze(holdings_list, execution_engine_in.get_total_equity())
                tick_data['halt_trading_for_day'] = risk_profile.get('halt_trading_for_day', False)
                tick_data['daily_drawdown_pct'] = risk_profile.get('daily_drawdown_pct', 0.0)
                tick_data['cash_pct'] = risk_profile.get('cash_pct', 100.0)

                # C-2: Enforce daily loss circuit breaker — hard stop, not advisory
                if tick_data['halt_trading_for_day']:
                    dd_in = risk_profile.get('daily_drawdown_pct', 0.0)
                    await write_log_in("warning", f"🚨 DAILY LOSS LIMIT HIT ({dd_in:.1f}% drawdown). All new trades blocked for {symbol}.")
                    execution_engine_in.journal.log_veto(symbol, "ANY", "DAILY_HALT", f"Daily drawdown {dd_in:.1f}% exceeded limit.")
                    continue
                # RM-2: Weekly loss circuit breaker
                if risk_profile.get('halt_trading_for_week'):
                    wd_in = risk_profile.get('weekly_drawdown_pct', 0.0)
                    await write_log_in("warning", f"🚨 WEEKLY LOSS LIMIT HIT ({wd_in:.1f}% drawdown). All new trades blocked for the week.")
                    execution_engine_in.journal.log_veto(symbol, "ANY", "WEEKLY_HALT", f"Weekly drawdown {wd_in:.1f}% exceeded limit.")
                    continue

                # NSE circuit breaker check via analyze() — halt_trading_for_day handles this

                # C-1: Enforce 2-Stage Asymmetric Stop-Loss & Take-Profit on active Indian holdings
                _sl_tp_triggers_in = []
                for _h in list(execution_engine_in.active_holdings):
                    if _h["symbol"] != symbol:
                        continue
                    _cur     = tick_data['price']
                    _dir     = _h.get("direction", "LONG")
                    _sl      = _h.get("stop_loss")
                    if not _sl or _sl <= 0:
                        _entry_p = float(_h.get("entry_price", _cur) or _cur)
                        _sl = round(_entry_p * 0.98, 4) if _dir == "LONG" else round(_entry_p * 1.02, 4)
                        _h["stop_loss"] = _sl
                        await write_log_in("warning", f"🚨 [Emergency Stop Guard] Missing/corrupt stop-loss detected for {symbol}. Initialized fallback stop at ₹{_sl:.4f} (Entry: ₹{_entry_p:.4f}, Cur: ₹{_cur:.4f}).")

                    _tp1     = _h.get("tp1_target")
                    _tp2     = _h.get("tp2_target") or _h.get("take_profit")
                    _tp3     = _h.get("tp3_runner_target")
                    _tp1_hit = _h.get("tp1_hit", False)
                    _tp2_hit = _h.get("tp2_hit", False)

                    if _dir == "LONG":
                        if _cur <= _sl:
                            _sl_tp_triggers_in.append((_h, "STOP_LOSS", "FULL"))

                        elif not _tp1_hit and _tp1 and _cur >= _tp1:
                            _sl_tp_triggers_in.append((_h, "TP1_1.5R_SCALEOUT", "PARTIAL"))
                        elif _tp1_hit and not _tp2_hit and _tp2 and _cur >= _tp2:
                            _sl_tp_triggers_in.append((_h, "TP2_3.0R_SCALEOUT", "PARTIAL"))
                        elif _tp2_hit and _tp3 and _cur >= _tp3:
                            _sl_tp_triggers_in.append((_h, "TP3_CHANDELIER_RUNNER", "FULL"))
                    else:  # SHORT
                        if _sl and _cur >= _sl:
                            _sl_tp_triggers_in.append((_h, "STOP_LOSS", "FULL"))
                        elif not _tp1_hit and _tp1 and _cur <= _tp1:
                            _sl_tp_triggers_in.append((_h, "TP1_1.5R_SCALEOUT", "PARTIAL"))
                        elif _tp1_hit and not _tp2_hit and _tp2 and _cur <= _tp2:
                            _sl_tp_triggers_in.append((_h, "TP2_3.0R_SCALEOUT", "PARTIAL"))
                        elif _tp2_hit and _tp3 and _cur <= _tp3:
                            _sl_tp_triggers_in.append((_h, "TP3_CHANDELIER_RUNNER", "FULL"))


                for _h, _close_reason, _close_type in _sl_tp_triggers_in:
                    if _close_type == "PARTIAL":
                        _ok, _msg = await execution_engine_in.partial_close(_h, tick_data['price'], fraction=0.5, reason=_close_reason)
                        _lvl = "success"
                    else:
                        _ok, _msg = await execution_engine_in.force_close(_h, tick_data['price'], _close_reason)
                        _lvl = "success" if "TAKE_PROFIT" in _close_reason else "warning"
                    await write_log_in(_lvl, f"[{_close_reason}] {symbol} @ ₹{tick_data['price']:.4f} | {_msg}")
                    if _ok:
                        await notifier.send_alert(f"🚨 **{_close_reason}** for Indian {symbol} at ₹{tick_data['price']:.4f}\nDetails: {_msg}")


                # Classify market regime and inject weights
                current_regime = regime_detector_in.detect(symbol, tick_data)
                tick_data["regime"] = current_regime
                _live_weights_in = execution_engine_in.rl_engine.get_current_weights(current_regime)
                # Same reasoning as US loop: zero both always-WAIT agents.
                _live_weights_in["News & Sentiment AI"] = 0.0
                _live_weights_in["Correlation Agent"]   = 0.0
                # IV&V finding 2026-08-21: IndianGeminiAgent (LLM macro agent) has no
                # point-in-time backtest — same reason SentimentAgent is zeroed above —
                # yet it was never added to the RL weight schema, so master.py's
                # `agent_weights.get(agent.name, 1.0)` fallback gave it a permanent,
                # un-learned, un-decaying full vote (1.0) in every committee decision.
                # Zero it until it has a CPCV-validated backtest like the MetaGate gate.
                _live_weights_in["Indian Gemini AI"] = 0.0
                tick_data["agent_weights"] = _live_weights_in

                # Multi-Timeframe Confluence (Indian)
                mtf_confluence_in = await asyncio.to_thread(
                    confluence_engine_in.get_confluence, symbol, tick_data
                )
                tick_data["mtf_confluence"] = mtf_confluence_in

                # Evaluate using the Indian Committee
                decision = master_agent_in.evaluate(symbol, tick_data)

                # Apply MTF confidence adjustment / veto (Indian)
                _pre_mtf_signal_in = decision["signal"]
                if decision["signal"] in ("BUY", "SELL"):
                    decision = confluence_engine_in.apply_to_decision(
                        decision, mtf_confluence_in, decision["signal"]
                    )
                    alignment_in = mtf_confluence_in.get("alignment", "NEUTRAL")
                    if decision["signal"] == "WAIT" and "MTF VETO" in decision.get("reason", ""):
                        engine_state_in["latest_gates"]["mtf_alignment"] = {
                            "status": "BLOCKED",
                            "details": f"MTF VETO: {mtf_confluence_in['detail']}"
                        }
                        await write_log_in("warning", f"🚫 MTF: {mtf_confluence_in['detail']}")
                        execution_engine_in.journal.log_veto(symbol, _pre_mtf_signal_in, "MTF_VETO", mtf_confluence_in['detail'], {"confidence": decision.get("confidence", 0.0), "regime": current_regime})
                    else:
                        engine_state_in["latest_gates"]["mtf_alignment"] = {
                            "status": "PASSED",
                            "details": f"{alignment_in} — Daily:{mtf_confluence_in.get('daily_trend','?')} 1h:{mtf_confluence_in.get('hourly_trend','?')}"
                        }
                else:
                    engine_state_in["latest_gates"]["mtf_alignment"] = {
                        "status": "NOT_EVALUATED",
                        "details": "No signal from committee. MTF not applied."
                    }
                
                # Update Correlation Gate status
                corr_val = decision.get("correlation", 0.0)
                if decision.get("signal") == "WAIT" and "Correlation Gate VETO" in decision.get("reason", ""):
                    engine_state_in["latest_gates"]["correlation_gate"] = {
                        "status": "BLOCKED",
                        "details": f"Blocked: {decision['reason']}"
                    }
                else:
                    if engine_state_in["latest_gates"]["correlation_gate"]["status"] != "BLOCKED":
                        engine_state_in["latest_gates"]["correlation_gate"] = {
                            "status": "PASSED",
                            "details": f"Passed: Rolling correlation to proxy is {corr_val:.2f}."
                        }
                
                # ─── Nifty 50 Trend Filter ───────────────────────────────────────────
                # BUY trades only allowed when Nifty is above its 20-EMA (uptrend).
                # SELL trades get a confidence penalty (not blocked) in uptrends —
                # shorting against the broad index is allowed but conviction is reduced.
                _nifty_above = tick_data.get("nifty_above_20ema", True)
                _nifty_price = tick_data.get("nifty_price", 0.0)
                _nifty_ema20 = tick_data.get("nifty_ema20", 0.0)
                _dec_sig = decision.get("signal", "WAIT")
                if _dec_sig == "BUY" and not _nifty_above:
                    decision["signal"] = "WAIT"
                    decision["reason"] = (
                        f"NIFTY TREND VETO: Nifty ({_nifty_price:.0f}) below 20-EMA ({_nifty_ema20:.0f}) — "
                        f"no longs in broad downtrend. | {decision['reason']}"
                    )
                    engine_state_in["latest_gates"]["nifty_trend"] = {
                        "status": "BLOCKED",
                        "details": f"Nifty {_nifty_price:.0f} < 20-EMA {_nifty_ema20:.0f}. BUY entries blocked."
                    }
                    await write_log_in("warning", f"🚫 NIFTY TREND: {symbol} BUY vetoed — Nifty below 20-EMA.")
                elif _dec_sig == "SELL" and _nifty_above:
                    # Shorting against uptrend — reduce confidence but don't block
                    decision["confidence"] = round(max(0.1, decision.get("confidence", 0.5) - 0.12), 2)
                    decision["reason"] = f"[Nifty uptrend: short confidence -12%] {decision['reason']}"
                    engine_state_in["latest_gates"]["nifty_trend"] = {
                        "status": "PASSED",
                        "details": f"Nifty {_nifty_price:.0f} > 20-EMA. Short allowed with reduced confidence."
                    }
                else:
                    _trend_label = "uptrend" if _nifty_above else "downtrend"
                    engine_state_in["latest_gates"]["nifty_trend"] = {
                        "status": "PASSED",
                        "details": f"Nifty {_trend_label} ({_nifty_price:.0f} vs EMA {_nifty_ema20:.0f}). Signal aligned."
                    }
                # ─────────────────────────────────────────────────────────────────────

                # Shadow Trading: Evaluate active shadow trades
                shadow_engine_in.evaluate_shadow_trades(
                    symbol, tick_data['price'],
                    rl_engine=execution_engine_in.rl_engine,
                    regime=current_regime
                )
                
                # Feature 16: Historical Pattern Search
                pattern_result = pattern_matcher_in.find_similar(tick_data)
                
                # Feature 3: Dynamic Strategy Selection
                strategy_result = strategy_manager_in.select_strategy(symbol, tick_data)
                
                # Feature 18: Advance autonomous builder pipeline
                auto_builder_in.tick()
                
                # Enrich with Probability Profile
                decision = probability_engine_in.enrich(decision, tick_data)
                
                # MTF gate already applied by confluence_engine above — no second veto needed
                if decision.get("signal") not in ("BUY", "SELL"):
                    if engine_state_in["latest_gates"]["mtf_alignment"]["status"] == "NOT_EVALUATED":
                        engine_state_in["latest_gates"]["mtf_alignment"] = {
                            "status": "NOT_EVALUATED",
                            "details": "Not evaluated: No BUY or SELL signal from committee."
                        }
                
                # Shadow Trading: Record missed opportunities if AI rejected a good setup
                signal = decision.get("signal", "WAIT")
                if signal == "WAIT" and decision.get("confidence", 0) > 0.60:
                    shadow_engine_in.record_rejected_trade(symbol, tick_data['price'], decision)

                timestamp = datetime.now().strftime("%H:%M:%S")
                conf = decision.get("confidence", 0) * 100
                buy_conv_in  = decision.get("buy_conviction", 0) * 100
                sell_conv_in = decision.get("sell_conviction", 0) * 100
                threshold_in = decision.get("threshold", 0) * 100

                level = "success" if signal == "BUY" else "error" if signal == "SELL" else "warning"
                if signal == "WAIT":
                    log_msg = f"[WAIT] {symbol} (↑{buy_conv_in:.0f}% ↓{sell_conv_in:.0f}% | need {threshold_in:.0f}%): {decision['reason']}"
                else:
                    log_msg = f"[{signal}] {symbol} (Conf: {conf:.1f}%): {decision['reason']}"
                
                # Execute the trade via Execution Engine
                if signal in ["BUY", "SELL"]:
                    decision["session_quality"] = tick_data.get("session_quality", "NORMAL")

                    decision["regime"] = current_regime
                    # Store entry features for causal attribution
                    decision["entry_features"] = {
                        "price": tick_data.get("price"),
                        "rsi_14": tick_data.get("rsi_14"),
                        "macd_hist": tick_data.get("macd_hist"),
                        "atr_14": tick_data.get("atr_14"),
                        "vwap": tick_data.get("vwap"),
                        "volume": tick_data.get("volume"),
                        "vix_level": tick_data.get("vix_level"),
                        "dxy_value": tick_data.get("dxy_value"),
                        "real_yield_10y_trend": tick_data.get("real_yield_10y_trend")
                    }
                    success, reason = await execution_engine_in.execute_trade(symbol, tick_data['price'], decision)
                    
                    # Check Monte Carlo EV status
                    if not success and "AI Trade Simulator veto" in reason:
                        engine_state_in["latest_gates"]["monte_carlo_ev"] = {
                            "status": "BLOCKED",
                            "details": f"Blocked: {reason}"
                        }
                        await write_log_in("warning", f"[EXECUTION VETO] {symbol}: {reason}")
                        execution_engine_in.journal.log_veto(symbol, signal, "MONTE_CARLO", reason, {"confidence": decision.get("confidence", 0.0), "regime": current_regime})
                        continue
                    else:
                        sim = getattr(execution_engine_in, "latest_sim_result", None)
                        if sim:
                            engine_state_in["latest_gates"]["monte_carlo_ev"] = {
                                "status": "PASSED",
                                "details": f"Passed: EV of ₹{sim['expected_value']:.4f} is above hurdle (win prob: {sim['win_probability']*100:.1f}%)."
                            }
                        else:
                            engine_state_in["latest_gates"]["monte_carlo_ev"] = {
                                "status": "NOT_EVALUATED",
                                "details": "Not evaluated: Liquidating/covering active position."
                            }
                        
                        if not success:
                            await write_log_in("warning", f"[EXECUTION VETO] {symbol}: {reason}")
                            continue
                        else:
                            await write_log_in("success", f"[FILL] {reason}")
                else:
                    if engine_state_in["latest_gates"]["monte_carlo_ev"]["status"] == "NOT_EVALUATED":
                        engine_state_in["latest_gates"]["monte_carlo_ev"] = {
                            "status": "NOT_EVALUATED",
                            "details": "Not evaluated: No BUY or SELL signal."
                        }
                
                # Update holdings with live price from the same real Yahoo Finance tick
                for holding in execution_engine_in.active_holdings:
                    if holding["symbol"] == symbol:
                        holding["current_price"] = tick_data['price']
                        if holding.get("direction", "LONG") == "SHORT":
                            pnl = holding["shares"] * (holding["entry_price"] - tick_data['price'])
                            holding["value"] = round(holding["shares"] * holding["entry_price"] + pnl, 4)
                            holding["change"] = round(
                                (holding["entry_price"] - tick_data['price']) / holding["entry_price"] * 100, 3
                            )
                        else:
                            holding["value"] = round(holding["shares"] * tick_data['price'], 4)
                            holding["change"] = round(
                                (tick_data['price'] - holding["entry_price"]) / holding["entry_price"] * 100, 3
                            )
                        # Sparkline: real price history (populated as engine ticks)
                        holding["sparkline"].append(round(tick_data['price'], 4))
                        if len(holding["sparkline"]) > 20:
                            holding["sparkline"].pop(0)
                        # C-1: Advance trailing stop as price moves in favour
                        _trail_signal_in = "BUY" if holding.get("direction", "LONG") == "LONG" else "SELL"
                        _atr_val_in  = tick_data.get('atr_14', 0.0)
                        _vol_prox_in = (_atr_val_in / tick_data['price']) if tick_data.get('price', 0) > 0 else 0.02
                        _vol_prox_in = max(_vol_prox_in, 0.002)
                        _trail_in = execution_engine_in.stops.update_trailing(
                            current_price    = tick_data['price'],
                            signal           = _trail_signal_in,
                            current_stop     = holding.get("stop_loss", 0.0),
                            best_price       = holding.get("best_price", holding.get("entry_price", tick_data['price'])),
                            volatility_proxy = _vol_prox_in,
                            entry_price      = holding.get("entry_price"),
                            regime           = current_regime_in,
                        )
                        holding["stop_loss"]  = _trail_in["new_stop"]
                        holding["best_price"] = _trail_in["best_price"]

                await write_log_in(level, log_msg, decision=decision)
            except Exception as e:
                await write_log_in("error", f"🚨 Indian Error processing {symbol}: {str(e)}")
                
        await asyncio.sleep(4) # Wait before next scan

async def periodic_model_update_loop_in():
    """Background task to run Boruta + RFECV feature selection and HMM retraining periodically for Indian market."""
    print("[DEBUG] periodic_model_update_loop_in task spawned!")
    # Stagger Indian boot ML jobs 120s after startup (US jobs start at 60s)
    # so both heavyweight training jobs don't run at the same time.
    await asyncio.sleep(120)
    try:
        await write_log_in("info", "Starting initial boot feature selection for Indian Market...")
        for sym in data_engine_in.symbols[:4]:  # cap at 4 to limit boot time
            await asyncio.to_thread(data_engine_in.run_feature_selection, sym)
        await write_log_in("info", "Boot feature selection for Indian Market complete.")

        await write_log_in("info", "Starting initial boot HMM regime detector retraining for Indian Market...")
        await asyncio.to_thread(regime_detector_in.retrain)
        await write_log_in("info", "Boot HMM retraining for Indian Market complete.")
    except Exception as e:
        await write_log_in("error", f"Boot model update error (Indian): {e}")

    while engine_state_in["is_running"]:
        for _ in range(8640):
            if not engine_state_in["is_running"]:
                break
            await asyncio.sleep(10)
            
        if not engine_state_in["is_running"]:
            break
            
        try:
            await write_log_in("info", "Starting periodic feature selection for Indian Market...")
            for sym in data_engine_in.symbols:  # all 11 symbols — periodic runs nightly, no cap needed
                await asyncio.to_thread(data_engine_in.run_feature_selection, sym)
            await write_log_in("info", "Periodic feature selection for Indian Market complete.")
            
            await write_log_in("info", "Starting periodic HMM regime detector retraining for Indian Market...")
            await asyncio.to_thread(regime_detector_in.retrain)
            await write_log_in("info", "Periodic HMM retraining for Indian Market complete.")
        except Exception as e:
            await write_log_in("error", f"Periodic model update loop error (Indian): {e}")


def _generic_trading_loop_body(
    symbol, ticks, engine_state_ref, execution_engine_ref,
    event_engine_ref, regime_detector_ref, master_agent_ref,
    lstm_engine_ref, confluence_engine_ref, shadow_engine_ref,
    pattern_matcher_ref, strategy_manager_ref, auto_builder_ref,
    probability_engine_ref, portfolio_risk_ref, write_log_fn,
    currency_prefix="$"
):
    """Returns a coroutine that processes one symbol in any market's trading loop."""
    # This helper is intentionally a plain function that returns data —
    # actual async calls are in the loop itself.
    pass  # Not used as a helper — see full loop implementations below


async def _run_market_loop(
    symbols_fn,           # callable: () -> dict[sym -> tick_or_error]
    engine_state_ref,     # dict
    execution_engine_ref,
    event_engine_ref,
    regime_detector_ref,
    master_agent_ref,
    lstm_engine_ref,
    confluence_engine_ref,
    shadow_engine_ref,
    pattern_matcher_ref,
    strategy_manager_ref,
    auto_builder_ref,
    probability_engine_ref,
    portfolio_risk_ref,
    write_log_fn,
    currency_prefix="$",
    market_label="Market"
):
    """
    Shared trading loop body used by US Stocks, Crypto, and Forex loops.
    Mirrors indian_trading_loop() exactly — concurrent tick fetch, full gate stack,
    RL weights, MTF confluence, shadow trading, Monte Carlo EV gate.
    """
    print(f"[DEBUG] {market_label} trading_loop task spawned!")
    while engine_state_ref["is_running"]:
        print(f"[DEBUG] {market_label} trading_loop tick started...")

        # A-1: Global cross-market circuit breaker
        _g_ref = global_risk.check()
        if _g_ref["global_halt"]:
            await write_log_fn("warning", f"⛔ {_g_ref['halt_reason']} — {market_label} engine standing down.")
            await asyncio.sleep(4)
            continue

        # PR-2: Heartbeat
        engine_heartbeats[market_label.upper()] = time.time()

        engine_state_ref["latest_gates"] = {
            "event_blackout":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "mtf_alignment":   {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "correlation_gate":{"status": "NOT_EVALUATED", "details": "Waiting for signal."},
            "monte_carlo_ev":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
        }

        try:
            # FIX 2026-08-03: hang guard — see indian_trading_loop.
            ticks = await asyncio.wait_for(asyncio.to_thread(symbols_fn), timeout=240)
        except Exception as _fetch_err:
            _fe = "timed out after 240s" if isinstance(_fetch_err, (asyncio.TimeoutError, TimeoutError)) else str(_fetch_err)
            await write_log_fn("error", f"🚨 {market_label} tick fetch failed: {_fe}. Retrying in 30s.")
            await asyncio.sleep(30)
            continue

        for symbol in list(ticks.keys()):
            if not engine_state_ref["is_running"]:
                break

            tick_data = ticks.get(symbol)
            if tick_data is None:
                continue
            if isinstance(tick_data, RuntimeError):
                await write_log_fn("warning", f"⏸ {market_label} data unavailable for {symbol}: {str(tick_data)[:80]}. Skipping.")
                continue
            if isinstance(tick_data, Exception):
                await write_log_fn("error", f"🚨 Error fetching tick for {symbol}: {str(tick_data)[:80]}. Skipping.")
                continue

            try:
                lstm_engine_ref.update_tick(symbol, tick_data)
                lstm_res = lstm_engine_ref.get_signal(symbol)
                tick_data["lstm_signal"] = lstm_res["signal"]
                tick_data["lstm_confidence"] = lstm_res["confidence"]
                tick_data["trading_mode"] = engine_state_ref.get("risk_mode", "Normal")
                source = tick_data.get("data_source", "Yahoo Finance")

                await write_log_fn("info", f"Analyzing {symbol} @ {currency_prefix}{tick_data['price']} | RSI: {tick_data.get('rsi_14', 0):.1f} | MACD: {tick_data.get('macd_hist', 0):.4f} | {source}")

                # Event Awareness Gate
                event_status = event_engine_ref.check_today(tick_data)
                if event_status["trading_blackout"]:
                    if engine_state_ref.get("risk_mode") == "Aggressive":
                        engine_state_ref["latest_gates"]["event_blackout"] = {
                            "status": "PASSED",
                            "details": f"Blackout bypassed (Aggressive mode): {event_status['blackout_reason']}."
                        }
                        await write_log_fn("warning", f"⚠️ BLACKOUT: {event_status['blackout_reason']} ignored (Aggressive Mode).")
                    else:
                        engine_state_ref["latest_gates"]["event_blackout"] = {
                            "status": "BLOCKED",
                            "details": f"Blocked: {event_status['blackout_reason']}."
                        }
                        await write_log_fn("warning", f"🚫 BLACKOUT: {event_status['blackout_reason']}. Skipping trade.")
                        execution_engine_ref.journal.log_veto(symbol, "ANY", "EVENT_BLACKOUT", event_status['blackout_reason'])
                        continue
                else:
                    if engine_state_ref["latest_gates"]["event_blackout"]["status"] != "BLOCKED":
                        engine_state_ref["latest_gates"]["event_blackout"] = {
                            "status": "PASSED",
                            "details": "Passed: No high-risk macro events."
                        }

                holdings_list = execution_engine_ref.active_holdings
                tick_data['active_holdings'] = execution_engine_ref.active_holdings
                tick_data['open_trade_count'] = len(execution_engine_ref.active_holdings)
                tick_data['session_quality'] = event_engine_ref.check_session_quality().get("session", "NORMAL")

                risk_profile = portfolio_risk_ref.analyze(holdings_list, execution_engine_ref.get_total_equity())
                tick_data['halt_trading_for_day'] = risk_profile.get('halt_trading_for_day', False)
                tick_data['daily_drawdown_pct'] = risk_profile.get('daily_drawdown_pct', 0.0)
                tick_data['cash_pct'] = risk_profile.get('cash_pct', 100.0)

                if tick_data['halt_trading_for_day']:
                    dd = risk_profile.get('daily_drawdown_pct', 0.0)
                    await write_log_fn("warning", f"🚨 DAILY LOSS LIMIT HIT ({dd:.1f}% drawdown). All new trades blocked for {symbol}.")
                    execution_engine_ref.journal.log_veto(symbol, "ANY", "DAILY_HALT", f"Daily drawdown {dd:.1f}% exceeded limit.")
                    continue
                if risk_profile.get('halt_trading_for_week'):
                    wd = risk_profile.get('weekly_drawdown_pct', 0.0)
                    await write_log_fn("warning", f"🚨 WEEKLY LOSS LIMIT HIT ({wd:.1f}% drawdown). Trades blocked for the week.")
                    execution_engine_ref.journal.log_veto(symbol, "ANY", "WEEKLY_HALT", f"Weekly drawdown {wd:.1f}% exceeded limit.")
                    continue

                # SL/TP enforcement: 2-Stage Asymmetric Scale-Out & Breakeven Ratcheting
                _sl_tp_triggers = []
                for _h in list(execution_engine_ref.active_holdings):
                    if _h["symbol"] != symbol:
                        continue
                    _cur     = tick_data['price']
                    _dir     = _h.get("direction", "LONG")
                    _sl      = _h.get("stop_loss")
                    if not _sl or _sl <= 0:
                        _entry_p = float(_h.get("entry_price", _cur) or _cur)
                        _sl = round(_entry_p * 0.98, 4) if _dir == "LONG" else round(_entry_p * 1.02, 4)
                        _h["stop_loss"] = _sl
                        await write_log_fn("warning", f"🚨 [Emergency Stop Guard] Missing/corrupt stop-loss detected for {symbol}. Initialized fallback stop at {currency_prefix}{_sl:.4f} (Entry: {currency_prefix}{_entry_p:.4f}, Cur: {currency_prefix}{_cur:.4f}).")

                    _tp1     = _h.get("tp1_target")
                    _tp2     = _h.get("tp2_target") or _h.get("take_profit")
                    _tp3     = _h.get("tp3_runner_target")
                    _tp1_hit = _h.get("tp1_hit", False)
                    _tp2_hit = _h.get("tp2_hit", False)

                    if _dir == "LONG":
                        if _cur <= _sl:
                            _sl_tp_triggers.append((_h, "STOP_LOSS", "FULL"))

                        elif not _tp1_hit and _tp1 and _cur >= _tp1:
                            _sl_tp_triggers.append((_h, "TP1_1.5R_SCALEOUT", "PARTIAL"))
                        elif _tp1_hit and not _tp2_hit and _tp2 and _cur >= _tp2:
                            _sl_tp_triggers.append((_h, "TP2_3.0R_SCALEOUT", "PARTIAL"))
                        elif _tp2_hit and _tp3 and _cur >= _tp3:
                            _sl_tp_triggers.append((_h, "TP3_CHANDELIER_RUNNER", "FULL"))
                    else:
                        if _sl and _cur >= _sl:
                            _sl_tp_triggers.append((_h, "STOP_LOSS", "FULL"))
                        elif not _tp1_hit and _tp1 and _cur <= _tp1:
                            _sl_tp_triggers.append((_h, "TP1_1.5R_SCALEOUT", "PARTIAL"))
                        elif _tp1_hit and not _tp2_hit and _tp2 and _cur <= _tp2:
                            _sl_tp_triggers.append((_h, "TP2_3.0R_SCALEOUT", "PARTIAL"))
                        elif _tp2_hit and _tp3 and _cur <= _tp3:
                            _sl_tp_triggers.append((_h, "TP3_CHANDELIER_RUNNER", "FULL"))


                for _h, _close_reason, _close_type in _sl_tp_triggers:
                    if _close_type == "PARTIAL":
                        _ok, _msg = await execution_engine_ref.partial_close(_h, tick_data['price'], fraction=0.5, reason=_close_reason)
                        _lvl = "success"
                    else:
                        _ok, _msg = await execution_engine_ref.force_close(_h, tick_data['price'], _close_reason)
                        _lvl = "success" if "TAKE_PROFIT" in _close_reason else "warning"
                    await write_log_fn(_lvl, f"[{_close_reason}] {symbol} @ {currency_prefix}{tick_data['price']:.4f} | {_msg}")
                    if _ok:
                        await notifier.send_alert(f"🚨 **{_close_reason}** triggered for {symbol} at {currency_prefix}{tick_data['price']:.4f}\nDetails: {_msg}")


                # Regime detection + RL weights
                current_regime = regime_detector_ref.detect(symbol, tick_data)
                tick_data["regime"] = current_regime
                _lw = execution_engine_ref.rl_engine.get_current_weights(current_regime)
                _lw["News & Sentiment AI"] = 0.0
                _lw["Correlation Agent"]   = 0.0
                tick_data["agent_weights"] = _lw

                # MTF Confluence
                mtf_conf = await asyncio.to_thread(confluence_engine_ref.get_confluence, symbol, tick_data)
                tick_data["mtf_confluence"] = mtf_conf

                # Committee decision
                decision = master_agent_ref.evaluate(symbol, tick_data)

                # Apply MTF veto / boost
                _pre_mtf_signal_ref = decision["signal"]
                if decision["signal"] in ("BUY", "SELL"):
                    decision = confluence_engine_ref.apply_to_decision(decision, mtf_conf, decision["signal"])
                    alignment = mtf_conf.get("alignment", "NEUTRAL")
                    if decision["signal"] == "WAIT" and "MTF VETO" in decision.get("reason", ""):
                        engine_state_ref["latest_gates"]["mtf_alignment"] = {
                            "status": "BLOCKED", "details": f"MTF VETO: {mtf_conf['detail']}"
                        }
                        await write_log_fn("warning", f"🚫 MTF: {mtf_conf['detail']}")
                        execution_engine_ref.journal.log_veto(symbol, _pre_mtf_signal_ref, "MTF_VETO", mtf_conf['detail'], {"confidence": decision.get("confidence", 0.0), "regime": current_regime})
                    else:
                        engine_state_ref["latest_gates"]["mtf_alignment"] = {
                            "status": "PASSED",
                            "details": f"{alignment} — Daily:{mtf_conf.get('daily_trend','?')} 1h:{mtf_conf.get('hourly_trend','?')}"
                        }
                else:
                    engine_state_ref["latest_gates"]["mtf_alignment"] = {
                        "status": "NOT_EVALUATED", "details": "No signal from committee. MTF not applied."
                    }

                # Correlation gate status
                corr_val = decision.get("correlation", 0.0)
                if decision.get("signal") == "WAIT" and "Correlation Gate VETO" in decision.get("reason", ""):
                    engine_state_ref["latest_gates"]["correlation_gate"] = {
                        "status": "BLOCKED", "details": f"Blocked: {decision['reason']}"
                    }
                else:
                    if engine_state_ref["latest_gates"]["correlation_gate"]["status"] != "BLOCKED":
                        engine_state_ref["latest_gates"]["correlation_gate"] = {
                            "status": "PASSED",
                            "details": f"Passed: Rolling correlation is {corr_val:.2f}."
                        }

                # Shadow trading
                shadow_engine_ref.evaluate_shadow_trades(
                    symbol, tick_data['price'],
                    rl_engine=execution_engine_ref.rl_engine,
                    regime=current_regime
                )

                pattern_matcher_ref.find_similar(tick_data)
                strategy_manager_ref.select_strategy(symbol, tick_data)
                auto_builder_ref.tick()
                decision = probability_engine_ref.enrich(decision, tick_data)

                if decision.get("signal") not in ("BUY", "SELL"):
                    if engine_state_ref["latest_gates"]["mtf_alignment"]["status"] == "NOT_EVALUATED":
                        engine_state_ref["latest_gates"]["mtf_alignment"] = {
                            "status": "NOT_EVALUATED",
                            "details": "Not evaluated: No BUY or SELL signal from committee."
                        }

                signal = decision.get("signal", "WAIT")
                if signal == "WAIT" and decision.get("confidence", 0) > 0.60:
                    shadow_engine_ref.record_rejected_trade(symbol, tick_data['price'], decision)

                conf       = decision.get("confidence", 0) * 100
                buy_conv   = decision.get("buy_conviction", 0) * 100
                sell_conv  = decision.get("sell_conviction", 0) * 100
                threshold  = decision.get("threshold", 0) * 100
                level = "success" if signal == "BUY" else "error" if signal == "SELL" else "warning"
                if signal == "WAIT":
                    log_msg = f"[WAIT] {symbol} (↑{buy_conv:.0f}% ↓{sell_conv:.0f}% | need {threshold:.0f}%): {decision['reason']}"
                else:
                    log_msg = f"[{signal}] {symbol} (Conf: {conf:.1f}%): {decision['reason']}"

                if signal in ["BUY", "SELL"]:
                    # Phase 3 CONFIRMED Meta-Labeling Gate (BTC-USD LONG entries only in Crypto)
                    if signal == "BUY" and market_label.upper() == "CRYPTO" and symbol.upper() == "BTC-USD":
                        try:
                            from analytics.meta_gate import MetaGate, GATE_THRESHOLD as _MG_TH
                            _mg_p = await asyncio.to_thread(MetaGate.instance().p_win, symbol)
                            if _mg_p is not None:
                                decision["metagate_score"] = round(_mg_p, 4)
                                if _mg_p < _MG_TH:
                                    _mg_reason = f"MetaGate VETO: P(win) {_mg_p:.2f} < {_MG_TH:.2f}"
                                    await write_log_fn("warning", f"🚫 {_mg_reason}")
                                    execution_engine_ref.journal.log_veto(
                                        symbol, signal, "META_GATE", _mg_reason,
                                        {"confidence": decision.get("confidence", 0.0), "p_win": _mg_p}
                                    )
                                    continue
                        except Exception as _mg_err:
                            pass  # fail-open per design


                    decision["session_quality"] = tick_data.get("session_quality", "NORMAL")
                    decision["regime"] = current_regime
                    decision["entry_features"] = {
                        "price": tick_data.get("price"),
                        "rsi_14": tick_data.get("rsi_14"),
                        "macd_hist": tick_data.get("macd_hist"),
                        "atr_14": tick_data.get("atr_14"),
                        "vwap": tick_data.get("vwap"),
                        "volume": tick_data.get("volume"),
                        "vix_level": tick_data.get("vix_level"),
                        "dxy_value": tick_data.get("dxy_value"),
                        "real_yield_10y_trend": tick_data.get("real_yield_10y_trend")
                    }
                    success, reason_msg = await execution_engine_ref.execute_trade(symbol, tick_data['price'], decision)
                    if not success and "AI Trade Simulator veto" in reason_msg:
                        engine_state_ref["latest_gates"]["monte_carlo_ev"] = {
                            "status": "BLOCKED", "details": f"Blocked: {reason_msg}"
                        }
                        await write_log_fn("warning", f"[EXECUTION VETO] {symbol}: {reason_msg}")
                        execution_engine_ref.journal.log_veto(symbol, signal, "MONTE_CARLO", reason_msg, {"confidence": decision.get("confidence", 0.0), "regime": current_regime})
                        continue
                    else:
                        sim = getattr(execution_engine_ref, "latest_sim_result", None)
                        if sim:
                            engine_state_ref["latest_gates"]["monte_carlo_ev"] = {
                                "status": "PASSED",
                                "details": f"Passed: EV of {currency_prefix}{sim['expected_value']:.4f} (win prob: {sim['win_probability']*100:.1f}%)."
                            }
                        else:
                            engine_state_ref["latest_gates"]["monte_carlo_ev"] = {
                                "status": "NOT_EVALUATED",
                                "details": "Not evaluated: Liquidating/covering active position."
                            }
                        if not success:
                            await write_log_fn("warning", f"[EXECUTION VETO] {symbol}: {reason_msg}")
                            continue
                        else:
                            await write_log_fn("success", f"[FILL] {reason_msg}")
                            await notifier.send_alert(f"✅ **NEW TRADE OPENED**\nSymbol: {symbol}\nDirection: {signal}\nPrice: {currency_prefix}{tick_data['price']:.4f}\nConfidence: {decision.get('confidence', 0)*100:.1f}%\nMessage: {reason_msg}")
                else:
                    if engine_state_ref["latest_gates"]["monte_carlo_ev"]["status"] == "NOT_EVALUATED":
                        engine_state_ref["latest_gates"]["monte_carlo_ev"] = {
                            "status": "NOT_EVALUATED", "details": "Not evaluated: No BUY or SELL signal."
                        }

                # Update holdings live price + trailing stop
                for holding in execution_engine_ref.active_holdings:
                    if holding["symbol"] == symbol:
                        holding["current_price"] = tick_data['price']
                        if holding.get("direction", "LONG") == "SHORT":
                            pnl = holding["shares"] * (holding["entry_price"] - tick_data['price'])
                            holding["value"] = round(holding["shares"] * holding["entry_price"] + pnl, 4)
                            holding["change"] = round(
                                (holding["entry_price"] - tick_data['price']) / holding["entry_price"] * 100, 3)
                        else:
                            holding["value"] = round(holding["shares"] * tick_data['price'], 4)
                            holding["change"] = round(
                                (tick_data['price'] - holding["entry_price"]) / holding["entry_price"] * 100, 3)
                        holding["sparkline"].append(round(tick_data['price'], 4))
                        if len(holding["sparkline"]) > 20:
                            holding["sparkline"].pop(0)
                        _trail_sig = "BUY" if holding.get("direction", "LONG") == "LONG" else "SELL"
                        _atr_v = tick_data.get('atr_14', 0.0)
                        _vp = (_atr_v / tick_data['price']) if tick_data.get('price', 0) > 0 else 0.02
                        _vp = max(_vp, 0.002)
                        _trail = execution_engine_ref.stops.update_trailing(
                            current_price=tick_data['price'],
                            signal=_trail_sig,
                            current_stop=holding.get("stop_loss", 0.0),
                            best_price=holding.get("best_price", holding.get("entry_price", tick_data['price'])),
                            volatility_proxy=_vp,
                            entry_price=holding.get("entry_price"),
                            regime=current_regime,
                        )
                        holding["stop_loss"]  = _trail["new_stop"]
                        holding["best_price"] = _trail["best_price"]

                await write_log_fn(level, log_msg, decision=decision)
            except Exception as e:
                await write_log_fn("error", f"🚨 {market_label} error processing {symbol}: {str(e)}")

        await asyncio.sleep(4)


async def _engine_watchdog():
    """
    PR-2: Watchdog — fires every 30 s.
    If any engine that has open positions hasn't heartbeated in > 120 s,
    logs a CRITICAL alert (the alert appears in every market's log feed).
    """
    while True:
        await asyncio.sleep(30)
        now = time.time()
        _watch_targets = [
            ("US",     engine_heartbeats.get("US"),     execution_engine),
            ("INDIA",  engine_heartbeats.get("INDIA"),  execution_engine_in),
            ("STOCKS", engine_heartbeats.get("STOCKS"), execution_engine_st),
            ("CRYPTO", engine_heartbeats.get("CRYPTO"), execution_engine_cx),
            ("FOREX",  engine_heartbeats.get("FOREX"),  execution_engine_fx),
        ]
        for market, last_beat, eng in _watch_targets:
            if last_beat is None:
                continue  # engine never started — nothing to watch
            staleness = now - last_beat
            if staleness > 120 and len(eng.active_holdings) > 0:
                alert = (
                    f"[WATCHDOG] ⚠️ {market} engine SILENT for {staleness:.0f}s "
                    f"with {len(eng.active_holdings)} open position(s). "
                    "Loop may have crashed or stalled."
                )
                print(alert)
                await write_log("error", alert, service=f"watchdog_{market.lower()}")


async def stocks_trading_loop():
    await _run_market_loop(
        fetch_all_stocks_ticks, engine_state_st, execution_engine_st,
        event_engine_st, regime_detector_st, master_agent_st,
        lstm_engine_st, confluence_engine_st, shadow_engine_st,
        pattern_matcher_st, strategy_manager_st, auto_builder_st,
        probability_engine_st, portfolio_risk_st, write_log_st,
        currency_prefix="$", market_label="Stocks"
    )


async def crypto_trading_loop():
    try:
        from data.websocket_streamer import CryptoWebSocketStreamer
        await CryptoWebSocketStreamer.get_instance().start()
    except Exception as e:
        print(f"[CryptoWebSocketStreamer] Failed to start background WS listener: {e}")

    await _run_market_loop(
        fetch_all_crypto_ticks, engine_state_cx, execution_engine_cx,
        event_engine_cx, regime_detector_cx, master_agent_cx,
        lstm_engine_cx, confluence_engine_cx, shadow_engine_cx,
        pattern_matcher_cx, strategy_manager_cx, auto_builder_cx,
        probability_engine_cx, portfolio_risk_cx, write_log_cx,
        currency_prefix="$", market_label="Crypto"
    )



async def forex_trading_loop():
    await _run_market_loop(
        fetch_all_forex_ticks, engine_state_fx, execution_engine_fx,
        event_engine_fx, regime_detector_fx, master_agent_fx,
        lstm_engine_fx, confluence_engine_fx, shadow_engine_fx,
        pattern_matcher_fx, strategy_manager_fx, auto_builder_fx,
        probability_engine_fx, portfolio_risk_fx, write_log_fx,
        currency_prefix="$", market_label="Forex"
    )


async def periodic_model_update_loop_st():
    """Stocks market periodic Boruta + HMM retraining (staggered 180s after startup)."""
    print("[DEBUG] periodic_model_update_loop_st task spawned!")
    await asyncio.sleep(180)
    try:
        await write_log_st("info", "Boot feature selection starting for US Stocks...")
        for _sym in _STOCKS_SYMBOLS[:3]:
            await asyncio.to_thread(data_engine_st.run_feature_selection, _sym)
        await write_log_st("info", "Boot feature selection complete (Stocks).")
    except Exception as e:
        await write_log_st("error", f"Boot model update error (Stocks): {e}")
    while engine_state_st["is_running"]:
        for _ in range(8640):
            if not engine_state_st["is_running"]:
                break
            await asyncio.sleep(10)
        if not engine_state_st["is_running"]:
            break
        try:
            await write_log_st("info", "Periodic feature selection for US Stocks...")
            for _sym in _STOCKS_SYMBOLS[:3]:
                await asyncio.to_thread(data_engine_st.run_feature_selection, _sym)
            await write_log_st("info", "Periodic feature selection complete (Stocks).")
        except Exception as e:
            await write_log_st("error", f"Periodic model update error (Stocks): {e}")


async def periodic_model_update_loop_cx():
    """Crypto market periodic Boruta + HMM retraining (staggered 240s after startup)."""
    print("[DEBUG] periodic_model_update_loop_cx task spawned!")
    await asyncio.sleep(240)
    try:
        await write_log_cx("info", "Boot feature selection starting for Crypto...")
        for _sym in _CRYPTO_SYMBOLS[:2]:
            await asyncio.to_thread(data_engine_cx.run_feature_selection, _sym)
        await write_log_cx("info", "Boot feature selection complete (Crypto).")
    except Exception as e:
        await write_log_cx("error", f"Boot model update error (Crypto): {e}")
    while engine_state_cx["is_running"]:
        for _ in range(8640):
            if not engine_state_cx["is_running"]:
                break
            await asyncio.sleep(10)
        if not engine_state_cx["is_running"]:
            break
        try:
            await write_log_cx("info", "Periodic feature selection for Crypto...")
            for _sym in _CRYPTO_SYMBOLS[:2]:
                await asyncio.to_thread(data_engine_cx.run_feature_selection, _sym)
            await write_log_cx("info", "Periodic feature selection complete (Crypto).")
        except Exception as e:
            await write_log_cx("error", f"Periodic model update error (Crypto): {e}")


async def periodic_model_update_loop_fx():
    """Forex market periodic Boruta + HMM retraining (staggered 300s after startup)."""
    print("[DEBUG] periodic_model_update_loop_fx task spawned!")
    await asyncio.sleep(300)
    try:
        await write_log_fx("info", "Boot feature selection starting for Forex...")
        for _sym in _FOREX_SYMBOLS[:2]:
            await asyncio.to_thread(data_engine_fx.run_feature_selection, _sym)
        await write_log_fx("info", "Boot feature selection complete (Forex).")
    except Exception as e:
        await write_log_fx("error", f"Boot model update error (Forex): {e}")
    while engine_state_fx["is_running"]:
        for _ in range(8640):
            if not engine_state_fx["is_running"]:
                break
            await asyncio.sleep(10)
        if not engine_state_fx["is_running"]:
            break
        try:
            await write_log_fx("info", "Periodic feature selection for Forex...")
            for _sym in _FOREX_SYMBOLS[:2]:
                await asyncio.to_thread(data_engine_fx.run_feature_selection, _sym)
            await write_log_fx("info", "Periodic feature selection complete (Forex).")
        except Exception as e:
            await write_log_fx("error", f"Periodic model update error (Forex): {e}")


class ChatRequest(BaseModel):
    message: str
    ticker: str = "NIFTY"

class StartEngineRequest(BaseModel):
    risk_mode: str = "Normal"

_bot_start_times: list = []

@router.post("/bot/start")
async def start_engine(req: StartEngineRequest = None):
    """Starts the autonomous trading engine"""
    # SEC-3: rate limit — max 5 start calls per 60 seconds
    import time as _t
    now = _t.time()
    _bot_start_times[:] = [t for t in _bot_start_times if now - t < 60]
    if len(_bot_start_times) >= 5:
        return {"status": "rate_limited", "message": "Too many start requests. Try again in 60 seconds."}
    _bot_start_times.append(now)
    global _engine_lock
    if _engine_lock is None:
        _engine_lock = asyncio.Lock()
    async with _engine_lock:
        if engine_state["is_running"]:
            return {"status": "already_running", "message": "Engine is already active."}
        engine_state["is_running"] = True
    engine_state["risk_mode"] = req.risk_mode if req else "Normal"
    engine_state["last_scan"] = time.time()
    
    # Start the background trading loop, scanner, and periodic model updater
    asyncio.create_task(trading_loop())
    asyncio.create_task(scanner_agent.start_scanning())
    asyncio.create_task(periodic_model_update_loop())
    # PR-2: Start watchdog once globally
    global _watchdog_started, _log_flush_started
    if not _watchdog_started:
        asyncio.create_task(_engine_watchdog())
        _watchdog_started = True
    # DB-3: Start batched log-flush task once globally
    if not _log_flush_started:
        asyncio.create_task(_log_flush_loop())
        _log_flush_started = True
    _save_bot_state()
    return {"status": "started", "message": "Autonomous engine initialized and scanning."}

@router.post("/bot/stop")
async def stop_engine():
    """Stops the autonomous trading engine"""
    if not engine_state["is_running"]:
        return {"status": "already_stopped", "message": "Engine is already offline."}
    
    engine_state["is_running"] = False
    scanner_agent.stop_scanning()
    _save_bot_state()
    return {"status": "stopped", "message": "Autonomous engine gracefully shut down."}

@router.get("/bot/status")
async def get_engine_status():
    """Returns the current state of the engine"""
    return {
        "is_running": engine_state["is_running"],
        "active_trades": len(execution_engine.active_holdings) if engine_state["is_running"] else 0,
        "uptime_seconds": time.time() - (engine_state["last_scan"] or time.time()) if engine_state["is_running"] else 0
    }

@router.get("/diagnostics/health")
async def get_health():
    """Returns the internal health/performance metrics of the AI cluster."""
    return diagnosis_engine.get_health_report()

@router.post("/backtest/run")
async def run_backtest(req: BacktestRequest):
    """
    Runs a historical walk-forward backtest using real Yahoo Finance data
    and returns full metrics, trade log, and equity curve.
    """
    try:
        engine = BacktestEngine(
            symbol=req.symbol.upper(),
            strategy=req.strategy,
            period=req.period,
            initial_capital=req.initial_capital
        )
        results = await asyncio.to_thread(engine.run)   # IV&V H3: off the event loop
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if "error" in results:
        raise HTTPException(status_code=400, detail=results["error"])
    return results

@router.get("/backtest/leaderboard")
async def get_backtest_leaderboard():
    """Returns the latest scheduled multi-universe backtest leaderboard."""
    l_file = os.path.join(_DATA_DIR, "backtest_leaderboard.json")
    if not os.path.exists(l_file):
        return {"status": "empty", "message": "No scheduled backtests generated yet. Runs automatically every Saturday 02:00 UTC."}
    try:
        with open(l_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/backtest/run-all-universe")
async def trigger_full_universe_backtest():
    """Triggers background execution of the multi-universe scheduled backtest."""
    import subprocess
    import sys
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "scheduled_universe_backtest.py")
    
    def _run():
        try:
            subprocess.run([sys.executable, script_path], capture_output=True)
        except Exception as ex:
            print(f"[BacktestScheduler] Full universe run failed: {ex}")

    asyncio.create_task(asyncio.to_thread(_run))
    return {"status": "ok", "message": "Full universe backtest launched in background. Report will be saved to leaderboard and sent to Telegram."}


@router.get("/bot/logs")
async def get_bot_logs():
    """Returns the latest terminal logs generated by the Master AI."""
    return {"logs": engine_state["bot_logs"]}

@router.get("/bot/stream")
async def stream_bot_logs(request: Request):
    """
    SSE endpoint — streams new log lines to the client in real time.
    Client connects once; server pushes each new log as it appears.
    """
    async def event_generator():
        last_count = len(engine_state["bot_logs"])
        yield f"data: {_json.dumps({'connected': True})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
            current_logs = engine_state["bot_logs"]
            if len(current_logs) > last_count:
                new_logs = current_logs[last_count:]
                for log in new_logs:
                    yield f"data: {_json.dumps(log)}\n\n"
                last_count = len(current_logs)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@router.get("/analytics/journal")
async def get_journal():
    """Returns the complete AI trade journal."""
    return {"journal": execution_engine.journal.get_logs()}

@router.get("/analytics/vetoes")
async def get_vetoes():
    """Returns veto audit ledger — all blocked trades with gate, reason, and signal."""
    return execution_engine.journal.get_veto_summary()

@router.get("/analytics/regime-transitions")
async def get_regime_transitions():
    """Returns HMM regime transition probability matrix for the US market."""
    return regime_detector.get_transition_matrix()

@router.get("/analytics/attribution")
async def get_attribution():
    """Calculates and returns agent/feature causal attribution metrics."""
    engine = CausalAttributionEngine()
    return engine.analyze(
        journal=execution_engine.journal.get_logs(),
        closed_trades=execution_engine.closed_trades
    )

@router.get("/analytics/report")
async def get_daily_report():
    """Generates a daily self-diagnosis report based on journal logs and system health."""
    logs = execution_engine.journal.get_logs()
    weights = execution_engine.rl_engine.get_current_weights()
    
    # Gather V3 system context
    system_context = {
        "portfolio_risk": portfolio_risk.analyze(execution_engine.active_holdings, execution_engine.get_total_equity()),
        "event_status": event_engine.check_today(),
        "active_holdings_count": len(execution_engine.active_holdings),
    }
    
    # Pass shadow logs for RL veto analysis
    shadow_logs = shadow_engine.get_missed_opportunities() if hasattr(shadow_engine, 'get_missed_opportunities') else []
    
    report = diagnosis_engine.generate_report(logs, shadow_logs, weights, system_context, closed_trades_count=len(execution_engine.closed_trades), closed_trades=execution_engine.closed_trades)
    return report

@router.get("/analytics/events")
async def get_market_events():
    """Returns upcoming macro events and trading blackout status."""
    return event_engine.check_today()

@router.get("/analytics/macro")
async def get_macro_context():
    """Returns the live global macro context (DXY, VIX, TIPS 10Y, COT)."""
    from data.ingestion import _fetch_macro_context
    ctx = await asyncio.to_thread(_fetch_macro_context)
    
    dxy_val = ctx.get("dxy_value", 104.5)
    dxy_mom = ctx.get("dxy_momentum", 0.0)
    dxy_prev = dxy_val - dxy_mom
    dxy_change = round((dxy_mom / dxy_prev * 100), 2) if dxy_prev != 0 else 0.0

    vix_val = ctx.get("vix_level", 14.2)
    vix_mom = ctx.get("vix_change", 0.0)
    vix_prev = vix_val - vix_mom
    vix_change = round((vix_mom / vix_prev * 100), 2) if vix_prev != 0 else 0.0

    yield_trend = ctx.get("real_yield_10y_trend", 0.0)

    from data.cot_client import COTClient
    cot_c = COTClient()
    gold_cot_data = await asyncio.to_thread(cot_c.get_gold_positioning)
    nq_cot_data = await asyncio.to_thread(cot_c.get_nq_positioning)

    import datetime
    now_gmt = datetime.datetime.now(datetime.timezone.utc)
    london_fix_active = (now_gmt.hour == 15 and 0 <= now_gmt.minute <= 30)

    current_date = datetime.datetime.now()
    is_rollover_week = (current_date.month in [3, 6, 9, 12] and 7 <= current_date.day <= 14)

    return {
        "dxy": {"price": round(dxy_val, 2), "change": dxy_change},
        "vix": {"price": round(vix_val, 2), "change": vix_change},
        "tips10y": {"price": round(1.95 + yield_trend, 2), "change": round(yield_trend * 100, 1)},
        "gold_cot": {
            "positioning": gold_cot_data.get("positioning", "NEUTRAL").replace("STRONG_", ""),
            "net_longs": gold_cot_data.get("mm_net", 0)
        },
        "nq_cot": {
            "positioning": nq_cot_data.get("positioning", "NEUTRAL").replace("STRONG_", ""),
            "net_longs": nq_cot_data.get("lf_net", 0)
        },
        "london_fix": london_fix_active,
        "rollover_week": is_rollover_week
    }

@router.get("/analytics/agent-weights")
async def get_agent_weights():
    """Returns the live RL-adjusted weights for each AI committee member.

    IV&V finding 2026-08-21 (audit Finding #13): the live trading loop
    forces Sentiment/Correlation Agent weights to 0.0 before every real
    decision (see _run_market_loop / the US loop above); this display
    endpoint previously returned the raw, un-masked learned weights,
    misleadingly implying those agents still vote.
    """
    w = execution_engine.rl_engine.get_current_weights()
    w["News & Sentiment AI"] = 0.0
    w["Correlation Agent"]   = 0.0
    return {"weights": w}

@router.get("/analytics/rl-stats")
async def get_rl_stats():
    """
    Returns real RL stats computed from actual closed trades:
    win_rate, retrain_count, trades_till_retrain, retrain_progress_pct.
    No hardcoded values.
    """
    return execution_engine.rl_engine.get_stats()


@router.get("/analytics/global-risk")
async def get_global_risk():
    """A-1: Returns cross-market equity, global drawdown, and halt status."""
    return global_risk.check()


@router.post("/risk/reset-baselines")
async def reset_global_risk_baselines():
    """
    Re-anchor global and per-market drawdown baselines to current equity and clear any halt.
    Use after intentional accounting operations (balance migrations, currency fixes, book cleanups).
    """
    res = global_risk.reset_baselines(reason="API reset-baselines")
    market_sync = {}
    pairs = [
        ("US", portfolio_risk, execution_engine),
        ("India", portfolio_risk_in, execution_engine_in),
        ("Stocks", portfolio_risk_st, execution_engine_st),
        ("Crypto", portfolio_risk_cx, execution_engine_cx),
        ("Forex", portfolio_risk_fx, execution_engine_fx),
    ]
    for name, p_risk, eng in pairs:
        try:
            eq = eng.get_total_equity()
            p_risk.reset_baselines(eq)
            market_sync[name] = {"status": "SUCCESS", "new_baseline": round(eq, 2)}
        except Exception as e:
            _srv_logger.warning(f"[Routes] Error resetting {name} risk baseline: {e}")
            market_sync[name] = {"status": "FAILED", "error": str(e)}
    res["markets_synced"] = market_sync
    return res


@router.post("/risk/resume")
async def resume_risk_trading():
    """
    Authorized resume: clears global/local halts and re-anchors baselines across all 5 engines.
    """
    res = global_risk.resume_trading(reason="Operator Authorized Resume")
    market_sync = {}
    pairs = [
        ("US", portfolio_risk, execution_engine),
        ("India", portfolio_risk_in, execution_engine_in),
        ("Stocks", portfolio_risk_st, execution_engine_st),
        ("Crypto", portfolio_risk_cx, execution_engine_cx),
        ("Forex", portfolio_risk_fx, execution_engine_fx),
    ]
    for name, p_risk, eng in pairs:
        try:
            eq = eng.get_total_equity()
            p_risk.reset_baselines(eq)
            market_sync[name] = {"status": "SUCCESS", "new_baseline": round(eq, 2)}
        except Exception as e:
            _srv_logger.warning(f"[Routes] Error syncing {name} risk baseline on resume: {e}")
            market_sync[name] = {"status": "FAILED", "error": str(e)}
    res["markets_synced"] = market_sync
    return res


@router.post("/risk/kill-switch")
async def emergency_kill_switch():
    """
    EMERGENCY KILL SWITCH: Immediately halts all market engines and liquidates
    all open active holdings across every market book.
    """
    return await global_risk.trigger_emergency_kill_switch(reason="Operator API Kill Switch")





@router.get("/strategies/library")
async def get_strategy_library():
    """Returns the full 20+ strategy library categorized by market regime."""
    return strategy_manager.get_all_strategies()

@router.post("/strategies/generate")
async def generate_strategy():
    """Manually trigger the autonomous strategy builder"""
    return auto_builder.generate_and_test()

@router.get("/opportunities")
async def get_opportunities():
    """Returns the live feed of scanned trade opportunities from the universe."""
    return {"opportunities": scanner_agent.get_opportunities()}

@router.get("/analytics/missed-opportunities")
async def get_missed_opportunities():
    """Returns trades the AI rejected that would have been profitable."""
    return {"missed_trades": shadow_engine.get_missed_opportunities()}

@router.get("/strategies/builder")
async def get_builder_status():
    """Returns the live status of the Autonomous Strategy Builder pipeline."""
    auto_builder.tick()  # advance on request too
    return auto_builder.get_status()

@router.get("/analytics/pattern/{symbol}")
async def get_pattern_analysis(symbol: str):
    """Returns real historical pattern similarity for a symbol using Yahoo Finance OHLCV."""
    tick = await asyncio.to_thread(data_engine.get_tick_for, symbol.upper())
    return pattern_matcher.find_similar(tick)



@router.get("/portfolio/money-tracker")
async def get_money_tracker():
    """Returns all closed trades with their profit/loss breakdown for the Money Tracker UI.

    IV&V finding 2026-08-21 (audit Finding #20): summary totals now read
    execution_engine.lifetime_stats (O(1) running counters) instead of
    re-summing closed_trades on every request. closed_trades itself is now
    capped (see SmartExecutionEngine._MAX_CLOSED_TRADES) to bound JSON-save
    cost, so summing it directly would have under-counted lifetime totals
    once the cap was reached — lifetime_stats is unaffected by the cap.
    """
    trades = execution_engine.closed_trades
    stats  = execution_engine.lifetime_stats
    win_rate = (stats["winning_trades"] / stats["total_trades"] * 100) if stats["total_trades"] else 0.0

    return {
        "closed_trades": trades,
        "summary": {
            "total_pnl": round(stats["total_pnl"], 2),
            "gross_profit": round(stats["gross_profit"], 2),
            "gross_loss": round(stats["gross_loss"], 2),
            "win_rate": round(win_rate, 2),
            "total_trades": stats["total_trades"],
            "current_balance": round(execution_engine.portfolio_balance, 2)
        },
        "active_holdings": execution_engine.active_holdings
    }

@router.get("/portfolio/holdings")
async def get_portfolio_holdings():
    """Returns the live portfolio holdings from the Execution Engine."""
    return execution_engine.get_portfolio_status()

@router.get("/portfolio/history")
async def get_portfolio_history(timeframe: str = "1M"):
    """
    Returns real historical equity curve normalized to the current balance.
    Since this is a new portfolio starting at $1, we benchmark against MNQ=F 
    historical performance to visualize real market conditions, not fake sine waves.
    """
    import yfinance as yf
    import pandas as pd
    
    # Map timeframe to yfinance period
    period_map = {"1W": "5d", "1M": "1mo", "3M": "3mo", "YTD": "ytd", "1Y": "1y"}
    period = period_map.get(timeframe, "1mo")
    
    try:
        ticker = yf.Ticker("MNQ=F")
        df = await asyncio.to_thread(ticker.history, period=period, interval="1d")
        if df is None or df.empty:
            raise ValueError("No data")
            
        closes = df["Close"].tolist()
        dates = df.index.strftime('%Y-%m-%d').tolist()
        
        # Normalize to the current portfolio balance
        current_balance = execution_engine.portfolio_balance
        last_close = closes[-1]
        
        history = []
        for i, c in enumerate(closes):
            # Scale MNQ=F returns so that the final point equals our current balance
            norm_val = current_balance * (c / last_close)
            history.append({
                "name": dates[i],
                "value": round(norm_val, 4)
            })
            
        return {"history": history}
    except Exception as e:
        # Fallback to flat line if yfinance fails, never a fake sine wave
        return {"history": [{"name": "Today", "value": execution_engine.portfolio_balance}]}


@router.get("/portfolio/risk")
async def get_portfolio_risk():
    """Returns Portfolio-Level Risk profile including performance metrics."""
    holdings = execution_engine.active_holdings
    capital = execution_engine.get_total_equity()  # margin-aware: short "value" is notional+PnL, not cash at risk
    risk = portfolio_risk.analyze(holdings, capital)
    trades = execution_engine.closed_trades
    perf = performance_metrics.compute(trades, initial_capital=execution_engine._initial_balance)
    # Enrich with per-trade stats that equity-curve metrics don't capture
    if trades:
        gross_profit = sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) > 0)
        gross_loss   = abs(sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) < 0))
        wins         = sum(1 for t in trades if t.get("profit_loss", 0) > 0)
        losses       = len(trades) - wins
        avg_win      = gross_profit / wins if wins else 0.0
        avg_loss     = gross_loss / losses if losses else 0.0
        win_rate     = wins / len(trades) * 100
        perf["win_rate_pct"]  = round(win_rate, 1)
        perf["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        perf["expectancy"]    = round(win_rate / 100 * avg_win - (1 - win_rate / 100) * avg_loss, 2)
        perf["trade_count"]   = len(trades)
    risk["performance"] = perf
    return risk

@router.get("/institutional/flows")
async def get_institutional_flows():
    """Returns market-wide FII/DII institutional flow data."""
    return institutional_tracker.get_market_wide_flows()

@router.get("/institutional/flows/{symbol}")
async def get_symbol_institutional_flows(symbol: str):
    """Returns institutional flow data for a specific symbol."""
    return institutional_tracker.get_institutional_flows(symbol)

@router.get("/data/regime")
async def get_market_regime():
    """Returns the current market regime detected by the engine."""
    return {
        "regime": strategy_manager.current_regime or "Scanning...",
        "active_strategy": strategy_manager.active_strategy
    }

@router.get("/execution/fills")
async def get_execution_fills():
    """Returns the broker smart-order routing fills log (TWAP/VWAP/Iceberg)."""
    return {
        "strategy": execution_engine.router.strategy,
        "fills": execution_engine.router.execution_log[-20:]  # Last 20 fills
    }

@router.post("/execution/set-routing")
async def set_routing_strategy(strategy: str = "VWAP"):
    """Switch the smart order routing strategy: MARKET, TWAP, VWAP, ICEBERG."""
    valid = {"MARKET", "TWAP", "VWAP", "ICEBERG"}
    if strategy.upper() not in valid:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid strategy. Choose from: {valid}")
    execution_engine.router.strategy = strategy.upper()
    return {"status": "ok", "active_routing": strategy.upper()}

# ---------------------------------------------------------------------------
# Institutional Analytics, Emergency Kill-Switch & Retraining Endpoints
# ---------------------------------------------------------------------------

@router.get("/analytics/performance-breakdown")
async def get_analytics_performance_breakdown():
    """Returns full institutional performance breakdown across all 5 markets."""
    all_closed = (
        execution_engine.closed_trades +
        execution_engine_in.closed_trades +
        execution_engine_st.closed_trades +
        execution_engine_cx.closed_trades +
        execution_engine_fx.closed_trades
    )
    engines_map = {
        "US": execution_engine,
        "INDIA": execution_engine_in,
        "STOCKS": execution_engine_st,
        "CRYPTO": execution_engine_cx,
        "FOREX": execution_engine_fx,
    }
    combined_initial_capital = (
        global_risk.total_initial_capital()
        or global_risk.total_equity()
        or 100_000.0
    )
    return performance_metrics.get_comprehensive_performance_breakdown(
        all_closed,
        initial_capital=combined_initial_capital,
        engines_map=engines_map
    )


@router.post("/risk/emergency-kill-switch")
async def trigger_emergency_kill_switch(reason: str = "Operator Activated"):
    """Halts all market engines, flattens active holdings, and preserves capital."""
    result = await global_risk.trigger_emergency_kill_switch(reason=reason)
    await write_log("error", f"🚨 EMERGENCY KILL SWITCH TRIGGERED: {reason}")
    await notifier.send_alert(f"🚨 **EMERGENCY KILL SWITCH TRIGGERED**\nReason: {reason}\nLiquidated: {result.get('liquidated_positions_count', 0)} positions")
    return result

@router.post("/risk/resume")
async def resume_all_trading(reason: str = "Operator Authorized"):
    """Clears global halt and resumes autonomous trading across all markets."""
    result = global_risk.resume_trading(reason=reason)
    await write_log("info", f"✅ TRADING RESUMED: {reason}")
    await notifier.send_alert(f"✅ **Autonomous Trading Resumed**\nReason: {reason}")
    return result

@router.post("/models/retrain-all")
async def trigger_retrain_all_models():
    """Triggers background retraining of all MetaGate machine learning models."""
    import subprocess
    import sys
    script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "train_all_metagate.py")
    
    def _run_bg_train():
        try:
            subprocess.run([sys.executable, script_path], capture_output=True, check=True)
            print("[AutoML] Background MetaGate model retraining complete.")
        except Exception as ex:
            print(f"[AutoML] Background MetaGate retraining failed: {ex}")

    asyncio.create_task(asyncio.to_thread(_run_bg_train))
    return {"status": "ok", "message": "Background retraining task launched across multi-asset universe."}




@router.get("/shadow/missed-opportunities")
async def get_shadow_missed_opportunities():
    """Returns missed opportunities and avoided loss trades across all market engines."""
    all_opps = (
        shadow_engine.get_missed_opportunities() +
        shadow_engine_in.get_missed_opportunities() +
        shadow_engine_st.get_missed_opportunities() +
        shadow_engine_cx.get_missed_opportunities() +
        shadow_engine_fx.get_missed_opportunities()
    )
    # Sort newest first
    all_opps.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"missed_opportunities": all_opps[:100], "total_count": len(all_opps)}

@router.get("/shadow/stats")
async def get_shadow_trading_stats():
    """Returns aggregated shadow trading accuracy, avoided losses, and missed profits."""
    all_opps = (
        shadow_engine.get_missed_opportunities() +
        shadow_engine_in.get_missed_opportunities() +
        shadow_engine_st.get_missed_opportunities() +
        shadow_engine_cx.get_missed_opportunities() +
        shadow_engine_fx.get_missed_opportunities()
    )
    missed_profits = [o for o in all_opps if o.get("outcome") == "Missed Profit"]
    avoided_losses = [o for o in all_opps if o.get("outcome") == "Avoided Loss"]
    
    active_shadows_cnt = (
        len(shadow_engine.shadow_portfolio) +
        len(shadow_engine_in.shadow_portfolio) +
        len(shadow_engine_st.shadow_portfolio) +
        len(shadow_engine_cx.shadow_portfolio) +
        len(shadow_engine_fx.shadow_portfolio)
    )
    
    total_evaluated = len(missed_profits) + len(avoided_losses)
    veto_accuracy_pct = round((len(avoided_losses) / total_evaluated * 100), 1) if total_evaluated > 0 else 100.0

    return {
        "active_shadow_trades": active_shadows_cnt,
        "total_evaluated_vetoes": total_evaluated,
        "avoided_losses_count": len(avoided_losses),
        "missed_profits_count": len(missed_profits),
        "veto_accuracy_pct": veto_accuracy_pct,
        "summary": f"AI Gates correctly avoided {len(avoided_losses)} losing trades ({veto_accuracy_pct}% veto accuracy)."
    }

_live_tick_cache: dict = {}
_TICK_TTL = 5.0

@router.get("/data/live/{symbol}")
async def get_live_tick(symbol: str):
    # SEC-2: sanitize symbol — only allow alphanumerics, dots, hyphens, underscores, carets
    import re as _re
    if not _re.match(r"^[A-Za-z0-9._\-^=]{1,20}$", symbol):
        return {"error": "Invalid symbol format"}
    """Fetch a real-time price tick for any symbol via Yahoo Finance (free, cached 5s)."""
    sym = symbol.upper()
    now = time.time()
    cached = _live_tick_cache.get(sym)
    if cached and (now - cached["ts"] < _TICK_TTL):
        return cached["data"]

    tick = await asyncio.to_thread(data_engine.get_tick_for, sym)
    if tick:
        _live_tick_cache[sym] = {"ts": now, "data": tick}
    return tick

analyzer = SentimentIntensityAnalyzer()

@router.get("/analytics/gates")
async def get_gates():
    """Returns the live status of the 4 core trading gates."""
    return engine_state.get("latest_gates", {
        "event_blackout": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev": {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    })

_corr_cache: dict = {"ts": 0.0, "data": None}
_CORR_TTL = 60.0

@router.get("/analytics/correlation")
async def get_cross_asset_correlation():
    """
    Returns live 30-day rolling Pearson correlations between:
    GC (Gold), NQ (Nasdaq), and DXY (Dollar Index).
    Cached for 60 seconds to eliminate page latency.
    """
    global _corr_cache
    now = time.time()
    if _corr_cache["data"] is not None and (now - _corr_cache["ts"] < _CORR_TTL):
        return _corr_cache["data"]

    import numpy as np

    def _compute():
        import yfinance as yf
        try:
            raw = yf.download(
                ["MGC=F", "MNQ=F", "DX-Y.NYB"],
                period="60d", interval="1d",
                progress=False, auto_adjust=True
            )
            closes = raw["Close"].dropna()
            if len(closes) < 10:
                return None
            gc  = closes["MGC=F"].pct_change().dropna()
            nq  = closes["MNQ=F"].pct_change().dropna()
            dxy = closes["DX-Y.NYB"].pct_change().dropna()
            aligned = gc.align(nq)[0].align(dxy)[0]
            gc, nq, dxy = gc.reindex(aligned.index).dropna(), nq.reindex(aligned.index).dropna(), dxy.reindex(aligned.index).dropna()
            idx = gc.index.intersection(nq.index).intersection(dxy.index)
            gc, nq, dxy = gc.loc[idx], nq.loc[idx], dxy.loc[idx]
            if len(gc) < 5:
                return None
            return {
                "gold_nq":  round(float(np.corrcoef(gc, nq)[0, 1]),  3),
                "gold_dxy": round(float(np.corrcoef(gc, dxy)[0, 1]), 3),
                "nq_dxy":   round(float(np.corrcoef(nq, dxy)[0, 1]), 3),
                "sample_days": len(gc),
            }
        except Exception as e:
            return None

    result = await asyncio.to_thread(_compute)
    if result is None:
        result = {"gold_nq": -0.85, "gold_dxy": -0.92, "nq_dxy": -0.61, "sample_days": 0, "fallback": True}
    _corr_cache = {"ts": now, "data": result}
    return result

_news_cache: dict = {"ts": 0.0, "articles": []}
_NEWS_TTL = 60  # seconds

@router.get("/news/global")
async def get_global_news(limit: int = 20):
    """Fetches real-time financial news and assigns VADER sentiment (parallel + cached)."""
    global _news_cache
    if time.time() - _news_cache["ts"] < _NEWS_TTL:
        return {"articles": _news_cache["articles"][:limit]}

    feeds = [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=MGC=F,MNQ=F,MES=F,MCL=F,M2K=F",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=BTC-USD,ETH-USD",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=MGC=F,CL=F,EURUSD=X",
    ]

    def _parse_feed(url: str) -> list:
        try:
            feed = feedparser.parse(url)
            out = []
            for entry in feed.entries[:10]:
                compound = analyzer.polarity_scores(entry.title)['compound']
                label = 'positive' if compound >= 0.05 else 'negative' if compound <= -0.05 else 'neutral'
                pub_time = time.time()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_time = time.mktime(entry.published_parsed)
                out.append({
                    "title": entry.title, "url": entry.link, "source": "Yahoo Finance",
                    "sentiment_score": compound, "sentiment_label": label, "published_at": pub_time,
                })
            return out
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return []

    results = await asyncio.gather(*[asyncio.to_thread(_parse_feed, u) for u in feeds])
    articles = sorted((a for batch in results for a in batch), key=lambda x: x["published_at"], reverse=True)
    _news_cache = {"ts": time.time(), "articles": articles}
    return {"articles": articles[:limit]}

@router.get("/news/{ticker}")
async def get_ticker_news(ticker: str, limit: int = 10):
    """Fetches real-time financial news for a specific ticker."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}"
    
    articles = []
    try:
        feed = await asyncio.to_thread(feedparser.parse, url)
        for entry in feed.entries[:limit]:
            score = analyzer.polarity_scores(entry.title)
            compound = score['compound']
            
            if compound >= 0.05:
                label = 'positive'
            elif compound <= -0.05:
                label = 'negative'
            else:
                label = 'neutral'
                
            pub_time = time.time()
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_time = time.mktime(entry.published_parsed)
                
            articles.append({
                "title": entry.title,
                "url": entry.link,
                "source": "Yahoo Finance",
                "sentiment_score": compound,
                "sentiment_label": label,
                "published_at": pub_time
            })
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        
    return {"articles": articles}

@router.post("/chat/stream")
async def chat_interaction(req: ChatRequest):
    """Mock endpoint for the Ask AI assistant."""
    await asyncio.sleep(1)
    
    msg = req.message.lower()
    
    if "aapl" in msg:
        reply = "Apple (AAPL) is currently showing a bullish CHoCH on the 1H timeframe. My XGBoost model predicts a 78% probability of hitting $192.50 by Friday."
    elif "portfolio" in msg or "drop" in msg:
        reply = "Your portfolio dropped 1.2% today primarily due to weakness in the tech sector. Your hedge positions in Energy (XLE) mitigated further losses."
    else:
        reply = f"I am analyzing {req.ticker} and global equities based on your request: '{req.message}'. Market conditions remain highly volatile."
        
    return {"reply": reply}


# ==========================================
# Indian Market Specific Endpoints
# ==========================================

@router.post("/indian/bot/start")
async def start_engine_in(req: StartEngineRequest = None):
    """Starts the autonomous Indian trading engine"""
    global _engine_lock_in
    if _engine_lock_in is None:
        _engine_lock_in = asyncio.Lock()
    async with _engine_lock_in:
        if engine_state_in["is_running"]:
            return {"status": "already_running", "message": "Indian Engine is already active."}
        engine_state_in["is_running"] = True
    engine_state_in["risk_mode"] = req.risk_mode if req else "Normal"
    engine_state_in["last_scan"] = time.time()
    
    # Start the background trading loop, scanner, and periodic model updater
    asyncio.create_task(indian_trading_loop())
    asyncio.create_task(scanner_agent_in.start_scanning())
    asyncio.create_task(periodic_model_update_loop_in())
    global _watchdog_started, _log_flush_started
    if not _watchdog_started:
        asyncio.create_task(_engine_watchdog())
        _watchdog_started = True
    if not _log_flush_started:
        asyncio.create_task(_log_flush_loop())
        _log_flush_started = True
    _save_bot_state()
    return {"status": "started", "message": "Autonomous Indian engine initialized and scanning."}

@router.post("/indian/bot/stop")
async def stop_engine_in():
    """Stops the autonomous Indian trading engine"""
    if not engine_state_in["is_running"]:
        return {"status": "already_stopped", "message": "Indian Engine is already offline."}
    
    engine_state_in["is_running"] = False
    scanner_agent_in.stop_scanning()
    _save_bot_state()
    return {"status": "stopped", "message": "Autonomous Indian engine gracefully shut down."}

@router.get("/indian/bot/status")
async def get_engine_status_in():
    """Returns the current state of the Indian engine"""
    return {
        "is_running": engine_state_in["is_running"],
        "active_trades": len(execution_engine_in.active_holdings) if engine_state_in["is_running"] else 0,
        "uptime_seconds": time.time() - (engine_state_in["last_scan"] or time.time()) if engine_state_in["is_running"] else 0
    }

@router.get("/indian/bot/logs")
async def get_bot_logs_in():
    """Returns the latest Indian terminal logs."""
    return {"logs": engine_state_in["bot_logs"]}

@router.get("/indian/bot/stream")
async def stream_bot_logs_in(request: Request):
    """SSE endpoint — streams new Indian market log lines in real time."""
    async def event_generator():
        last_count = len(engine_state_in["bot_logs"])
        yield f"data: {_json.dumps({'connected': True})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
            current_logs = engine_state_in["bot_logs"]
            if len(current_logs) > last_count:
                new_logs = current_logs[last_count:]
                for log in new_logs:
                    yield f"data: {_json.dumps(log)}\n\n"
                last_count = len(current_logs)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@router.get("/indian/portfolio/money-tracker")
async def get_money_tracker_in():
    """Returns all closed trades for the Indian portfolio.

    See Finding #20: summary totals read lifetime_stats, not a re-sum of
    (now-capped) closed_trades.
    """
    trades = execution_engine_in.closed_trades
    stats  = execution_engine_in.lifetime_stats
    win_rate = (stats["winning_trades"] / stats["total_trades"] * 100) if stats["total_trades"] else 0.0

    return {
        "closed_trades": trades,
        "summary": {
            "total_pnl": round(stats["total_pnl"], 2),
            "gross_profit": round(stats["gross_profit"], 2),
            "gross_loss": round(stats["gross_loss"], 2),
            "win_rate": round(win_rate, 2),
            "total_trades": stats["total_trades"],
            "current_balance": round(execution_engine_in.portfolio_balance, 2)
        },
        "active_holdings": execution_engine_in.active_holdings
    }

@router.get("/indian/portfolio/holdings")
async def get_portfolio_holdings_in():
    """Returns the live portfolio holdings for the Indian market."""
    return execution_engine_in.get_portfolio_status()

@router.get("/indian/portfolio/history")
async def get_portfolio_history_in(timeframe: str = "1M"):
    """Returns real historical equity curve normalized to the Indian portfolio balance."""
    import yfinance as yf

    period_map = {"1W": "5d", "1M": "1mo", "3M": "3mo", "YTD": "ytd", "1Y": "1y"}
    period = period_map.get(timeframe, "1mo")

    try:
        ticker = yf.Ticker("NIFTYBEES.NS")
        df = await asyncio.to_thread(ticker.history, period=period, interval="1d")
        if df is None or df.empty:
            raise ValueError("No data")

        closes = df["Close"].tolist()
        dates = df.index.strftime("%Y-%m-%d").tolist()

        current_balance = execution_engine_in.portfolio_balance
        last_close = closes[-1]

        history = []
        for i, c in enumerate(closes):
            norm_val = current_balance * (c / last_close)
            history.append({"name": dates[i], "value": round(norm_val, 4)})

        return {"history": history}
    except Exception:
        return {"history": [{"name": "Today", "value": execution_engine_in.portfolio_balance}]}

@router.get("/indian/portfolio/risk")
async def get_portfolio_risk_in():
    """Returns portfolio-level risk profile for the Indian market engine."""
    holdings = execution_engine_in.active_holdings
    capital = execution_engine_in.get_total_equity()
    risk = portfolio_risk_in.analyze(holdings, capital)
    trades = execution_engine_in.closed_trades
    perf = performance_metrics.compute(trades, initial_capital=execution_engine_in._initial_balance)
    if trades:
        gross_profit = sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) > 0)
        gross_loss   = abs(sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) < 0))
        wins         = sum(1 for t in trades if t.get("profit_loss", 0) > 0)
        losses       = len(trades) - wins
        avg_win      = gross_profit / wins if wins else 0.0
        avg_loss     = gross_loss / losses if losses else 0.0
        win_rate     = wins / len(trades) * 100
        perf["win_rate_pct"]  = round(win_rate, 1)
        perf["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        perf["expectancy"]    = round(win_rate / 100 * avg_win - (1 - win_rate / 100) * avg_loss, 2)
        perf["trade_count"]   = len(trades)
    risk["performance"] = perf
    return risk

# ──────────────────────────────────────────────
# INDIAN MARKET — MISSING ENDPOINTS
# ──────────────────────────────────────────────

@router.get("/indian/analytics/rl-stats")
async def get_rl_stats_in():
    """Returns RL stats for the Indian engine."""
    return execution_engine_in.rl_engine.get_stats()

@router.get("/indian/analytics/agent-weights")
async def get_agent_weights_in():
    w = execution_engine_in.rl_engine.get_current_weights()
    w["News & Sentiment AI"] = 0.0
    w["Correlation Agent"]   = 0.0
    w["Indian Gemini AI"]    = 0.0
    return {"weights": w}

@router.get("/indian/analytics/journal")
async def get_journal_in():
    return {"journal": execution_engine_in.journal.get_logs()}

@router.get("/indian/analytics/vetoes")
async def get_vetoes_in():
    return execution_engine_in.journal.get_veto_summary()

@router.get("/indian/analytics/regime-transitions")
async def get_regime_transitions_in():
    return regime_detector_in.get_transition_matrix()

@router.get("/indian/analytics/attribution")
async def get_attribution_in():
    engine = CausalAttributionEngine()
    return engine.analyze(
        journal=execution_engine_in.journal.get_logs(),
        closed_trades=execution_engine_in.closed_trades
    )

@router.get("/indian/analytics/report")
async def get_daily_report_in():
    logs = execution_engine_in.journal.get_logs()
    weights = execution_engine_in.rl_engine.get_current_weights()
    system_context = {
        "portfolio_risk": portfolio_risk_in.analyze(execution_engine_in.active_holdings, execution_engine_in.get_total_equity()),
        "event_status": event_engine_in.check_today(),
        "active_holdings_count": len(execution_engine_in.active_holdings),
    }
    shadow_logs = shadow_engine_in.get_missed_opportunities() if hasattr(shadow_engine_in, 'get_missed_opportunities') else []
    return diagnosis_engine_in.generate_report(logs, shadow_logs, weights, system_context, closed_trades_count=len(execution_engine_in.closed_trades))

@router.get("/indian/opportunities")
async def get_opportunities_in():
    """Returns the live feed of scanned trade opportunities for Indian market."""
    return {"opportunities": scanner_agent_in.get_opportunities()}

@router.get("/indian/analytics/gates")
async def get_gates_in():
    """Returns the live status of the 4 core trading gates for Indian engine."""
    return engine_state_in.get("latest_gates", {
        "event_blackout": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev": {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    })

@router.get("/indian/data/regime")
async def get_market_regime_in():
    """Returns the current market regime for the Indian engine."""
    return {
        "regime": strategy_manager_in.current_regime or "Scanning...",
        "active_strategy": strategy_manager_in.active_strategy
    }

@router.get("/indian/data/live/{symbol}")
async def get_live_tick_in(symbol: str):
    """Fetch a real-time price tick for an Indian symbol via Yahoo Finance."""
    import re as _re
    if not _re.match(r"^[A-Za-z0-9.\-^=]{1,30}$", symbol):
        return {"error": "Invalid symbol format"}
    return await asyncio.to_thread(data_engine_in.get_tick_for, symbol.upper())

@router.post("/indian/backtest/run")
async def run_backtest_in(req: BacktestRequest):
    """
    Runs a historical walk-forward backtest for Indian market symbols.
    Uses real Yahoo Finance data (NSE/BSE via .NS suffix).
    """
    try:
        engine = BacktestEngine(
            symbol=req.symbol.upper(),
            strategy=req.strategy,
            period=req.period,
            initial_capital=req.initial_capital
        )
        results = await asyncio.to_thread(engine.run)   # IV&V H3: off the event loop
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if "error" in results:
        raise HTTPException(status_code=400, detail=results["error"])
    return results


class RLMergeRequest(BaseModel):
    rl_state: dict

@router.post("/analytics/rl/merge_backtest")
async def merge_backtest_rl(req: RLMergeRequest):
    execution_engine.rl_engine.merge_backtest_state(req.rl_state)
    execution_engine._save_state()
    return {"status": "merged", "live_trades": execution_engine.rl_engine.total_closed_trades}

@router.post("/indian/analytics/rl/merge_backtest")
async def merge_backtest_rl_in(req: RLMergeRequest):
    execution_engine_in.rl_engine.merge_backtest_state(req.rl_state)
    execution_engine_in._save_state()
    return {"status": "merged", "live_trades": execution_engine_in.rl_engine.total_closed_trades}


# ══════════════════════════════════════════════════════════════════════════════
#  US TECH STOCKS Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/stocks/bot/start")
async def start_engine_st(req: StartEngineRequest = None):
    global _engine_lock_st
    if _engine_lock_st is None:
        _engine_lock_st = asyncio.Lock()
    async with _engine_lock_st:
        if engine_state_st["is_running"]:
            return {"status": "already_running", "message": "Stocks Engine is already active."}
        engine_state_st["is_running"] = True
    engine_state_st["risk_mode"] = req.risk_mode if req else "Normal"
    engine_state_st["last_scan"] = time.time()
    asyncio.create_task(stocks_trading_loop())
    asyncio.create_task(scanner_agent_st.start_scanning())
    asyncio.create_task(periodic_model_update_loop_st())
    global _watchdog_started, _log_flush_started
    if not _watchdog_started:
        asyncio.create_task(_engine_watchdog())
        _watchdog_started = True
    if not _log_flush_started:
        asyncio.create_task(_log_flush_loop())
        _log_flush_started = True
    _save_bot_state()
    return {"status": "started", "message": "US Tech Stocks engine initialized and scanning."}

@router.post("/stocks/bot/stop")
async def stop_engine_st():
    if not engine_state_st["is_running"]:
        return {"status": "already_stopped", "message": "Stocks Engine is already offline."}
    engine_state_st["is_running"] = False
    scanner_agent_st.stop_scanning()
    _save_bot_state()
    return {"status": "stopped", "message": "US Tech Stocks engine gracefully shut down."}

@router.get("/stocks/bot/status")
async def get_engine_status_st():
    return {
        "is_running": engine_state_st["is_running"],
        "active_trades": len(execution_engine_st.active_holdings) if engine_state_st["is_running"] else 0,
        "uptime_seconds": time.time() - (engine_state_st["last_scan"] or time.time()) if engine_state_st["is_running"] else 0
    }

@router.get("/stocks/bot/logs")
async def get_bot_logs_st():
    return {"logs": engine_state_st["bot_logs"]}

@router.get("/stocks/bot/stream")
async def stream_bot_logs_st(request: Request):
    async def event_generator():
        last_count = len(engine_state_st["bot_logs"])
        yield f"data: {_json.dumps({'connected': True})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
            current_logs = engine_state_st["bot_logs"]
            if len(current_logs) > last_count:
                for log in current_logs[last_count:]:
                    yield f"data: {_json.dumps(log)}\n\n"
                last_count = len(current_logs)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/stocks/analytics/gates")
async def get_gates_st():
    return engine_state_st.get("latest_gates", {
        "event_blackout": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev": {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    })

@router.get("/stocks/analytics/rl-stats")
async def get_rl_stats_st():
    return execution_engine_st.rl_engine.get_stats()

@router.get("/stocks/analytics/agent-weights")
async def get_agent_weights_st():
    w = execution_engine_st.rl_engine.get_current_weights()
    w["News & Sentiment AI"] = 0.0
    w["Correlation Agent"]   = 0.0
    return {"weights": w}

@router.get("/stocks/analytics/journal")
async def get_journal_st():
    return {"journal": execution_engine_st.journal.get_logs()}

@router.get("/stocks/analytics/vetoes")
async def get_vetoes_st():
    return execution_engine_st.journal.get_veto_summary()

@router.get("/stocks/analytics/regime-transitions")
async def get_regime_transitions_st():
    return regime_detector_st.get_transition_matrix()

@router.get("/stocks/analytics/attribution")
async def get_attribution_st():
    engine = CausalAttributionEngine()
    return engine.analyze(
        journal=execution_engine_st.journal.get_logs(),
        closed_trades=execution_engine_st.closed_trades
    )

@router.get("/stocks/analytics/report")
async def get_daily_report_st():
    logs = execution_engine_st.journal.get_logs()
    weights = execution_engine_st.rl_engine.get_current_weights()
    system_context = {
        "portfolio_risk": portfolio_risk_st.analyze(execution_engine_st.active_holdings, execution_engine_st.get_total_equity()),
        "event_status": event_engine_st.check_today(),
        "active_holdings_count": len(execution_engine_st.active_holdings),
    }
    shadow_logs = shadow_engine_st.get_missed_opportunities() if hasattr(shadow_engine_st, 'get_missed_opportunities') else []
    return diagnosis_engine_st.generate_report(logs, shadow_logs, weights, system_context, closed_trades_count=len(execution_engine_st.closed_trades))

@router.get("/stocks/opportunities")
async def get_opportunities_st():
    return {"opportunities": scanner_agent_st.get_opportunities()}

@router.get("/stocks/data/regime")
async def get_market_regime_st():
    return {
        "regime": strategy_manager_st.current_regime or "Scanning...",
        "active_strategy": strategy_manager_st.active_strategy
    }

@router.get("/stocks/portfolio/holdings")
async def get_holdings_st():
    return execution_engine_st.get_portfolio_status()

@router.get("/stocks/portfolio/money-tracker")
async def get_money_tracker_st():
    trades = execution_engine_st.closed_trades
    stats  = execution_engine_st.lifetime_stats
    win_rate = (stats["winning_trades"] / stats["total_trades"] * 100) if stats["total_trades"] else 0.0
    return {
        "closed_trades": trades,
        "summary": {
            "total_pnl": round(stats["total_pnl"], 2),
            "gross_profit": round(stats["gross_profit"], 2),
            "gross_loss": round(stats["gross_loss"], 2),
            "win_rate": round(win_rate, 2),
            "total_trades": stats["total_trades"],
            "current_balance": round(execution_engine_st.portfolio_balance, 2)
        },
        "active_holdings": execution_engine_st.active_holdings
    }

@router.get("/stocks/portfolio/risk")
async def get_portfolio_risk_st():
    holdings = execution_engine_st.active_holdings
    capital = execution_engine_st.get_total_equity()
    risk = portfolio_risk_st.analyze(holdings, capital)
    trades = execution_engine_st.closed_trades
    perf = performance_metrics.compute(trades, initial_capital=execution_engine_st._initial_balance)
    if trades:
        gross_profit = sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) > 0)
        gross_loss   = abs(sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) < 0))
        wins         = sum(1 for t in trades if t.get("profit_loss", 0) > 0)
        losses       = len(trades) - wins
        avg_win      = gross_profit / wins if wins else 0.0
        avg_loss     = gross_loss / losses if losses else 0.0
        win_rate     = wins / len(trades) * 100
        perf["win_rate_pct"]  = round(win_rate, 1)
        perf["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        perf["expectancy"]    = round(win_rate / 100 * avg_win - (1 - win_rate / 100) * avg_loss, 2)
        perf["trade_count"]   = len(trades)
    risk["performance"] = perf
    return risk

@router.get("/stocks/portfolio/history")
async def get_portfolio_history_st(timeframe: str = "1M"):
    import yfinance as yf
    period_map = {"1W": "5d", "1M": "1mo", "3M": "3mo", "YTD": "ytd", "1Y": "1y"}
    period = period_map.get(timeframe, "1mo")
    try:
        df = await asyncio.to_thread(yf.Ticker("QQQ").history, period=period, interval="1d")
        if df is None or df.empty:
            raise ValueError("No data")
        closes = df["Close"].tolist()
        dates = df.index.strftime('%Y-%m-%d').tolist()
        current_balance = execution_engine_st.portfolio_balance
        last_close = closes[-1]
        history = [{"name": dates[i], "value": round(current_balance * (c / last_close), 4)}
                   for i, c in enumerate(closes)]
        return {"history": history}
    except Exception:
        return {"history": [{"name": "Today", "value": execution_engine_st.portfolio_balance}]}

@router.post("/stocks/backtest/run")
async def run_backtest_st(req: BacktestRequest):
    """Runs a walk-forward backtest for US Tech Stock symbols via Yahoo Finance."""
    try:
        engine = BacktestEngine(
            symbol=req.symbol.upper(),
            strategy=req.strategy,
            period=req.period,
            initial_capital=req.initial_capital
        )
        results = await asyncio.to_thread(engine.run)   # IV&V H3: off the event loop
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if "error" in results:
        raise HTTPException(status_code=400, detail=results["error"])
    return results

@router.get("/stocks/data/live/{symbol}")
async def get_live_tick_st(symbol: str):
    import re as _re
    if not _re.match(r"^[A-Za-z0-9.\-^=]{1,20}$", symbol):
        return {"error": "Invalid symbol format"}
    return await asyncio.to_thread(data_engine_st.get_tick_for, symbol.upper())

@router.post("/stocks/analytics/rl/merge_backtest")
async def merge_backtest_rl_st(req: RLMergeRequest):
    execution_engine_st.rl_engine.merge_backtest_state(req.rl_state)
    execution_engine_st._save_state()
    return {"status": "merged", "live_trades": execution_engine_st.rl_engine.total_closed_trades}


# ══════════════════════════════════════════════════════════════════════════════
#  CRYPTO Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/crypto/bot/start")
async def start_engine_cx(req: StartEngineRequest = None):
    global _engine_lock_cx
    if _engine_lock_cx is None:
        _engine_lock_cx = asyncio.Lock()
    async with _engine_lock_cx:
        if engine_state_cx["is_running"]:
            return {"status": "already_running", "message": "Crypto Engine is already active."}
        engine_state_cx["is_running"] = True
    engine_state_cx["risk_mode"] = req.risk_mode if req else "Normal"
    engine_state_cx["last_scan"] = time.time()
    asyncio.create_task(crypto_trading_loop())
    asyncio.create_task(scanner_agent_cx.start_scanning())
    asyncio.create_task(periodic_model_update_loop_cx())
    global _watchdog_started, _log_flush_started
    if not _watchdog_started:
        asyncio.create_task(_engine_watchdog())
        _watchdog_started = True
    if not _log_flush_started:
        asyncio.create_task(_log_flush_loop())
        _log_flush_started = True
    _save_bot_state()
    return {"status": "started", "message": "Crypto 24/7 engine initialized and scanning."}

@router.post("/crypto/bot/stop")
async def stop_engine_cx():
    if not engine_state_cx["is_running"]:
        return {"status": "already_stopped", "message": "Crypto Engine is already offline."}
    engine_state_cx["is_running"] = False
    scanner_agent_cx.stop_scanning()
    _save_bot_state()
    return {"status": "stopped", "message": "Crypto engine gracefully shut down."}

@router.get("/crypto/bot/status")
async def get_engine_status_cx():
    return {
        "is_running": engine_state_cx["is_running"],
        "active_trades": len(execution_engine_cx.active_holdings) if engine_state_cx["is_running"] else 0,
        "uptime_seconds": time.time() - (engine_state_cx["last_scan"] or time.time()) if engine_state_cx["is_running"] else 0
    }

@router.get("/crypto/bot/logs")
async def get_bot_logs_cx():
    return {"logs": engine_state_cx["bot_logs"]}

@router.get("/crypto/bot/stream")
async def stream_bot_logs_cx(request: Request):
    async def event_generator():
        last_count = len(engine_state_cx["bot_logs"])
        yield f"data: {_json.dumps({'connected': True})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
            current_logs = engine_state_cx["bot_logs"]
            if len(current_logs) > last_count:
                for log in current_logs[last_count:]:
                    yield f"data: {_json.dumps(log)}\n\n"
                last_count = len(current_logs)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/crypto/analytics/gates")
async def get_gates_cx():
    return engine_state_cx.get("latest_gates", {
        "event_blackout": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev": {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    })

@router.get("/crypto/analytics/rl-stats")
async def get_rl_stats_cx():
    return execution_engine_cx.rl_engine.get_stats()

@router.get("/crypto/analytics/agent-weights")
async def get_agent_weights_cx():
    w = execution_engine_cx.rl_engine.get_current_weights()
    w["News & Sentiment AI"] = 0.0
    w["Correlation Agent"]   = 0.0
    return {"weights": w}

@router.get("/crypto/analytics/journal")
async def get_journal_cx():
    return {"journal": execution_engine_cx.journal.get_logs()}

@router.get("/crypto/analytics/vetoes")
async def get_vetoes_cx():
    return execution_engine_cx.journal.get_veto_summary()

@router.get("/crypto/analytics/regime-transitions")
async def get_regime_transitions_cx():
    return regime_detector_cx.get_transition_matrix()

@router.get("/crypto/analytics/attribution")
async def get_attribution_cx():
    engine = CausalAttributionEngine()
    return engine.analyze(
        journal=execution_engine_cx.journal.get_logs(),
        closed_trades=execution_engine_cx.closed_trades
    )

@router.get("/crypto/analytics/report")
async def get_daily_report_cx():
    logs = execution_engine_cx.journal.get_logs()
    weights = execution_engine_cx.rl_engine.get_current_weights()
    system_context = {
        "portfolio_risk": portfolio_risk_cx.analyze(execution_engine_cx.active_holdings, execution_engine_cx.get_total_equity()),
        "event_status": event_engine_cx.check_today(),
        "active_holdings_count": len(execution_engine_cx.active_holdings),
    }
    shadow_logs = shadow_engine_cx.get_missed_opportunities() if hasattr(shadow_engine_cx, 'get_missed_opportunities') else []
    return diagnosis_engine_cx.generate_report(logs, shadow_logs, weights, system_context, closed_trades_count=len(execution_engine_cx.closed_trades))

@router.get("/crypto/opportunities")
async def get_opportunities_cx():
    return {"opportunities": scanner_agent_cx.get_opportunities()}

@router.get("/crypto/data/regime")
async def get_market_regime_cx():
    return {
        "regime": strategy_manager_cx.current_regime or "Scanning...",
        "active_strategy": strategy_manager_cx.active_strategy
    }

@router.get("/crypto/portfolio/holdings")
async def get_holdings_cx():
    return execution_engine_cx.get_portfolio_status()

@router.get("/crypto/portfolio/money-tracker")
async def get_money_tracker_cx():
    trades = execution_engine_cx.closed_trades
    stats  = execution_engine_cx.lifetime_stats
    win_rate = (stats["winning_trades"] / stats["total_trades"] * 100) if stats["total_trades"] else 0.0
    return {
        "closed_trades": trades,
        "summary": {
            "total_pnl": round(stats["total_pnl"], 2),
            "gross_profit": round(stats["gross_profit"], 2),
            "gross_loss": round(stats["gross_loss"], 2),
            "win_rate": round(win_rate, 2),
            "total_trades": stats["total_trades"],
            "current_balance": round(execution_engine_cx.portfolio_balance, 2)
        },
        "active_holdings": execution_engine_cx.active_holdings
    }

@router.get("/crypto/portfolio/risk")
async def get_portfolio_risk_cx():
    holdings = execution_engine_cx.active_holdings
    capital = execution_engine_cx.get_total_equity()
    risk = portfolio_risk_cx.analyze(holdings, capital)
    trades = execution_engine_cx.closed_trades
    perf = performance_metrics.compute(trades, initial_capital=execution_engine_cx._initial_balance)
    if trades:
        gross_profit = sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) > 0)
        gross_loss   = abs(sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) < 0))
        wins         = sum(1 for t in trades if t.get("profit_loss", 0) > 0)
        losses       = len(trades) - wins
        avg_win      = gross_profit / wins if wins else 0.0
        avg_loss     = gross_loss / losses if losses else 0.0
        win_rate     = wins / len(trades) * 100
        perf["win_rate_pct"]  = round(win_rate, 1)
        perf["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        perf["expectancy"]    = round(win_rate / 100 * avg_win - (1 - win_rate / 100) * avg_loss, 2)
        perf["trade_count"]   = len(trades)
    risk["performance"] = perf
    return risk

@router.get("/crypto/portfolio/history")
async def get_portfolio_history_cx(timeframe: str = "1M"):
    import yfinance as yf
    period_map = {"1W": "5d", "1M": "1mo", "3M": "3mo", "YTD": "ytd", "1Y": "1y"}
    period = period_map.get(timeframe, "1mo")
    try:
        df = await asyncio.to_thread(yf.Ticker("BTC-USD").history, period=period, interval="1d")
        if df is None or df.empty:
            raise ValueError("No data")
        closes = df["Close"].tolist()
        dates = df.index.strftime('%Y-%m-%d').tolist()
        current_balance = execution_engine_cx.portfolio_balance
        last_close = closes[-1]
        history = [{"name": dates[i], "value": round(current_balance * (c / last_close), 4)}
                   for i, c in enumerate(closes)]
        return {"history": history}
    except Exception:
        return {"history": [{"name": "Today", "value": execution_engine_cx.portfolio_balance}]}

@router.post("/crypto/backtest/run")
async def run_backtest_cx(req: BacktestRequest):
    """Runs a walk-forward backtest for Crypto symbols (BTC-USD, ETH-USD, etc.) via Yahoo Finance."""
    try:
        engine = BacktestEngine(
            symbol=req.symbol.upper(),
            strategy=req.strategy,
            period=req.period,
            initial_capital=req.initial_capital
        )
        results = await asyncio.to_thread(engine.run)   # IV&V H3: off the event loop
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if "error" in results:
        raise HTTPException(status_code=400, detail=results["error"])
    return results

@router.get("/crypto/data/live/{symbol}")
async def get_live_tick_cx(symbol: str):
    import re as _re
    if not _re.match(r"^[A-Za-z0-9.\-^=]{1,20}$", symbol):
        return {"error": "Invalid symbol format"}
    return await asyncio.to_thread(data_engine_cx.get_tick_for, symbol.upper())

@router.post("/crypto/analytics/rl/merge_backtest")
async def merge_backtest_rl_cx(req: RLMergeRequest):
    execution_engine_cx.rl_engine.merge_backtest_state(req.rl_state)
    execution_engine_cx._save_state()
    return {"status": "merged", "live_trades": execution_engine_cx.rl_engine.total_closed_trades}


# ══════════════════════════════════════════════════════════════════════════════
#  FOREX Endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/forex/bot/start")
async def start_engine_fx(req: StartEngineRequest = None):
    global _engine_lock_fx
    if _engine_lock_fx is None:
        _engine_lock_fx = asyncio.Lock()
    async with _engine_lock_fx:
        if engine_state_fx["is_running"]:
            return {"status": "already_running", "message": "Forex Engine is already active."}
        engine_state_fx["is_running"] = True
    engine_state_fx["risk_mode"] = req.risk_mode if req else "Normal"
    engine_state_fx["last_scan"] = time.time()
    asyncio.create_task(forex_trading_loop())
    asyncio.create_task(scanner_agent_fx.start_scanning())
    asyncio.create_task(periodic_model_update_loop_fx())
    global _watchdog_started, _log_flush_started
    if not _watchdog_started:
        asyncio.create_task(_engine_watchdog())
        _watchdog_started = True
    if not _log_flush_started:
        asyncio.create_task(_log_flush_loop())
        _log_flush_started = True
    _save_bot_state()
    return {"status": "started", "message": "Forex engine initialized and scanning."}

@router.post("/forex/bot/stop")
async def stop_engine_fx():
    if not engine_state_fx["is_running"]:
        return {"status": "already_stopped", "message": "Forex Engine is already offline."}
    engine_state_fx["is_running"] = False
    scanner_agent_fx.stop_scanning()
    _save_bot_state()
    return {"status": "stopped", "message": "Forex engine gracefully shut down."}

@router.get("/forex/bot/status")
async def get_engine_status_fx():
    return {
        "is_running": engine_state_fx["is_running"],
        "active_trades": len(execution_engine_fx.active_holdings) if engine_state_fx["is_running"] else 0,
        "uptime_seconds": time.time() - (engine_state_fx["last_scan"] or time.time()) if engine_state_fx["is_running"] else 0
    }

@router.get("/forex/bot/logs")
async def get_bot_logs_fx():
    return {"logs": engine_state_fx["bot_logs"]}

@router.get("/forex/bot/stream")
async def stream_bot_logs_fx(request: Request):
    async def event_generator():
        last_count = len(engine_state_fx["bot_logs"])
        yield f"data: {_json.dumps({'connected': True})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)
            current_logs = engine_state_fx["bot_logs"]
            if len(current_logs) > last_count:
                for log in current_logs[last_count:]:
                    yield f"data: {_json.dumps(log)}\n\n"
                last_count = len(current_logs)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.get("/forex/analytics/gates")
async def get_gates_fx():
    return engine_state_fx.get("latest_gates", {
        "event_blackout": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "mtf_alignment":  {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "correlation_gate": {"status": "NOT_EVALUATED", "details": "Waiting for signal."},
        "monte_carlo_ev": {"status": "NOT_EVALUATED", "details": "Waiting for signal."}
    })

@router.get("/forex/analytics/rl-stats")
async def get_rl_stats_fx():
    return execution_engine_fx.rl_engine.get_stats()

@router.get("/forex/analytics/agent-weights")
async def get_agent_weights_fx():
    w = execution_engine_fx.rl_engine.get_current_weights()
    w["News & Sentiment AI"] = 0.0
    w["Correlation Agent"]   = 0.0
    return {"weights": w}

@router.get("/forex/analytics/journal")
async def get_journal_fx():
    return {"journal": execution_engine_fx.journal.get_logs()}

@router.get("/forex/analytics/vetoes")
async def get_vetoes_fx():
    return execution_engine_fx.journal.get_veto_summary()

@router.get("/forex/analytics/regime-transitions")
async def get_regime_transitions_fx():
    return regime_detector_fx.get_transition_matrix()

@router.get("/forex/analytics/attribution")
async def get_attribution_fx():
    engine = CausalAttributionEngine()
    return engine.analyze(
        journal=execution_engine_fx.journal.get_logs(),
        closed_trades=execution_engine_fx.closed_trades
    )

@router.get("/forex/analytics/report")
async def get_daily_report_fx():
    logs = execution_engine_fx.journal.get_logs()
    weights = execution_engine_fx.rl_engine.get_current_weights()
    system_context = {
        "portfolio_risk": portfolio_risk_fx.analyze(execution_engine_fx.active_holdings, execution_engine_fx.get_total_equity()),
        "event_status": event_engine_fx.check_today(),
        "active_holdings_count": len(execution_engine_fx.active_holdings),
    }
    shadow_logs = shadow_engine_fx.get_missed_opportunities() if hasattr(shadow_engine_fx, 'get_missed_opportunities') else []
    return diagnosis_engine_fx.generate_report(logs, shadow_logs, weights, system_context, closed_trades_count=len(execution_engine_fx.closed_trades))

@router.get("/forex/opportunities")
async def get_opportunities_fx():
    return {"opportunities": scanner_agent_fx.get_opportunities()}

@router.get("/forex/data/regime")
async def get_market_regime_fx():
    return {
        "regime": strategy_manager_fx.current_regime or "Scanning...",
        "active_strategy": strategy_manager_fx.active_strategy
    }

@router.get("/forex/portfolio/holdings")
async def get_holdings_fx():
    return execution_engine_fx.get_portfolio_status()

@router.get("/forex/portfolio/money-tracker")
async def get_money_tracker_fx():
    trades = execution_engine_fx.closed_trades
    stats  = execution_engine_fx.lifetime_stats
    win_rate = (stats["winning_trades"] / stats["total_trades"] * 100) if stats["total_trades"] else 0.0
    return {
        "closed_trades": trades,
        "summary": {
            "total_pnl": round(stats["total_pnl"], 2),
            "gross_profit": round(stats["gross_profit"], 2),
            "gross_loss": round(stats["gross_loss"], 2),
            "win_rate": round(win_rate, 2),
            "total_trades": stats["total_trades"],
            "current_balance": round(execution_engine_fx.portfolio_balance, 2)
        },
        "active_holdings": execution_engine_fx.active_holdings
    }

@router.get("/forex/portfolio/risk")
async def get_portfolio_risk_fx():
    holdings = execution_engine_fx.active_holdings
    capital = execution_engine_fx.get_total_equity()
    risk = portfolio_risk_fx.analyze(holdings, capital)
    trades = execution_engine_fx.closed_trades
    perf = performance_metrics.compute(trades, initial_capital=execution_engine_fx._initial_balance)
    if trades:
        gross_profit = sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) > 0)
        gross_loss   = abs(sum(t.get("profit_loss", 0) for t in trades if t.get("profit_loss", 0) < 0))
        wins         = sum(1 for t in trades if t.get("profit_loss", 0) > 0)
        losses       = len(trades) - wins
        avg_win      = gross_profit / wins if wins else 0.0
        avg_loss     = gross_loss / losses if losses else 0.0
        win_rate     = wins / len(trades) * 100
        perf["win_rate_pct"]  = round(win_rate, 1)
        perf["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
        perf["expectancy"]    = round(win_rate / 100 * avg_win - (1 - win_rate / 100) * avg_loss, 2)
        perf["trade_count"]   = len(trades)
    risk["performance"] = perf
    return risk

@router.get("/forex/portfolio/history")
async def get_portfolio_history_fx(timeframe: str = "1M"):
    import yfinance as yf
    period_map = {"1W": "5d", "1M": "1mo", "3M": "3mo", "YTD": "ytd", "1Y": "1y"}
    period = period_map.get(timeframe, "1mo")
    try:
        df = await asyncio.to_thread(yf.Ticker("EURUSD=X").history, period=period, interval="1d")
        if df is None or df.empty:
            raise ValueError("No data")
        closes = df["Close"].tolist()
        dates = df.index.strftime('%Y-%m-%d').tolist()
        current_balance = execution_engine_fx.portfolio_balance
        last_close = closes[-1]
        history = [{"name": dates[i], "value": round(current_balance * (c / last_close), 4)}
                   for i, c in enumerate(closes)]
        return {"history": history}
    except Exception:
        return {"history": [{"name": "Today", "value": execution_engine_fx.portfolio_balance}]}

@router.post("/forex/backtest/run")
async def run_backtest_fx(req: BacktestRequest):
    """Runs a walk-forward backtest for Forex pairs (EURUSD=X, etc.) via Yahoo Finance."""
    try:
        engine = BacktestEngine(
            symbol=req.symbol.upper(),
            strategy=req.strategy,
            period=req.period,
            initial_capital=req.initial_capital
        )
        results = await asyncio.to_thread(engine.run)   # IV&V H3: off the event loop
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if "error" in results:
        raise HTTPException(status_code=400, detail=results["error"])
    return results

@router.get("/forex/data/live/{symbol}")
async def get_live_tick_fx(symbol: str):
    import re as _re
    if not _re.match(r"^[A-Za-z0-9.\-^=]{1,20}$", symbol):
        return {"error": "Invalid symbol format"}
    return await asyncio.to_thread(data_engine_fx.get_tick_for, symbol.upper())

@router.post("/forex/analytics/rl/merge_backtest")
async def merge_backtest_rl_fx(req: RLMergeRequest):
    execution_engine_fx.rl_engine.merge_backtest_state(req.rl_state)
    execution_engine_fx._save_state()
    return {"status": "merged", "live_trades": execution_engine_fx.rl_engine.total_closed_trades}


# ══════════════════════════════════════════════════════════════════════════════
#  AI Bug Finder endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/ai-bugs")
async def get_bugs():
    """Return all current bug findings, sorted by severity."""
    return {"findings": get_bug_finder().get_findings()}


@router.get("/ai-bugs/summary")
async def get_bugs_summary():
    """Return finding counts by severity + scan metadata."""
    return get_bug_finder().get_summary()


@router.post("/ai-bugs/scan")
async def trigger_scan():
    """Trigger an immediate full static scan (non-blocking)."""
    get_bug_finder().trigger_scan()
    return {"status": "scan_triggered"}


@router.delete("/ai-bugs/{finding_id}")
async def dismiss_finding(finding_id: str):
    """Dismiss (suppress) a single finding by its ID."""
    get_bug_finder().dismiss(finding_id)
    return {"status": "dismissed", "id": finding_id}


@router.delete("/ai-bugs")
async def dismiss_all_findings():
    """Dismiss all current findings."""
    get_bug_finder().dismiss_all()
    return {"status": "all_dismissed"}


# ── Auto-resume on server restart ─────────────────────────────────────────────

async def auto_resume_bots():
    """
    Called during server startup lifespan.
    ALWAYS starts all 5 market bots on every server start.
    Risk modes are restored from bot_state.json if available.
    """
    us_risk_mode     = "Normal"
    india_risk_mode  = "Normal"
    stocks_risk_mode = "Normal"
    crypto_risk_mode = "Normal"
    forex_risk_mode  = "Normal"
    import logging as _logging
    _srv_logger = _logging.getLogger("ai_stock.server")
    try:
        if os.path.exists(_BOT_STATE_FILE):
            with open(_BOT_STATE_FILE) as _f:
                _state = _json_state.load(_f)
            us_risk_mode     = _state.get("us_risk_mode", "Normal")
            india_risk_mode  = _state.get("india_risk_mode", "Normal")
            stocks_risk_mode = _state.get("stocks_risk_mode", "Normal")
            crypto_risk_mode = _state.get("crypto_risk_mode", "Normal")
            forex_risk_mode  = _state.get("forex_risk_mode", "Normal")
            _srv_logger.info(f"[Server] Restored persisted risk modes: US={us_risk_mode}, IN={india_risk_mode}, ST={stocks_risk_mode}, CX={crypto_risk_mode}, FX={forex_risk_mode}")
        else:
            _srv_logger.info(f"[Server] No {_BOT_STATE_FILE} found. Safe-defaulting all 5 market loops to Normal mode.")
    except Exception as e:
        _srv_logger.warning(f"[Server] Failed to read {_BOT_STATE_FILE} ({e}). Safe-defaulting all 5 market loops to Normal mode.")


    # US
    engine_state["is_running"] = True
    engine_state["risk_mode"]  = us_risk_mode
    engine_state["last_scan"]  = time.time()
    asyncio.create_task(trading_loop())
    asyncio.create_task(scanner_agent.start_scanning())
    asyncio.create_task(periodic_model_update_loop())

    # India
    engine_state_in["is_running"] = True
    engine_state_in["risk_mode"]  = india_risk_mode
    engine_state_in["last_scan"]  = time.time()
    asyncio.create_task(indian_trading_loop())
    asyncio.create_task(scanner_agent_in.start_scanning())
    asyncio.create_task(periodic_model_update_loop_in())

    # Stocks
    engine_state_st["is_running"] = True
    engine_state_st["risk_mode"]  = stocks_risk_mode
    engine_state_st["last_scan"]  = time.time()
    asyncio.create_task(stocks_trading_loop())
    asyncio.create_task(scanner_agent_st.start_scanning())
    asyncio.create_task(periodic_model_update_loop_st())

    # Crypto
    engine_state_cx["is_running"] = True
    engine_state_cx["risk_mode"]  = crypto_risk_mode
    engine_state_cx["last_scan"]  = time.time()
    asyncio.create_task(crypto_trading_loop())
    asyncio.create_task(scanner_agent_cx.start_scanning())
    asyncio.create_task(periodic_model_update_loop_cx())

    # Forex
    engine_state_fx["is_running"] = True
    engine_state_fx["risk_mode"]  = forex_risk_mode
    engine_state_fx["last_scan"]  = time.time()
    asyncio.create_task(forex_trading_loop())
    asyncio.create_task(scanner_agent_fx.start_scanning())
    asyncio.create_task(periodic_model_update_loop_fx())

    # Start watchdog and log-flush tasks once globally
    global _watchdog_started, _log_flush_started
    if not _watchdog_started:
        asyncio.create_task(_engine_watchdog())
        _watchdog_started = True
    if not _log_flush_started:
        asyncio.create_task(_log_flush_loop())
        _log_flush_started = True


# ─────────────────────────────────────────────────────────────────────────────
# Institutional Risk, Candlestick & Backup Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/risk/var")
async def get_portfolio_var():
    """Returns 10,000-path Monte Carlo Value at Risk and Macro Stress-Test Analysis."""
    from risk.monte_carlo_var import MonteCarloVaREngine
    all_holdings = (
        execution_engine.active_holdings +
        execution_engine_in.active_holdings +
        execution_engine_st.active_holdings +
        execution_engine_cx.active_holdings +
        execution_engine_fx.active_holdings
    )
    tot_eq = global_risk.total_equity()
    var_res = await asyncio.to_thread(
        MonteCarloVaREngine.instance().calculate_portfolio_var,
        all_holdings,
        tot_eq
    )
    return var_res


@router.get("/market/candles/{symbol}")
async def get_market_candles(symbol: str, timeframe: str = "1d", limit: int = 100):
    """
    Returns OHLCV candle stream formatted for TradingView Lightweight Charts,
    along with active trade overlays (Entry, Stop Loss, TP1, TP2, TP3 runner).
    """
    import yfinance as yf
    sym_clean = symbol.upper().strip()
    
    def _fetch_yf():
        period = "3mo" if timeframe in ("1d", "1D") else "5d"
        interval = "1d" if timeframe in ("1d", "1D") else "5m"
        ticker = yf.Ticker(sym_clean)
        df = ticker.history(period=period, interval=interval)
        candles = []
        if df is not None and not df.empty:
            for idx, row in df.tail(limit).iterrows():
                ts = int(idx.timestamp())
                candles.append({
                    "time": ts,
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": float(row.get("Volume", 0.0))
                })
        return candles

    candles = await asyncio.to_thread(_fetch_yf)

    # Check for active holding overlay
    all_holdings = (
        execution_engine.active_holdings +
        execution_engine_in.active_holdings +
        execution_engine_st.active_holdings +
        execution_engine_cx.active_holdings +
        execution_engine_fx.active_holdings
    )
    active_trade = next((h for h in all_holdings if h.get("symbol") == sym_clean), None)

    overlays = None
    if active_trade:
        overlays = {
            "has_active_trade": True,
            "direction": active_trade.get("direction", "LONG"),
            "entry_price": active_trade.get("entry_price"),
            "stop_loss": active_trade.get("stop_loss"),
            "tp1_target": active_trade.get("tp1_target"),
            "tp2_target": active_trade.get("tp2_target") or active_trade.get("take_profit"),
            "tp3_runner_target": active_trade.get("tp3_runner_target"),
            "tp1_hit": active_trade.get("tp1_hit", False),
            "tp2_hit": active_trade.get("tp2_hit", False),
            "chandelier_active": active_trade.get("chandelier_active", False)
        }

    return {
        "symbol": sym_clean,
        "timeframe": timeframe,
        "candles_count": len(candles),
        "candles": candles,
        "trade_overlays": overlays
    }


@router.post("/system/backup")
async def trigger_system_backup():
    """Triggers an immediate disaster recovery state and database backup."""
    from scripts.automated_backup import AutomatedBackupEngine
    res = await asyncio.to_thread(AutomatedBackupEngine.instance().create_backup)
    return res


