"""
Real Multi-Timeframe Analyzer using Yahoo Finance.
Downloads actual OHLCV for each timeframe and computes real RSI per timeframe.
"""
import warnings as _warnings
# Suppress hmmlearn transmat_ warning — fires on every predict() call when some
# HMM states have no observed transitions (common with sparse training windows).
_warnings.filterwarnings("ignore", message=".*transmat_.*")

import pandas as pd
from typing import Dict, Any, Tuple, Optional
import time
import threading
from concurrent.futures import ThreadPoolExecutor


def _rsi(closes: list, period: int = 14) -> float:
    """Wilder's RSI via pandas EWM — vectorized, matches ingestion.py."""
    if len(closes) < period + 1:
        return 50.0
    s    = pd.Series(closes, dtype=float).diff()
    gain = s.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-s.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    last_loss = float(loss.iloc[-1])
    return round(100.0 if last_loss == 0 else 100 - 100 / (1 + float(gain.iloc[-1]) / last_loss), 1)


def _fetch_rsi_for_interval(symbol: str, interval: str, period: str) -> float:
    """Fetch real RSI via shared DataProvider (benefits from read-through cache)."""
    try:
        from .provider import DataProviderFactory
        df = DataProviderFactory.get_provider().get_historical_ohlcv(symbol, period=period, interval=interval)
        if df is None or df.empty or len(df) < 16:
            return 50.0
        return _rsi(df["Close"].tolist())
    except Exception:
        return 50.0


HMM_TO_RL = {
    "Strong Trend Bull": "Trending Bull",
    "Weak Trend Bull": "Trending Bull",
    "Compression": "Sideways",
    "Low Liquidity": "Sideways",
    "Expansion": "Trending Bull",
    "Strong Trend Bear": "Trending Bear",
    "Weak Trend Bear": "Trending Bear",
    "News Shock": "High Volatility",
    "High Liquidity": "High Volatility",
    "Gap Day": "High Volatility",
    "Trending Bull": "Trending Bull",
    "Sideways": "Sideways",
    "Trending Bear": "Trending Bear",
    "High Volatility": "High Volatility",
    "Range Bound": "Sideways"
}


class MarketRegimeDetector:
    """
    Feature 2: Gaussian HMM Market Regime Detector with 10 states
    consolidated to 4 RL regimes for downstream AI decision-making.
    """
    def __init__(self, training_symbol: str = "DX-Y.NYB"):
        self.training_symbol = training_symbol
        self.hmm_model = None
        self.regime_map = {}

        # Mean and standard deviation vectors for scaling
        self.means = None
        self.stds  = None

        # ML-1: guards against detect() seeing a half-initialized model during
        # a concurrent retrain().  retrain() trains into temp vars, then swaps
        # all four references atomically under this lock.  detect() holds the
        # lock only for the brief snapshot read, so it never blocks training.
        self._model_lock = threading.Lock()

        self._initialize_hmm()

    def _train_hmm(self) -> Optional[Tuple]:
        """
        Train a new HMM model and return (model, regime_map, means, stds).
        Returns None on failure.  Does NOT touch self — caller does the atomic swap.
        """
        try:
            from hmmlearn.hmm import GaussianHMM
            import numpy as np
            import warnings
            warnings.filterwarnings("ignore")

            from .provider import DataProviderFactory
            df = DataProviderFactory.get_provider().get_historical_ohlcv(
                self.training_symbol, period="60d", interval="1h"
            )
            if df is None or df.empty:
                return None

            df["Return"]     = df["Close"].pct_change()
            df["Volatility"] = df["Return"].rolling(window=10).std()
            df["Volume_Z"]   = (
                (df["Volume"] - df["Volume"].rolling(20).mean())
                / df["Volume"].rolling(20).std()
            ).fillna(0)
            df.dropna(inplace=True)

            X       = np.column_stack([df["Return"], df["Volatility"], df["Volume_Z"]])
            means_  = X.mean(axis=0)
            stds_   = X.std(axis=0)
            stds_[stds_ == 0] = 1.0

            X_scaled = (X - means_) / stds_

            model = GaussianHMM(n_components=4, covariance_type="diag", n_iter=200, random_state=42)
            model.fit(X_scaled)

            hmm_means  = model.means_
            by_vol     = sorted(range(4), key=lambda i: hmm_means[i][1])
            high_vol   = by_vol[-1]
            remaining  = [i for i in range(4) if i != high_vol]
            by_ret     = sorted(remaining, key=lambda i: hmm_means[i][0])
            trend_bear = by_ret[0]
            trend_bull = by_ret[-1]
            sideways   = by_ret[1]

            regime_map_ = {
                high_vol:   "High Volatility",
                trend_bull: "Trending Bull",
                trend_bear: "Trending Bear",
                sideways:   "Sideways",
            }
            return model, regime_map_, means_, stds_
        except Exception as e:
            print(f"[RegimeDetector] Training failed: {e}")
            return None

    def _initialize_hmm(self):
        """Train and atomically swap the model into self (startup path)."""
        result = self._train_hmm()
        if result is None:
            print("[RegimeDetector] HMM Initialization skipped (no data or error).")
            return
        new_model, new_map, new_means, new_stds = result
        with self._model_lock:
            self.hmm_model  = new_model
            self.regime_map = new_map
            self.means      = new_means
            self.stds       = new_stds
        print("[RegimeDetector] HMM Initialized successfully. 4 Regimes mapped.")

    def retrain(self):
        """
        ML-1: Retrain the HMM off the hot path, then atomically swap.
        detect() always sees either the old complete model or the new complete
        model — never a partially-initialized one.
        """
        result = self._train_hmm()      # train without holding the lock
        if result is None:
            print("[RegimeDetector] Retrain skipped — training returned None.")
            return
        new_model, new_map, new_means, new_stds = result
        with self._model_lock:          # brief critical section: swap 4 refs
            self.hmm_model  = new_model
            self.regime_map = new_map
            self.means      = new_means
            self.stds       = new_stds
        print("[RegimeDetector] HMM retrained and atomically swapped.")

    def get_transition_matrix(self) -> Dict[str, Any]:
        """
        Returns the HMM's named regime transition probability matrix.
        Each entry matrix[from_regime][to_regime] is the probability of
        switching to that regime on the next observation.
        Useful for detecting regime stickiness vs. fragility.
        """
        REGIMES = ["Trending Bull", "Trending Bear", "Sideways", "High Volatility"]

        if self.hmm_model is None or not hasattr(self.hmm_model, "transmat_"):
            # HMM not yet trained — return uniform placeholder
            return {
                "fitted": False,
                "matrix": {r: {r2: round(1.0 / len(REGIMES), 4) for r2 in REGIMES} for r in REGIMES},
            }

        transmat = self.hmm_model.transmat_
        matrix: Dict[str, Dict[str, float]] = {}
        for from_state, from_name in self.regime_map.items():
            row: Dict[str, float] = {}
            for to_state, to_name in self.regime_map.items():
                row[to_name] = round(float(transmat[from_state][to_state]), 4)
            matrix[from_name] = row

        # Persistence: diagonal probability (probability of staying in same regime)
        persistence = {name: matrix[name][name] for name in matrix}

        return {
            "fitted": True,
            "matrix": matrix,
            "persistence": persistence,
        }

    def detect(self, symbol: str, data: Dict[str, Any]) -> str:
        # ML-1: snapshot the four model references under lock so that a
        # concurrent retrain() cannot swap them while we are predicting.
        with self._model_lock:
            model      = self.hmm_model
            means      = self.means
            stds       = self.stds
            regime_map = self.regime_map

        hmm_regime = "Compression"
        # Compute HMM features from live tick data if not already present
        if "return" not in data and "price" in data:
            data["return"] = data.get("daily_change_pct", 0.0) / 100.0
        if "volatility" not in data and "atr_14" in data:
            data["volatility"] = data.get("atr_14", 0.0) / max(data.get("price", 1.0), 1.0)
        if model is not None and means is not None and stds is not None \
                and "return" in data and "volatility" in data:
            try:
                import numpy as np
                vol_z      = data.get("volume_z", 0.0)
                obs        = np.array([[data["return"], data["volatility"], vol_z]])
                obs_scaled = (obs - means) / stds
                state      = model.predict(obs_scaled)[0]
                hmm_regime = regime_map.get(state, "Sideways")
            except Exception:
                hmm_regime = self._fallback_detect(symbol, data)
        else:
            hmm_regime = self._fallback_detect(symbol, data)

        # regime_map now returns RL regime names directly; HMM_TO_RL kept as
        # fallback for any legacy "Compression" / "News Shock" values.
        return HMM_TO_RL.get(hmm_regime, hmm_regime)

    def _fallback_detect(self, symbol: str, data: Dict[str, Any]) -> str:
        rsi = data.get("rsi_14", 50.0)
        flow = data.get("institutional_flow", "NEUTRAL")
        volume = data.get("volume", 10000)
        macd = data.get("macd_hist", 0.0)
        atr = data.get("atr_14", 0.0)
        price = data.get("price", 1.0)
        
        atr_pct = (atr / price) * 100 if price > 0 else 0

        # ATR% thresholds below are calibrated for 1-MINUTE bars. Daily bars
        # carry ~10x the ATR%, so backtests pass bar_interval to scale them —
        # otherwise every daily bar classified as "News Shock" (High Volatility),
        # which forced the strictest consensus threshold and blocked all trades.
        _scale = {"1m": 1.0, "2m": 1.3, "5m": 2.0, "15m": 3.0, "30m": 4.0,
                  "60m": 5.0, "1h": 5.0, "90m": 6.0, "4h": 8.0,
                  "1d": 10.0, "5d": 18.0, "1wk": 25.0, "1mo": 45.0}.get(
            str(data.get("bar_interval", "1m")).lower(), 1.0)

        if atr_pct > 0.5 * _scale:
            return "News Shock"
        elif rsi > 70 and macd > 0 and flow == "BULLISH":
            return "Strong Trend Bull"
        elif rsi > 60 and macd > 0:
            return "Weak Trend Bull"
        elif rsi < 30 and macd < 0 and flow == "BEARISH":
            return "Strong Trend Bear"
        elif rsi < 40 and macd < 0:
            return "Weak Trend Bear"
        elif 45 <= rsi <= 55 and atr_pct < 0.1 * _scale:
            return "Compression"
        elif atr_pct > 0.3 * _scale:
            return "Expansion"
        elif volume > 50000:
            return "High Liquidity"
        elif volume < 5000:
            return "Low Liquidity"
        else:
            return "Gap Day"


class MultiTimeframeAnalyzer:
    """
    Feature 6: Multi-Timeframe Consensus — real RSI pulled from Yahoo Finance
    for Daily, 4H, 1H, and 15m intervals. Never trade from one chart.
    """

    TIMEFRAMES = [
        ("Daily",  "1d",   "3mo"),
        ("4H",     "4h",   "1mo"),
        ("1H",     "1h",   "5d"),
        ("15m",    "15m",  "2d"),
    ]

    def __init__(self):
        self._cache: Dict[tuple, tuple] = {}  # Key: (symbol, tf_name) -> (rsi_value, expiry, cached_price)
        self._executor = ThreadPoolExecutor(max_workers=4)
        self.ttls = {
            "Daily": 3600,   # 1 hour
            "4H": 1800,      # 30 minutes
            "1H": 600,       # 10 minutes
            "15m": 180,      # 3 minutes
        }

    def check_alignment(self, symbol: str, target_direction: str, tick_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetches real OHLCV for each timeframe from Yahoo Finance and computes RSI.
        Uses concurrent thread pool and cached timeframes to eliminate sequential latency.
        Invalidates cached timeframe data if the price has moved significantly (>= 0.4%)
        since the cache was created, preventing stale data risk in highly volatile periods.
        """
        alignment: Dict[str, str] = {}
        rsi_readings: Dict[str, float] = {}
        now = time.time()
        current_price = tick_data.get("price")

        # Check cache and collect misses
        to_fetch = []
        for tf_name, interval, period in self.TIMEFRAMES:
            cache_key = (symbol, tf_name)
            if cache_key in self._cache:
                cache_entry = self._cache[cache_key]
                # Dynamic compatibility for old cache format
                if len(cache_entry) == 3:
                    val, expiry, cached_price = cache_entry
                else:
                    val, expiry = cache_entry
                    cached_price = None

                # Calculate price divergence to protect against stale data under high volatility
                price_moved_significantly = False
                if cached_price and current_price:
                    ttl = self.ttls.get(tf_name, 180)
                    cache_age = now - (expiry - ttl)
                    # Enforce a minimum cache lifetime of 30 seconds to prevent thrashing
                    if cache_age >= 30:
                        price_diff_pct = abs(current_price - cached_price) / cached_price
                        if price_diff_pct >= 0.004:  # 0.4% threshold
                            price_moved_significantly = True

                if now < expiry and not price_moved_significantly:
                    rsi_readings[tf_name] = val
                    continue
            to_fetch.append((tf_name, interval, period))

        # Fetch misses concurrently
        if to_fetch:
            futures = {
                self._executor.submit(_fetch_rsi_for_interval, symbol, interval, period): tf_name
                for tf_name, interval, period in to_fetch
            }
            for fut in futures:
                tf_name = futures[fut]
                try:
                    tf_rsi = fut.result()
                except Exception:
                    tf_rsi = 50.0
                rsi_readings[tf_name] = tf_rsi
                
                # Update cache with current price for future invalidation checks
                ttl = self.ttls.get(tf_name, 180)
                self._cache[(symbol, tf_name)] = (tf_rsi, now + ttl, current_price)

        # Build alignment mappings
        for tf_name, _, _ in self.TIMEFRAMES:
            tf_rsi = rsi_readings.get(tf_name, 50.0)
            if target_direction == "BULLISH":
                # Bullish on this TF if RSI not overbought (not > 68)
                direction = "BULLISH" if tf_rsi < 68 else "BEARISH"
            else:
                # Bearish on this TF if RSI not oversold (not < 32)
                direction = "BEARISH" if tf_rsi > 32 else "BULLISH"
            alignment[tf_name] = direction

        # Check alignment using a weighted scoring system instead of unanimous veto
        # Daily = 3 pts, 4H = 2 pts, 1H = 1 pt, 15m = 1 pt. Total = 7 pts. Threshold = 5 pts.
        score = 0
        weights = {"Daily": 3, "4H": 2, "1H": 1, "15m": 1}
        
        for tf, d in alignment.items():
            if d == target_direction:
                score += weights.get(tf, 1)

        is_aligned = score >= 5
        conflicts = [tf for tf, d in alignment.items() if d != target_direction]

        return {
            "symbol": symbol,
            "is_aligned": is_aligned,
            "target_direction": target_direction,
            "breakdown": alignment,
            "rsi_by_timeframe": rsi_readings,
            "conflicts": conflicts,
            "score": score,
            "reason": (
                "✅ MTF Aligned (Score: {}/7) — macro trends support setup.".format(score)
                if is_aligned
                else f"⚠️ MTF Conflict (Score: {score}/7). Dragged down by {', '.join(conflicts)}. (Daily alignment is mathematically required to pass)."
            ),
            "data_source": "Yahoo Finance (real)"
        }
