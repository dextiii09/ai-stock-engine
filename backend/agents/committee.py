import yfinance as yf
from typing import Dict, Any
from .base_agent import BaseAgent


def _fetch_info(symbol: str) -> Dict:
    """Fetch real company fundamentals from Yahoo Finance (free)."""
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


# ATR%-based thresholds below are calibrated for 1-MINUTE bars (live loop).
# ATR grows roughly with sqrt(bar duration), so a daily bar carries ~10x the
# ATR% of a 1-min bar. Backtests pass data["bar_interval"] (e.g. "1d") so the
# volatility filters scale instead of tripping on EVERY historical bar —
# previously this made the AI Committee vote WAIT on all daily bars, producing
# 0-trade backtests and a flat equity curve.
_INTERVAL_ATR_SCALE: Dict[str, float] = {
    "1m": 1.0, "2m": 1.3, "5m": 2.0, "15m": 3.0, "30m": 4.0,
    "60m": 5.0, "1h": 5.0, "90m": 6.0, "4h": 8.0,
    "1d": 10.0, "5d": 18.0, "1wk": 25.0, "1mo": 45.0,
}


def _atr_interval_scale(data: Dict[str, Any]) -> float:
    """Multiplier for ATR%-based thresholds given the bar interval of `data`.
    Live ticks omit bar_interval → defaults to 1m → scale 1.0 (unchanged)."""
    return _INTERVAL_ATR_SCALE.get(str(data.get("bar_interval", "1m")).lower(), 1.0)


class TechnicalAgent(BaseAgent):
    """
    Technical Analyst — evaluates price action signals from real OHLCV data.
    Uses RSI, MACD, VWAP, and volume to determine signal.
    """
    def __init__(self):
        super().__init__("Technical Analyst")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        rsi = data.get("rsi_14", 50.0)
        macd = data.get("macd_hist", 0.0)
        price = data.get("price", 0.0)
        vwap = data.get("vwap", price)
        flow = data.get("institutional_flow", "NEUTRAL")
        atr = data.get("atr_14", 0.0)

        # Volatility filter — threshold varies by asset class because 1-minute ATR% for
        # crypto/tech stocks is structurally 5-10x higher than for futures/forex.
        # Using a flat 0.3% threshold would permanently block BTC (ATR%≈0.5-1.5%) and
        # NVDA (ATR%≈0.3-1.5%), leaving TechnicalAgent stuck on WAIT forever for those markets.
        _CRYPTO   = {"BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"}
        _TECH     = {"AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META"}
        if symbol in _CRYPTO:
            _atr_thresh = 0.020   # 2.0% — crypto is structurally high-ATR on 1-min bars
        elif symbol in _TECH:
            _atr_thresh = 0.015   # 1.5% — tech stocks trade with larger intraday swings
        elif symbol.endswith(".NS"):
            _atr_thresh = 0.008   # 0.8% — Indian equities (mid-range volatility)
        else:
            _atr_thresh = 0.003   # 0.3% — futures / forex (original calibration)
        _atr_thresh *= _atr_interval_scale(data)   # scale for daily/hourly backtest bars
        if price > 0 and atr > price * _atr_thresh:
            return {
                "signal": "WAIT",
                "confidence": 0.85,
                "reason": f"High volatility detected (ATR {atr:.2f} > {_atr_thresh*100:.1f}% of price). Halting technical entries."
            }

        # Real RSI-based signal logic
        # Extreme oversold/overbought: relax the MACD constraint — at RSI extremes,
        # MACD lags price and should not veto an obvious mean-reversion entry.
        #
        # VWAP proximity bands (±0.5% / ±0.2%) are 1-MINUTE calibrations: on a
        # 1-min chart price can dip to RSI 20 while holding near session VWAP.
        # On DAILY bars an RSI<20 selloff sits several percent below the 20-bar
        # rolling VWAP, so unscaled bands made these rules unreachable and the
        # agent voted WAIT on every backtest bar. Scale bands by bar interval.
        _s = _atr_interval_scale(data)
        _band_wide  = 0.005 * _s   # extreme-RSI band  (1m: 0.5%, 1d: 5%)
        _band_tight = 0.002 * _s   # moderate-RSI band (1m: 0.2%, 1d: 2%)
        if rsi < 20 and price > vwap * (1 - _band_wide):
            signal = "BUY"
            confidence = round(min((50 - rsi) / 30 + 0.45, 0.95), 2)
            reason = f"RSI extreme oversold ({rsi:.1f}) — mean reversion entry near VWAP."
        elif rsi > 80 and price < vwap * (1 + _band_wide):
            signal = "SELL"
            confidence = round(min((rsi - 50) / 30 + 0.45, 0.95), 2)
            reason = f"RSI extreme overbought ({rsi:.1f}) — mean reversion short near VWAP."
        elif rsi < 35 and macd > 0 and price > vwap * (1 - _band_tight):
            signal = "BUY"
            confidence = round(min((50 - rsi) / 30 + 0.3, 0.95), 2)
            reason = f"RSI oversold ({rsi:.1f}) with bullish MACD cross near VWAP. Demand zone entry."
        elif rsi > 65 and macd < 0 and price < vwap * (1 + _band_tight):
            signal = "SELL"
            confidence = round(min((rsi - 50) / 30 + 0.3, 0.95), 2)
            reason = f"RSI overbought ({rsi:.1f}) with bearish MACD near VWAP. Supply zone rejection."
        elif 40 <= rsi <= 60 and flow == "BULLISH" and macd > 0:
            signal = "BUY"
            confidence = 0.58
            reason = f"RSI neutral ({rsi:.1f}) with bullish institutional flow and positive MACD momentum."
        elif 40 <= rsi <= 60 and flow == "BEARISH" and macd < 0:
            signal = "SELL"
            confidence = 0.55
            reason = f"RSI neutral ({rsi:.1f}) with bearish institutional flow and negative MACD."
        else:
            signal = "WAIT"
            confidence = 0.30
            reason = f"RSI {rsi:.1f} — no clear price action signal. Waiting for setup."

        return {"signal": signal, "confidence": confidence, "reason": reason}


class FundamentalAgent(BaseAgent):
    """
    Fundamental Analyst — uses CFTC Commitment of Traders (COT) data.
    CommodityFundamentals for Gold, FuturesFundamentals for NQ.
    """
    def __init__(self):
        super().__init__("Fundamental Analyst")
        from data.cot_client import COTClient
        self.cot_client = COTClient()

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        cot_data = self.cot_client.get_for_symbol(symbol)
        positioning = cot_data.get("positioning", "NEUTRAL")
        
        confidence = 0.50
        signal = "WAIT"
        reasons = []

        if positioning == "STRONG_BULLISH":
            signal = "BUY"
            confidence = 0.85
            reasons.append("Hedge funds are heavily net long (COT Strong Bullish)")
        elif positioning == "BULLISH":
            signal = "BUY"
            confidence = 0.65
            reasons.append("Hedge funds are net long (COT Bullish)")
        elif positioning == "STRONG_BEARISH":
            signal = "SELL"
            confidence = 0.85
            reasons.append("Hedge funds are heavily net short (COT Strong Bearish)")
        elif positioning == "BEARISH":
            signal = "SELL"
            confidence = 0.65
            reasons.append("Hedge funds are net short (COT Bearish)")
        else:
            reasons.append("COT positioning is neutral")

        # Check for divergence with price momentum (RSI)
        rsi = data.get("rsi_14", 50.0)
        if signal == "BUY" and rsi < 40:
            reasons.append("Note: Price is bearish but institutional positioning is bullish (Accumulation)")
        elif signal == "SELL" and rsi > 60:
            reasons.append("Note: Price is bullish but institutional positioning is bearish (Distribution)")

        reason = " | ".join(reasons)
        return {"signal": signal, "confidence": confidence, "reason": reason}


class SentimentAgent(BaseAgent):
    """
    News & Sentiment AI — evaluates real news sentiment from the data layer.
    Uses VADER compound score passed through the tick_data pipeline.
    """
    def __init__(self):
        super().__init__("News & Sentiment AI")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        # Sentiment score from news pipeline (-1.0 to +1.0)
        sentiment = data.get("news_sentiment", 0.0)
        flow = data.get("institutional_flow", "NEUTRAL")

        if sentiment > 0.25 or flow == "BULLISH":
            signal = "BUY"
            # Use max(sentiment, 0) so negative sentiment lowers BUY confidence rather than
            # abs() which would give high BUY confidence even for deeply negative sentiment
            confidence = round(min(0.5 + max(sentiment, 0.0) * 0.5, 0.90), 2)
            reason = f"Positive news sentiment ({sentiment:+.2f}). Institutional flow: {flow}."
        elif sentiment < -0.25 or flow == "BEARISH":
            signal = "SELL"
            # Use max(-sentiment, 0) so positive sentiment lowers SELL confidence
            confidence = round(min(0.5 + max(-sentiment, 0.0) * 0.5, 0.90), 2)
            reason = f"Negative news sentiment ({sentiment:+.2f}). Institutional flow: {flow}."
        else:
            signal = "WAIT"
            confidence = 0.40
            reason = f"Neutral sentiment ({sentiment:+.2f}). No directional institutional signal."

        return {"signal": signal, "confidence": confidence, "reason": reason}


class MacroAgent(BaseAgent):
    """
    Macro Economic AI — instrument-specific logic.
    Gold: DXY, TIPS yields, London Fix window.
    NQ: VIX, Rollover week.
    """
    def __init__(self):
        super().__init__("Macro Economic AI")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        signal = "WAIT"
        confidence = 0.50
        reason = "No macro drivers detected."

        if symbol == "MGC=F":
            # Gold macro logic
            if data.get("is_london_fix_window"):
                return {
                    "signal": "WAIT",
                    "confidence": 0.80,
                    "reason": "London Fix window active (10:25-10:35 UTC). High liquidity-driven volatility expected. Waiting."
                }
                
            dxy_momentum = data.get("dxy_momentum", 0.0)
            yield_trend = data.get("real_yield_10y_trend", 0.0)
            
            # Gold is inversely correlated with DXY and Real Yields
            if dxy_momentum > 0.2 and yield_trend > 0.05:
                signal = "SELL"
                confidence = 0.75
                reason = f"DXY rising (+{dxy_momentum:.2f}) and Real Yields rising (+{yield_trend:.2f}). Strong macro headwinds for Gold."
            elif dxy_momentum < -0.2 and yield_trend < -0.05:
                signal = "BUY"
                confidence = 0.75
                reason = f"DXY falling ({dxy_momentum:.2f}) and Real Yields falling ({yield_trend:.2f}). Strong macro tailwinds for Gold."
            elif dxy_momentum > 0.4:
                signal = "SELL"
                confidence = 0.65
                reason = f"DXY surging (+{dxy_momentum:.2f}). Headwind for Gold."
            elif dxy_momentum < -0.4:
                signal = "BUY"
                confidence = 0.65
                reason = f"DXY dropping ({dxy_momentum:.2f}). Tailwind for Gold."
            else:
                signal = "WAIT"
                confidence = 0.50
                reason = "DXY and Real Yields are flat. No clear directional macro edge for Gold."

        elif symbol == "MNQ=F":
            # Nasdaq-100: VIX + rollover week
            vix = data.get("vix_level", 18.0)
            is_rollover = data.get("is_rollover_week", False)

            if vix > 30:
                signal = "SELL"
                confidence = 0.85
                reason = f"VIX at {vix:.1f} — high systemic fear. Significant macro risk for tech equities."
            elif vix > 20:
                signal = "WAIT"
                confidence = 0.70
                reason = f"VIX at {vix:.1f} — elevated volatility. Momentum strategies may bleed."
            else:
                signal = "BUY"
                confidence = 0.65
                reason = f"VIX at {vix:.1f} — low volatility regime. Favorable for structural NQ trend."

            if is_rollover:
                confidence = max(0.1, confidence - 0.20)
                reason += " (Rollover week: front-month liquidity dropping, expect noisy ATR)"

        elif symbol == "MES=F":
            # S&P 500: VIX + DXY (multinationals exposed to dollar strength)
            vix = data.get("vix_level", 18.0)
            dxy_momentum = data.get("dxy_momentum", 0.0)
            is_rollover = data.get("is_rollover_week", False)

            if vix > 28:
                signal = "SELL"
                confidence = 0.80
                reason = f"VIX at {vix:.1f} — systemic risk elevated. S&P 500 macro headwind."
            elif vix > 20:
                signal = "WAIT"
                confidence = 0.65
                reason = f"VIX at {vix:.1f} — caution zone. Waiting for volatility to compress."
            elif dxy_momentum > 0.5:
                signal = "WAIT"
                confidence = 0.60
                reason = f"DXY surging (+{dxy_momentum:.2f}) — dollar headwind for S&P multinationals."
            else:
                signal = "BUY"
                confidence = 0.62
                reason = f"VIX {vix:.1f}, DXY {dxy_momentum:+.2f} — favorable macro for S&P 500."

            if is_rollover:
                confidence = max(0.1, confidence - 0.15)
                reason += " (Rollover week: expect intraday ATR noise)"

        elif symbol == "MCL=F":
            # Crude Oil: DXY inverse + VIX risk-off = demand destruction
            dxy_momentum = data.get("dxy_momentum", 0.0)
            vix = data.get("vix_level", 18.0)

            if vix > 28 and dxy_momentum > 0.2:
                signal = "SELL"
                confidence = 0.80
                reason = f"Risk-off: VIX {vix:.1f} + DXY +{dxy_momentum:.2f}. Dual headwind for crude."
            elif dxy_momentum > 0.3:
                signal = "SELL"
                confidence = 0.70
                reason = f"DXY rising (+{dxy_momentum:.2f}) — dollar strength suppresses oil prices."
            elif dxy_momentum < -0.3 and vix < 20:
                signal = "BUY"
                confidence = 0.70
                reason = f"DXY weakening ({dxy_momentum:.2f}) in low-vol environment — tailwind for crude."
            elif vix > 25:
                signal = "WAIT"
                confidence = 0.65
                reason = f"VIX at {vix:.1f} — demand destruction fears. Crude macro ambiguous."
            else:
                signal = "WAIT"
                confidence = 0.50
                reason = "DXY and volatility neutral. No clear macro edge for crude oil."

        elif symbol == "M2K=F":
            # Russell 2000: VIX-sensitive small caps, domestic economy proxy
            vix = data.get("vix_level", 18.0)
            dxy_momentum = data.get("dxy_momentum", 0.0)
            is_rollover = data.get("is_rollover_week", False)

            if vix > 25:
                signal = "SELL"
                confidence = 0.82
                reason = f"VIX at {vix:.1f} — small caps highly vulnerable in risk-off. Russell macro headwind."
            elif vix > 18:
                signal = "WAIT"
                confidence = 0.65
                reason = f"VIX at {vix:.1f} — elevated. Small caps underperform in uncertain macro."
            elif dxy_momentum > 0.4:
                signal = "WAIT"
                confidence = 0.58
                reason = f"DXY rising (+{dxy_momentum:.2f}). Small cap caution warranted."
            else:
                signal = "BUY"
                confidence = 0.63
                reason = f"VIX low ({vix:.1f}), DXY stable — risk-on environment favors small cap momentum."

            if is_rollover:
                confidence = max(0.1, confidence - 0.15)
                reason += " (Rollover week: thin liquidity in small cap futures)"

        elif symbol in ("AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META"):
            # US Tech Stocks: VIX-driven + DXY headwind for multinationals
            vix = data.get("vix_level", 18.0)
            dxy_momentum = data.get("dxy_momentum", 0.0)

            if vix > 30:
                signal = "SELL"
                confidence = 0.85
                reason = f"VIX at {vix:.1f} — systemic fear. Tech equity selloff risk."
            elif vix > 22:
                signal = "WAIT"
                confidence = 0.68
                reason = f"VIX elevated ({vix:.1f}). Tech macro uncertain — wait for compression."
            elif dxy_momentum > 0.5 and symbol in ("AAPL", "MSFT", "AMZN", "META"):
                signal = "WAIT"
                confidence = 0.60
                reason = f"DXY surging (+{dxy_momentum:.2f}). Dollar headwind for multinational revenue."
            elif vix < 18 and dxy_momentum < 0.2:
                signal = "BUY"
                confidence = 0.68
                reason = f"VIX {vix:.1f} low + DXY stable ({dxy_momentum:+.2f}) — risk-on. Tech macro favorable."
            else:
                signal = "WAIT"
                confidence = 0.52
                reason = f"VIX {vix:.1f} — neutral tech macro environment."

        elif symbol in ("BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"):
            # Crypto: risk-sensitive — VIX spike + DXY surge = dual headwind
            vix = data.get("vix_level", 18.0)
            dxy_momentum = data.get("dxy_momentum", 0.0)

            if vix > 30:
                signal = "SELL"
                confidence = 0.88
                reason = f"VIX at {vix:.1f} — extreme risk-off. Crypto liquidity squeeze risk."
            elif vix > 22 and dxy_momentum > 0.3:
                signal = "SELL"
                confidence = 0.78
                reason = f"VIX {vix:.1f} + DXY +{dxy_momentum:.2f}. Dual macro headwind for crypto."
            elif dxy_momentum > 0.4:
                signal = "SELL"
                confidence = 0.68
                reason = f"DXY surging (+{dxy_momentum:.2f}). Dollar strength suppresses crypto prices."
            elif dxy_momentum < -0.3 and vix < 18:
                signal = "BUY"
                confidence = 0.72
                reason = f"DXY weakening ({dxy_momentum:.2f}) + risk-on (VIX {vix:.1f}). Crypto macro tailwind."
            elif vix < 15:
                signal = "BUY"
                confidence = 0.62
                reason = f"VIX {vix:.1f} — very low fear index. Risk assets including crypto are favored."
            else:
                signal = "WAIT"
                confidence = 0.50
                reason = f"VIX {vix:.1f}, DXY {dxy_momentum:+.2f} — neutral crypto macro."

        elif symbol.endswith("=X"):
            # Forex: DXY momentum drives pair direction; USDJPY has safe-haven overlay
            dxy_momentum = data.get("dxy_momentum", 0.0)
            vix = data.get("vix_level", 18.0)

            if symbol == "EURUSD=X":
                # EUR/USD inversely correlated with DXY
                if dxy_momentum > 0.3:
                    signal = "SELL"; confidence = 0.72
                    reason = f"DXY rising (+{dxy_momentum:.2f}) — bearish EURUSD."
                elif dxy_momentum < -0.3:
                    signal = "BUY"; confidence = 0.72
                    reason = f"DXY falling ({dxy_momentum:.2f}) — bullish EURUSD."
                else:
                    signal = "WAIT"; confidence = 0.50
                    reason = f"DXY flat ({dxy_momentum:+.2f}) — no directional macro edge for EURUSD."

            elif symbol == "GBPUSD=X":
                if dxy_momentum > 0.3:
                    signal = "SELL"; confidence = 0.70
                    reason = f"DXY rising (+{dxy_momentum:.2f}) — bearish GBPUSD."
                elif dxy_momentum < -0.3:
                    signal = "BUY"; confidence = 0.70
                    reason = f"DXY falling ({dxy_momentum:.2f}) — bullish GBPUSD."
                else:
                    signal = "WAIT"; confidence = 0.50
                    reason = f"DXY flat ({dxy_momentum:+.2f}) — no clear GBPUSD macro signal."

            elif symbol == "USDJPY=X":
                # USD/JPY: positively correlated with DXY, but JPY is safe haven (VIX spike = USDJPY falls)
                if vix > 25:
                    signal = "SELL"; confidence = 0.70
                    reason = f"VIX at {vix:.1f} — JPY safe-haven demand. USDJPY bearish."
                elif dxy_momentum > 0.3:
                    signal = "BUY"; confidence = 0.70
                    reason = f"DXY rising (+{dxy_momentum:.2f}) — bullish USDJPY."
                elif dxy_momentum < -0.3:
                    signal = "SELL"; confidence = 0.68
                    reason = f"DXY falling ({dxy_momentum:.2f}) — bearish USDJPY."
                else:
                    signal = "WAIT"; confidence = 0.50
                    reason = f"DXY flat + VIX {vix:.1f} — no directional edge for USDJPY."

            elif symbol == "AUDUSD=X":
                # AUD is risk-on commodity currency — DXY inverse + VIX sensitive
                if vix > 25 or dxy_momentum > 0.3:
                    signal = "SELL"; confidence = 0.70
                    reason = f"Risk-off (VIX {vix:.1f}) + DXY {dxy_momentum:+.2f}. Bearish for risk-sensitive AUD."
                elif vix < 15 and dxy_momentum < -0.2:
                    signal = "BUY"; confidence = 0.72
                    reason = f"Risk-on (VIX {vix:.1f}) + DXY falling ({dxy_momentum:.2f}). Bullish AUDUSD."
                else:
                    signal = "WAIT"; confidence = 0.50
                    reason = f"Neutral VIX {vix:.1f} / DXY {dxy_momentum:+.2f} — no clear AUDUSD macro edge."
            else:
                signal = "WAIT"; confidence = 0.50
                reason = f"Unknown forex pair {symbol}. No specific macro logic."

        elif symbol.endswith(".NS"):
            # Sector-specific Indian macro logic
            india_vix       = data.get("india_vix_level", 15.0)
            usdinr_momentum = data.get("usdinr_momentum", 0.0)
            nifty_above_ema = data.get("nifty_above_20ema", True)

            _IT_STOCKS   = {"TCS.NS", "INFY.NS"}
            _BANK_STOCKS = {"HDFCBANK.NS", "ICICIBANK.NS"}
            _GOLD_ETFS   = {"GOLDBEES.NS"}
            _INDEX_ETFS  = {"NIFTYBEES.NS", "BANKBEES.NS"}

            if symbol in _GOLD_ETFS:
                # GOLDBEES tracks gold — same drivers as MGC=F (DXY + real yields)
                dxy_momentum = data.get("dxy_momentum", 0.0)
                yield_trend  = data.get("real_yield_10y_trend", 0.0)
                if dxy_momentum < -0.2 and yield_trend < -0.05:
                    signal = "BUY"; confidence = 0.75
                    reason = f"DXY falling ({dxy_momentum:.2f}) + real yields falling. Gold ETF tailwind."
                elif dxy_momentum > 0.2 and yield_trend > 0.05:
                    signal = "SELL"; confidence = 0.75
                    reason = f"DXY rising (+{dxy_momentum:.2f}) + yields rising. Gold ETF headwind."
                else:
                    signal = "WAIT"; confidence = 0.50
                    reason = "No clear DXY/yield signal for GOLDBEES."

            elif symbol in _INDEX_ETFS:
                # NIFTYBEES/BANKBEES: India VIX + Nifty trend
                if india_vix > 22:
                    signal = "SELL"; confidence = 0.78
                    reason = f"India VIX at {india_vix:.1f} — elevated. Index ETF macro headwind."
                elif nifty_above_ema and india_vix < 16:
                    signal = "BUY"; confidence = 0.70
                    reason = f"India VIX low ({india_vix:.1f}) + Nifty above 20 EMA. Bullish macro."
                else:
                    signal = "WAIT"; confidence = 0.55
                    reason = f"India VIX {india_vix:.1f} — neutral. No clear macro edge."

            elif symbol in _IT_STOCKS:
                # IT stocks: USDINR momentum — rising INR hurts exporters
                if usdinr_momentum > 0.5:
                    signal = "BUY"; confidence = 0.70
                    reason = f"USDINR rising ({usdinr_momentum:+.2f}) — tailwind for IT exporters."
                elif usdinr_momentum < -0.5:
                    signal = "SELL"; confidence = 0.68
                    reason = f"USDINR falling ({usdinr_momentum:+.2f}) — headwind for IT exporters."
                else:
                    signal = "WAIT"; confidence = 0.50
                    reason = f"USDINR momentum flat ({usdinr_momentum:+.2f}). No clear IT macro edge."

            elif symbol in _BANK_STOCKS:
                # Bank stocks: India VIX + Nifty trend
                if india_vix < 16 and nifty_above_ema:
                    signal = "BUY"; confidence = 0.72
                    reason = f"India VIX low ({india_vix:.1f}) + Nifty trend bullish. Banks macro positive."
                elif india_vix > 20:
                    signal = "SELL"; confidence = 0.75
                    reason = f"India VIX elevated ({india_vix:.1f}) — banking sector macro stress."
                else:
                    signal = "WAIT"; confidence = 0.55
                    reason = f"India VIX {india_vix:.1f} neutral. No strong bank macro signal."

            else:
                # Other Indian stocks (RELIANCE, TATAMOTORS, etc.)
                if india_vix < 15 and nifty_above_ema:
                    signal = "BUY"; confidence = 0.62
                    reason = f"Broad India macro positive: VIX={india_vix:.1f}, Nifty in uptrend."
                elif india_vix > 22:
                    signal = "SELL"; confidence = 0.68
                    reason = f"India VIX elevated ({india_vix:.1f}) — broad market macro pressure."
                else:
                    signal = "WAIT"; confidence = 0.52
                    reason = f"India VIX {india_vix:.1f} — neutral macro environment."

        return {"signal": signal, "confidence": round(confidence, 2), "reason": reason}


class IndianInstitutionalFlowAgent(BaseAgent):
    """
    Indian Institutional Flow Agent — tracks FII/DII activity for Indian market.
    Uses FII net buy/sell data as a directional signal.
    """
    def __init__(self):
        super().__init__("India Institutional Flow")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if not symbol.endswith(".NS"):
            return {"signal": "WAIT", "confidence": 0.50,
                    "reason": "India Flow Agent: non-Indian symbol, inactive."}

        india_vix = data.get("india_vix_level", 15.0)

        # Prefer real FII/DII data if available (future live data feed integration)
        fii_net = data.get("fii_net_buys_cr", None)
        dii_net = data.get("dii_net_buys_cr", 0.0)

        if fii_net is not None:
            # Real FII data path
            if fii_net > 500 and dii_net > 200:
                conf = min(0.85, 0.65 + fii_net / 5000)
                return {"signal": "BUY", "confidence": round(conf, 2),
                        "reason": f"FII +{fii_net:.0f} Cr + DII +{dii_net:.0f} Cr — strong institutional accumulation."}
            if fii_net > 500:
                conf = min(0.78, 0.60 + fii_net / 5000)
                return {"signal": "BUY", "confidence": round(conf, 2),
                        "reason": f"FII net buying +{fii_net:.0f} Cr — foreign institutional accumulation."}
            if fii_net < -500 and india_vix > 18:
                return {"signal": "SELL", "confidence": 0.82,
                        "reason": f"FII net selling {fii_net:.0f} Cr + elevated VIX ({india_vix:.1f}) — institutional exit."}
            if fii_net < -300:
                return {"signal": "SELL", "confidence": 0.68,
                        "reason": f"FII net selling {fii_net:.0f} Cr — foreign institutional distribution."}
            if fii_net < -200 and dii_net > 400:
                return {"signal": "WAIT", "confidence": 0.60,
                        "reason": f"FII selling ({fii_net:.0f} Cr) offset by DII buying ({dii_net:.0f} Cr). Mixed flow."}
            return {"signal": "WAIT", "confidence": 0.52,
                    "reason": f"FII {fii_net:+.0f} Cr, DII {dii_net:+.0f} Cr — neutral institutional flow."}

        # Proxy path: Nifty 3-day return as FII flow proxy.
        # Strong Nifty gains + low VIX → FII accumulation likely.
        # Strong Nifty losses + elevated VIX → FII distribution likely.
        nifty_3d = data.get("nifty_3d_return", 0.0)

        if nifty_3d > 2.5 and india_vix < 17:
            return {"signal": "BUY", "confidence": 0.68,
                    "reason": f"Nifty 3d +{nifty_3d:.1f}% + VIX {india_vix:.1f} — FII accumulation proxy."}
        elif nifty_3d > 1.5:
            return {"signal": "BUY", "confidence": 0.60,
                    "reason": f"Nifty 3d +{nifty_3d:.1f}% — broad market strength, likely institutional buying."}
        elif nifty_3d < -2.5 and india_vix > 18:
            return {"signal": "SELL", "confidence": 0.70,
                    "reason": f"Nifty 3d {nifty_3d:.1f}% + VIX {india_vix:.1f} — FII exit proxy."}
        elif nifty_3d < -1.5:
            return {"signal": "SELL", "confidence": 0.60,
                    "reason": f"Nifty 3d {nifty_3d:.1f}% — broad market weakness, likely institutional distribution."}
        else:
            return {"signal": "WAIT", "confidence": 0.52,
                    "reason": f"Nifty 3d {nifty_3d:+.1f}% — neutral flow proxy."}


class RiskAgent(BaseAgent):
    """
    Risk Manager — acts as a final veto before any trade is executed.
    Monitors cash reserves and position concentration.

    IV&V finding 2026-08-21 (audit Finding #17): this agent previously also
    vetoed on `daily_pnl_pct < -3.0` and `max_drawdown_pct < -8.0`, but
    routes.py never populates either key in tick_data for any of the 5
    markets — those branches were permanently dead code, misleadingly
    implying this agent enforced a daily/drawdown circuit breaker. The real,
    working daily (3.0%) and weekly (6.0%) drawdown circuit breakers are
    enforced separately by GlobalRiskAggregator / portfolio_risk.analyze()
    at the loop level. Removed the dead branches rather than wiring in
    unused inputs — this agent's real job is cash/concentration, not
    duplicating the global circuit breaker.
    """
    def __init__(self):
        super().__init__("Risk Manager")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        cash_pct    = data.get("cash_pct", 100.0)
        open_trades = data.get("open_trade_count", 0)

        if cash_pct < 20.0:
            return {
                "signal": "VETO", "confidence": 0.99,
                "reason": f"Cash critically low ({cash_pct:.1f}%). Cannot allocate capital to new positions."
            }

        if open_trades >= 5:
            return {
                "signal": "VETO", "confidence": 0.95,
                "reason": f"Maximum concurrent positions reached ({open_trades}). Risk concentration too high."
            }

        return {
            "signal": "OK", "confidence": 0.90,
            "reason": f"Risk metrics within acceptable range. Cash: {cash_pct:.1f}%, Trades: {open_trades}."
        }


class VolatilityAgent(BaseAgent):
    """
    Volatility Regime Agent — assesses whether current volatility is tradable.
    High ATR spike = skip. Low vol regime = favorable for trend entries.
    """
    def __init__(self):
        super().__init__("Volatility Regime")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        atr      = data.get("atr_14", 0.0)
        price    = data.get("price", 1.0)
        hist_vol = data.get("hist_vol_20", 0.0)

        if price <= 0:
            return {"signal": "WAIT", "confidence": 0.50, "reason": "No price data available."}

        atr_pct = (atr / price) * 100

        # Thresholds vary by asset class — 1-min ATR% for crypto/tech is structurally
        # higher than for futures/forex. A flat 0.3% BUY ceiling permanently excludes
        # high-volatility assets from ever receiving a BUY vote from this agent.
        _CRYPTO = {"BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"}
        _TECH   = {"AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META"}
        if symbol in _CRYPTO:
            _high_thresh, _low_thresh = 3.0, 1.5   # BTC ATR% typically 0.5-2%
        elif symbol in _TECH:
            _high_thresh, _low_thresh = 2.0, 0.8   # Tech ATR% typically 0.3-1.5%
        elif symbol.endswith(".NS"):
            _high_thresh, _low_thresh = 1.5, 0.6   # Indian stocks (mid-range)
        else:
            _high_thresh, _low_thresh = 1.5, 0.3   # Futures / forex (original)

        _scale = _atr_interval_scale(data)          # scale for daily/hourly backtest bars
        _high_thresh *= _scale
        _low_thresh  *= _scale

        if atr_pct > _high_thresh:
            return {
                "signal": "WAIT", "confidence": 0.80,
                "reason": f"ATR spike detected ({atr_pct:.2f}% > {_high_thresh}%). Extreme intraday volatility — skipping entry."
            }
        elif hist_vol > 0.35:
            return {
                "signal": "WAIT", "confidence": 0.65,
                "reason": f"Historical volatility elevated ({hist_vol:.2f}). Reducing conviction for new entries."
            }
        elif atr_pct < _low_thresh and hist_vol < 0.15:
            return {
                "signal": "BUY", "confidence": 0.62,
                "reason": f"Low volatility regime (ATR {atr_pct:.2f}% < {_low_thresh}%, HV {hist_vol:.2f}). Favorable for trend entries."
            }

        return {"signal": "WAIT", "confidence": 0.50, "reason": f"Volatility neutral (ATR {atr_pct:.2f}%)."}


class LiquidityAgent(BaseAgent):
    """
    Liquidity Agent — uses volume Z-score to assess market depth.
    High volume = institutional activity. Low volume = thin market, avoid.
    """
    def __init__(self):
        super().__init__("Liquidity Agent")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        volume_z = data.get("volume_z", 0.0)
        # institutional_flow already encodes direction: BULLISH = spike above VWAP, BEARISH = below
        flow = data.get("institutional_flow", "NEUTRAL")

        if volume_z > 2.0:
            # Extreme volume spike — institutional-grade signal
            if flow == "BEARISH":
                return {
                    "signal": "SELL", "confidence": 0.80,
                    "reason": f"Volume spike below VWAP (Z={volume_z:.2f}). Institutional distribution — high conviction sell window."
                }
            return {
                "signal": "BUY", "confidence": 0.80,
                "reason": f"Volume spike above VWAP (Z={volume_z:.2f}). Institutional accumulation — high conviction buy window."
            }
        elif volume_z > 1.0:
            # Moderate volume elevation — meaningful but not extreme
            if flow == "BEARISH":
                return {
                    "signal": "SELL", "confidence": 0.65,
                    "reason": f"Above-average volume below VWAP (Z={volume_z:.2f}). Distribution signal — moderate sell conviction."
                }
            return {
                "signal": "BUY", "confidence": 0.65,
                "reason": f"Above-average volume above VWAP (Z={volume_z:.2f}). Accumulation signal — moderate buy conviction."
            }
        elif volume_z < -1.0:
            return {
                "signal": "WAIT", "confidence": 0.70,
                "reason": f"Below-average volume (Z={volume_z:.2f}). Thin liquidity — avoid new positions."
            }

        return {"signal": "WAIT", "confidence": 0.50,
                "reason": f"Volume neutral (Z={volume_z:.2f}). Liquidity is normal."}


class CorrelationAgent(BaseAgent):
    """
    Correlation Agent — evaluates GC/NQ (Gold-Nasdaq) correlation.
    High absolute correlation = fractured or risk-on consensus regime.
    """
    def __init__(self):
        super().__init__("Correlation Agent")

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        # Only US futures have meaningful GC/NQ correlation data.
        # Return WAIT for Indian stocks, US equities, crypto, and forex.
        _is_us_future = symbol.endswith("=F")
        if not _is_us_future:
            return {
                "signal": "WAIT", "confidence": 0.50,
                "reason": "Correlation Agent: non-futures symbol — GC/NQ correlation not applicable."
            }

        correlation_gc_nq = data.get("correlation_gc_nq", 0.0)

        if abs(correlation_gc_nq) > 0.8:
            return {
                "signal": "WAIT", "confidence": 0.85,
                "reason": f"GC/NQ correlation extreme ({correlation_gc_nq:.2f}). Macro regime unstable — elevated event risk."
            }

        return {
            "signal": "WAIT", "confidence": 0.60,
            "reason": f"GC/NQ correlation normal ({correlation_gc_nq:.2f}). No cross-asset warning."
        }
