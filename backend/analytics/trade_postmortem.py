import os
import json
import time
import threading
from typing import Dict, Any, List, Optional


JOURNAL_FILE = os.environ.get("TRADE_JOURNAL_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "trade_journal.json"
)


class TradePostMortemEngine:
    """
    Automated Institutional Trade Post-Mortem & AI Journaling Engine.
    
    Whenever a position is closed in SmartExecution (via Stop Loss, TP1 Scale-Out,
    TP2 Runner, or Force Close), this engine asynchronously queries NVIDIA Nemotron 120B
    to generate an institutional post-mortem breakdown and appends it to trade_journal.json.
    """

    _instance: Optional["TradePostMortemEngine"] = None

    def __init__(self):
        self.journal_path = JOURNAL_FILE
        self._ensure_journal_exists()

    @classmethod
    def instance(cls) -> "TradePostMortemEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_journal_exists(self):
        os.makedirs(os.path.dirname(self.journal_path), exist_ok=True)
        if not os.path.exists(self.journal_path):
            with open(self.journal_path, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    def get_recent_postmortems(self, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            if os.path.exists(self.journal_path):
                with open(self.journal_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data[-limit:] if isinstance(data, list) else []
        except Exception as e:
            print(f"[PostMortem] Error reading journal: {e}")
        return []

    def record_closed_trade_async(self, trade_data: Dict[str, Any], market: str = "US"):
        """Asynchronously triggers the LLM post-mortem in a background daemon thread."""
        threading.Thread(
            target=self._process_trade_postmortem,
            args=(trade_data, market),
            daemon=True
        ).start()

    def _process_trade_postmortem(self, trade: Dict[str, Any], market: str):
        symbol = trade.get("symbol", "UNKNOWN")
        entry_px = trade.get("entry_price", 0.0)
        exit_px = trade.get("exit_price", entry_px)
        profit = trade.get("profit", trade.get("pnl", 0.0))
        shares = trade.get("shares", 0.0)
        direction = trade.get("direction", "LONG")
        exit_reason = trade.get("exit_reason", "STOP_OR_TARGET")
        regime_entry = trade.get("regime_at_entry", "Unknown")
        regime_exit = trade.get("regime_at_exit", regime_entry)

        # Build prompt for NVIDIA Nemotron
        prompt = f"""You are an elite quantitative hedge-fund Chief Investment Officer.
Perform a concise post-mortem analysis on this closed trade:

Market: {market}
Symbol: {symbol}
Direction: {direction}
Entry Price: {entry_px} | Exit Price: {exit_px}
Realized Profit/Loss: {profit:+.2f} ({'WIN' if profit > 0 else 'LOSS'})
Exit Reason: {exit_reason}
Market Regime (Entry -> Exit): {regime_entry} -> {regime_exit}

Respond ONLY with a valid JSON object:
{{
  "outcome_driver": "1-sentence on what macro/technical factor drove the outcome",
  "regime_harmony": "Aligned" | "Divergent" | "Transition",
  "lesson": "1 actionable quantitative rule/takeaway for future trades"
}}
"""
        postmortem_res = {
            "outcome_driver": f"Trade closed with {profit:+.2f} ({'profit' if profit > 0 else 'loss'}).",
            "regime_harmony": "Aligned" if profit > 0 else "Transition",
            "lesson": "Preserve strict stop-loss discipline."
        }

        try:
            from agents.gemini_agent import NvidiaMacroAgent
            agent = NvidiaMacroAgent()
            raw = agent._call_nvidia(prompt).strip()
            
            # Clean markdown code fences
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

            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                postmortem_res.update(parsed)
        except Exception as e:
            print(f"[PostMortem] LLM error for {symbol}: {e}")

        record = {
            "timestamp": time.time(),
            "time_str": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "market": market,
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_px,
            "exit_price": exit_px,
            "profit": round(profit, 4),
            "exit_reason": exit_reason,
            "postmortem": postmortem_res
        }

        self._save_record(record)

    def _save_record(self, record: Dict[str, Any]):
        try:
            self._ensure_journal_exists()
            data = []
            try:
                with open(self.journal_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if not isinstance(data, list):
                            data = []
            except Exception:
                data = []

            data.append(record)
            with open(self.journal_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[PostMortem] Saved post-mortem for {record.get('symbol')} ({record.get('profit'):+.2f})")
        except Exception as e:
            print(f"[PostMortem] Failed to save record: {e}")

