"""
Live MetaGate Machine Learning Veto Gate (Multi-Asset Institutional Architecture).

Scope: 14 financial assets across 5 markets (US Futures, Indian Equities/ETFs,
US Tech Stocks, 24/7 Crypto, and Global Forex), each with an asset-specific
RandomForestClassifier / GradientBoosting meta-labeling model in backend/data/models/.

The model acts strictly as a VETO FILTER: it identifies unfavorable macro regimes
to skip, enforcing high-conviction probability P(win) >= GATE_THRESHOLD (0.65).
Signals below threshold are blocked from execution.

Fail-open design: if an individual model file, data feed, or feature calculation is
unavailable for a symbol, p_win returns None and the caller proceeds normally — the
gate only ever filters trades, never adds risk.

Feature parity: features are computed dynamically using feature_lab helpers
and aligned with each model's saved feature order. Models are retrained weekly via AutoML.
"""

import os
import time
import threading
from typing import Optional

import numpy as np

from analytics.feature_lab import (
    _daily, _close_series, _wilder_rsi, _macd_hist, _atr_pct,
)
from analytics.meta_label import MODEL_PATH, get_model_path

# Sniper Meta-Gate: require high-conviction probability P(win) >= 0.65 to pass trades
GATE_THRESHOLD = 0.65
_P_CACHE_TTL   = 900.0     # 15 min — inputs are daily series; p moves slowly



class MetaGate:
    _inst = None
    _lock = threading.Lock()

    def __init__(self):
        self._models = {}           # symbol -> (model, features)
        self._load_failed = set()   # symbols that failed loading
        self._p_cache = {}          # symbol -> (p, fetched_at)

    @classmethod
    def instance(cls) -> "MetaGate":
        with cls._lock:
            if cls._inst is None:
                cls._inst = MetaGate()
            return cls._inst

    def _ensure_loaded(self, symbol: str) -> bool:
        sym_key = symbol.upper()
        if sym_key in self._models:
            return True
        if sym_key in self._load_failed:
            return False

        # Attempt to load symbol-specific model, with fallback to meta_btc if BTC
        candidate_paths = [get_model_path(symbol)]
        if sym_key == "BTC-USD":
            candidate_paths.append(MODEL_PATH)

        for path in candidate_paths:
            if os.path.exists(path):
                try:
                    import joblib
                    art = joblib.load(path)
                    self._models[sym_key] = (art["model"], art["features"])
                    print(f"[MetaGate] Loaded {os.path.basename(path)} for {symbol} "
                          f"({len(art['features'])} features, trained rows {art.get('trained_rows')})")
                    return True
                except Exception as e:
                    print(f"[MetaGate] Error loading {path}: {e}")

        # Model not available — fail-open
        self._load_failed.add(sym_key)
        return False

    def _current_features(self, symbol: str) -> Optional[dict]:
        """Latest feature row, computed identically to training (feature_lab)."""
        try:
            df = _daily(symbol, "1y")
            if df is None or len(df) < 60:
                return None
            close = df["Close"]
            vol = df["Volume"].fillna(0)
            feats = {
                "rsi":       float(_wilder_rsi(close).iloc[-1]),
                "macd_hist": float((_macd_hist(close) / close).iloc[-1]),
                "atr_pct":   float(_atr_pct(df).iloc[-1]),
                "ret_5d":    float(close.pct_change(5).iloc[-1]),
                "vol_z":     float((((vol - vol.rolling(20).mean()) /
                                     vol.rolling(20).std().replace(0, np.nan))
                                    .fillna(0)).iloc[-1]),
            }
            vix   = _close_series("^VIX", "6mo")
            vix3m = _close_series("^VIX3M", "6mo")
            if vix is not None and len(vix) >= 5:
                feats["vix_lvl"] = float(vix.iloc[-1])
                if vix3m is not None and len(vix3m) >= 5:
                    feats["vix_ts"] = float(vix3m.iloc[-1] - vix.iloc[-1])
                else:
                    feats["vix_ts"] = 0.0
            else:
                feats["vix_lvl"] = 18.0
                feats["vix_ts"] = 0.0

            tnx = _close_series("^TNX", "6mo")
            irx = _close_series("^IRX", "6mo")
            if tnx is not None and irx is not None and len(tnx) >= 6 and len(irx) >= 6:
                ys = (tnx - irx).dropna()
                feats["yield_spread"]      = float(ys.iloc[-1])
                feats["yield_spread_mom5"] = float(ys.iloc[-1] - ys.iloc[-6]) if len(ys) > 6 else 0.0
            else:
                feats["yield_spread"] = 0.5
                feats["yield_spread_mom5"] = 0.0

            return feats
        except Exception as e:
            print(f"[MetaGate] Feature computation failed for {symbol}: {e}")
            return None

    def p_win(self, symbol: str = "BTC-USD") -> Optional[float]:
        """P(profit barrier before stop) for a trade entered now.
        None → caller must fail open (no veto). Synchronous & network-bound:
        call via asyncio.to_thread from the event loop."""
        sym_key = symbol.upper()
        now = time.time()
        cached = self._p_cache.get(sym_key)
        if cached and now - cached[1] < _P_CACHE_TTL:
            return cached[0]

        if not self._ensure_loaded(symbol):
            return None

        feats = self._current_features(symbol)
        if feats is None:
            return None

        try:
            model, features = self._models[sym_key]
            row = [feats.get(f, 0.0) for f in features]
            if any(v is None or not np.isfinite(v) for v in row):
                return None
            p = float(model.predict_proba(np.array([row]))[0, 1])
            self._p_cache[sym_key] = (p, now)
            return p
        except Exception as e:
            print(f"[MetaGate] predict failed for {symbol}: {e}")
            return None
