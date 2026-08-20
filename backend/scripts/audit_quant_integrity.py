import asyncio
import sys
import os
import time
import math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 75)
print("DEEP QUANT MATHEMATICAL & ALGORITHMIC INTEGRITY AUDIT")
print("=" * 75)

# [1/7] ADAPTIVE STOPS
print("\n[1/7] Auditing AdaptiveStopLoss Asymmetric 2-Stage Calculations...")
from risk.adaptive_stops import AdaptiveStopLoss, REGIME_STOP_CONFIG

stops = AdaptiveStopLoss()
p_entry = 250.0
vol = 0.015

res_buy = stops.calculate(current_price=p_entry, signal="BUY", volatility_proxy=vol, regime="Trending Bull")
exp_dist = p_entry * (vol * 2.5) # 9.375
exp_sl = p_entry - exp_dist      # 240.625
exp_tp1 = p_entry + exp_dist * 1.5 # 264.0625
exp_tp2 = p_entry + exp_dist * 3.5 # 282.8125

assert abs(res_buy["stop_loss"] - exp_sl) < 1e-3
assert abs(res_buy["tp1_target"] - exp_tp1) < 1e-3
assert abs(res_buy["tp2_target"] - exp_tp2) < 1e-3

res_short = stops.calculate(current_price=p_entry, signal="SELL", volatility_proxy=vol, regime="Trending Bear")
assert abs(res_short["stop_loss"] - (p_entry + exp_dist)) < 1e-3
assert abs(res_short["tp1_target"] - (p_entry - exp_dist * 1.5)) < 1e-3
assert abs(res_short["tp2_target"] - (p_entry - exp_dist * 3.5)) < 1e-3

trail_buy = stops.update_trailing(current_price=265.0, signal="BUY", current_stop=240.625, best_price=265.0, volatility_proxy=vol, entry_price=p_entry, tp1_hit=True)
assert trail_buy["new_stop"] >= p_entry

trail_short = stops.update_trailing(current_price=235.0, signal="SELL", current_stop=259.375, best_price=235.0, volatility_proxy=vol, entry_price=p_entry, tp1_hit=True)
assert trail_short["new_stop"] <= p_entry
print("  [PASS] AdaptiveStopLoss Math: ALL FORMULAS 100% ACCURATE")

# [2/7] SMART EXECUTION
print("\n[2/7] Auditing SmartExecutionEngine Partial Scale-Out Accounting...")
from execution.smart_execution import SmartExecutionEngine

async def audit_execution():
    eng = SmartExecutionEngine(state_filename="audit_state_test.json", initial_balance=50000.0)
    await asyncio.sleep(0.1) # allow async DB init to settle
    initial_bal = eng.portfolio_balance

    h_long = {
        "symbol": "NVDA",
        "shares": 100.0,
        "entry_price": 120.0,
        "current_price": 130.0,
        "value": 12000.0,
        "stop_loss": 115.0,
        "tp1_target": 127.5,
        "tp2_target": 135.0,
        "tp1_hit": False,
        "direction": "LONG",
    }
    eng.active_holdings = [h_long]

    ok, msg = await eng.partial_close(h_long, price=127.5, fraction=0.5, reason="TP1_1.5R")
    assert ok is True
    assert h_long["shares"] == 50.0
    assert h_long["tp1_hit"] is True
    assert h_long["stop_loss"] >= 120.0
    credited_long = eng.portfolio_balance - initial_bal
    # 50 shares * 127.5 - slippage - commission ~ 6360 to 6375
    assert 6350.0 <= credited_long <= 6380.0, f"Long credited balance unexpected: {credited_long}"

    eng_short = SmartExecutionEngine(state_filename="audit_state_test_s.json", initial_balance=50000.0)
    await asyncio.sleep(0.1)
    initial_bal_s = eng_short.portfolio_balance

    h_short = {
        "symbol": "MNQ=F",
        "shares": 10.0,
        "entry_price": 2000.0,
        "current_price": 1950.0,
        "value": 20000.0,
        "margin_reserved": 3000.0,
        "stop_loss": 2050.0,
        "tp1_target": 1925.0,
        "tp2_target": 1850.0,
        "tp1_hit": False,
        "direction": "SHORT",
    }
    eng_short.active_holdings = [h_short]

    ok_s, msg_s = await eng_short.partial_close(h_short, price=1925.0, fraction=0.5, reason="TP1_1.5R")
    assert ok_s is True
    assert h_short["shares"] == 5.0
    assert h_short["margin_reserved"] == 1500.0
    assert h_short["stop_loss"] <= 2000.0
    credited_short = eng_short.portfolio_balance - initial_bal_s
    # Margin released ($1500) + gain on 5 contracts ($375) - slippage - comm ~ 1860 to 1880
    assert 1850.0 <= credited_short <= 1890.0, f"Short credited balance unexpected: {credited_short}"


asyncio.run(audit_execution())
print("  [PASS] SmartExecutionEngine Balance & Margin Accounting: 100% ACCURATE")

# [3/7] HTF CONFLUENCE
print("\n[3/7] Auditing TimeframeConfluenceEngine Strict HTF Gate...")
from data.timeframe_confluence import TimeframeConfluenceEngine
tc = TimeframeConfluenceEngine()

conf_bear = {"daily_trend": "BEAR", "hourly_trend": "BULL", "alignment": "MODERATE", "confidence_multiplier": 1.0, "detail": "Daily BEAR"}
res_bear = tc.apply_to_decision({"signal": "BUY", "confidence": 0.88}, conf_bear, "BUY")
assert res_bear["signal"] == "WAIT"

conf_bull = {"daily_trend": "BULL", "hourly_trend": "BEAR", "alignment": "MODERATE", "confidence_multiplier": 1.0, "detail": "Daily BULL"}
res_bull = tc.apply_to_decision({"signal": "SELL", "confidence": 0.85}, conf_bull, "SELL")
assert res_bull["signal"] == "WAIT"
print("  [PASS] TimeframeConfluenceEngine Directional Vetoes: 100% ACCURATE")

# [4/7] REGIME DIRECTIONAL GATE
print("\n[4/7] Auditing MasterAgent Directional Regime Rules...")
from agents.master import MasterAgent
ma = MasterAgent()

d_bear = {"regime": "Trending Bear", "trading_mode": "Normal", "agent_weights": {a.name: 1.0 for a in ma.committee}}
for c in ma.committee:
    c.evaluate = lambda s, d: {"signal": "BUY", "confidence": 0.95, "reason": "Buy"}
eval_bear = ma.evaluate("BTC-USD", d_bear)
assert eval_bear["signal"] == "WAIT"

d_bull = {"regime": "Trending Bull", "trading_mode": "Normal", "agent_weights": {a.name: 1.0 for a in ma.committee}}
for c in ma.committee:
    c.evaluate = lambda s, d: {"signal": "SELL", "confidence": 0.95, "reason": "Sell"}
eval_bull = ma.evaluate("BTC-USD", d_bull)
assert eval_bull["signal"] == "WAIT"
print("  [PASS] MasterAgent Directional Regime Rules: 100% ACCURATE")

# [5/7] PERFORMANCE
print("\n[5/7] Auditing Performance Metrics & Expectancy Arithmetic...")
from analytics.performance_metrics import get_comprehensive_performance_breakdown

now = 1724000000.0
sample_trades = [
    {"symbol": "BTC-USD", "profit_loss": 30.0, "time": now - 86400 * 5},
    {"symbol": "BTC-USD", "profit_loss": 30.0, "time": now - 86400 * 4},
    {"symbol": "BTC-USD", "profit_loss": -10.0, "time": now - 86400 * 3},
    {"symbol": "BTC-USD", "profit_loss": 30.0, "time": now - 86400 * 3},
    {"symbol": "BTC-USD", "profit_loss": -10.0, "time": now - 86400 * 2},
    {"symbol": "BTC-USD", "profit_loss": 30.0, "time": now - 86400 * 2},
    {"symbol": "BTC-USD", "profit_loss": 30.0, "time": now - 86400 * 1},
    {"symbol": "BTC-USD", "profit_loss": -10.0, "time": now - 86400 * 1},
    {"symbol": "BTC-USD", "profit_loss": -10.0, "time": now},
    {"symbol": "BTC-USD", "profit_loss": 30.0, "time": now},
]

perf_out = get_comprehensive_performance_breakdown(sample_trades, initial_capital=10000.0)
ov = perf_out["overall"]

assert ov["total_trades"] == 10
assert abs(ov["win_rate_pct"] - 60.0) < 1e-2
assert abs(ov["gross_profit"] - 180.0) < 1e-2
assert abs(ov["gross_loss"] - 40.0) < 1e-2
assert abs(ov["net_pnl"] - 140.0) < 1e-2
assert abs(ov["profit_factor"] - 4.5) < 1e-2
assert abs(ov["expectancy_per_trade"] - 14.0) < 1e-2
assert ov["realized_risk_reward"] == 3.0
print("  [PASS] Mathematical Expectancy E[R] & Risk Ratios: 100% ACCURATE")

# [6/7] GLOBAL RISK
print("\n[6/7] Auditing GlobalRiskAggregator Circuit Breakers...")
from risk.global_risk import GlobalRiskAggregator, GLOBAL_DAILY_HALT_PCT, GLOBAL_WEEKLY_HALT_PCT

gra = GlobalRiskAggregator(state_file=None)
assert GLOBAL_DAILY_HALT_PCT == 3.5
assert GLOBAL_WEEKLY_HALT_PCT == 7.0

e1 = SmartExecutionEngine(state_filename="audit_state_risk_test.json", initial_balance=10000.0)
e1.portfolio_balance = 10000.0

e1.active_holdings = [{"symbol": "AAPL", "shares": 10, "entry_price": 150.0, "current_price": 155.0, "direction": "LONG"}]
gra.register_engines([e1])

res_kill = asyncio.run(gra.trigger_emergency_kill_switch(reason="Deep Audit Test"))
assert res_kill["status"] == "EMERGENCY_HALTED"
assert gra.global_halt is True
assert len(e1.active_holdings) == 0

res_resume = gra.resume_trading(reason="Deep Audit Resume")
assert gra.global_halt is False
print("  [PASS] Global Circuit Breaker (3.5%), Kill-Switch & Resume: 100% ACCURATE")

# [7/7] WEBSOCKET STREAMER
print("\n[7/7] Auditing CryptoWebSocketStreamer Cache & Data...")
from data.websocket_streamer import CryptoWebSocketStreamer

ws = CryptoWebSocketStreamer.get_instance()
ws.update_tick("BTC-USD", {
    "symbol": "BTC-USD",
    "price": 65000.0,
    "timestamp": time.time(),
    "data_source": "Binance WebSocket (Live 0-Delay)",
})

t_btc = ws.get_tick("BTC-USD")
assert t_btc is not None
assert t_btc["price"] == 65000.0
print("  [PASS] Real-Time WebSocket Cache: 100% ACCURATE")

print("\n" + "=" * 75)
print("ALL 7 MATHEMATICAL & ALGORITHMIC AUDITS PASSED WITH 100% INTEGRITY!")
print("=" * 75)
