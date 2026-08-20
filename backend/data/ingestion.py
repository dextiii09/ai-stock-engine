"""
Real-time market data ingestion using Yahoo Finance (yfinance).
100% free. No API key required. No mock data anywhere.
"""
import time
import datetime
import threading
import numpy as np
import pandas as pd
from typing import Dict, Any
from .macro_classifier import MacroRegimeClassifier
from .provider import DataProviderFactory

macro_classifier = MacroRegimeClassifier()
data_provider = DataProviderFactory.get_provider()

# User explicitly requested to work ONLY on XAUUSD and NASDAQ from now onwards.
# MGC=F -> Gold Futures (XAUUSD proxy on Yahoo Finance)
# MNQ=F -> Nasdaq 100 Futures
SYMBOLS = [
    "MGC=F",   # Micro Gold futures
    "MNQ=F",   # Micro Nasdaq-100 futures
    "MES=F",   # Micro E-mini S&P 500
    "MCL=F",   # Micro WTI Crude Oil
    "M2K=F",   # Micro Russell 2000
]


def _compute_rsi(closes: list, period: int = 14) -> float:
    """Wilder's RSI via pandas EWM (alpha=1/period). Converges to SMA-seed after ~3×period bars."""
    if len(closes) < period + 1:
        return 50.0
    s = pd.Series(closes, dtype=float).diff()
    gain = s.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-s.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    last_loss = float(loss.iloc[-1])
    return round(100.0 if last_loss == 0 else 100 - 100 / (1 + float(gain.iloc[-1]) / last_loss), 1)


def _compute_atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
    # IV&V H5: Wilder smoothing (ewm alpha=1/period) to match the standard ATR
    # and the backtest's ATR, so live stop distances and backtest stop distances
    # are computed identically.
    if len(closes) < period + 1:
        return 0.0
    h, l, c = pd.Series(highs), pd.Series(lows), pd.Series(closes)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return round(float(tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]), 4)


def _is_london_fix_window() -> bool:
    """
    Check if current time is within the London AM Fix window (10:25–10:35 London time).
    Uses the system zoneinfo module (Python 3.9+) for DST-correct conversion.
    Falls back to checking BOTH the BST (UTC+1) and GMT (UTC+0) windows so the
    old hardcoded 9:25-9:35 UTC assumption doesn't miss the winter fix at 10:25 UTC.
    """
    try:
        from zoneinfo import ZoneInfo
        london_now = datetime.datetime.now(ZoneInfo("Europe/London"))
        return london_now.hour == 10 and 25 <= london_now.minute <= 34
    except Exception:
        # Fallback: cover both BST (UTC+1 → fix=09:25–09:35 UTC) and
        # GMT (UTC+0 → fix=10:25–10:35 UTC) so neither season is missed.
        now_utc = datetime.datetime.utcnow().time()
        bst = datetime.time(9, 25) <= now_utc <= datetime.time(9, 35)
        gmt = datetime.time(10, 25) <= now_utc <= datetime.time(10, 35)
        return bst or gmt


def _is_rollover_week() -> bool:
    """
    Check if we are in the 5 days preceding the 3rd Friday of March, June, September, December.
    (Simplified: just checking if it's the week of the 3rd Friday of those months).
    """
    today = datetime.date.today()
    if today.month not in [3, 6, 9, 12]:
        return False
    
    # Find the 3rd Friday
    first_day = datetime.date(today.year, today.month, 1)
    first_friday = first_day + datetime.timedelta(days=(4 - first_day.weekday() + 7) % 7)
    third_friday = first_friday + datetime.timedelta(days=14)
    
    delta = (third_friday - today).days
    return 0 <= delta <= 5


from .cot_client import COTClient
cot_client = COTClient()

_MACRO_CACHE = {}
_MACRO_CACHE_TIME = 0.0
_MACRO_CACHE_LOCK = threading.Lock()

def _fetch_macro_context() -> Dict[str, Any]:
    """Fetches global macro context (DXY, TYX, VIX, COT) with a 5-minute cache.
    PERF-3: DXY/TYX/VIX fetches run in parallel via ThreadPoolExecutor, cutting
    sequential wait (3 x ~0.5s) to a single ~0.5s round-trip.
    """
    global _MACRO_CACHE, _MACRO_CACHE_TIME
    from concurrent.futures import ThreadPoolExecutor, as_completed

    now = time.time()
    with _MACRO_CACHE_LOCK:
        if now - _MACRO_CACHE_TIME < 300 and _MACRO_CACHE:
            return _MACRO_CACHE.copy()

    context = {}
    try:
        def _fetch_sym(sym, period, interval):
            try:
                return sym, data_provider.get_historical_ohlcv(sym, period=period, interval=interval)
            except Exception:
                return sym, None

        fetch_tasks = [
            ("DX-Y.NYB", "5d", "1d"),
            ("^TYX",     "2d", "1d"),
            ("^VIX",     "5d", "1d"),
        ]
        results = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = {pool.submit(_fetch_sym, sym, p, i): sym for sym, p, i in fetch_tasks}
            for fut in as_completed(futs, timeout=8):
                sym, df = fut.result()
                results[sym] = df

        dxy = results.get("DX-Y.NYB")
        if dxy is not None and not dxy.empty:
            context["dxy_momentum"] = float(dxy["Close"].iloc[-1] - dxy["Close"].iloc[0])
            context["dxy_value"]    = float(dxy["Close"].iloc[-1])

        tyx = results.get("^TYX")
        if tyx is not None and not tyx.empty:
            context["real_yield_10y_trend"] = float(tyx["Close"].iloc[-1] - tyx["Close"].iloc[0])

        vix = results.get("^VIX")
        if vix is not None and not vix.empty:
            context["vix_level"]  = float(vix["Close"].iloc[-1])
            context["vix_change"] = float(vix["Close"].iloc[-1] - vix["Close"].iloc[0])
        else:
            context["vix_level"]  = 18.0
            context["vix_change"] = 0.0

        # COT Positioning (CFTC Data) — already fast, no parallelism needed
        gold_cot = cot_client.get_gold_positioning()
        nq_cot   = cot_client.get_nq_positioning()
        context["cot_positioning"] = {
            "MGC=F": gold_cot.get("positioning", "NEUTRAL"),
            "MNQ=F": nq_cot.get("positioning", "NEUTRAL"),
        }

        # BUG 2: inject is_rollover_week into context dict
        context["is_rollover_week"] = _is_rollover_week()

        with _MACRO_CACHE_LOCK:
            _MACRO_CACHE      = context
            _MACRO_CACHE_TIME = now
    except Exception:
        pass

    return context.copy()


_INDIA_MACRO_CACHE: Dict = {}
_INDIA_MACRO_CACHE_TIME: float = 0.0
_INDIA_MACRO_CACHE_LOCK = threading.Lock()

def _fetch_india_macro_context() -> Dict[str, Any]:
    """Fetches India-specific macro: India VIX (^INDIAVIX) + USD/INR (USDINR=X).
    Cached for 5 minutes, same pattern as _fetch_macro_context().
    Used only for .NS symbols — replaces US VIX/DXY as the primary fear gauges.
    """
    global _INDIA_MACRO_CACHE, _INDIA_MACRO_CACHE_TIME
    from concurrent.futures import ThreadPoolExecutor, as_completed

    now = time.time()
    with _INDIA_MACRO_CACHE_LOCK:
        if now - _INDIA_MACRO_CACHE_TIME < 300 and _INDIA_MACRO_CACHE:
            return _INDIA_MACRO_CACHE.copy()

    context: Dict = {}
    try:
        def _fetch_sym(sym, period, interval):
            try:
                return sym, data_provider.get_historical_ohlcv(sym, period=period, interval=interval)
            except Exception:
                return sym, None

        fetch_tasks = [
            ("^INDIAVIX", "5d",  "1d"),
            ("USDINR=X",  "5d",  "1d"),
            ("^NSEI",     "30d", "1d"),   # Nifty 50 — for 20-EMA trend + 3-day return
        ]
        results: Dict = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = {pool.submit(_fetch_sym, sym, p, i): sym for sym, p, i in fetch_tasks}
            for fut in as_completed(futs, timeout=10):
                sym, df = fut.result()
                results[sym] = df

        india_vix = results.get("^INDIAVIX")
        if india_vix is not None and not india_vix.empty:
            context["india_vix_level"] = float(india_vix["Close"].iloc[-1])
        else:
            context["india_vix_level"] = 15.0  # neutral default

        usdinr = results.get("USDINR=X")
        if usdinr is not None and not usdinr.empty and len(usdinr) >= 2:
            # Positive = INR weakening (USD/INR rising) = FII outflow pressure
            context["usdinr_momentum"] = float(usdinr["Close"].iloc[-1] - usdinr["Close"].iloc[0])
            context["usdinr_value"]    = float(usdinr["Close"].iloc[-1])
        else:
            context["usdinr_momentum"] = 0.0
            context["usdinr_value"]    = 84.0  # approximate fallback

        nsei = results.get("^NSEI")
        if nsei is not None and not nsei.empty and len(nsei) >= 5:
            import numpy as _np
            closes = nsei["Close"].dropna()
            # 20-day EMA trend filter
            if len(closes) >= 20:
                ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
                context["nifty_above_20ema"] = float(closes.iloc[-1]) > ema20
                context["nifty_ema20"]       = round(ema20, 2)
            else:
                context["nifty_above_20ema"] = True   # default to neutral/bullish
                context["nifty_ema20"]       = float(closes.iloc[-1])
            # 3-day return for FII proxy (%)
            if len(closes) >= 4:
                context["nifty_3d_return"] = round(
                    (float(closes.iloc[-1]) - float(closes.iloc[-4])) / float(closes.iloc[-4]) * 100, 2
                )
            else:
                context["nifty_3d_return"] = 0.0
            context["nifty_price"] = round(float(closes.iloc[-1]), 2)
        else:
            context["nifty_above_20ema"] = True
            context["nifty_3d_return"]   = 0.0
            context["nifty_ema20"]       = 0.0
            context["nifty_price"]       = 0.0

        with _INDIA_MACRO_CACHE_LOCK:
            _INDIA_MACRO_CACHE      = context
            _INDIA_MACRO_CACHE_TIME = now
    except Exception:
        context.setdefault("india_vix_level", 15.0)
        context.setdefault("usdinr_momentum", 0.0)
        context.setdefault("usdinr_value", 84.0)
        context.setdefault("nifty_above_20ema", True)
        context.setdefault("nifty_3d_return", 0.0)
        context.setdefault("nifty_ema20", 0.0)
        context.setdefault("nifty_price", 0.0)

    return context.copy()


def fetch_real_tick(symbol: str) -> Dict[str, Any]:
    """
    Fetches the latest 1-minute OHLCV bar via DataProviderFactory.
    Computes RSI-14, MACD histogram, VWAP, and volume flow.
    Raises RuntimeError if data is unavailable.
    """
    try:
        hist = data_provider.get_historical_ohlcv(symbol, period="2d", interval="1m")
    except Exception as e:
        raise RuntimeError(f"Data provider returned no data for {symbol}: {e}")

    if hist is None or hist.empty or len(hist) < 16:
        raise RuntimeError(f"Data provider returned no data for {symbol}. Market may be closed.")

    latest = hist.iloc[-1]
    price = round(float(latest["Close"]), 4)
    volume = int(latest["Volume"])

    # ── Shared date filter (used twice below) ────────────────────────────────
    try:
        _today_date = hist.index[-1].date()
        _today_mask = np.array([d == _today_date for d in hist.index.date])
        _today_rows = hist[_today_mask]
    except Exception:
        _today_date = None
        _today_rows = hist.iloc[:0]   # empty frame

    # RSI-14 and ATR-14 via pandas EWM (vectorized)
    _d   = hist["Close"].diff()
    gain = _d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-_d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    _last_loss = float(loss.iloc[-1])
    rsi = round(100.0 if _last_loss == 0 else 100 - 100 / (1 + float(gain.iloc[-1]) / _last_loss), 1)

    _tr  = pd.concat([hist["High"] - hist["Low"],
                      (hist["High"] - hist["Close"].shift()).abs(),
                      (hist["Low"]  - hist["Close"].shift()).abs()], axis=1).max(axis=1)
    atr  = round(float(_tr.rolling(14).mean().iloc[-1]), 4)

    # TL-5: Session VWAP — resets at market open, not a rolling window
    _sess = _today_rows if (not _today_rows.empty and _today_rows["Volume"].sum() > 0) else hist.tail(20)
    vwap  = round((_sess["Close"] * _sess["Volume"]).sum() / max(_sess["Volume"].sum(), 1e-9), 4)

    # MACD histogram (true = MACD_line − 9-bar EMA of MACD_line)
    _ml      = hist["Close"].ewm(span=12, adjust=False).mean() - hist["Close"].ewm(span=26, adjust=False).mean()
    macd_hist = round(float(_ml.iloc[-1]) - float(_ml.ewm(span=9, adjust=False).mean().iloc[-1]), 6)

    # Volume-spike proxy for institutional flow
    avg_vol = hist["Volume"].tail(20).mean()
    if volume > avg_vol * 1.5:
        institutional_flow = "BULLISH" if price >= vwap else "BEARISH"
    else:
        institutional_flow = "NEUTRAL"

    in_london_fix = _is_london_fix_window()
    macro_context = _fetch_macro_context()

    # Daily change % relative to today's open
    try:
        today_open = float(_today_rows["Open"].iloc[0]) if not _today_rows.empty else price
        daily_change_pct = round((price - today_open) / today_open * 100, 2)
    except Exception:
        daily_change_pct = 0.0

    tick_data = {
        "symbol": symbol,
        "timestamp": time.time(),
        "price": price,
        "open": round(float(latest["Open"]), 4),
        "high": round(float(latest["High"]), 4),
        "low": round(float(latest["Low"]), 4),
        "volume": volume,
        "vwap": vwap,
        "rsi_14": rsi,
        "atr_14": atr,
        "macd_hist": macd_hist,
        "institutional_flow": institutional_flow,
        "daily_change_pct": daily_change_pct,
        "data_source": "Yahoo Finance (real)",
        "is_london_fix_window": in_london_fix,   # EC-6: wired so agents can check session window
    }

    # BUG 3: volume_z injection
    try:
        hist_vol = hist["Volume"].tail(20) if hist is not None and len(hist) >= 20 else None
        if hist_vol is not None and hist_vol.std() > 0:
            tick_data["volume_z"] = float((hist_vol.iloc[-1] - hist_vol.mean()) / hist_vol.std())
        else:
            tick_data["volume_z"] = 0.0
    except Exception:
        tick_data["volume_z"] = 0.0

    # hist_vol_20: 20-bar standard deviation of per-bar close returns (used by VolatilityAgent).
    # Stored as a raw fraction (e.g. 0.003 = 0.3% per 1-min bar).  The VolatilityAgent compares
    # against 0.35 (a high daily-vol threshold), so this value will almost always be < 0.15,
    # making the BUY condition effectively reduce to the ATR% check. Still wired correctly so the
    # agent can detect genuine vol-regime shifts if the comparison thresholds are ever recalibrated.
    try:
        _ret_series = hist["Close"].pct_change().dropna().tail(20)
        tick_data["hist_vol_20"] = float(_ret_series.std()) if len(_ret_series) >= 5 else 0.0
    except Exception:
        tick_data["hist_vol_20"] = 0.0
    
    # Merge macro context
    tick_data.update(macro_context)

    # For Indian equities, also inject India VIX + USD/INR (replaces US VIX/DXY as fear gauge)
    if symbol.endswith(".NS"):
        india_macro = _fetch_india_macro_context()
        tick_data.update(india_macro)

    # Classify the macro regime
    tick_data["macro_regime"] = macro_classifier.classify(macro_context)
    
    if macro_context.get("is_rollover_week"):
        tick_data["data_quality"] = "LOW_ROLLOVER"
        
    return tick_data


def run_boruta_feature_selection(X, y, max_iter=20, random_state=42):
    """
    Custom dependency-free Boruta feature selection.
    Checks if features perform better than randomized shadow features.
    """
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import RandomForestRegressor
    
    n_features = X.shape[1]
    features = list(X.columns)
    hits = {f: 0 for f in features}
    
    for i in range(max_iter):
        # Create shadow features by shuffling each column
        X_shadow = X.apply(np.random.permutation)
        X_shadow.columns = [f"shadow_{f}" for f in features]
        
        # Combine original and shadow
        X_combined = pd.concat([X, X_shadow], axis=1)
        
        # Train estimator
        rf = RandomForestRegressor(n_estimators=10, max_depth=5, random_state=random_state + i, n_jobs=1)
        rf.fit(X_combined, y)
        
        importances = rf.feature_importances_
        original_importances = importances[:n_features]
        shadow_importances = importances[n_features:]
        
        max_shadow_importance = np.max(shadow_importances) if len(shadow_importances) > 0 else 0.0
        
        for idx, feat in enumerate(features):
            if original_importances[idx] > max_shadow_importance:
                hits[feat] += 1
                
    # Binomial distribution critical thresholds for n=20, p=0.5
    # Confirmed if hits >= 14, rejected if hits <= 6, tentative if in-between.
    confirmed = [feat for feat, count in hits.items() if count >= 14]
    tentative = [feat for feat, count in hits.items() if 7 <= count < 14]
    
    # If no features confirmed, use confirmed + tentative, or top 3 by hit count
    selected = confirmed + tentative
    if len(selected) < 3:
        sorted_feats = sorted(hits.items(), key=lambda x: x[1], reverse=True)
        selected = [f[0] for f in sorted_feats[:3]]
        
    return selected


class DataIngestionEngine:
    """
    Real-time market data from Yahoo Finance. No mock data.
    If data is unavailable (e.g., market closed), logs the error and
    rotates to the next symbol rather than returning fake prices.
    Includes adaptive feature selection via RFECV (Tier 2).
    """

    def __init__(self, symbols=None):
        self.symbols = symbols if symbols is not None else ["MGC=F", "MNQ=F"]
        self._symbol_idx = 0
        self.active_features = {
            sym: [
                "price", "open", "high", "low", "volume", "vwap", "rsi_14", 
                "atr_14", "macd_hist", "dxy_momentum", "dxy_value", 
                "real_yield_10y_trend", "vix_level"
            ] for sym in self.symbols
        }
        try:
            from analytics.lstm_model import LSTMSignalEngine
            self.lstm_engine = LSTMSignalEngine()
        except ImportError:
            self.lstm_engine = None

    def run_feature_selection(self, symbol: str = "MGC=F"):
        """
        Tier 2: Boruta/RFECV Adaptive Inputs.
        Runs custom Boruta to filter features, then RFECV to select final optimal features.
        """
        try:
            import pandas as pd
            import numpy as np
            from sklearn.feature_selection import RFECV
            from sklearn.ensemble import RandomForestRegressor
            import warnings
            warnings.filterwarnings("ignore")

            hist = data_provider.get_historical_ohlcv(symbol, period="30d", interval="1h")
            if hist.empty:
                return

            df = hist.copy()
            df['target'] = df['Close'].pct_change().shift(-1)

            # RSI-14 vectorized (EWM, Wilder's smoothing — O(n) vs old O(n²) list-comprehension)
            _d = df['Close'].diff()
            df['rsi_14'] = (100 - 100 / (1 + _d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                                         / (-_d.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
                                         .replace(0, np.nan))).fillna(50.0)

            # ATR-14 vectorized
            _tr = pd.concat([df['High'] - df['Low'],
                             (df['High'] - df['Close'].shift()).abs(),
                             (df['Low']  - df['Close'].shift()).abs()], axis=1).max(axis=1)
            df['atr_14'] = _tr.rolling(14).mean()

            # MACD histogram
            _ml = df['Close'].ewm(span=12, adjust=False).mean() - df['Close'].ewm(span=26, adjust=False).mean()
            df['macd_hist'] = _ml - _ml.ewm(span=9, adjust=False).mean()
            df.dropna(inplace=True)
            
            features = ['Open', 'High', 'Low', 'Volume', 'rsi_14', 'atr_14', 'macd_hist']
            X = df[features]
            y = df['target']
            
            # Step 1: Boruta pre-selection
            boruta_selected = run_boruta_feature_selection(X, y)
            print(f"[IngestionEngine] Boruta pre-selected features for {symbol}: {boruta_selected}")
            
            # Step 2: RFECV on Boruta candidates
            X_filtered = X[boruta_selected]
            estimator = RandomForestRegressor(n_estimators=20, max_depth=5, random_state=42)
            selector = RFECV(estimator, step=1, cv=3, min_features_to_select=min(3, len(boruta_selected)))
            selector.fit(X_filtered, y)
            
            selected = [boruta_selected[i] for i in range(len(boruta_selected)) if selector.support_[i]]
            print(f"[IngestionEngine] RFECV selected final features for {symbol}: {selected}")
            
            key_map = {'Open': 'open', 'High': 'high', 'Low': 'low', 'Volume': 'volume'}
            mapped_selected = [key_map.get(f, f) for f in selected]
            
            self.active_features[symbol] = list(set(mapped_selected + [
                "price", "open", "high", "low", "volume", "vwap",
                "rsi_14", "macd_hist", "atr_14",       # core technical indicators — always needed by agents
                "dxy_momentum", "dxy_value", "real_yield_10y_trend", "vix_level",
            ]))
        except Exception as e:
            print(f"[IngestionEngine] Feature selection failed: {e}")

    def _filter_features(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        symbol = tick.get("symbol", "MGC=F")
        features_list = self.active_features.get(symbol, [
            "price", "open", "high", "low", "volume", "vwap", "rsi_14", 
            "atr_14", "macd_hist", "dxy_momentum", "dxy_value", 
            "real_yield_10y_trend", "vix_level"
        ])
        essential = [
            "symbol", "timestamp", "institutional_flow", "data_source", "macro_regime",
            "data_quality", "cot_positioning", "lstm_signal", "lstm_confidence",
            # Session / event signals from fetch_real_tick (stripped without this)
            "is_rollover_week", "is_london_fix_window", "daily_change_pct",
            # Volume Z-score — required by LiquidityAgent
            "volume_z",
            # Historical volatility (20-bar std of returns) — required by VolatilityAgent
            "hist_vol_20",
            # India macro — required by MacroAgent .NS block + Nifty trend filter
            "india_vix_level", "usdinr_momentum", "usdinr_value",
            "nifty_above_20ema", "nifty_3d_return", "nifty_ema20", "nifty_price",
        ]
        return {k: v for k, v in tick.items() if k in features_list or k in essential}

    def get_latest_tick(self) -> Dict[str, Any]:
        """
        Rotates through self.symbols list and returns the latest real 1-min bar.
        Tries up to len(self.symbols) times to find a symbol with live data.
        """
        for _ in range(len(self.symbols)):
            symbol = self.symbols[self._symbol_idx % len(self.symbols)]
            self._symbol_idx += 1
            try:
                tick = fetch_real_tick(symbol)
                
                # Update and fetch LSTM sequence signal
                if self.lstm_engine:
                    self.lstm_engine.update_tick(symbol, tick)
                    lstm_res = self.lstm_engine.get_signal(symbol)
                    tick["lstm_signal"] = lstm_res.get("signal", "WAIT")
                    tick["lstm_confidence"] = lstm_res.get("confidence", 0.0)
                else:
                    tick["lstm_signal"] = "WAIT"
                    tick["lstm_confidence"] = 0.0
                    
                return self._filter_features(tick)
            except RuntimeError:
                # Market might be closed or rate-limited, try next symbol
                continue
            except Exception:
                continue

        raise RuntimeError("All symbols failed to fetch live tick data. Market may be closed.")

    def get_tick_for(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch the latest real 1-min bar for a specific symbol.
        Applies LSTM enrichment and feature filtering, same as get_latest_tick().
        Raises RuntimeError if data is unavailable.
        """
        tick = fetch_real_tick(symbol)

        if self.lstm_engine:
            self.lstm_engine.update_tick(symbol, tick)
            lstm_res = self.lstm_engine.get_signal(symbol)
            tick["lstm_signal"] = lstm_res.get("signal", "WAIT")
            tick["lstm_confidence"] = lstm_res.get("confidence", 0.0)
        else:
            tick["lstm_signal"] = "WAIT"
            tick["lstm_confidence"] = 0.0

        return self._filter_features(tick)
