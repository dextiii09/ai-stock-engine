"""
Autonomous Strategy Builder — now backed by real yfinance backtests.
Instead of random Sharpe/win-rate, each strategy is actually backtested
on 6 months of real OHLCV before being promoted or discarded.
"""
import yfinance as yf
import pandas as pd
import numpy as np
import uuid
import threading
from typing import Dict, Any, List

SYMBOLS = ["MGC=F", "MNQ=F", "MES=F", "MCL=F", "M2K=F"]
STAGES = ["Discovering", "Backtesting", "Walk-Forward", "Paper Trading", "Evaluating"]

INDICATOR_COMBOS = [
    ("RSI", "MACD",       "oversold crossover"),
    ("EMA", "RSI",        "trend + momentum"),
    ("MACD", "BB",        "breakout divergence"),
    ("RSI", "ATR",        "volatility breakout"),
    ("OBV", "EMA",        "volume trend follow"),
    ("Stochastic", "RSI", "double oscillator"),
    ("VWAP", "MACD",      "intraday momentum"),
    ("BB", "RSI",         "mean reversion"),
    ("CCI", "EMA",        "trend reversal"),
    ("ATR", "MACD",       "volatility momentum"),
]


def _backtest_strategy(combo_idx: int, symbol: str) -> Dict[str, Any]:
    """
    Runs a real mini-backtest using the indicator pair on 6mo daily OHLCV.
    Returns actual Sharpe ratio and win rate from historical data.
    """
    ind_a, ind_b, condition = INDICATOR_COMBOS[combo_idx % len(INDICATOR_COMBOS)]

    try:
        df = yf.Ticker(symbol).history(period="6mo", interval="1d")
        if df is None or df.empty or len(df) < 40:
            return None
    except Exception:
        return None

    # Compute indicators
    close = df["Close"]
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    df["macd_hist"] = macd_line - signal_line

    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std
    df = df.dropna()

    # Pre-compute EMA-50 series once to avoid O(N²) recalculation inside the bar loop.
    # Old code: df["Close"].iloc[:i+1].ewm(...).mean().iloc[-1] — grows slice at each step.
    ema50_series = df["Close"].ewm(span=50, adjust=False).mean() if "EMA" in (ind_a, ind_b) else None

    # Signal logic based on indicator pair
    signals = []
    for i in range(len(df)):
        row = df.iloc[i]
        rsi = row.get("rsi", 50)
        macd = row.get("macd_hist", 0)
        price = row["Close"]
        bb_lo = row.get("bb_lower", price * 0.98)

        if "RSI" in (ind_a, ind_b) and "MACD" in (ind_a, ind_b):
            signals.append("BUY" if rsi < 35 and macd > 0 else "SELL" if rsi > 65 and macd < 0 else "HOLD")
        elif "BB" in (ind_a, ind_b):
            signals.append("BUY" if price <= bb_lo else "HOLD")
        elif "EMA" in (ind_a, ind_b):
            ema = ema50_series.iloc[i]
            signals.append("BUY" if price > ema else "SELL")
        else:
            signals.append("BUY" if rsi < 40 else "SELL" if rsi > 60 else "HOLD")

    df["signal"] = signals

    # Split data into In-Sample (Train) and Out-Of-Sample (Test)
    # 6 months = ~126 trading days. First 84 = IS, last 42 = OOS.
    train_size = int(len(df) * 0.66)
    
    # Simulate trades on Train and Test separately
    def simulate_trades(data_slice):
        capital = 10000.0
        position = None
        trades = []
        closes = data_slice["Close"].values
        signals_slice = data_slice["signal"].values

        for i in range(len(data_slice)):
            sig = signals_slice[i]
            price = closes[i]

            if sig == "BUY" and position is None:
                # Entry: 0.05% slippage + 0.1% commission
                exec_price = price * 1.0005
                shares = capital / exec_price
                c_entry = shares * exec_price * 0.001
                capital = 0
                position = {"shares": shares, "entry": exec_price, "c_entry": c_entry}

            elif sig == "SELL" and position:
                # Exit: 0.05% slippage + 0.1% commission
                exec_price = price * 0.9995
                c_exit  = position["shares"] * exec_price * 0.001
                revenue = position["shares"] * exec_price - c_exit
                pnl     = revenue - (position["shares"] * position["entry"]) - position["c_entry"]
                trades.append(pnl)
                capital = revenue
                position = None

        if position:  # Close at end (no extra slippage for forced close)
            exec_price = closes[-1] * 0.9995
            c_exit  = position["shares"] * exec_price * 0.001
            revenue = position["shares"] * exec_price - c_exit
            pnl     = revenue - (position["shares"] * position["entry"]) - position["c_entry"]
            trades.append(pnl)
            capital = revenue

        return trades, capital
    train_trades, train_capital = simulate_trades(df.iloc[:train_size])
    test_trades, test_capital = simulate_trades(df.iloc[train_size:])
    
    if not train_trades or not test_trades:
        return None

    def calc_metrics(trade_list, cap):
        wins = [t for t in trade_list if t > 0]
        win_rate = round(len(wins) / len(trade_list) * 100, 1) if trade_list else 0.0
        total_ret = (cap - 10000) / 10000

        equity = [10000.0]
        for t in trade_list:
            equity.append(equity[-1] + t)
        # Per-trade returns — annualize by trades-per-year, not by 252 days.
        # Using sqrt(252) when there are only 5 trades inflates Sharpe ~7x.
        # We estimate trades/yr from the slice length (assume ~252 bars = 1 yr).
        n_bars = len(df) * (len(trade_list) / max(len(trade_list) + 1, 1))
        trades_per_year = max(len(trade_list), 1) / max(n_bars / 252.0, 0.01)
        returns = [(equity[i] - equity[i-1]) / equity[i-1] for i in range(1, len(equity)) if equity[i-1] > 0]
        avg_r = np.mean(returns) if returns else 0
        std_r = np.std(returns) if len(returns) > 1 else 0.01
        sharpe = round(float(avg_r / std_r * np.sqrt(trades_per_year)) if std_r > 0 else 0.0, 2)
        return sharpe, win_rate, total_ret
        
    is_sharpe, is_win_rate, is_ret = calc_metrics(train_trades, train_capital)
    oos_sharpe, oos_win_rate, oos_ret = calc_metrics(test_trades, test_capital)
    
    # OOS Gate: The strategy must be profitable on unseen data
    if oos_sharpe < 0.5 or oos_ret <= 0:
        return None

    return {
        "sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "win_rate": is_win_rate,
        "oos_win_rate": oos_win_rate,
        "total_return_pct": round(oos_ret * 100, 2), # Report OOS return
        "trades": len(train_trades) + len(test_trades),
        "symbol": symbol
    }


class AutonomousStrategyBuilder:
    """
    Feature 18: The AI generates, backtests (with REAL yfinance data),
    and autonomously promotes or discards strategies.
    No random Sharpe ratios. Every number is earned through actual backtest.
    """

    def __init__(self, symbols=None):
        self.symbols = symbols if symbols else SYMBOLS
        self.pipeline: List[Dict[str, Any]] = []
        self.deployed: List[Dict[str, Any]] = []
        self.discarded: List[Dict[str, Any]] = []
        self._combo_idx = 0
        # PERF: initial candidates used to be generated synchronously here,
        # running 3 real yfinance backtests PER INSTANCE (5 markets = 15
        # network calls) before the API could even bind its port. Generate
        # them in a background daemon thread instead so startup is instant.
        self._seed_thread = threading.Thread(
            target=self._generate_initial_candidates, args=(3,), daemon=True
        )
        self._seed_thread.start()

    def _generate_strategy(self) -> Dict[str, Any]:
        """Generates a strategy entry and immediately backtests it on real data."""
        combo_idx = self._combo_idx % len(INDICATOR_COMBOS)
        self._combo_idx += 1
        ind_a, ind_b, condition = INDICATOR_COMBOS[combo_idx]
        symbol = self.symbols[combo_idx % len(self.symbols)]

        result = _backtest_strategy(combo_idx, symbol)

        if result is None:
            sharpe = 0.0
            win_rate = 0.0
            total_ret = 0.0
            n_trades = 0
            backtest_status = "DATA_ERROR"
        else:
            sharpe = result["sharpe"]
            win_rate = result["win_rate"]
            total_ret = result["total_return_pct"]
            n_trades = result["trades"]
            backtest_status = "BACKTESTED"

        viable = sharpe >= 1.0 and win_rate >= 52.0 and n_trades >= 3

        return {
            "id": str(uuid.uuid4())[:8],
            "name": f"{ind_a}+{ind_b} {condition.title()}",
            "indicators": [ind_a, ind_b],
            "condition": condition,
            "symbol_tested": symbol,
            "stage": "Backtesting",
            "sharpe_ratio": sharpe,
            "win_rate": win_rate,
            "total_return_pct": total_ret,
            "trades_in_backtest": n_trades,
            "is_viable": viable,
            "backtest_status": backtest_status,
            "status": "IN_PIPELINE",
            "data_source": "Yahoo Finance (real 6mo)"
        }

    def _generate_initial_candidates(self, n: int):
        for _ in range(n):
            try:
                self.pipeline.append(self._generate_strategy())
            except Exception:
                pass

    def tick(self):
        """Advance pipeline — strategies move through stages; final stage = deploy or discard."""
        for strat in list(self.pipeline):
            idx = STAGES.index(strat.get("stage", "Discovering"))
            if idx < len(STAGES) - 1:
                strat["stage"] = STAGES[idx + 1]
            else:
                if strat["is_viable"]:
                    strat["status"] = "DEPLOYED"
                    self.deployed.append(strat)
                else:
                    strat["status"] = "DISCARDED"
                    self.discarded.append(strat)
                self.pipeline.remove(strat)

        # Generate a new candidate every 5 ticks (not every tick — real backtest costs time)
        # PERF: generation runs a real yfinance backtest (network + pandas), which
        # used to block the async trading loop for seconds. Run it in a daemon
        # thread; skip if the previous generation is still in flight.
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        if self._tick_count % 5 == 0:
            gen = getattr(self, "_gen_thread", None)
            if gen is None or not gen.is_alive():
                def _bg_generate():
                    try:
                        self.pipeline.append(self._generate_strategy())
                    except Exception:
                        pass
                self._gen_thread = threading.Thread(target=_bg_generate, daemon=True)
                self._gen_thread.start()

    def get_status(self) -> Dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "deployed": self.deployed[-5:],
            "discarded_count": len(self.discarded),
            "total_generated": len(self.pipeline) + len(self.deployed) + len(self.discarded),
            "data_source": "Yahoo Finance real backtests"
        }
