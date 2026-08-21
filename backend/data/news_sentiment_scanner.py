import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Tuple, Optional


import logging as _logging
_news_logger = _logging.getLogger("ai_stock.news")


class NewsSentimentScanner:
    """
    Real-Time RSS News Headline Ingestion & Sentiment Gating Engine.
    
    Pulls live financial headlines for US Equities, Crypto, Forex, and Indian Markets,
    evaluates news sentiment via NVIDIA Nemotron / fast keyword heuristic, and
    flags High-Impact Adverse News (News Veto) to prevent opening LONG positions
    during breaking black-swan events.
    """

    _instance: Optional["NewsSentimentScanner"] = None

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5-minute cache per symbol

    @classmethod
    def instance(cls) -> "NewsSentimentScanner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _clean_query(self, symbol: str) -> str:
        """Constructs a targeted search query based on asset class."""
        sym = symbol.upper().strip()
        if sym.endswith("=X"):
            pair = sym.replace("=X", "")
            if len(pair) == 6:
                return f"{pair[:3]}/{pair[3:]}+forex+news"
            return f"{pair}+currency+news"
        elif sym.endswith("-USD"):
            coin = sym.replace("-USD", "")
            return f"{coin}+crypto+news"
        elif sym.endswith("=F"):
            fut = sym.replace("=F", "")
            return f"{fut}+futures+market+news"
        elif sym.endswith(".NS"):
            stock = sym.replace(".NS", "")
            return f"{stock}+share+news+india"
        return f"{sym}+stock+news"

    def fetch_headlines(self, symbol: str, limit: int = 5) -> Tuple[List[str], bool]:
        """Fetches top financial headlines via Google News RSS with asset-specific query. Returns (headlines, success)."""
        query = self._clean_query(symbol)
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        
        headlines = []
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_data = resp.read()
                root = ET.fromstring(xml_data)
                for item in root.findall("./channel/item")[:limit]:
                    title = item.find("title")
                    if title is not None and title.text:
                        headlines.append(title.text.strip())
            return headlines, True
        except Exception as e:
            _news_logger.warning(f"[NewsScanner] RSS headline fetch failed for {symbol} (query: {query}): {e}")
            return [], False


    def check_news_veto(self, symbol: str) -> Tuple[bool, bool, float, str]:
        """
        Evaluates news sentiment for symbol.
        Returns: (adverse_veto: bool, euphoric_veto: bool, sentiment_score: float, reason: str)
        adverse_veto  -> True on breaking negative black-swan news; blocks new LONG entries.
        euphoric_veto -> True on breaking positive black-swan news; blocks new SHORT entries.
        """
        now = time.time()
        cached = self._cache.get(symbol)
        if cached and (now - cached.get("timestamp", 0)) < self._cache_ttl:
            return cached["adverse_veto"], cached["euphoric_veto"], cached["score"], cached["reason"]

        headlines, fetch_ok = self.fetch_headlines(symbol, limit=4)
        if not headlines:
            if not fetch_ok:
                # Do NOT cache network/parser errors! Allow immediate retry on next tick.
                return False, False, 0.0, "News feed temporarily unreachable (retry on next tick)"
            res = (False, False, 0.0, "No breaking news alerts")
            self._cache[symbol] = {"adverse_veto": False, "euphoric_veto": False, "score": 0.0, "reason": res[3], "timestamp": now}
            return res


        # Fast heuristic keyword veto check for extreme black-swans
        adverse_keywords = [
            "lawsuit", "sec investigation", "fraud", "bankruptcy", "delisting",
            "indictment", "probe", "hacked", "default", "subpoena", "crash",
            "accounting irregularities", "raided", "scam"
        ]
        euphoric_keywords = [
            "fda approval", "acquisition", "buyout", "acquired by", "beats estimates",
            "raises guidance", "record profit", "upgraded to buy", "patent granted",
            "strategic partnership", "record revenue", "earnings beat"
        ]
        
        headline_text = " | ".join(headlines).lower()
        matched_adverse = [kw for kw in adverse_keywords if kw in headline_text]
        matched_euphoric = [kw for kw in euphoric_keywords if kw in headline_text]

        if matched_adverse or matched_euphoric:
            adverse_veto = bool(matched_adverse)
            euphoric_veto = bool(matched_euphoric)
            score = -0.85 if matched_adverse else 0.85
            parts = []
            if matched_adverse:
                parts.append(f"Adverse: {', '.join(matched_adverse)}")
            if matched_euphoric:
                parts.append(f"Euphoric: {', '.join(matched_euphoric)}")
            reason = "News Detected - " + " | ".join(parts)
            res = (adverse_veto, euphoric_veto, score, reason)
            self._cache[symbol] = {"adverse_veto": adverse_veto, "euphoric_veto": euphoric_veto, "score": score, "reason": reason, "timestamp": now}
            return res

        # LLM Sentiment Evaluation with NVIDIA Nemotron
        prompt = f"""You are an elite financial news sentiment analyst.
Evaluate these latest headlines for {symbol}:
Headlines:
{chr(10).join(f"- {h}" for h in headlines)}

Score the net sentiment from -1.0 (extremely negative/disastrous) to +1.0 (extremely positive/bullish).
Respond ONLY with a valid JSON object:
{{"sentiment_score": float, "summary": "1-sentence summary", "is_adverse_blackswan": boolean}}
"""
        score = 0.0
        reason = "Neutral news flow"
        adverse_veto = False
        euphoric_veto = False

        try:
            from agents.gemini_agent import NvidiaMacroAgent
            agent = NvidiaMacroAgent()
            raw = agent._call_nvidia(prompt).strip()

            if raw.startswith("```json"):
                raw = raw[7:]
            elif raw.startswith("```"):
                raw = raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            if not raw.startswith("{"):
                _s, _e = raw.find("{"), raw.rfind("}")
                if _s != -1 and _e != -1:
                    raw = raw[_s:_e + 1]

            import json
            parsed = json.loads(raw)
            score = float(parsed.get("sentiment_score", 0.0))
            reason = str(parsed.get("summary", "Normal news sentiment"))
            adverse_veto = bool(parsed.get("is_adverse_blackswan", False) or score < -0.70)
            euphoric_veto = bool(score > 0.70)
        except Exception:
            # Safe neutral fallback
            score = 0.0
            reason = f"Normal headline flow ({len(headlines)} items)"
            adverse_veto = False
            euphoric_veto = False

        self._cache[symbol] = {"adverse_veto": adverse_veto, "euphoric_veto": euphoric_veto, "score": score, "reason": reason, "timestamp": now}
        return adverse_veto, euphoric_veto, score, reason
