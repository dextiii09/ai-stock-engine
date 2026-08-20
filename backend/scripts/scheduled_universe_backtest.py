"""
Scheduled Multi-Universe Backtesting Engine.
Runs automated weekend walk-forward backtests across all 5 asset classes,
generates a strategy leaderboard, and pushes a summary report to Telegram.
"""
import os
import sys
import json
import time
from datetime import datetime
from dotenv import load_dotenv

# Ensure root backend in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from backtesting.engine import BacktestEngine
from utils.notifier import notifier

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "backtest_leaderboard.json")

# Representative multi-asset universe (15 core assets)
TARGET_UNIVERSE = [
    # US Futures / Indices
    {"symbol": "MNQ=F", "market": "US", "name": "Micro Nasdaq"},
    {"symbol": "MGC=F", "market": "US", "name": "Micro Gold"},
    {"symbol": "SPY",   "market": "US", "name": "S&P 500 ETF"},
    
    # Indian NSE Equities
    {"symbol": "NIFTYBEES.NS", "market": "INDIA", "name": "Nifty 50 ETF"},
    {"symbol": "RELIANCE.NS",  "market": "INDIA", "name": "Reliance Ind."},
    {"symbol": "HDFCBANK.NS",  "market": "INDIA", "name": "HDFC Bank"},
    {"symbol": "TCS.NS",       "market": "INDIA", "name": "Tata Consultancy"},
    
    # US Tech Mega-caps
    {"symbol": "AAPL",  "market": "STOCKS", "name": "Apple Inc."},
    {"symbol": "NVDA",  "market": "STOCKS", "name": "Nvidia Corp."},
    {"symbol": "MSFT",  "market": "STOCKS", "name": "Microsoft Corp."},
    {"symbol": "TSLA",  "market": "STOCKS", "name": "Tesla Inc."},
    
    # Crypto
    {"symbol": "BTC-USD", "market": "CRYPTO", "name": "Bitcoin"},
    {"symbol": "ETH-USD", "market": "CRYPTO", "name": "Ethereum"},
    
    # Forex
    {"symbol": "EURUSD=X", "market": "FOREX", "name": "EUR/USD"},
    {"symbol": "GBPUSD=X", "market": "FOREX", "name": "GBP/USD"},
]

CORE_STRATEGIES = ["AI Committee", "RSI Mean Reversion", "Supertrend"]


def run_full_universe_backtest(period: str = "1y", initial_capital: float = 100000.0) -> dict:
    """Executes backtests across the entire multi-asset universe."""
    print(f"\n=======================================================")
    print(f"  STARTING SCHEDULED MULTI-UNIVERSE BACKTEST ({period})")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"=======================================================\n")
    
    results_list = []
    start_time = time.time()
    
    for item in TARGET_UNIVERSE:
        sym = item["symbol"]
        mkt = item["market"]
        name = item["name"]
        
        for strat in CORE_STRATEGIES:
            print(f"--> Testing [{mkt}] {sym} ({name}) with '{strat}'...", end=" ", flush=True)
            try:
                engine = BacktestEngine(
                    symbol=sym,
                    strategy=strat,
                    period=period,
                    initial_capital=initial_capital
                )
                res = engine.run()
                if "error" in res:
                    print(f"SKIPPED ({res['error']})")
                    continue
                
                entry = {
                    "symbol": sym,
                    "market": mkt,
                    "name": name,
                    "strategy": strat,
                    "period": period,
                    "total_trades": res.get("total_trades", 0),
                    "win_rate_pct": res.get("win_rate_pct", 0.0),
                    "total_return_pct": res.get("total_return_pct", 0.0),
                    "profit_factor": res.get("profit_factor", 0.0),
                    "sharpe_ratio": res.get("sharpe_ratio", 0.0),
                    "max_drawdown_pct": res.get("max_drawdown_pct", 0.0),
                    "winning_trades": res.get("winning_trades", 0),
                    "losing_trades": res.get("losing_trades", 0),
                    "currency": res.get("currency", "USD"),
                }
                results_list.append(entry)
                print(f"OK (WR: {entry['win_rate_pct']}% | Return: {entry['total_return_pct']:+.1f}% | Sharpe: {entry['sharpe_ratio']})")
            except Exception as e:
                print(f"FAILED ({e})")
            
            # 1 second rate-limit buffer between Yahoo Finance requests
            time.sleep(0.8)
            
    elapsed = round(time.time() - start_time, 1)
    print(f"\nCompleted {len(results_list)} backtest runs in {elapsed}s.")
    
    # Sort leaderboard by Sharpe Ratio and Return
    results_list.sort(key=lambda x: (x.get("sharpe_ratio", -99), x.get("total_return_pct", -99)), reverse=True)
    
    payload = {
        "timestamp": time.time(),
        "date_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "period": period,
        "total_simulations": len(results_list),
        "elapsed_seconds": elapsed,
        "top_performers": results_list[:10],
        "all_results": results_list,
    }
    
    # Save to disk
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Leaderboard saved to: {OUTPUT_FILE}")
    
    return payload


async def send_telegram_summary(payload: dict):
    """Sends a formatted leaderboard summary to Telegram."""
    top = payload.get("top_performers", [])
    if not top:
        return
    
    lines = [
        "🏆 *Automated Multi-Universe Backtest Report*",
        f"📅 Date: `{payload.get('date_str')}`",
        f"⏱️ Tested: `{payload.get('total_simulations')}` asset-strategy combinations (1 Year)\n",
        "*🌟 Top 5 Strategy Performers:*",
    ]
    
    for i, t in enumerate(top[:5], 1):
        sym = t["symbol"]
        strat = t["strategy"]
        wr = t["win_rate_pct"]
        ret = t["total_return_pct"]
        pf = t["profit_factor"]
        sh = t["sharpe_ratio"]
        lines.append(
            f"*{i}. {sym}* (`{strat}`)\n"
            f"   • Return: `{ret:+.2f}%` | Win Rate: `{wr}%`\n"
            f"   • Profit Factor: `{pf}` | Sharpe: `{sh}`"
        )
    
    lines.append(f"\n_Next scheduled run: Saturday 02:00 UTC_")
    msg = "\n".join(lines)
    await notifier.send_alert(msg)


async def main():
    period = sys.argv[1] if len(sys.argv) > 1 else "1y"
    payload = run_full_universe_backtest(period=period)
    await send_telegram_summary(payload)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
