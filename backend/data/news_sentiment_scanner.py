import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Tuple, Optional


class NewsSentimentScanner:
    """
    Real-Time RSS News Headline Ingestion & Sentiment Gating Engine.
    
    Pulls live financial headlines for US Equities, Crypto, and Indian Markets,
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

    def fetch_headlines(self, symbol: str, limit: int = 5) -> List[str]:
        """Fetches top financial headlines via Google News / Yahoo Finance RSS feeds."""
        clean_sym = symbol.replace(".NS", "").replace("-USD", "").replace("=X", "").replace("=F", "").replace("^", "")
        url = f"https://news.google.com/rss/search?q={clean_sym}+stock+news&hl=en-US&gl=US&ceid=US:en"
        
        headlines = []
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                xml_data = resp.read()
                root = ET.fromstring(xml_data)
                for item in root.findall("./channel/item")[:limit]:
                    title = item.find("title")
                    if title is not None and title.text:
                        headlines.append(title.text.strip())
        except Exception as e:
            # Fallback or silent return
            pass
        return headlines

    def check_news_veto(self, symbol: str) -> Tuple[bool, float, str]:
        """
        Evaluates news sentiment for symbol.
        Returns: (is_vetoed: bool, sentiment_score: float, reason: str)
        """
        now = time.time()
        cached = self._cache.get(symbol)
        if cached and (now - cached.get("timestamp", 0)) < self._cache_ttl:
            return cached["is_veto"], cached["score"], cached["reason"]

        headlines = self.fetch_headlines(symbol, limit=4)
        if not headlines:
            res = (False, 0.0, "No breaking news alerts")
            self._cache[symbol] = {"is_veto": False, "score": 0.0, "reason": res[2], "timestamp": now}
            return res

        # Fast heuristic keyword veto check for extreme black-swans
        adverse_keywords = [
            "lawsuit", "sec investigation", "fraud", "bankruptcy", "delisting",
            "indictment", "probe", "hacked", "default", "subpoena", "crash",
            "accounting irregularities", "raided", "scam"
        ]
        
        headline_text = " | ".join(headlines).lower()
        matched_adverse = [kw for kw in adverse_keywords if kw in headline_text]

        if matched_adverse:
            res = (True, -0.85, f"Adverse News Detected: {', '.join(matched_adverse)}")
            self._cache[symbol] = {"is_veto": True, "score": -0.85, "reason": res[2], "timestamp": now}
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
        is_veto = False

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
            is_veto = bool(parsed.get("is_adverse_blackswan", False) or score < -0.70)
        except Exception:
            # Safe neutral fallback
            score = 0.0
            reason = f"Normal headline flow ({len(headlines)} items)"
            is_veto = False

        self._cache[symbol] = {"is_veto": is_veto, "score": score, "reason": reason, "timestamp": now}
        return is_veto, score, reason
