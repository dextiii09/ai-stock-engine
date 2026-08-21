"""
Live meta-label veto gate (Phase 3 CONFIRMED -> deployed to paper).

Scope: BTC-USD LONG entries only — exactly what the model was trained and
validated on (CPCV 15/15 splits uplift-positive, mean +0.166R net of costs, DSR=1.0).
The model is a VETO FILTER: it identifies unfavorable macro regimes to skip
(Phase 2 calibration showed skill concentrated in the bottom quintiles), so
the only supported use is "block entries with P(win) < GATE_THRESHOLD (0.65)". It must NOT be
used to size up "high-confidence" trades — the top quintiles were not ranked
reliably.

Fail-open design: if the model file, data feeds, or feature computation are
unavailable, the gate returns None and the caller proceeds normally — the
gate can only ever remove trades, never add risk paths.

Feature parity: features are computed with the SAME functions used to build
the training dataset (analytics.feature_lab helpers) and ordered by the
feature list saved inside the joblib artifact.
"""


import os
import time
import threading
import logging as _logging
from typing import Optional

import numpy as np

_meta_logger = _logging.getLogger("ai_stock.meta_gate")

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
        self._load_failed = {}      # symbol -> failure_timestamp
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
            if time.time() - self._load_failed[sym_key] < 300.0:
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
                    _meta_logger.info(f"[MetaGate] Loaded {os.path.basename(path)} for {symbol} "
                                      f"({len(art['features'])} features, trained rows {art.get('trained_rows')})")
                    return True
                except Exception as e:
                    _meta_logger.warning(f"[MetaGate] Error loading {path}: {e}")

        # Model not available — fail-open
        self._load_failed[sym_key] = time.time()
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
                    _meta_logger.warning(f"[MetaGate] Missing VIX3M data for {symbol}. Failing open.")
                    return None
            else:
                _meta_logger.warning(f"[MetaGate] Missing VIX data for {symbol}. Failing open.")
                return None

            tnx = _close_series("^TNX", "6mo")
            irx = _close_series("^IRX", "6mo")
            if tnx is not None and irx is not None and len(tnx) >= 6 and len(irx) >= 6:
                ys = (tnx - irx).dropna()
                feats["yield_spread"]      = float(ys.iloc[-1])
                if len(ys) > 6:
                    feats["yield_spread_mom5"] = float(ys.iloc[-1] - ys.iloc[-6])
                else:
                    _meta_logger.warning(f"[MetaGate] Insufficient yield history for mom5, {symbol}. Failing open.")
                    return None
            else:
                _meta_logger.warning(f"[MetaGate] Missing yield curve data for {symbol}. Failing open.")
                return None

            return feats
        except Exception as e:
            _meta_logger.warning(f"[MetaGate] Feature computation failed for {symbol}: {e}")
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
            missing = [f for f in features if f not in feats]
            if missing:
                _meta_logger.warning(f"[MetaGate] missing features for {symbol}: {missing}")
                return None
            
            row = [feats[f] for f in features]
            if any(v is None or not np.isfinite(v) for v in row):
                return None
            p = float(model.predict_proba(np.array([row]))[0, 1])
            self._p_cache[sym_key] = (p, now)
            return p
        except Exception as e:
            _meta_logger.warning(f"[MetaGate] predict failed for {symbol}: {e}")
            return None
