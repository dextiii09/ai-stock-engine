"""
CFTC Commitment of Traders (COT) Client.
Replaces the legacy institutional.py (NSE FII/DII) which had no relevance
for Gold or Nasdaq futures.

Data source: CFTC Public Reporting Environment — tokenless, free, official.
  - Gold (XAUUSD proxy): Disaggregated COT, CFTC commodity code 088691
  - Nasdaq NQ futures: Traders in Financial Futures (TFF), CFTC code 209742

Updated every Friday at ~3:30 PM ET. This module caches for 24h.
"""
import time
import urllib.request
import json
from typing import Dict, Any, Optional

# CFTC Public API — no token required (Socrata endpoint)
_CFTC_BASE = "https://publicreporting.cftc.gov/resource"

# Gold Futures — Disaggregated COT report
_GOLD_COMMODITY_CODE = "088691"
# Nasdaq 100 E-Mini — TFF report (Traders in Financial Futures)
_NQ_COMMODITY_CODE = "209742"

# 24-hour cache
_CACHE: Dict[str, Any] = {}
_CACHE_EXPIRY: Dict[str, float] = {}
_CACHE_TTL = 86400  # 24 hours in seconds


def _fetch_cot(commodity_code: str, report_type: str = "disaggregated") -> Optional[Dict]:
    """
    Fetches the most recent COT report entry for a given commodity code.
    report_type: "disaggregated" for Gold, "tff" for NQ (financial futures).
    """
    import urllib.parse
    import ssl

    cache_key = f"{commodity_code}_{report_type}"
    now = time.time()

    if cache_key in _CACHE and now < _CACHE_EXPIRY.get(cache_key, 0):
        return _CACHE[cache_key]

    # CFTC Socrata API endpoint (Updated Dataset IDs)
    if report_type == "tff":
        # Traders in Financial Futures (TFF Combined)
        endpoint = f"{_CFTC_BASE}/yw9f-hn96.json"
    else:
        # Disaggregated Futures and Options Combined
        endpoint = f"{_CFTC_BASE}/kh3c-gbw2.json"

    # URL construction (avoid urlencoding the Socrata $ syntax as some endpoints reject %24)
    socrata_params = {
        "cftc_contract_market_code": commodity_code
    }
    encoded_params = urllib.parse.urlencode(socrata_params)
    # Keep SODA system parameters raw to avoid escaping $ symbol
    params_str = f"{encoded_params}&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=1"
    url = f"{endpoint}?{params_str}"

    failure_ttl = 120  # Default to 2 minutes for transient network/server/rate-limit errors
    try:
        # Use the default verified SSL context (not _create_unverified_context).
        # The Socrata CFTC endpoint uses a valid certificate — no need to skip verification.
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "AiStock/1.0"})
        with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
            data = json.loads(response.read().decode())
            if data and len(data) > 0:
                _CACHE[cache_key] = data[0]
                _CACHE_EXPIRY[cache_key] = now + _CACHE_TTL
                return data[0]
            else:
                print(f"[COT] Empty response for {commodity_code}")
    except urllib.error.HTTPError as e:
        # Permanent client errors (like 400 Bad Request or 404 Not Found) won't recover by retrying,
        # so cache for 10 minutes (600s) to limit lockout in case of misclassification.
        # Transient server or rate-limiting errors (like 429, 5xx) default to 2 mins (120s).
        if e.code in (400, 404):
            failure_ttl = 600
            print(f"[COT] Permanent HTTP Error {e.code} for {commodity_code}: {e.reason} - Cached for 10 mins. URL: {url}")
        else:
            failure_ttl = 120
            print(f"[COT] Transient HTTP Error {e.code} for {commodity_code}: {e.reason} - Cached for 2 mins (will retry). URL: {url}")
    except Exception as e:
        print(f"[COT] Failed to fetch CFTC data for {commodity_code}: {e} - Cached for 2 mins (will retry).")
        # Dns timeouts, connection errors, URLErrors, etc. are transient, so cache for 2 minutes.

    # Cache the failure
    _CACHE[cache_key] = None
    _CACHE_EXPIRY[cache_key] = now + failure_ttl
    return None


def _parse_gold_cot(raw: Dict) -> Dict[str, Any]:
    """Parse Disaggregated COT for Gold — extract Managed Money positioning."""
    try:
        mm_long = int(raw.get("m_money_positions_long_all", 0))
        mm_short = int(raw.get("m_money_positions_short_all", 0))
        mm_net = mm_long - mm_short
        report_date = raw.get("report_date_as_yyyy_mm_dd", "unknown")

        # Positioning signal — net > 0 means hedge funds are net long Gold
        if mm_net > 50000:
            positioning = "STRONG_BULLISH"
        elif mm_net > 10000:
            positioning = "BULLISH"
        elif mm_net < -50000:
            positioning = "STRONG_BEARISH"
        elif mm_net < -10000:
            positioning = "BEARISH"
        else:
            positioning = "NEUTRAL"

        return {
            "symbol": "MGC=F",
            "report_type": "Disaggregated COT",
            "report_date": report_date,
            "mm_long": mm_long,
            "mm_short": mm_short,
            "mm_net": mm_net,
            "positioning": positioning,
            "data_source": "CFTC Official (tokenless)"
        }
    except Exception as e:
        return _fallback("MGC=F", f"Parse error: {e}")


def _parse_nq_cot(raw: Dict) -> Dict[str, Any]:
    """Parse TFF COT for NQ — extract Leveraged Funds (hedge fund) positioning."""
    try:
        # TFF report uses "lev_money" fields for Leveraged Funds (hedge funds)
        lf_long = int(raw.get("lev_money_positions_long", 0))
        lf_short = int(raw.get("lev_money_positions_short", 0))
        lf_net = lf_long - lf_short
        report_date = raw.get("report_date_as_yyyy_mm_dd", "unknown")

        if lf_net > 20000:
            positioning = "STRONG_BULLISH"
        elif lf_net > 5000:
            positioning = "BULLISH"
        elif lf_net < -20000:
            positioning = "STRONG_BEARISH"
        elif lf_net < -5000:
            positioning = "BEARISH"
        else:
            positioning = "NEUTRAL"

        return {
            "symbol": "MNQ=F",
            "report_type": "TFF (Traders in Financial Futures)",
            "report_date": report_date,
            "lf_long": lf_long,
            "lf_short": lf_short,
            "lf_net": lf_net,
            "positioning": positioning,
            "data_source": "CFTC Official (tokenless)"
        }
    except Exception as e:
        return _fallback("MNQ=F", f"Parse error: {e}")


def _fallback(symbol: str, reason: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "positioning": "NEUTRAL",
        "mm_net": 0,
        "report_date": "unavailable",
        "error": reason,
        "data_source": "CFTC (unavailable — using neutral fallback)"
    }


class COTClient:
    """
    CFTC Commitment of Traders client.
    Provides Managed Money / Leveraged Funds net positioning for Gold and NQ.
    Used by the Macro Economic AI agent as a weekly macro sentiment input.
    """

    def get_gold_positioning(self) -> Dict[str, Any]:
        """Returns the most recent Managed Money net position for Gold futures."""
        raw = _fetch_cot(_GOLD_COMMODITY_CODE, "disaggregated")
        if raw:
            return _parse_gold_cot(raw)
        return _fallback("MGC=F", "CFTC API unavailable")

    def get_nq_positioning(self) -> Dict[str, Any]:
        """Returns the most recent Leveraged Funds net position for NQ futures."""
        raw = _fetch_cot(_NQ_COMMODITY_CODE, "tff")
        if raw:
            return _parse_nq_cot(raw)
        return _fallback("MNQ=F", "CFTC API unavailable")

    def get_both(self) -> Dict[str, Dict]:
        """Returns COT positioning for both instruments."""
        return {
            "MGC=F": self.get_gold_positioning(),
            "MNQ=F": self.get_nq_positioning()
        }

    def get_for_symbol(self, symbol: str) -> Dict[str, Any]:
        """Returns COT for a specific symbol."""
        s = symbol.upper()
        if s == "MGC=F":
            return self.get_gold_positioning()
        elif s == "MNQ=F":
            return self.get_nq_positioning()
        return _fallback(symbol, f"No COT mapping for {symbol}")
