import os
import json
import time
import threading
from typing import Dict, Any, List
import requests
from .base_agent import BaseAgent

# NVIDIA NIM — OpenAI-compatible chat completions endpoint.
NVIDIA_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"


class NvidiaMacroAgent(BaseAgent):
    """
    Multi-Market Institutional Quantitative Macro LLM Agent.
    
    Backed by NVIDIA NIM (integrate.api.nvidia.com) with high-parameter reasoning
    models (Nemotron-3-120B, Llama-3.3-70B, Llama-3.1-8B).
    
    Architecture & Safety:
    - Runs asynchronously in background daemon threads (zero block on tick loops).
    - Caches per-symbol structured reasoning for `cache_ttl` seconds (default 300s).
    - Automatically rotates API keys on 429/quota limits.
    - Tailors macroeconomic prompts dynamically for Indian Equities, US Futures,
      Tech Stocks, 24/7 Crypto, and Global Forex.
    """

    def __init__(self, name: str = "Nvidia Macro AI", cache_ttl: int = 300):
        super().__init__(name)
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}

        # API keys rotation
        rotating = os.getenv("NVIDIA_ROTATING_KEYS", "")
        self._api_keys = [k.strip() for k in rotating.split(",") if k.strip()] if rotating else []
        base_key = (os.getenv("NVIDIA_API_KEY") or "").strip()
        if base_key and base_key not in self._api_keys:
            self._api_keys.insert(0, base_key)

        self._current_key_idx = 0
        self._global_quota_lock_until = 0.0

        # Model candidates (prioritize Nemotron 3 120B and Llama 3.3 70B)
        env_model = os.getenv("NVIDIA_MODEL", "").strip()
        self._model_candidates = ([env_model] if env_model else []) + [
            "nvidia/nemotron-3-super-120b-a12b",
            "meta/llama-3.1-8b-instruct",
            "meta/llama-3.3-70b-instruct",
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ]
        self._model_idx = 0

    def _current_key(self):
        return self._api_keys[self._current_key_idx] if self._api_keys else None

    def _rotate_api_key(self):
        if not self._api_keys:
            return
        self._current_key_idx = (self._current_key_idx + 1) % len(self._api_keys)
        print(f"[NvidiaAgent] Rotating API key to index {self._current_key_idx}...")

    def _call_nvidia(self, prompt: str) -> str:
        """One synchronous NVIDIA chat-completion call. Raises on non-200."""
        key = self._current_key()
        if not key:
            raise RuntimeError("No NVIDIA API key configured")
        payload = {
            "model":       self._model_candidates[self._model_idx],
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens":  200,
        }
        resp = requests.post(
            NVIDIA_ENDPOINT,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()["choices"][0]["message"]["content"]

    def _build_prompt(self, symbol: str, data: Dict[str, Any]) -> str:
        price  = data.get("price", "Unknown")
        regime = data.get("regime", "Unknown")
        rsi    = data.get("rsi_14", data.get("rsi", "Unknown"))
        macd   = data.get("macd_hist", data.get("macd", "Unknown"))
        macro  = data.get("macro_regime", "Unknown")
        sym_up = symbol.upper()

        if sym_up.endswith(".NS") or sym_up.endswith(".BO"):
            specialization = "Indian Stock Market (NSE/BSE). Focus on FII/DII institutional flows, India VIX, and USD/INR dynamics."
        elif "-USD" in sym_up or "BTC" in sym_up or "ETH" in sym_up:
            specialization = "Global 24/7 Cryptocurrency Markets. Focus on macro liquidity, Bitcoin dominance, funding rates, and risk-on/risk-off sentiment."
        elif "=X" in sym_up or "/" in sym_up:
            specialization = "Global Foreign Exchange (Forex). Focus on central bank rate divergence, DXY Dollar momentum, and macro yield spreads."
        else:
            specialization = "US Equities and Index Futures (CME/Nasdaq). Focus on VIX term structure, US 10-Year Treasury Yields, and macro sector momentum."

        return f"""You are a quantitative macro hedge-fund trading analyst specializing in {specialization}
Evaluate the current asset setup and provide a high-conviction decision.

Symbol: {symbol}
Current Price: {price}
Market Regime: {regime}
Global Macro Regime: {macro}
Technical Signals: RSI={rsi}, MACD_Hist={macd}

Respond ONLY with a valid JSON object:
{{"signal": "BUY" | "SELL" | "WAIT", "confidence": float (0.0 to 1.0), "reason": "Concise quantitative justification"}}
"""

    def _fetch_llm(self, symbol: str, data: Dict[str, Any]):
        sym_cache = self._cache.get(symbol)
        if not sym_cache or not self._api_keys:
            if sym_cache:
                sym_cache["is_fetching"] = False
            return

        prompt = self._build_prompt(symbol, data)
        try:
            for attempt in range(len(self._api_keys)):
                try:
                    text = self._call_nvidia(prompt).strip()

                    # Strip markdown code fences
                    if text.startswith("```json"):
                        text = text[7:]
                    elif text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                    # Extract the first valid JSON block
                    if not text.startswith("{"):
                        _s, _e = text.find("{"), text.rfind("}")
                        if _s != -1 and _e != -1 and _e > _s:
                            text = text[_s:_e + 1]

                    result = json.loads(text)
                    if result.get("signal") not in ["BUY", "SELL", "WAIT"]:
                        result["signal"] = "WAIT"
                    if not isinstance(result.get("confidence"), (int, float)):
                        result["confidence"] = 0.5

                    sym_cache["result"] = {
                        "signal":     result["signal"],
                        "confidence": float(result["confidence"]),
                        "reason":     result.get("reason", "NVIDIA LLM quantitative analysis complete."),
                    }
                    sym_cache["last_fetch_time"] = time.time()
                    return

                except Exception as e:
                    _msg = str(e).lower()
                    print(f"[NvidiaAgent] Error with key index {self._current_key_idx} for {symbol}: {e}")

                    # Rate-limited / quota / auth -> rotate key
                    if any(t in _msg for t in ("429", "quota", "rate limit", "too many", "401", "403")):
                        if attempt == len(self._api_keys) - 1:
                            print("[NvidiaAgent] All API keys exhausted. Locking LLM calls for 1 hour.")
                            self._global_quota_lock_until = time.time() + 3600
                        self._rotate_api_key()
                        continue

                    # Model unavailable -> advance to next model
                    if ("not found" in _msg or "404" in _msg or "model" in _msg) \
                            and self._model_idx < len(self._model_candidates) - 1:
                        self._model_idx += 1
                        print(f"[NvidiaAgent] Switching model -> {self._model_candidates[self._model_idx]}")
                        continue

                    if (isinstance(e, json.JSONDecodeError)
                            or "unterminated" in _msg or "expecting value" in _msg
                            or "extra data" in _msg) \
                            and attempt < len(self._api_keys) - 1:
                        print(f"[NvidiaAgent] Malformed JSON for {symbol}; retrying with next key.")
                        self._rotate_api_key()
                        continue

                    sym_cache["result"] = {
                        "signal": "WAIT", "confidence": 0.5,
                        "reason": f"NVIDIA API error: {str(e)[:120]}",
                    }
                    sym_cache["last_fetch_time"] = time.time() - self.cache_ttl + 60
                    return

            sym_cache["result"] = {
                "signal": "WAIT", "confidence": 0.5,
                "reason": "All NVIDIA API keys exhausted or rate-limited.",
            }
            sym_cache["last_fetch_time"] = time.time() - self.cache_ttl + 60
        finally:
            sym_cache["is_fetching"] = False

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if symbol not in self._cache:
            self._cache[symbol] = {
                "result": {
                    "signal": "WAIT",
                    "confidence": 0.5,
                    "reason": "Initializing NVIDIA LLM for symbol...",
                },
                "last_fetch_time": 0.0,
                "is_fetching": False,
            }

        sym_cache = self._cache[symbol]
        now = time.time()

        if now < self._global_quota_lock_until:
            sym_cache["result"]["reason"] = "NVIDIA LLM keys rate-limited (cooling down)."
            return sym_cache["result"]

        if now - sym_cache["last_fetch_time"] > self.cache_ttl and not sym_cache["is_fetching"]:
            sym_cache["is_fetching"] = True
            threading.Thread(target=self._fetch_llm, args=(symbol, data), daemon=True).start()

        return sym_cache["result"]


class IndianGeminiAgent(NvidiaMacroAgent):
    """Backward compatibility alias for IndianMasterAgent."""
    def __init__(self, cache_ttl: int = 300):
        super().__init__(name="Indian Gemini AI", cache_ttl=cache_ttl)
