"""
Real Walk-Forward Backtesting Engine — v2.1.
Downloads real OHLCV from Yahoo Finance. No mock data anywhere.

Integrity fixes in v2.1:
  - RL training is frozen at the 60% train boundary. Trades closing in the
    validation or test splits NEVER call process_trade_outcome(), so the
    reported val/test returns are truly out-of-sample from the RL perspective.
  - SentimentAgent weight is forced to 0.0 for every backtest bar. We have no
    point-in-time news archive, so using the current RSS snapshot for historical
    bars introduces future-leak. Sentiment is live-only.

Upgrades over v1:
  - Short selling support (SELL signals open SHORT positions)
  - Sortino, VaR-95%, CVaR-95% in output
  - Benchmark comparison (SPY for US, NIFTYBEES.NS for India)
  - Monthly returns matrix for heatmap
  - Monte Carlo simulation (200 paths → p5 / p50 / p95)
  - Trade duration stats (avg/max hold bars, win/loss streaks)
  - Long vs Short breakdown
  - New strategies: Supertrend, VWAP Reversion, ADX Trend Strength
  - Indian market: STT 0.1% on sell-side, INR currency label
"""
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime
import math
from data.provider import DataProviderFactory
from agents.master import MasterAgent, IndianMasterAgent
from analytics.rl_engine import ReinforcementLearningEngine
from data.regime_detector import MarketRegimeDetector
from analytics.performance_metrics import from_equity_curve
from risk.adaptive_stops import AdaptiveStopLoss
from risk.position_sizing import PositionSizer


data_provider = DataProviderFactory.get_provider()

RISK_FREE_DAILY = 0.05 / 252   # 5 % annual risk-free rate


# ─────────────────────────────────────────────────────────────────────────────
# Market helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_indian(symbol: str) -> bool:
    s = symbol.upper()
    return s.endswith(".NS") or s.endswith(".BO")

def _benchmark_sym(symbol: str) -> str:
    return "NIFTYBEES.NS" if _is_indian(symbol) else "SPY"

def _currency(symbol: str) -> str:
    return "INR" if _is_indian(symbol) else "USD"


# ─────────────────────────────────────────────────────────────────────────────
# Supertrend helper (needs sequential pass — computed separately)
# ─────────────────────────────────────────────────────────────────────────────

def _add_supertrend(df: pd.DataFrame, mult: float = 3.0) -> pd.DataFrame:
    """Adds supertrend_dir (+1 bullish / -1 bearish) and supertrend_line columns."""
    hl2    = (df["High"].values + df["Low"].values) / 2
    atr    = df["atr"].values
    upper  = hl2 + mult * atr
    lower  = hl2 - mult * atr
    close  = df["Close"].values
    n      = len(df)

    direction = np.ones(n, dtype=int)
    for i in range(1, n):
        if close[i] > upper[i - 1]:
            direction[i] = 1
        elif close[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
            # Only tighten bands — never widen
            if direction[i] == 1 and lower[i] < lower[i - 1]:
                lower[i] = lower[i - 1]
            if direction[i] == -1 and upper[i] > upper[i - 1]:
                upper[i] = upper[i - 1]

    df["supertrend_dir"]  = direction
    df["supertrend_line"] = np.where(direction == 1, lower, upper)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Indicator computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds to OHLCV df:
      RSI-14, MACD (12/26/9), Bollinger (20,2), ATR-14,
      ADX-14 + DI+/DI-, rolling-VWAP (20-bar),
      Volume z-score, EMA-50, Supertrend (3×ATR)
    """
    close = df["Close"]

    # ── RSI-14 (Wilder) ───────────────────────────────────────────────────────
    # IV&V H5: Wilder smoothing (ewm alpha=1/14) to match the live feed
    # (data/ingestion.py::_compute_rsi) and the standard RSI definition. The
    # previous SMA rolling mean diverged from live by several points near turns,
    # flipping threshold signals and invalidating backtest→live extrapolation.
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ── MACD (12/26/9) ────────────────────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"]        = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # ── Bollinger Bands (20, 2) ───────────────────────────────────────────────
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_mid"]   = sma20

    # ── ATR-14 (Wilder) ───────────────────────────────────────────────────────
    # IV&V H5: Wilder smoothing to match the standard ATR and the (now Wilder)
    # live _compute_atr. Affects stop distances so backtest stops mirror live.
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - close.shift()).abs()
    lc  = (df["Low"]  - close.shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # ── ADX-14 + DI+/DI- (Wilder) ─────────────────────────────────────────────
    # IV&V H5: Wilder-smooth TR and directional movement (ewm alpha=1/14), the
    # standard ADX construction, instead of simple rolling sums/means.
    dm_p = (df["High"] - df["High"].shift()).clip(lower=0)
    dm_m = (df["Low"].shift()  - df["Low"]).clip(lower=0)
    
    # Save original for correct simultaneous comparison
    dm_p_orig = dm_p.copy()
    dm_p = dm_p.where(dm_p > dm_m, 0)
    dm_m = dm_m.where(dm_m > dm_p_orig, 0)
    tr_w    = tr.ewm(alpha=1 / 14, adjust=False).mean()
    di_p    = 100 * dm_p.ewm(alpha=1 / 14, adjust=False).mean() / tr_w.replace(0, np.nan)
    di_m    = 100 * dm_m.ewm(alpha=1 / 14, adjust=False).mean() / tr_w.replace(0, np.nan)
    dx      = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    df["adx"]      = dx.ewm(alpha=1 / 14, adjust=False).mean()
    df["di_plus"]  = di_p
    df["di_minus"] = di_m

    # ── Rolling VWAP (20-bar) ─────────────────────────────────────────────────
    tp       = (df["High"] + df["Low"] + close) / 3
    vol      = df["Volume"].fillna(0)
    vol_sum  = vol.rolling(20).sum()
    # Forex and some crypto pairs have Volume=0; fall back to typical price so
    # VWAP stays finite and dropna() doesn't wipe the entire dataframe.
    df["vwap"] = np.where(vol_sum > 0,
                          (tp * vol).rolling(20).sum() / vol_sum,
                          tp)

    # ── Volume z-score ────────────────────────────────────────────────────────
    df["vol_zscore"] = ((vol - vol.rolling(20).mean()) /
                        vol.rolling(20).std()).fillna(0)

    # ── EMA-50 ────────────────────────────────────────────────────────────────
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # Drop NaN rows (warm-up period), then add Supertrend
    df = df.dropna().copy()
    df = _add_supertrend(df)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Strategy signal generator
# ─────────────────────────────────────────────────────────────────────────────

STRATEGIES = {
    "AI Committee":       "Full 7-agent AI committee with RL weight adaptation",
    "RSI Mean Reversion": "Buy oversold (<30), Sell overbought (>70)",
    "MACD Crossover":     "Buy MACD cross above signal; Sell cross below",
    "Bollinger Breakout": "Buy above upper BB with volume; Sell below lower BB",
    "EMA Trend Follow":   "Buy price > EMA50 + RSI > 50; Sell price < EMA50",
    "Supertrend":         "ATR-based trend bands — flip on direction change",
    "VWAP Reversion":     "Buy dips below VWAP with oversold RSI; Sell above VWAP",
    "ADX Trend Strength": "Enter when ADX > 25 confirms DI+/DI- crossover",
}


def get_signal(row: pd.Series, strategy: str,
               prev_row: Optional[pd.Series] = None) -> str:
    """Returns BUY / SELL / HOLD for one bar."""
    rsi      = float(row.get("rsi",     50))
    macd_h   = float(row.get("macd_hist", 0))
    macd     = float(row.get("macd",    0))
    macd_sig = float(row.get("macd_signal", 0))
    close    = float(row.get("Close",   0))
    ema50    = float(row.get("ema50",   close))
    bb_up    = float(row.get("bb_upper", close * 1.05))
    bb_lo    = float(row.get("bb_lower", close * 0.95))
    vol_z    = float(row.get("vol_zscore", 0))
    vwap     = float(row.get("vwap",    close))
    adx      = float(row.get("adx",    0))
    di_p     = float(row.get("di_plus",  0))
    di_m     = float(row.get("di_minus", 0))
    st_dir   = int(row.get("supertrend_dir", 0))

    if strategy == "AI Committee":
        if rsi < 35 and macd_h > 0 and close > ema50 * 0.995:  return "BUY"
        if rsi > 65 and macd_h < 0 and close < ema50 * 1.005:  return "SELL"
        if rsi < 30:   return "BUY"
        if rsi > 70:   return "SELL"
        return "HOLD"

    elif strategy == "RSI Mean Reversion":
        if rsi < 30:  return "BUY"
        if rsi > 70:  return "SELL"
        return "HOLD"

    elif strategy == "MACD Crossover":
        if macd_h > 0 and macd > macd_sig:  return "BUY"
        if macd_h < 0:                       return "SELL"
        return "HOLD"

    elif strategy == "Bollinger Breakout":
        if close > bb_up and vol_z > 1.0:  return "BUY"
        if close < bb_lo:                   return "SELL"
        return "HOLD"

    elif strategy == "EMA Trend Follow":
        if close > ema50 and rsi > 50 and macd_h > 0:  return "BUY"
        if close < ema50 and rsi < 50:                   return "SELL"
        return "HOLD"

    elif strategy == "Supertrend":
        # Direction flip = signal
        prev_dir = int(prev_row.get("supertrend_dir", st_dir)) if prev_row is not None else st_dir
        if st_dir == 1  and prev_dir == -1:  return "BUY"   # flipped bullish
        if st_dir == -1 and prev_dir ==  1:  return "SELL"  # flipped bearish
        return "HOLD"

    elif strategy == "VWAP Reversion":
        if close < vwap * 0.99 and rsi < 40:   return "BUY"
        if close > vwap * 1.01 and rsi > 60:   return "SELL"
        return "HOLD"

    elif strategy == "ADX Trend Strength":
        if adx > 25 and di_p > di_m and rsi > 45:  return "BUY"
        if adx > 25 and di_m > di_p and rsi < 55:  return "SELL"
        return "HOLD"   # ADX < 20 = ranging, skip

    return "HOLD"


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo simulation
# ─────────────────────────────────────────────────────────────────────────────

def _monte_carlo(trades: List[Dict], initial_capital: float,
                 n: int = 200) -> Dict[str, Any]:
    """Bootstrap trade PnLs N times → p5/p50/p95 confidence on final equity."""
    if len(trades) < 5:
        return {"p5": round(initial_capital, 2),
                "p50": round(initial_capital, 2),
                "p95": round(initial_capital, 2),
                "expected_final": round(initial_capital, 2)}
    pnls   = np.array([t["net_pnl"] for t in trades])
    finals = sorted(
        initial_capital + float(np.sum(np.random.choice(pnls, size=len(pnls), replace=True)))
        for _ in range(n)
    )
    return {
        "p5":           round(finals[int(n * 0.05)], 2),
        "p50":          round(finals[int(n * 0.50)], 2),
        "p95":          round(finals[int(n * 0.95)], 2),
        "expected_final": round(float(np.mean(finals)), 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Monthly returns helper
# ─────────────────────────────────────────────────────────────────────────────

def _monthly_returns(equity_curve: List[Dict]) -> Dict[str, float]:
    """Returns {YYYY-MM: monthly_return_pct, ...} from equity curve."""
    by_month: Dict[str, List[float]] = {}
    for pt in equity_curve:
        m = pt["date"][:7]
        by_month.setdefault(m, []).append(pt["equity"])

    result: Dict[str, float] = {}
    prev_end: Optional[float] = None
    for m in sorted(by_month):
        pts   = by_month[m]
        start = prev_end if prev_end is not None else pts[0]
        end   = pts[-1]
        result[m] = round((end / start - 1) * 100, 2) if start > 0 else 0.0
        prev_end  = end
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark helper
# ─────────────────────────────────────────────────────────────────────────────

def _benchmark_return(symbol: str, period: str, interval: str) -> Dict[str, Any]:
    """Buy-and-hold return + Sharpe for SPY (US) or NIFTYBEES.NS (India)."""
    try:
        bench = _benchmark_sym(symbol)
        df    = data_provider.get_historical_ohlcv(symbol=bench, period=period, interval=interval)
        if df is None or df.empty or len(df) < 2:
            return {"error": "No benchmark data", "symbol": bench}
        closes  = df["Close"].dropna().values
        bh_ret  = (closes[-1] / closes[0] - 1) * 100
        rets    = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        avg_r   = float(np.mean(rets))
        std_r   = float(np.std(rets)) or 1e-9
        sharpe  = (avg_r - RISK_FREE_DAILY) / std_r * math.sqrt(252)
        return {
            "symbol":     bench,
            "return_pct": round(float(bh_ret), 2),   # plain float — np.float64 can break JSON serialization
            "sharpe":     round(float(sharpe), 3),
        }
    except Exception as ex:
        return {"error": str(ex), "symbol": _benchmark_sym(symbol)}


# ─────────────────────────────────────────────────────────────────────────────
# Core Backtesting Engine
# ─────────────────────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Replays a strategy bar-by-bar on real Yahoo Finance OHLCV.
    Supports LONG and SHORT positions.
    Indian symbols: STT (0.1 % on sell-side) is applied automatically.
    """

    def __init__(self,
                 symbol: str,
                 strategy: str = "AI Committee",
                 initial_capital: float = 100_000.0,
                 position_size_pct: float = 10.0,
                 stop_loss_atr: float = 2.0,
                 take_profit_atr: float = 4.0,
                 commission_pct: float = 0.1,
                 period: str = "1y",
                 interval: str = "1d",
                 use_adaptive_stops: bool = True,
                 use_metagate: bool = True,
                 strict_macro: bool = True):
        self.symbol = symbol.upper()
        self.strict_macro = strict_macro
        # Back-compat: legacy strategy names from old frontend cache
        strategy_map = {
            "Trend Following": "EMA Trend Follow",
            "Mean Reversion":  "RSI Mean Reversion",
            "Breakout":        "Bollinger Breakout",
        }
        self.strategy          = strategy_map.get(strategy, strategy)
        self.initial_capital   = float(initial_capital)
        # DEPRECATED (2026-08-21, audit Finding #11 fix): no longer used for
        # sizing — every trade is now sized via self.sizer (Half-Kelly),
        # matching live. Kept only so any external caller still passing
        # position_size_pct= doesn't break on an unexpected-kwarg TypeError;
        # nothing in this codebase currently passes it explicitly.
        self.position_size_pct = position_size_pct / 100
        self.stop_loss_atr     = stop_loss_atr
        self.take_profit_atr   = take_profit_atr
        self.commission_pct    = commission_pct / 100
        self.period            = period
        self.interval          = interval
        self.is_indian         = _is_indian(self.symbol)
        self.currency          = _currency(self.symbol)
        self.use_adaptive_stops = use_adaptive_stops
        self.use_metagate      = use_metagate

        # Indian symbols get the 8-agent committee (includes IndianInstitutionalFlowAgent)
        self.master_agent    = IndianMasterAgent() if self.is_indian else MasterAgent()
        self.rl_engine       = ReinforcementLearningEngine()
        self.regime_detector = MarketRegimeDetector()
        self.stops           = AdaptiveStopLoss()
        # IV&V finding 2026-08-21 (audit Finding #11): every backtested trade was
        # previously sized as a flat position_size_pct (default 10%) of capital,
        # never Half-Kelly — live trading always sizes through PositionSizer
        # (1% fixed-fractional under 30 closed trades, hard-capped at 5% max
        # risk). A flat-10% backtest measures a different risk/return profile
        # than what live trading actually risks, so every reported Sharpe/
        # drawdown/VaR number was not representative of live risk. Now sized
        # identically to live via the same PositionSizer. `self.rl_engine` is a
        # FRESH instance per backtest run (see above) that only accumulates
        # trade history/win-rate during the 60% train split (process_trade_outcome
        # is gated by `in_train_split` below) — so recent_win_rate/n_closed_trades
        # fed to Kelly here automatically inherit the same point-in-time,
        # leakage-free discipline already enforced for RL weight updates,
        # with no additional bookkeeping needed.
        self.sizer           = PositionSizer()

    # ── Download ──────────────────────────────────────────────────────────────

    def _download(self) -> "pd.DataFrame":
        try:
            return data_provider.get_historical_ohlcv(
                symbol=self.symbol, period=self.period, interval=self.interval
            )
        except Exception as ex:
            raise RuntimeError("Backtest download failed for %s: %s" % (self.symbol, ex)) from ex

    def _download_macro_series(self):
        """Historical ^VIX level and DX-Y.NYB 5-day momentum, keyed by date str.

        The live MacroAgent votes off vix_level / dxy_momentum in the tick
        context, but backtests never supplied them, so it defaulted to WAIT
        on every bar for crypto / forex / stock symbols (only MNQ/MGC got
        real committee votes via COT) — the main reason "AI Committee"
        backtests drew a flat line outside futures. Momentum matches live
        semantics (ingestion.py): close minus close ~5 trading days earlier.
        Failures degrade gracefully to empty maps (agent falls back to
        neutral defaults).
        """
        def _dstr(ts):
            return ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]

        def _level_map(sym):
            m = {}
            df_ = data_provider.get_historical_ohlcv(sym, period=self.period, interval="1d")
            for ts, row in df_.iterrows():
                m[_dstr(ts)] = float(row["Close"])
            return m

        def _mom_map(sym, lookback=5):
            m = {}
            df_ = data_provider.get_historical_ohlcv(sym, period=self.period, interval="1d")
            closes = df_["Close"]
            for i in range(len(closes)):
                m[_dstr(df_.index[i])] = float(closes.iloc[i] - closes.iloc[max(0, i - lookback)])
            return m

        maps: Dict[str, Dict[str, Any]] = {}
        for key, fn in (("vix", lambda: _level_map("^VIX")),
                        ("dxy", lambda: _mom_map("DX-Y.NYB"))):
            try:
                maps[key] = fn()
            except Exception as ex:
                if self.strict_macro:
                    raise RuntimeError(f"Macro fetch failed for '{key}': {ex}") from ex
                else:
                    import logging
                    logging.getLogger("ai_stock.backtest").warning(f"Macro fetch failed for '{key}' (strict_macro=False, returning {{}}): {ex}")
                    maps[key] = {}

        if self.is_indian:
            try:
                maps["india_vix"] = _level_map("^INDIAVIX")
            except Exception as ex:
                if self.strict_macro:
                    raise RuntimeError(f"Macro fetch failed for 'india_vix': {ex}") from ex
                else:
                    import logging
                    logging.getLogger("ai_stock.backtest").warning(f"Macro fetch failed for 'india_vix' (strict_macro=False, returning {{}}): {ex}")
                    maps["india_vix"] = {}
                    
            try:
                # Nifty 50: 3-day % return (FII flow proxy) + above-20EMA trend flag
                n3d, nema = {}, {}
                nifty  = data_provider.get_historical_ohlcv("^NSEI", period=self.period, interval="1d")
                closes = nifty["Close"]
                ema20  = closes.ewm(span=20, adjust=False).mean()
                for i in range(len(closes)):
                    d = _dstr(nifty.index[i])
                    prev = float(closes.iloc[max(0, i - 3)])
                    n3d[d]  = (float(closes.iloc[i]) - prev) / max(prev, 1e-9) * 100
                    nema[d] = bool(float(closes.iloc[i]) > float(ema20.iloc[i]))
                maps["nifty_3d"], maps["nifty_ema"] = n3d, nema
            except Exception as ex:
                if self.strict_macro:
                    raise RuntimeError(f"Macro fetch failed for 'nifty_3d/nifty_ema': {ex}") from ex
                else:
                    import logging
                    logging.getLogger("ai_stock.backtest").warning(f"Macro fetch failed for 'nifty_3d/nifty_ema' (strict_macro=False, returning {{}}): {ex}")
                    maps["nifty_3d"], maps["nifty_ema"] = {}, {}
                    
            try:
                maps["usdinr"] = _mom_map("INR=X")
            except Exception as ex:
                if self.strict_macro:
                    raise RuntimeError(f"Macro fetch failed for 'usdinr': {ex}") from ex
                else:
                    import logging
                    logging.getLogger("ai_stock.backtest").warning(f"Macro fetch failed for 'usdinr' (strict_macro=False, returning {{}}): {ex}")
                    maps["usdinr"] = {}
        return maps

    # -- Commission helper -------------------------------------------------

    def _get_realized_b(self) -> float:
        """Realized R:R from this backtest's own RL trade history (train-split
        only — see the leakage-discipline note in __init__). Falls back to 2.0
        when thin. Mirrors SmartExecutionEngine._get_realized_b() exactly, so
        live and backtest use the identical Half-Kelly `b` calibration."""
        history = self.rl_engine._trade_history
        wins    = [t["pnl"] for t in history if t.get("is_win") and t["pnl"] > 0]
        losses  = [abs(t["pnl"]) for t in history if not t.get("is_win") and t["pnl"] < 0]
        if wins and losses:
            return round((sum(wins) / len(wins)) / (sum(losses) / len(losses)), 3)
        return 2.0

    def _commission(self, price: float, shares: float, is_sell: bool) -> float:
        """Percentage-of-notional commission (+ Indian STT on sell-side).

        Was a flat $0.50/share, which broke on non-stock instruments:
        EURUSD @ ~1.17 needs ~8,600 'shares' per $10k position → $4,300
        commission PER SIDE (a +2.7% winner netted -$8,336), while 0.06 BTC
        'shares' paid ~$0.03 (essentially free). Percentage-of-notional is
        instrument-agnostic and matches the live engine's 0.1%.
        """
        c = price * shares * self.commission_pct
        if self.is_indian and is_sell:
            c += price * shares * 0.001
        return c

    # -- Main simulation loop ----------------------------------------------

    def run(self) -> "Dict[str, Any]":
        raw = self._download()
        df  = compute_indicators(raw.copy())

        # Historical macro context for the committee (see _download_macro_series)
        macro = self._download_macro_series() if self.strategy == "AI Committee" else {}
        vix_map  = macro.get("vix", {})
        dxy_map  = macro.get("dxy", {})
        ivix_map = macro.get("india_vix", {})
        n3d_map  = macro.get("nifty_3d", {})
        nema_map = macro.get("nifty_ema", {})
        inr_map  = macro.get("usdinr", {})
        # Forward-fill holders (live agent defaults)
        _last_vix, _last_dxy = 18.0, 0.0
        _last_ivix, _last_n3d, _last_nema, _last_inr = 15.0, 0.0, True, 0.0

        capital   = self.initial_capital
        position  = None
        pending_signal    = None
        pending_committee = None
        pending_regime    = None
        equity_curve = []
        trades       = []
        peak_equity  = capital
        prev_row     = None
        rows         = list(df.iterrows())
        n_rows       = len(rows)

        # RL integrity: freeze weights after the train split (first 60%).
        # Trades closing after this bar must NOT update RL weights.
        rl_train_cutoff = int(n_rows * 0.60)

        # Volume-aware slippage: pre-compute rolling mean/std so loop is O(N) not O(N²).
        # High volume → tighter spreads → less slippage (mult < 1.0).
        # Low volume → wider spreads → more slippage (mult > 1.0).
        _vol_roll_mean = df["Volume"].rolling(20, min_periods=1).mean()
        _vol_roll_std  = df["Volume"].rolling(20, min_periods=1).std().fillna(1.0)

        for i, (ts, row) in enumerate(rows):
            close      = float(row["Close"])
            open_price = float(row["Open"])
            atr        = float(row["atr"]) if not math.isnan(float(row["atr"])) else close * 0.01
            date_str   = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]

            # Volume z-score → slippage multiplier for this bar
            _vol = float(row.get("Volume", 0) or 0)
            _vz  = (_vol - float(_vol_roll_mean.iloc[i])) / max(float(_vol_roll_std.iloc[i]), 1.0)
            _vz  = max(-3.0, min(3.0, _vz))
            vol_slip_mult = max(0.5, min(2.0, 1.0 - _vz * 0.3))

            # Execute pending entry on this bar's open
            if pending_signal in ("BUY", "SELL") and position is None:
                is_long  = (pending_signal == "BUY")
                slip     = atr * 0.05 * vol_slip_mult
                entry_price = (open_price + slip) if is_long else (open_price - slip)

                # Half-Kelly sizing — identical to live (SmartExecutionEngine),
                # replacing the old flat position_size_pct. `confidence` is
                # accepted but unused inside calculate_size (sizing is
                # win-rate-calibrated, not confidence-based — see its
                # docstring), so a placeholder is fine here.
                _atr_pct    = (atr / max(entry_price, 1e-9)) * 100 if atr > 0 else 0.0
                _realized_b = self._get_realized_b()
                size_data = self.sizer.calculate_size(
                    confidence=0.0,
                    current_capital=capital,
                    current_price=entry_price,
                    regime=pending_regime,
                    recent_win_rate=self.rl_engine.win_rate / 100.0,
                    atr_pct=_atr_pct,
                    n_closed_trades=self.rl_engine.total_closed_trades,
                    realized_b=_realized_b,
                )
                shares = size_data["shares"]

                if shares > 0:
                    c_entry = self._commission(entry_price, shares, is_sell=not is_long)
                    capital -= (entry_price * shares) + c_entry
                    if self.use_adaptive_stops:
                        _vp = (atr / max(entry_price, 1e-9)) if atr > 0 else 0.02
                        stop_data = self.stops.calculate(entry_price, pending_signal, volatility_proxy=_vp, regime=pending_regime)
                        stop = stop_data["stop_loss"]
                        tp   = stop_data["take_profit"]
                        tp1  = stop_data.get("tp1_target", tp)
                        tp2  = stop_data.get("tp2_target", tp)
                    else:
                        if is_long:
                            stop = entry_price - self.stop_loss_atr  * atr
                            tp   = entry_price + self.take_profit_atr * atr
                        else:
                            stop = entry_price + self.stop_loss_atr  * atr
                            tp   = entry_price - self.take_profit_atr * atr
                        tp1  = stop_data.get("tp1_target", tp) if self.use_adaptive_stops else tp
                        tp2  = stop_data.get("tp2_target", tp) if self.use_adaptive_stops else tp

                    position = {
                        "side":        pending_signal,
                        "entry_date":  date_str,
                        "entry_price": entry_price,
                        "shares":      shares,
                        "stop_loss":   stop,
                        "initial_stop": stop,
                        "take_profit": tp,
                        "tp1_target":  tp1,
                        "tp2_target":  tp2,
                        "tp1_hit":     False,
                        "best_price":  entry_price,
                        "entry_bar":   i,
                        "committee":   pending_committee,
                        "regime":      pending_regime,
                        "c_entry":     c_entry,
                        "initial_shares": shares,
                        "realized_pnl": 0.0,
                    }

            pending_signal    = None
            pending_committee = None
            pending_regime    = None

            # Update trailing stops if position is open
            if self.use_adaptive_stops and position:
                _trail_sig = position["side"]
                _vp = (atr / max(close, 1e-9)) if atr > 0 else 0.02
                _trail = self.stops.update_trailing(
                    current_price=close,
                    signal=_trail_sig,
                    current_stop=position["stop_loss"],
                    best_price=position.get("best_price", position["entry_price"]),
                    volatility_proxy=_vp,
                    entry_price=position["entry_price"],
                    regime=position.get("regime"),
                    tp1_hit=position.get("tp1_hit", False),
                )
                position["stop_loss"]  = _trail["new_stop"]
                position["best_price"] = _trail["best_price"]

            # Check exit conditions: 2-Stage Asymmetric Scale-Out
            if position:
                is_long   = (position["side"] == "BUY")
                bar_high  = float(row["High"])
                bar_low   = float(row["Low"])
                _stop     = position["stop_loss"]
                _tp1      = position["tp1_target"]
                _tp2      = position["tp2_target"]
                _tp1_hit  = position.get("tp1_hit", False)

                # Check TP1 Partial Scale-Out (50% at 1.5R)
                if not _tp1_hit and _tp1 and ((is_long and bar_high >= _tp1) or (not is_long and bar_low <= _tp1)):
                    scale_shares = round(position["shares"] * 0.5, 4)
                    if scale_shares > 0 and scale_shares < position["shares"]:
                        rem_shares = position["shares"] - scale_shares
                        c_exit_p   = self._commission(_tp1, scale_shares, is_sell=is_long)
                        c_entry_p  = position.get("c_entry", 0.0) * (scale_shares / max(position["shares"], 1e-9))
                        if is_long:
                            p_gross = (_tp1 - position["entry_price"]) * scale_shares
                            capital += _tp1 * scale_shares - c_exit_p
                        else:
                            p_gross = (position["entry_price"] - _tp1) * scale_shares
                            capital += (2 * position["entry_price"] - _tp1) * scale_shares - c_exit_p
                        p_net = p_gross - c_entry_p - c_exit_p
                        
                        trades.append({
                            "entry_date":  position["entry_date"],
                            "exit_date":   date_str,
                            "symbol":      self.symbol,
                            "side":        "LONG" if is_long else "SHORT",
                            "entry_price": round(position["entry_price"], 4),
                            "exit_price":  round(_tp1, 4),
                            "shares":      scale_shares,
                            "gross_pnl":   round(p_gross, 2),
                            "net_pnl":     round(p_net, 2),
                            "return_pct":  round(((_tp1 / position["entry_price"] - 1) * 100 * (1 if is_long else -1)), 2),
                            "hold_bars":   i - position["entry_bar"],
                            "exit_reason": "TP1_1.5R_SCALEOUT",
                            "won":         p_net > 0,
                        })
                        position["shares"] = rem_shares
                        position["tp1_hit"] = True
                        position["realized_pnl"] += p_net
                        # Ratchet Stop Loss to Breakeven
                        if is_long:
                            position["stop_loss"] = max(position["stop_loss"], round(position["entry_price"] * 1.001, 4))
                        else:
                            position["stop_loss"] = min(position["stop_loss"], round(position["entry_price"] * 0.999, 4))

                # Check Final Exit Conditions (SL, TP2, End of Period)
                _stop = position["stop_loss"]
                if is_long:
                    hit_stop = bar_low  <= _stop
                    hit_tp   = bar_high >= _tp2
                else:
                    hit_stop = bar_high >= _stop
                    hit_tp   = bar_low  <= _tp2
                end_data = (i == n_rows - 1)

                if hit_stop or hit_tp or end_data:
                    if hit_stop:
                        exit_price = min(open_price, _stop) if is_long else max(open_price, _stop)
                        exit_price = (exit_price - atr * 0.05 * vol_slip_mult) if is_long \
                                     else (exit_price + atr * 0.05 * vol_slip_mult)
                        hit_tp = False
                    elif hit_tp:
                        exit_price = _tp2
                    else:
                        exit_price = close

                    c_exit = self._commission(exit_price, position["shares"], is_sell=is_long)
                    _c_entry = position.get("c_entry", 0.0) * (position["shares"] / max(position.get("initial_shares", position["shares"]), 1e-9))
                    if is_long:
                        gross_pnl = (exit_price - position["entry_price"]) * position["shares"]
                        net_pnl   = gross_pnl - _c_entry - c_exit
                        capital  += exit_price * position["shares"] - c_exit
                    else:
                        gross_pnl = (position["entry_price"] - exit_price) * position["shares"]
                        net_pnl   = gross_pnl - _c_entry - c_exit
                        capital  += (2 * position["entry_price"] - exit_price) * position["shares"] - c_exit

                    hold_bars  = i - position["entry_bar"]
                    return_pct = round(
                        (exit_price / position["entry_price"] - 1) * 100 * (1 if is_long else -1), 2
                    )

                    trades.append({
                        "entry_date":  position["entry_date"],
                        "exit_date":   date_str,
                        "symbol":      self.symbol,
                        "side":        "LONG" if is_long else "SHORT",
                        "entry_price": round(position["entry_price"], 4),
                        "exit_price":  round(exit_price, 4),
                        "shares":      position["shares"],
                        "gross_pnl":   round(gross_pnl, 2),
                        "net_pnl":     round(net_pnl, 2),
                        "return_pct":  return_pct,
                        "hold_bars":   hold_bars,
                        "exit_reason": "STOP_LOSS" if hit_stop else ("TAKE_PROFIT" if hit_tp else "END_OF_PERIOD"),
                        "won":         net_pnl > 0,
                    })

                    # Feed RL ONLY in train split (first 60%). Val/test are out-of-sample.
                    in_train_split = (i < rl_train_cutoff)
                    if self.strategy == "AI Committee" and position.get("committee") and in_train_split:
                        _stop_dist = abs(position["entry_price"] - position["initial_stop"])
                        _stop_dist_pct = (_stop_dist / max(position["entry_price"], 1e-9)) * 100
                        self.rl_engine.process_trade_outcome({
                            "profit_loss":       net_pnl + position.get("realized_pnl", 0.0),
                            "capital_allocated": position["entry_price"] * position.get("initial_shares", position["shares"]),
                            "action":            position["side"],
                            "regime":            position.get("regime", "Sideways"),
                            "stop_distance_pct": _stop_dist_pct,
                        }, position["committee"])

                    position = None

            # Generate entry signal (only when flat)
            if position is None:
                if self.strategy == "AI Committee":
                    # Forward-fill macro values (weekends/holidays have no VIX bar)
                    _last_vix  = vix_map.get(date_str, _last_vix)
                    _last_dxy  = dxy_map.get(date_str, _last_dxy)
                    _last_ivix = ivix_map.get(date_str, _last_ivix)
                    _last_n3d  = n3d_map.get(date_str, _last_n3d)
                    _last_nema = nema_map.get(date_str, _last_nema)
                    _last_inr  = inr_map.get(date_str, _last_inr)
                    data_dict = {
                        "symbol":             self.symbol,
                        "bar_interval":       self.interval,  # scales 1-min ATR% thresholds
                        "price":              close,
                        "rsi_14":             float(row["rsi"]),
                        "macd_hist":          float(row["macd_hist"]),
                        "vwap":               float(row.get("vwap", close)),
                        "atr_14":             float(row["atr"]),
                        "institutional_flow": "NEUTRAL",
                        # "Aggressive" to match the live engine's risk_mode.
                        # With "Normal" (0.38-0.49 thresholds) the committee —
                        # fed only sparse daily-bar features here (no COT, no
                        # news) — almost never cleared threshold: 0 trades in
                        # a full year on BTC/EURUSD, i.e. the flat-line
                        # backtest curves. Live floor for Aggressive is 0.35.
                        "trading_mode":       "Aggressive",
                        "volume":             float(row["Volume"]),
                        "macd":               float(row["macd"]),
                        "macd_signal":        float(row["macd_signal"]),
                        "bb_upper":           float(row["bb_upper"]),
                        "bb_lower":           float(row["bb_lower"]),
                        "vol_zscore":         float(row["vol_zscore"]),
                        # LiquidityAgent + HMM regime features read "volume_z"
                        # (the live-tick key) — without it every backtest bar
                        # looked like a dead market to the Liquidity agent.
                        "volume_z":           float(row["vol_zscore"]),
                        "ema50":              float(row["ema50"]),
                        # Real historical macro (forward-filled) — the
                        # MacroAgent's vote source for crypto/forex/stocks.
                        "vix_level":          _last_vix,
                        "dxy_momentum":       _last_dxy,
                        # Indian committee inputs (MacroAgent .NS branch +
                        # IndianInstitutionalFlowAgent's FII proxy).
                        "india_vix_level":    _last_ivix,
                        "nifty_3d_return":    _last_n3d,
                        "nifty_above_20ema":  _last_nema,
                        "usdinr_momentum":    _last_inr,
                    }
                    regime  = self.regime_detector.detect(self.symbol, data_dict)
                    data_dict["regime"] = regime
                    # deterministic=True: use Beta mean, not random sample.
                    # Backtests must be reproducible.
                    weights = self.rl_engine.get_current_weights(regime=regime, deterministic=True)
                    # Zero SentimentAgent: no point-in-time news archive.
                    # Current RSS feed leaks future sentiment into historical bars.
                    weights["News & Sentiment AI"] = 0.0
                    # Zero CorrelationAgent: always votes WAIT in live loop (weight=0.0).
                    # Must match live behavior so conviction denominator is identical.
                    weights["Correlation Agent"] = 0.0
                    data_dict["agent_weights"] = weights
                    decision  = self.master_agent.evaluate(self.symbol, data_dict)
                    sig       = decision.get("signal", "HOLD")
                    if sig == "WAIT":
                        sig = "HOLD"
                    committee = decision.get("committee_breakdown", [])
                else:
                    sig       = get_signal(row, self.strategy, prev_row)
                    committee = []
                    regime    = "Sideways"

                if sig in ("BUY", "SELL"):
                    if self.use_metagate and sig == "BUY" and self.symbol.upper() == "BTC-USD":
                        try:
                            from analytics.meta_gate import MetaGate, GATE_THRESHOLD as _MG_TH
                            _p_win = MetaGate.instance().p_win(self.symbol)
                            if _p_win is not None and _p_win < _MG_TH:
                                sig = "HOLD"
                        except Exception:
                            pass


                if sig in ("BUY", "SELL"):
                    pending_signal    = sig
                    pending_committee = committee
                    pending_regime    = regime

            # Equity snapshot
            if position:
                _is_long_pos = (position["side"] == "BUY")
                if _is_long_pos:
                    # LONG: mark-to-market = current close * shares
                    total_equity = capital + close * position["shares"]
                else:
                    # SHORT: collateral + unrealised PnL = (2*entry - close) * shares
                    total_equity = capital + (2 * position["entry_price"] - close) * position["shares"]
            else:
                total_equity = capital

            peak_equity = max(peak_equity, total_equity)
            drawdown    = ((peak_equity - total_equity) / peak_equity * 100) if peak_equity > 0 else 0

            equity_curve.append({
                "date":          date_str,
                "equity":        round(total_equity, 2),
                "drawdown":      round(drawdown, 2),
                "in_position":   position is not None,
                "position_side": position["side"] if position else None,
            })

            prev_row = row

        return self._compute_metrics(equity_curve, trades)

    # -- Metrics -----------------------------------------------------------

    def _compute_metrics(self, equity_curve, trades):
        if not equity_curve:
            return {"error": "No data to process"}

        initial      = self.initial_capital
        final        = equity_curve[-1]["equity"]
        total_return = (final - initial) / initial * 100

        ratio_m = from_equity_curve(equity_curve)
        # NB: `or 0.0` (not .get default) — _empty_ratio_metrics() returns the
        # keys with value None (e.g. zero-trade flat curve), and .get's default
        # only applies when the key is absent. round(None) was 500-ing
        # /forex/backtest/run whenever a strategy produced no trades.
        sharpe  = ratio_m.get("sharpe_ratio")  or 0.0
        sortino = ratio_m.get("sortino_ratio") or 0.0
        max_dd  = ratio_m.get("max_drawdown")  or 0.0
        calmar  = ratio_m.get("calmar_ratio")  or 0.0
        var_95  = ratio_m.get("var_95")        or 0.0
        cvar_95 = ratio_m.get("cvar_95")       or 0.0

        total_trades = len(trades)
        wins   = [t for t in trades if t["won"]]
        losses = [t for t in trades if not t["won"]]
        win_rate    = len(wins) / total_trades * 100 if total_trades > 0 else 0.0
        avg_win     = float(np.mean([t["net_pnl"] for t in wins]))  if wins   else 0.0
        avg_loss    = abs(float(np.mean([t["net_pnl"] for t in losses]))) if losses else 1.0
        profit_fact = (avg_win * len(wins)) / (avg_loss * max(len(losses), 1))

        long_t  = [t for t in trades if t.get("side") == "LONG"]
        short_t = [t for t in trades if t.get("side") == "SHORT"]

        hold_bars = [t.get("hold_bars", 1) for t in trades]
        avg_hold  = float(np.mean(hold_bars)) if hold_bars else 0.0
        max_hold  = max(hold_bars, default=0)

        max_win_streak = max_lose_streak = cur_w = cur_l = 0
        for t in trades:
            if t["won"]:
                cur_w += 1; cur_l = 0
            else:
                cur_l += 1; cur_w = 0
            max_win_streak  = max(max_win_streak,  cur_w)
            max_lose_streak = max(max_lose_streak, cur_l)

        n    = len(equity_curve)
        if n < 5: return {"error": "Insufficient data for walk-forward analysis", "sharpe": 0, "total_return": 0}
        sp60 = int(n * 0.6)
        sp80 = int(n * 0.8)
        wf_train = (equity_curve[sp60]["equity"] - initial) / initial * 100
        wf_val   = ((equity_curve[sp80]["equity"] - equity_curve[sp60]["equity"]) /
                    max(equity_curve[sp60]["equity"], 1e-9)) * 100
        wf_test  = ((equity_curve[-1]["equity"] - equity_curve[sp80]["equity"]) /
                    max(equity_curve[sp80]["equity"], 1e-9)) * 100

        monthly   = _monthly_returns(equity_curve)
        benchmark = _benchmark_return(self.symbol, self.period, self.interval)
        mc        = _monte_carlo(trades, initial)

        return {
            "symbol":           self.symbol,
            "strategy":         self.strategy,
            "period":           self.period,
            "currency":         self.currency,
            "is_indian":        self.is_indian,
            "initial_capital":  initial,
            "final_equity":     round(final, 2),
            "total_return_pct": round(total_return, 2),
            "sharpe_ratio":     round(float(sharpe),  3),
            "sortino_ratio":    round(float(sortino), 3),
            "max_drawdown_pct": round(max_dd, 2),
            "calmar_ratio":     round(calmar, 3),
            "var_95_pct":       round(var_95, 3),
            "cvar_95_pct":      round(cvar_95, 3),
            "profit_factor":    round(min(profit_fact, 99.0), 2),
            "total_trades":     total_trades,
            "winning_trades":   len(wins),
            "losing_trades":    len(losses),
            "long_trades":      len(long_t),
            "short_trades":     len(short_t),
            "win_rate_pct":     round(win_rate, 1),
            "avg_win_usd":      round(float(avg_win),  2),
            "avg_loss_usd":     round(float(avg_loss), 2),
            "avg_hold_bars":    round(avg_hold, 1),
            "max_hold_bars":    max_hold,
            "max_win_streak":   max_win_streak,
            "max_lose_streak":  max_lose_streak,
            "walk_forward": {
                "train_60pct":      round(wf_train, 2),
                "validation_20pct": round(wf_val,   2),
                "test_20pct":       round(wf_test,  2),
            },
            "monthly_returns":  monthly,
            "benchmark":        benchmark,
            "monte_carlo":      mc,
            "trained_weights":  self.rl_engine.get_current_weights(),
            "rl_state":         self.rl_engine.get_full_state(),
            "equity_curve":     equity_curve,
            "trades":           trades[-50:],
            "all_trades":       trades,
            "data_source":      "Yahoo Finance (real)",
        }
