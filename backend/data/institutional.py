"""
Institutional Data via Yahoo Finance (free tier).

DATA QUALITY WARNING — READ BEFORE TRUSTING SIGNALS
====================================================
yfinance `institutional_holders` is sourced from 13F SEC filings.
  - Filing deadline: 45 days after quarter-end.
  - Typical data age: 45–135 days stale.
  - This is NOT real-time FII/DII flow data.
  - MacroEconomicAgent (weight ~1.82) votes on this quarterly snapshot.

What this module ACTUALLY provides:
  - Quarterly 13F holdings snapshot (% ownership, top-5 holders)
  - Real-time Put/Call Ratio from live options chain ← only fresh signal
  - Beta from trailing price history
  - Volume/price-action "smart money bias" proxy

The signal is useful as a long-horizon structural indicator, NOT as a
real-time flow detector. Do not interpret it as same-day FII/DII buying.
"""
import yfinance as yf
from typing import Dict, Any, List


def _safe_get(ticker: Any, attr: str, default=None):
    try:
        return getattr(ticker, attr)
    except Exception:
        return default


class InstitutionalTracker:
    """
    Feature 5: Institutional Money Tracking — 100% real data via Yahoo Finance.
    """

    def get_institutional_flows(self, symbol: str) -> Dict[str, Any]:
        """
        Returns real institutional data for a symbol from Yahoo Finance:
        - Top institutional holders and % ownership
        - Real Put/Call Ratio from options chain
        - Real beta (proxy for institutional exposure)
        - Real earnings date
        - Smart money bias inferred from volume and price action
        """
        sym = symbol.upper()
        ticker = yf.Ticker(sym)

        # 1. Real institutional holders
        holders = _safe_get(ticker, "institutional_holders")
        top_holders = []
        if holders is not None and not holders.empty:
            for _, row in holders.head(5).iterrows():
                top_holders.append({
                    "holder": str(row.get("Holder", "Unknown")),
                    "shares": int(row.get("Shares", 0)),
                    "pct_out": round(float(row.get("% Out", 0)) * 100, 2)
                })

        inst_pct = 0.0
        if holders is not None and not holders.empty and "% Out" in holders.columns:
            inst_pct = round(float(holders["% Out"].sum()) * 100, 2)

        # 2. Real Options Chain — Put/Call Ratio
        pcr = None
        pcr_signal = "NEUTRAL"
        oi_data = {}
        try:
            expirations = ticker.options
            if expirations:
                chain = ticker.option_chain(expirations[0])
                total_call_oi = int(chain.calls["openInterest"].sum()) if not chain.calls.empty else 0
                total_put_oi = int(chain.puts["openInterest"].sum()) if not chain.puts.empty else 0
                # Both legs must have data — a zero call OI (non-optionable symbols) must
                # not produce a false-bullish signal (0.0 pcr < 0.7 → "BULLISH").
                if total_call_oi > 0 and total_put_oi > 0:
                    pcr = round(total_put_oi / total_call_oi, 3)
                    pcr_signal = "BEARISH" if pcr > 1.2 else "BULLISH" if pcr < 0.7 else "NEUTRAL"
                else:
                    pcr = 0.0
                    pcr_signal = "NEUTRAL"
                oi_data = {"calls_oi": total_call_oi, "puts_oi": total_put_oi}
        except Exception:
            pass

        # 3. Real fundamentals
        info = _safe_get(ticker, "info") or {}
        beta = info.get("beta", None)
        short_float = info.get("shortPercentOfFloat")
        short_ratio = info.get("shortRatio")

        # 4. Real earnings calendar
        earnings_date = None
        try:
            cal = ticker.calendar
            if cal is not None and not cal.empty:
                dates = cal.get("Earnings Date", [])
                dates_list = list(dates) if hasattr(dates, "__iter__") else []
                if dates_list:
                    earnings_date = str(dates_list[0])
        except Exception:
            pass

        # 5. Smart money bias from volume profile
        history = None
        try:
            history = ticker.history(period="5d", interval="1h")
        except Exception:
            pass

        delivery_pct = None
        vwap_position = "UNKNOWN"
        smart_money_bias = "NEUTRAL"
        if history is not None and not history.empty:
            recent_vol = history["Volume"].tail(5).mean()
            latest_vol = history["Volume"].iloc[-1]
            latest_close = history["Close"].iloc[-1]
            # VWAP over last 5 hours
            vol_sum = history["Volume"].tail(5).sum()
            vwap = (history["Close"].tail(5) * history["Volume"].tail(5)).sum() / vol_sum if vol_sum > 0 else history["Close"].tail(5).mean()
            vwap_position = "ABOVE_VWAP" if latest_close > vwap else "BELOW_VWAP"

            # Infer smart money direction from volume spike + VWAP
            if latest_vol > recent_vol * 1.5 and vwap_position == "ABOVE_VWAP":
                smart_money_bias = "BULLISH"
            elif latest_vol > recent_vol * 1.5 and vwap_position == "BELOW_VWAP":
                smart_money_bias = "BEARISH"
            elif pcr_signal == "BULLISH":
                smart_money_bias = "BULLISH"
            elif pcr_signal == "BEARISH":
                smart_money_bias = "BEARISH"

        return {
            "symbol": sym,
            "smart_money_bias": smart_money_bias,
            "institutional_ownership_pct": inst_pct,
            "top_holders": top_holders,
            "beta": beta,
            "short_float_pct": round(short_float * 100, 2) if short_float else None,
            "short_ratio": short_ratio,
            "earnings_date": earnings_date,
            "options_chain": {
                "put_call_ratio": pcr,
                "pcr_signal": pcr_signal,
                **oi_data
            },
            "vwap_position": vwap_position,
            "data_source": "Yahoo Finance (real)"
        }

    def get_market_wide_flows(self) -> Dict[str, Any]:
        """
        Returns market-wide institutional flow proxy using real data.
        MNQ=F = broad market proxy. MGC=F = safe haven proxy.
        """
        flows = {}
        most_bought = []
        most_sold = []

        for etf in ["MGC=F", "MNQ=F"]:
            try:
                t = yf.Ticker(etf)
                hist = t.history(period="5d", interval="1d")
                if hist is not None and len(hist) >= 2:
                    five_day_change = (hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100
                    flows[etf] = round(five_day_change, 2)
                    if five_day_change > 0.5:
                        most_bought.append(etf)
                    elif five_day_change < -0.5:
                        most_sold.append(etf)
            except Exception:
                continue

        # Market trend from MNQ=F 5-day change
        nq_change = flows.get("MNQ=F", 0)
        market_trend = "ACCUMULATION" if nq_change > 0 else "DISTRIBUTION"

        return {
            "market_trend": market_trend,
            "etf_5day_flows": flows,
            "most_bought_etfs": most_bought,
            "most_sold_etfs": most_sold,
            "nq_5day_change_pct": nq_change,
            "data_source": "Yahoo Finance (real)"
        }
