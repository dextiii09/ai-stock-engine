import json
import os
import time
from typing import Dict, Any


def _atomic_json_write(filepath: str, data) -> None:
    """
    Write JSON atomically: dump to .tmp then os.replace().
    A crash during the write leaves the original file intact.
    """
    tmp = filepath + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, filepath)


class AIJournal:
    """
    Persistently logs every executed trade AND every vetoed opportunity
    (where a gate blocked a signal) for post-trade and opportunity-cost analysis.

    PERF NOTE: entries are still serialized to disk as a single JSON array on
    every append, so write cost grows with file size (this file already has
    tens of thousands of entries and grows continuously). A `_cache` is kept
    in memory so we no longer re-read + re-parse the whole file on every
    single call (that was the dominant cost and also meant every append paid
    for an O(n) JSON parse). The remaining O(n) write-out is a known
    limitation — a real fix means moving to an append-only format (JSONL) or
    a DB table; flagged as a follow-up rather than done here since it changes
    the on-disk format that other code (self_diagnosis, API endpoints) reads.
    """
    def __init__(self, filepath: str = "journal.json"):
        self.filepath = filepath
        self._cache: list = None  # lazy-loaded, then kept in sync in-memory
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.filepath):
            _atomic_json_write(self.filepath, [])

    def _load_cache(self) -> list:
        if self._cache is None:
            try:
                with open(self.filepath, 'r') as f:
                    self._cache = json.load(f)
            except Exception:
                self._cache = []
        return self._cache

    def _append(self, entry: Dict[str, Any]):
        """Internal: append to in-memory cache → atomic write (no re-read)."""
        logs = self._load_cache()
        logs.append(entry)
        try:
            _atomic_json_write(self.filepath, logs)
        except Exception as e:
            print(f"[Journal] Failed to save entry: {e}")

    def log_trade(self, symbol: str, action: str, price: float, decision_context: Dict[str, Any]):
        """Appends an executed trade to the Journal."""
        self._append({
            "timestamp": time.time(),
            "type": "TRADE",
            "symbol": symbol,
            "action": action,
            "execution_price": price,
            "ai_confidence": decision_context.get("confidence", 0.0),
            "ai_reason": decision_context.get("reason", ""),
            "regime": decision_context.get("regime", "Unknown"),
            "committee_breakdown": decision_context.get("committee_breakdown", []),
        })

    def log_veto(self, symbol: str, signal: str, gate: str, reason: str,
                 decision_context: Dict[str, Any] = None):
        """
        Appends a vetoed trade opportunity for opportunity-cost analysis.
        Tracks which gates are blocking setups — essential for tuning gate thresholds.

        Args:
            symbol:           Trading symbol (e.g. "MNQ=F")
            signal:           The blocked signal ("BUY" or "SELL")
            gate:             Which gate fired: "EVENT_BLACKOUT", "DAILY_HALT",
                              "WEEKLY_HALT", "MTF_VETO", "MONTE_CARLO", "CORRELATION", etc.
            reason:           Human-readable reason string from the gate
            decision_context: Optional dict with confidence, regime, committee_breakdown
        """
        ctx = decision_context or {}
        self._append({
            "timestamp": time.time(),
            "type": "VETO",
            "symbol": symbol,
            "signal": signal,
            "gate": gate,
            "reason": reason,
            "ai_confidence": ctx.get("confidence", 0.0),
            "regime": ctx.get("regime", "Unknown"),
            "committee_breakdown": ctx.get("committee_breakdown", []),
        })

    def get_logs(self):
        """Returns the complete journal (TRADE + VETO entries)."""
        return self._load_cache()

    def get_vetoes(self) -> list:
        """Returns only VETO entries — for opportunity-cost analysis."""
        return [e for e in self.get_logs() if e.get("type") == "VETO"]

    def get_veto_summary(self) -> Dict[str, Any]:
        """
        Aggregates veto counts by gate and signal direction.
        Quickly shows which gate is most restrictive.
        """
        vetoes = self.get_vetoes()
        by_gate: Dict[str, int] = {}
        by_signal: Dict[str, int] = {}
        for v in vetoes:
            g = v.get("gate", "UNKNOWN")
            s = v.get("signal", "UNKNOWN")
            by_gate[g]   = by_gate.get(g, 0) + 1
            by_signal[s] = by_signal.get(s, 0) + 1
        return {
            "total_vetoes": len(vetoes),
            "by_gate":      by_gate,
            "by_signal":    by_signal,
            "recent":       vetoes[-10:],
        }
