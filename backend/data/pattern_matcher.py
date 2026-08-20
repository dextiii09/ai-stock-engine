"""
Historical Pattern Matcher using real OHLCV data from Yahoo Finance.
Builds a live database of real historical setups and their outcomes.
"""
import yfinance as yf
import pandas as pd
from typing import Dict, Any, List


class HistoricalPatternMatcher:
    """
    Feature 16: Historical Pattern Search.
    Downloads real 6-month daily OHLCV from Yahoo Finance,
    computes RSI + MACD for each bar, then finds similar past setups
    and measures what happened 5 bars later.
    """

    SYMBOLS = ["MGC=F", "MNQ=F"]

    def __init__(self):
        self._db: List[Dict] = []
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
            
        # Fetch macro data for the same period
        try:
            dxy = yf.Ticker("DX-Y.NYB").history(period="6mo", interval="1d")["Close"]
            vix = yf.Ticker("^VIX").history(period="6mo", interval="1d")["Close"]
            tyx = yf.Ticker("^TYX").history(period="6mo", interval="1d")["Close"]
        except Exception:
            dxy, vix, tyx = pd.Series(), pd.Series(), pd.Series()

        for sym in self.SYMBOLS:
            try:
                df = yf.Ticker(sym).history(period="6mo", interval="1d")
                if df is None or df.empty or len(df) < 30:
                    continue
                df = self._compute_indicators(df)
                
                # Align macro data
                df["dxy"] = dxy
                df["vix"] = vix
                df["tyx"] = tyx
                # Forward fill any missing macro data
                df = df.ffill().bfill()
                
                self._extract_patterns(sym, df)
            except Exception as e:
                print(f"Error loading {sym}: {e}")
                continue
        self._loaded = True

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        # RSI-14
        delta = df["Close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, float("nan"))
        df["rsi"] = 100 - (100 / (1 + rs))

        # MACD histogram = MACD Line − Signal Line (not just MACD Line)
        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        df["macd_hist"] = macd_line - signal_line

        # Volume z-score (volume spike detection)
        df["vol_zscore"] = (df["Volume"] - df["Volume"].rolling(20).mean()) / df["Volume"].rolling(20).std()
        df["vol_zscore"] = df["vol_zscore"].fillna(0)
        return df.dropna()

    def _extract_patterns(self, symbol: str, df: pd.DataFrame):
        """For each bar, record the setup and what happened 5 bars later."""
        from .macro_classifier import MacroRegimeClassifier
        classifier = MacroRegimeClassifier()
        
        closes = df["Close"].values
        dxy = df["dxy"].values
        vix = df["vix"].values
        tyx = df["tyx"].values
        
        for i in range(5, len(df) - 5): # start at 5 to allow 5-day momentum
            rsi = float(df["rsi"].iloc[i])
            macd = float(df["macd_hist"].iloc[i])
            vol_z = float(df["vol_zscore"].iloc[i])
            
            # Compute macro metrics for classification
            dxy_mom = float(dxy[i] - dxy[i-5]) if not pd.isna(dxy[i]) else 0.0
            tyx_trend = float(tyx[i] - tyx[i-2]) if not pd.isna(tyx[i]) else 0.0
            vix_val = float(vix[i]) if not pd.isna(vix[i]) else 15.0
            
            macro_data = {
                "dxy_momentum": dxy_mom,
                "vix_level": vix_val,
                "real_yield_10y_trend": tyx_trend
            }
            regime = classifier.classify(macro_data)
            
            future_return = (closes[i + 5] - closes[i]) / closes[i]
            outcome = "UP" if future_return > 0.005 else "DOWN" if future_return < -0.005 else "FLAT"
            self._db.append({
                "symbol": symbol,
                "rsi": rsi,
                "macd_positive": macd > 0,
                "volume_spike": vol_z > 1.5,
                "macro_regime": regime,
                "outcome": outcome,
                "future_return_pct": round(future_return * 100, 3)
            })

    def find_similar(self, tick_data: Dict[str, Any], top_k: int = 50) -> Dict[str, Any]:
        """
        Finds the top_k real historical setups most similar to the current tick.
        Returns historical win probability.
        """
        self._ensure_loaded()

        if not self._db:
            return {
                "similar_patterns_found": 0,
                "went_up_count": 0,
                "went_down_count": 0,
                "historical_win_probability": 50.0,
                "historical_loss_probability": 50.0,
                "recommendation": "WAIT",
                "data_source": "Yahoo Finance (real — loading)"
            }

        current_rsi = tick_data.get("rsi_14", 50.0)
        symbol = tick_data.get("symbol", "MNQ=F")
        current_macro_regime = tick_data.get("macro_regime", "Risk-On")
        
        # Feature 7: Gold RSI overbought threshold adjustment
        # Gold often stays overbought in strong trending regimes longer than equities.
        # Cap the effective matching RSI so we don't penalize high-RSI Gold setups.
        if symbol == "MGC=F" and current_rsi > 70.0:
            current_rsi = min(current_rsi, 75.0)
            
        current_macd_pos = tick_data.get("macd_hist", 0.0) > 0
        current_flow = tick_data.get("institutional_flow", "NEUTRAL")
        current_vol_spike = current_flow == "BULLISH"

        # Score each historical pattern by similarity
        # Strictly filter by the same macro regime
        scored = []
        for entry in self._db:
            if entry.get("macro_regime") != current_macro_regime:
                continue
                
            rsi_sim = max(0.0, 1 - abs(entry.get("rsi", 50) - current_rsi) / 100)
            macd_sim = 1.0 if entry["macd_positive"] == current_macd_pos else 0.3
            vol_sim = 1.0 if entry["volume_spike"] == current_vol_spike else 0.5
            similarity = (rsi_sim * 0.5) + (macd_sim * 0.3) + (vol_sim * 0.2)
            scored.append((similarity, entry["outcome"], entry["future_return_pct"]))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        up_count = sum(1 for _, o, _ in top if o == "UP")
        down_count = sum(1 for _, o, _ in top if o == "DOWN")
        avg_return = sum(r for _, _, r in top) / len(top) if top else 0

        win_prob = round(up_count / max(len(top), 1) * 100, 1)

        return {
            "similar_patterns_found": len(top),
            "database_size": len(self._db),
            "went_up_count": up_count,
            "went_down_count": down_count,
            "historical_win_probability": win_prob,
            "historical_loss_probability": round(100 - win_prob, 1),
            "avg_5day_return_pct": round(avg_return, 3),
            "recommendation": "BUY" if win_prob >= 57 else "SELL" if win_prob <= 43 else "WAIT",
            "data_source": f"Yahoo Finance (real — {len(self._db)} bars)"
        }
