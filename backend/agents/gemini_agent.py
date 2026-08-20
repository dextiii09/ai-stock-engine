import os
import json
import time
import threading
from typing import Dict, Any
import requests
from .base_agent import BaseAgent

# NVIDIA NIM — OpenAI-compatible chat completions endpoint.
NVIDIA_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"


class IndianGeminiAgent(BaseAgent):
    """
    Indian Market specialized LLM agent.

    Backed by NVIDIA's OpenAI-compatible API (integrate.api.nvidia.com) instead
    of Google Gemini — the Gemini free-tier keys returned quota `limit: 0`.
    Runs asynchronously in a background thread so it never blocks the trading
    tick loop, caches per symbol for `cache_ttl` seconds, and rotates keys on
    rate-limit / quota errors.

    NOTE: the class name and committee identity ("Indian Gemini AI") are kept
    unchanged for backward compatibility with master.py wiring and the RL
    weight bookkeeping — only the backend provider changed.
    """

    def __init__(self, cache_ttl: int = 300):
        super().__init__("Indian Gemini AI")
        self.cache_ttl = cache_ttl

        # Cache: symbol -> { "result": dict, "last_fetch_time": float, "is_fetching": bool }
        self._cache: Dict[str, Dict[str, Any]] = {}

        # API keys (rotation supported). Prefer NVIDIA_* env vars; fall back to
        # NVIDIA keys ONLY. Do NOT fall back to GEMINI_ROTATING_KEYS — those are
        # Gemini keys and sending them to the NVIDIA endpoint just yields 401s
        # and pollutes the log (observed on first run).
        rotating = os.getenv("NVIDIA_ROTATING_KEYS", "")
        self._api_keys = [k.strip() for k in rotating.split(",") if k.strip()] if rotating else []
        base_key = (os.getenv("NVIDIA_API_KEY") or "").strip()
        if base_key and base_key not in self._api_keys:
            self._api_keys.insert(0, base_key)

        self._current_key_idx = 0

        # If ALL keys are exhausted, lock the agent for 1 hour (avoids spamming).
        self._global_quota_lock_until = 0.0

        # NVIDIA model candidates (fast instruct models). Override via NVIDIA_MODEL.
        env_model = os.getenv("NVIDIA_MODEL", "").strip()
        self._model_candidates = ([env_model] if env_model else []) + [
            "meta/llama-3.1-8b-instruct",
            "meta/llama-3.3-70b-instruct",
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ]
        self._model_idx = 0

    # ── key helpers ──────────────────────────────────────────────────────────
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
            "max_tokens":  160,
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

    # ── background fetch ─────────────────────────────────────────────────────
    def _fetch_llm(self, symbol: str, data: Dict[str, Any]):
        """Runs in a background thread; tries each key on rate-limit/quota."""
        sym_cache = self._cache.get(symbol)
        if not sym_cache or not self._api_keys:
            if sym_cache:
                sym_cache["is_fetching"] = False
            return

        price  = data.get("price", "Unknown")
        regime = data.get("regime", "Unknown")
        rsi    = data.get("rsi", "Unknown")
        macd   = data.get("macd", "Unknown")
        macro  = data.get("macro_regime", "Unknown")
        prompt = f"""You are an expert AI Trading Assistant specializing in the Indian Stock Market (NSE/BSE).
Your goal is to provide a trading signal based on the current market context.
Focus on FII/DII dynamics, India VIX implications, USD/INR effects, and RBI monetary policy context where applicable.

Symbol: {symbol}
Current Price: {price}
Market Regime: {regime}
Global Macro Regime: {macro}
Technical Data: RSI={rsi}, MACD={macd}

Respond ONLY with a valid JSON object in the following format:
{{"signal": "BUY" | "SELL" | "WAIT", "confidence": float (0.0 to 1.0), "reason": "Brief explanation focused on Indian market dynamics"}}
"""
        try:
            for attempt in range(len(self._api_keys)):
                try:
                    text = self._call_nvidia(prompt).strip()

                    # Strip markdown code fences if present.
                    if text.startswith("```json"):
                        text = text[7:]
                    elif text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                    # Some models prepend prose — extract the first {...} block.
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
                        "reason":     result.get("reason", "NVIDIA LLM analysis complete."),
                    }
                    sym_cache["last_fetch_time"] = time.time()
                    return

                except Exception as e:
                    _msg = str(e).lower()
                    print(f"[NvidiaAgent] Error with key index {self._current_key_idx} for {symbol}: {e}")

                    # Rate-limited / quota / auth → rotate to the next key.
                    if any(t in _msg for t in ("429", "quota", "rate limit", "too many", "401", "403")):
                        if attempt == len(self._api_keys) - 1:
                            print("[NvidiaAgent] All API keys exhausted. Locking LLM calls for 1 hour.")
                            self._global_quota_lock_until = time.time() + 3600
                        self._rotate_api_key()
                        continue

                    # Model unavailable → advance to the next candidate model.
                    if ("not found" in _msg or "404" in _msg or "model" in _msg) \
                            and self._model_idx < len(self._model_candidates) - 1:
                        self._model_idx += 1
                        print(f"[NvidiaAgent] Switching model -> {self._model_candidates[self._model_idx]}")
                        continue

                    # Truncated / malformed JSON (e.g. "Unterminated string") — the
                    # model response was cut off, usually a transient network/stream
                    # issue. Retry with the next key instead of a full 60s back-off;
                    # only fall through to WAIT once every key has been tried.
                    if (isinstance(e, json.JSONDecodeError)
                            or "unterminated" in _msg or "expecting value" in _msg
                            or "extra data" in _msg) \
                            and attempt < len(self._api_keys) - 1:
                        print(f"[NvidiaAgent] Malformed JSON for {symbol}; retrying with next key.")
                        self._rotate_api_key()
                        continue

                    # Other non-retryable error — back off ~60s.
                    sym_cache["result"] = {
                        "signal": "WAIT", "confidence": 0.5,
                        "reason": f"NVIDIA API error: {str(e)[:120]}",
                    }
                    sym_cache["last_fetch_time"] = time.time() - self.cache_ttl + 60
                    return

            # Fell through the loop: every key failed.
            sym_cache["result"] = {
                "signal": "WAIT", "confidence": 0.5,
                "reason": "All NVIDIA API keys exhausted or rate-limited.",
            }
            sym_cache["last_fetch_time"] = time.time() - self.cache_ttl + 60
        finally:
            sym_cache["is_fetching"] = False

    # ── public API (unchanged contract) ──────────────────────────────────────
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

        # Global cooldown active — serve cached vote.
        if now < self._global_quota_lock_until:
            sym_cache["result"]["reason"] = "NVIDIA LLM keys rate-limited (cooling down)."
            return sym_cache["result"]

        # Trigger a background refresh if the cache is stale.
        if now - sym_cache["last_fetch_time"] > self.cache_ttl and not sym_cache["is_fetching"]:
            sym_cache["is_fetching"] = True
            threading.Thread(target=self._fetch_llm, args=(symbol, data), daemon=True).start()

        return sym_cache["result"]
