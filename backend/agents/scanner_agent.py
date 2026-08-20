import asyncio
import time
from typing import List, Dict, Any, Optional
from data.ingestion import SYMBOLS, fetch_real_tick
from agents.master import MasterAgent

class ScannerAgent:
    """
    Background worker that continuously scans the entire symbol universe.
    It evaluates every symbol and maintains a sorted list of the best opportunities.
    """
    def __init__(self, master_agent: MasterAgent, symbols: Optional[List[str]] = None,
                 regime_detector=None, rl_engine=None):
        self.master_agent = master_agent
        self.symbols = symbols if symbols else SYMBOLS
        self.latest_opportunities: List[Dict[str, Any]] = []
        self.is_scanning = False
        # Optional: inject the live regime detector and RL engine so scanner
        # opportunities reflect actual bot state rather than default Sideways/uniform weights.
        self._regime_detector = regime_detector
        self._rl_engine = rl_engine

    async def start_scanning(self):
        self.is_scanning = True
        while self.is_scanning:
            current_scan = []

            for symbol in self.symbols:
                if not self.is_scanning:
                    break

                try:
                    # 1. Fetch live data — in a worker thread. fetch_real_tick is a
                    #    BLOCKING network call (with retry sleeps); calling it directly
                    #    from this async task froze the whole event loop, starving
                    #    every API endpoint and SSE stream while scans were running.
                    tick_data = await asyncio.to_thread(fetch_real_tick, symbol)

                    # 2. Inject live regime + RL weights so the scanner matches the
                    #    actual bot state (without this, all evals use Sideways + uniform 1.0 weights)
                    if self._regime_detector is not None:
                        try:
                            regime = self._regime_detector.detect(symbol, tick_data)
                            tick_data["regime"] = regime
                            if self._rl_engine is not None:
                                tick_data["agent_weights"] = self._rl_engine.get_current_weights(regime)
                        except Exception:
                            pass  # degrade gracefully — scanner still works without regime

                    # 3. Evaluate with Master AI (CPU-bound + may fetch MTF data) —
                    #    also off the event loop.
                    decision = await asyncio.to_thread(self.master_agent.evaluate, symbol, tick_data)
                    
                    # 3. Record opportunity
                    current_scan.append({
                        "symbol": symbol.replace(".NS", ""), # Strip .NS for UI
                        "price": tick_data["price"],
                        "signal": decision["signal"],
                        "confidence": round(decision["confidence"] * 100, 1),
                        "reason": decision["reason"],
                        "recommendation": decision.get("recommendation", "Wait for better setup."),
                        "timestamp": time.time()
                    })
                    
                    # Small delay to prevent rate-limiting from Yahoo Finance
                    await asyncio.sleep(2)
                    
                except RuntimeError as e:
                    print(f"[Scanner] Data error for {symbol}: {e}")
                    await asyncio.sleep(1)
                except Exception as e:
                    print(f"[Scanner] Error evaluating {symbol}: {e}")
                    await asyncio.sleep(1)

            # Sort by confidence descending
            current_scan.sort(key=lambda x: x["confidence"], reverse=True)
            self.latest_opportunities = current_scan
            
            # Rest before next full market scan
            await asyncio.sleep(15)

    def stop_scanning(self):
        self.is_scanning = False
        
    def get_opportunities(self) -> List[Dict[str, Any]]:
        return self.latest_opportunities
