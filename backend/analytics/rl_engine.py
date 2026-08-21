from typing import Dict, Any, List
import json
import os
import logging as _logging

_rl_logger = _logging.getLogger("ai_stock.rl_engine")

RETRAIN_INTERVAL = 5  # Retrain every N closed trades

# Serializes RL DB saves scheduled on the event loop (see save_state).
_rl_db_lock = None

def _get_rl_db_lock():
    global _rl_db_lock
    if _rl_db_lock is None:
        import asyncio
        _rl_db_lock = asyncio.Lock()
    return _rl_db_lock


def _infer_market_from_filepath(filepath: str) -> str:
    """
    CRITICAL FIX 2026-07-20: was `"_st" in filepath` etc. — but
    "rl_state.json", "rl_state_cx.json" and "rl_state_fx.json" ALL contain
    "_st" (inside "_state"!), so US/STOCKS/CRYPTO/FOREX RL engines all
    resolved to market="STOCKS" and shared the same RLWeight DB rows.
    Suffix-of-stem matching is unambiguous.
    """
    stem = os.path.basename(filepath).rsplit(".", 1)[0]
    if stem.endswith("_in"):
        return "INDIA"
    if stem.endswith("_st"):
        return "STOCKS"
    if stem.endswith("_cx"):
        return "CRYPTO"
    if stem.endswith("_fx"):
        return "FOREX"
    return "US"


class ReinforcementLearningEngine:
    """
    Continuous Improvement Loop.
    Adjusts voting weights of the Multi-AI Committee based on post-trade outcomes.
    Tracks real win rate, retrain count, and trades-until-next-retrain.
    """

    REGIMES = ["Trending Bull", "Sideways", "Trending Bear", "High Volatility"]

    def __init__(self):
        # Feature: Regime-Specific weights
        agents = ["Technical Analyst", "Fundamental Analyst", "News & Sentiment AI", "Macro Economic AI", "Volatility Agent", "Liquidity Agent", "Correlation Agent"]
        self.agent_weights = {
            regime: {a: 1.0 for a in agents}
            for regime in self.REGIMES
        }
        
        # Thompson Sampling Beta params
        self.agent_alpha = {
            regime: {a: 1.0 for a in agents}
            for regime in self.REGIMES
        }
        self.agent_beta = {
            regime: {a: 1.0 for a in agents}
            for regime in self.REGIMES
        }
        
        # Regime Blending
        self.active_regime = None
        self.previous_regime = None
        self.ticks_since_switch = 5
        self.trades_in_active_regime = 0  # For MAML fast adaptation
        self.learning_rate = 0.005
        
        # Feature: Recency bias decay factor
        self.decay_factor = 0.95

        # Real tracking counters
        self.total_closed_trades = 0
        self.winning_trades = 0
        self.retrain_count = 0
        self._trades_since_last_retrain = 0
        self._trade_history: List[Dict] = []
        self._last_regime = None
        self._trades_in_new_regime = 0
        self._trades_since_td = 0
        
        # Batch accumulator for weights (accumulates by regime)
        self._batch_weight_deltas = {
            regime: {a: 0.0 for a in agents}
            for regime in self.REGIMES
        }

        # UCB1 exploration: tracks how many times each agent participated per regime
        self._agent_trade_counts: Dict[str, Dict[str, int]] = {
            regime: {a: 0 for a in agents}
            for regime in self.REGIMES
        }

        self.load_hyperparams()

    def load_hyperparams(self):
        import os
        import json
        base_dir = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(base_dir, "data", "hyperparams.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    params = json.load(f)
                if "learning_rate" in params:
                    self.learning_rate = params["learning_rate"]
                if "decay_factor" in params:
                    self.decay_factor = params["decay_factor"]
                _rl_logger.info(f"[RL_Engine] Loaded optimized params from hyperparams.json: LR={self.learning_rate}, decay={self.decay_factor}")
            except Exception as e:
                _rl_logger.error(f"[RL_Engine] Error loading hyperparams.json: {e}")

    def _match_regime(self, regime: str) -> str:
        # Standardize matching to the exact 4 regimes
        if not regime or not isinstance(regime, str):
            return self.REGIMES[0]
        if regime not in self.REGIMES:
            # Try fuzzy match just in case
            for r in self.REGIMES:
                if r in regime or regime in r:
                    return r
            return "Sideways"  # Safe default
        return regime

    @property
    def win_rate(self) -> float:
        if self.total_closed_trades == 0:
            return 0.0
        return round(self.winning_trades / self.total_closed_trades * 100, 1)

    def regime_win_rate(self, regime: str, k: float = 20.0):
        """
        Regime-conditional win rate, shrunk toward the global rate (James-Stein style).
        Returns a FRACTION (0–1), already clamped to [0.05, 0.95] for logit safety.
        Returns None when global n < 30 — caller must bypass the MC gate entirely.

        k=20: 20 regime-specific trades gives a 50/50 blend of regime vs global.
        As bucket fills, blend shifts toward the regime-specific rate.
        Requires each _trade_history entry to carry 'regime' (stamped since Session 5).
        """
        n_global = self.total_closed_trades
        if n_global < 30:
            return None                               # cold start — bypass gate in caller

        p_global = self.winning_trades / n_global     # fraction

        # _trade_history entries are stamped with the 4-RL vocab (via _match_regime).
        # Callers pass the raw 10-name HMM regime → normalize before bucket lookup.
        matched = self._match_regime(regime)
        bucket = [t for t in self._trade_history if t.get("regime") == matched]
        n_r    = len(bucket)
        if n_r == 0:
            p = p_global
        else:
            p_regime = sum(1 for t in bucket if t.get("is_win")) / n_r
            w = n_r / (n_r + k)                      # 0→lean global, 1→lean regime
            p = w * p_regime + (1.0 - w) * p_global

        return float(min(0.95, max(0.05, p)))

    @property
    def trades_till_retrain(self) -> int:
        return RETRAIN_INTERVAL - self._trades_since_last_retrain

    def process_trade_outcome(self, trade_result: Dict[str, Any], committee_breakdown: Any):
        """
        Called after every closed trade with real P&L outcome.
        Updates agent weights using Sharpe-adjusted rewards, drawdown penalties,
        adaptive learning rate, and herding/diversity guard.
        """
        # Safe conversion of committee_breakdown from list of dicts to dict if needed.
        # NOTE: missing confidence must default to 0.5 (neutral), matching the
        # downstream `agent_data.get("confidence", 0.5)` default. It previously
        # defaulted to 0.0 here, which multiplied every weight delta by zero and
        # silently disabled RL learning for list-shaped breakdowns.
        if isinstance(committee_breakdown, list):
            committee_breakdown = {
                vote.get("agent", ""): {"signal": vote.get("signal", "WAIT"), "confidence": vote.get("confidence", 0.5)}
                for vote in committee_breakdown if "agent" in vote
            }

        pnl         = trade_result.get("profit_loss", 0.0)
        capital     = trade_result.get("capital_allocated", 1.0)
        regime      = self._match_regime(trade_result.get("regime", "Sideways"))
        action      = trade_result.get("action", "BUY")

        # 1. Sharpe-adjusted reward (rolling 30-trade std)
        pnl_pct = (pnl / capital) * 100 if capital > 0 else 0.0
        self._trade_history.append({"pnl_pct": pnl_pct, "pnl": pnl, "is_win": pnl > 0,
                                    "regime": regime})
        if len(self._trade_history) > 200:
            self._trade_history.pop(0)

        recent_pnls = [t["pnl_pct"] for t in self._trade_history[-30:]]
        import numpy as np
        import math as _math
        # EMA recency decay: recent trades get full weight, older trades decay by 0.95 per step
        if len(recent_pnls) >= 5:
            _dw = np.array([self.decay_factor ** i for i in range(len(recent_pnls) - 1, -1, -1)])
            _dw /= _dw.sum()
            _wmean = float(np.dot(_dw, recent_pnls))
            _wvar  = float(np.dot(_dw, (np.array(recent_pnls) - _wmean) ** 2))
            std_pnl = max(_math.sqrt(_wvar), 1e-4)
        else:
            std_pnl = 1.0
        sharpe_reward = float(np.clip(pnl_pct / std_pnl, -5.0, 5.0))

        # 2. Drawdown penalty (cumulative equity drawdown on the last 20 trades)
        equity = 100.0
        peak = 100.0
        max_dd = 0.0
        for t in self._trade_history[-20:]:
            p_val = t["pnl_pct"]
            equity += p_val
            if equity > peak:
                peak = equity
            dd = ((peak - equity) / peak * 100) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        reward_base = sharpe_reward - (max_dd * 0.3)
        if sharpe_reward >= 0:
            reward_base = max(reward_base, 0.0)  # no sign flip on wins

        # 2b. R-multiple: reward profit relative to risk taken (blended 60/40 with Sharpe)
        stop_dist_pct = float(trade_result.get("stop_distance_pct", 0.0))
        if stop_dist_pct > 0.01 and abs(pnl_pct) > 0.001:
            r_multiple = float(np.clip(pnl_pct / stop_dist_pct, -5.0, 5.0))
            reward_base = reward_base * 0.6 + r_multiple * 0.4

        # 3. Adaptive learning rate (win-rate based)
        last5     = self._trade_history[-5:]
        recent_wr = sum(1 for t in last5 if t["pnl"] > 0) / max(len(last5), 1)
        lr = self.learning_rate * (2.0 if recent_wr < 0.40 else 1.5 if recent_wr < 0.50 else 1.0)

        # 4. LR warmup on regime switch (5× for first 10 trades in new regime)
        #    Instant mini-retrain: flush old-regime deltas before switching so knowledge is locked in.
        if regime != self._last_regime:
            if self._last_regime is not None:
                _old = self._last_regime
                for _ag, _dl in self._batch_weight_deltas.get(_old, {}).items():
                    if abs(_dl) < 1e-6:
                        continue
                    _cp = float(np.clip(_dl, -0.15, 0.15))
                    self.agent_weights[_old][_ag] = float(np.clip(
                        self.agent_weights[_old].get(_ag, 1.0) + _cp, 0.1, 2.0))
                    if _old in self.agent_alpha and _ag in self.agent_alpha[_old]:
                        if _cp > 0:
                            self.agent_alpha[_old][_ag] = float(np.clip(
                                self.agent_alpha[_old][_ag] + _cp * 5.0, 1.0, 50.0))
                        elif _cp < 0:
                            self.agent_beta[_old][_ag] = float(np.clip(
                                self.agent_beta[_old][_ag] - _cp * 5.0, 1.0, 50.0))
                    self._batch_weight_deltas[_old][_ag] = 0.0
                print(f"[RL] Regime switch {_old} → {regime}: mini-retrain applied.")
            self._last_regime          = regime
            self._trades_in_new_regime = 0
        self._trades_in_new_regime += 1
        if self._trades_in_new_regime <= 10:
            lr *= 5.0

        # 5. Diversity guard (>85% agreement = herding penalty)
        total_agents  = len(committee_breakdown)
        agreed_count  = sum(1 for a in committee_breakdown.values() if a.get("signal") == action)
        herding_mult  = 0.5 if total_agents > 0 and (agreed_count / total_agents) >= 0.85 else 1.0

        # 6. Accumulate batch deltas with confidence-weighted eligibility traces.
        # Sentiment and Correlation Agent are excluded: both have their weights forced
        # to 0.0 in the live loop, so updating their α/β wastes cycles and creates stale state.
        _GHOST_AGENTS = {"News & Sentiment AI", "Correlation Agent"}
        self._batch_weight_deltas.setdefault(regime, {})
        for agent_name, agent_data in committee_breakdown.items():
            if agent_name in _GHOST_AGENTS:
                continue
            
            signal = agent_data.get("signal", "WAIT")
            if signal == "WAIT":
                mult = 0.0
            elif signal == action:
                mult = 1.0
            else:
                mult = -1.0

            # Confidence weighting: high-conviction correct → bigger reward; wrong → bigger penalty
            confidence = float(agent_data.get("confidence", 0.5))
            delta      = reward_base * lr * herding_mult * confidence * mult
            self._batch_weight_deltas[regime][agent_name] = \
                self._batch_weight_deltas[regime].get(agent_name, 0.0) + delta
            # UCB1 bookkeeping: track participation count per agent per regime
            if regime not in self._agent_trade_counts:
                self._agent_trade_counts[regime] = {}
            self._agent_trade_counts[regime][agent_name] = \
                self._agent_trade_counts[regime].get(agent_name, 0) + 1

        # 7. TD partial update every 3 trades (20% of accumulated deltas)
        # CQ-3 fix: deduct the applied partial from batch_weight_deltas so that when
        # step 8 fires on the same trade (LCM(3,5)=15), it only applies the remaining
        # 80%, not the full 100% again (old bug: 20%+100% = 120% on trade 15,30,45...).
        self._trades_since_td += 1
        if self._trades_since_td >= 3:
            for r, agents in list(self._batch_weight_deltas.items()):
                for agent, delta in agents.items():
                    partial = float(np.clip(delta * 0.20, -0.05, 0.05))  # max 0.05 per TD step
                    current = self.agent_weights[r].get(agent, 1.0)
                    self.agent_weights[r][agent] = float(np.clip(current + partial, 0.1, 2.0))
                    # Deduct applied portion so batch step never double-counts it
                    self._batch_weight_deltas[r][agent] = delta - partial
                    # Propagate to Thompson Sampling Beta parameters (capped at 50 to prevent divergence)
                    # Auto-initialize alpha/beta for agents added after startup (e.g. India Flow Agent)
                    if r in self.agent_alpha:
                        if agent not in self.agent_alpha[r]:
                            self.agent_alpha[r][agent] = 1.0
                            self.agent_beta[r][agent]  = 1.0
                        if partial > 0:
                            self.agent_alpha[r][agent] = float(np.clip(
                                self.agent_alpha[r][agent] + partial * 5.0, 1.0, 50.0))
                        elif partial < 0:
                            self.agent_beta[r][agent]  = float(np.clip(
                                self.agent_beta[r][agent]  - partial * 5.0, 1.0, 50.0))
            self._trades_since_td = 0

        # 8. Full batch update every 5 trades
        # C-3: Also update agent_alpha/beta so Thompson Sampling actually learns.
        self._trades_since_last_retrain += 1
        if self._trades_since_last_retrain >= RETRAIN_INTERVAL:
            self.retrain_count += 1
            for r, agents in self._batch_weight_deltas.items():
                for agent, delta in agents.items():
                    capped  = float(np.clip(delta, -0.25, 0.25))
                    current = self.agent_weights[r].get(agent, 1.0)
                    self.agent_weights[r][agent] = float(np.clip(current + capped, 0.1, 2.0))
                    # Propagate to Thompson Sampling Beta parameters (capped at 50 to prevent divergence)
                    # Auto-initialize alpha/beta for agents added after startup (e.g. India Flow Agent)
                    if r in self.agent_alpha:
                        if agent not in self.agent_alpha[r]:
                            self.agent_alpha[r][agent] = 1.0
                            self.agent_beta[r][agent]  = 1.0
                        if capped > 0:
                            self.agent_alpha[r][agent] = float(np.clip(
                                self.agent_alpha[r][agent] + capped * 5.0, 1.0, 50.0))
                        elif capped < 0:
                            self.agent_beta[r][agent]  = float(np.clip(
                                self.agent_beta[r][agent]  - capped * 5.0, 1.0, 50.0))
            # Reset batch deltas for all regimes
            self._batch_weight_deltas = {
                reg: {a: 0.0 for a in self.agent_weights[reg].keys()}
                for reg in self.REGIMES
            }
            self._trades_since_last_retrain = 0

        self.total_closed_trades += 1
        if pnl > 0:
            self.winning_trades += 1

    def _partial_update(self, regime: str):
        """DEPRECATED (CQ-2): superseded by inline TD logic in process_trade_outcome step 7.
        Left here to avoid breaking any external callers; do NOT call from new code."""
        for agent_name, delta in self._batch_weight_deltas[regime].items():
            if delta != 0.0:
                partial_delta = delta * 0.2
                self._adjust_weight(regime, agent_name, partial_delta)
                # Deduct the applied delta so it's not double-counted
                self._batch_weight_deltas[regime][agent_name] -= partial_delta

    def _retrain(self):
        """DEPRECATED (CQ-2): superseded by inline batch logic in process_trade_outcome step 8.
        Left here for compatibility; do NOT call from new code.
        """
        self.retrain_count += 1
        self._trades_since_last_retrain = 0
        
        # Apply the accumulated weight deltas per regime with momentum cap
        for regime in self.REGIMES:
            for agent_name, delta in self._batch_weight_deltas[regime].items():
                capped_delta = max(-0.25, min(0.25, delta))  # Prevent instant saturation
                self._adjust_weight(regime, agent_name, capped_delta)
                
            # Reset batch accumulator for this regime
            self._batch_weight_deltas[regime] = {agent: 0.0 for agent in self._batch_weight_deltas[regime].keys()}

    def _adjust_weight(self, regime: str, agent_name: str, adjustment: float):
        if regime in self.agent_alpha and agent_name in self.agent_alpha[regime]:
            # Update Beta distribution parameters for Thompson Sampling
            if adjustment > 0:
                self.agent_alpha[regime][agent_name] = max(1.0, self.agent_alpha[regime][agent_name] + adjustment * 5.0)
            else:
                self.agent_beta[regime][agent_name] = max(1.0, self.agent_beta[regime][agent_name] - adjustment * 5.0)

        if regime in self.agent_weights and agent_name in self.agent_weights[regime]:
            self.agent_weights[regime][agent_name] = round(
                max(0.1, min(2.0, self.agent_weights[regime][agent_name] + adjustment)), 4
            )

    def get_current_weights(self, regime: str = None,
                             deterministic: bool = False) -> Dict[str, float]:
        """
        Returns the 7-agent weight dict for the given regime.

        Args:
            regime:        The current HMM regime string.
            deterministic: If True, return the Beta distribution MEAN
                           (2α/(α+β)) instead of a random sample.
                           Use deterministic=True in backtests and
                           walk-forward evaluation so results are
                           reproducible. Leave False for the live loop
                           (Thompson Sampling = exploration).
        """
        import numpy as np

        if regime is not None:
            matched_regime = self._match_regime(regime)

            # Update regime state for blending
            if matched_regime != self.active_regime:
                if self.active_regime is not None:
                    self.previous_regime = self.active_regime
                    self.ticks_since_switch = 0
                self.active_regime = matched_regime
            else:
                if self.ticks_since_switch < 5:
                    self.ticks_since_switch += 1

            sampled_weights = {}
            all_agents = list(self.agent_weights[matched_regime].keys())
            for agent in all_agents:
                alpha = self.agent_alpha[matched_regime].get(agent, 1.0)
                beta  = self.agent_beta[matched_regime].get(agent, 1.0)

                if deterministic:
                    # Deterministic: Beta distribution mean = 2α/(α+β)
                    # No RNG → backtests are reproducible; run twice, get same number.
                    weight = 2.0 * alpha / (alpha + beta)
                else:
                    # Thompson Sampling — stochastic exploration for live loop
                    weight = np.random.beta(alpha, beta) * 2.0

                    # Regime blending (smooth transition over 5 ticks after switch)
                    if self.ticks_since_switch < 5 and self.previous_regime:
                        prev_alpha  = self.agent_alpha[self.previous_regime].get(agent, 1.0)
                        prev_beta   = self.agent_beta[self.previous_regime].get(agent, 1.0)
                        prev_weight = np.random.beta(prev_alpha, prev_beta) * 2.0
                        blend       = self.ticks_since_switch / 5.0
                        weight      = prev_weight * (1.0 - blend) + weight * blend

                sampled_weights[agent] = round(float(np.clip(weight, 0.1, 2.0)), 4)

            # UCB1 exploration bonus (live mode only, requires ≥5 closed trades)
            if not deterministic and self.total_closed_trades >= 5:
                import math as _math
                _total = max(self.total_closed_trades, 1)
                for _ag in all_agents:
                    _cnt = max(self._agent_trade_counts.get(matched_regime, {}).get(_ag, 0), 1)
                    _ucb = 0.15 * _math.sqrt(_math.log(_total) / _cnt)
                    sampled_weights[_ag] = round(float(np.clip(sampled_weights[_ag] + _ucb, 0.1, 2.5)), 4)

            # RL Weight Soft-Cap: cap each agent at 35% of total committee weight.
            # Prevents a single agent from monopolizing decisions after a winning streak.
            _total_w = sum(sampled_weights.values())
            if _total_w > 0:
                _cap = 0.35 * _total_w
                for _ag in list(sampled_weights.keys()):
                    if sampled_weights[_ag] > _cap:
                        sampled_weights[_ag] = round(_cap, 4)

            return sampled_weights

        # No regime specified — return deterministic average across all regimes
        avg_weights = {}
        all_agents = list(self.agent_weights[self.REGIMES[0]].keys())
        for agent in all_agents:
            avg_weights[agent] = round(
                sum(self.agent_weights[r].get(agent, 1.0) for r in self.REGIMES) / len(self.REGIMES), 4
            )
        return avg_weights

    def process_shadow_outcome(self, trade_result: Dict[str, Any]):
        """
        Learns from shadow (simulated) trade outcomes at a 0.3× dampened rate.
        Called by ShadowTradingEngine when a rejected setup hits its target or stop.
        Provides ~3× more learning signal without crowding out real trade updates.
        """
        import numpy as np
        SHADOW_DAMPENING = 0.3

        pnl_pct = float(trade_result.get("pnl_pct", 0.0))
        regime  = self._match_regime(trade_result.get("regime", "Sideways"))

        # Sharpe-style reward from recent live history (shadow trades share the same baseline)
        recent_pnls = [t["pnl_pct"] for t in self._trade_history[-20:]]
        std_pnl = max(float(np.std(recent_pnls)), 1e-4) if len(recent_pnls) >= 5 else 1.0
        reward  = float(np.clip(pnl_pct / std_pnl, -3.0, 3.0)) * SHADOW_DAMPENING

        committee = trade_result.get("committee_breakdown", {})
        if isinstance(committee, list):
            committee = {v.get("agent", ""): v for v in committee if "agent" in v}

        _GHOST_AGENTS = {"News & Sentiment AI"}
        action = trade_result.get("action", "BUY" if pnl_pct > 0 else "SELL")

        self._batch_weight_deltas.setdefault(regime, {})
        for agent_name, agent_data in committee.items():
            if not agent_name or agent_name in _GHOST_AGENTS:
                continue
            agreed     = (agent_data.get("signal") == action)
            confidence = float(agent_data.get("confidence", 0.5))
            delta = float(np.clip(
                reward * self.learning_rate * confidence * (1.0 if agreed else -1.0),
                -0.03, 0.03  # hard cap: shadow trades move weights slowly
            ))
            self._batch_weight_deltas[regime][agent_name] = \
                self._batch_weight_deltas[regime].get(agent_name, 0.0) + delta

    def pre_seed_from_backtest(self, trades: List[Dict]):
        """
        Feature 10: Backtest Pre-Seeding.
        Ingests the last 6 months of autonomous_builder.py backtest results
        and adjusts committee weights before the first live tick.
        """
        if not trades:
            return
            
        print(f"[RL Engine] Pre-seeding weights from {len(trades)} historical trades...")
        for trade in trades:
            committee_breakdown = trade.get("committee_breakdown", [])
            if not committee_breakdown:
                continue

            # Guard: seed trades generated without capital_allocated defaulted to
            # 1.0 downstream, inflating pnl_pct ~100x and poisoning the Sharpe
            # normalization for all subsequent REAL trades. Force a sane capital.
            if not trade.get("capital_allocated") or trade.get("capital_allocated", 0) <= 1.0:
                trade = {**trade, "capital_allocated": 10000.0}

            self.process_trade_outcome(trade, committee_breakdown)
            
        print(f"[RL Engine] Pre-seeding complete. Average weights: {self.get_current_weights()}")

    def save_state(self, filepath: str):
        """
        Persists the full RL engine state to SQLite if enabled, and fallbacks to JSON.
        """
        market = _infer_market_from_filepath(filepath)
        import os
        DB_ENABLED = os.getenv("DB_ENABLED", "false").lower() == "true"
        
        def run_async(coro):
            import asyncio
            import threading
            from concurrent.futures import Future
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            if loop.is_running():
                # Called from the running loop's own thread (sync helper in an
                # async route). A new-loop-in-thread breaks aiosqlite ("Queue
                # is bound to a different event loop") because the DB pool
                # belongs to THIS loop. Schedule fire-and-forget on the
                # running loop instead; JSON fallback below still saves
                # synchronously either way.
                task = loop.create_task(coro)
                def _on_done(t):
                    if not t.cancelled():
                        exc = t.exception()
                        if exc:
                            _rl_logger.error(f"[RL Engine] async save failed: {exc}")
                task.add_done_callback(_on_done)
                return None

            else:
                return loop.run_until_complete(coro)


        if DB_ENABLED:
            try:
                from database.database import AsyncSessionLocal
                from database.models import RLWeight, Portfolio
                from sqlalchemy import select

                async def save_db():
                    # Serialize with other RL saves on this loop: concurrent
                    # fire-and-forget tasks race select-then-insert on
                    # RLWeight rows (same UNIQUE failure mode as portfolio).
                    async with _get_rl_db_lock():
                        await _save_db_inner()

                async def _save_db_inner():
                    async with AsyncSessionLocal() as session:
                        # 1. Save weights to RLWeight table
                        for regime in self.REGIMES:
                            for agent, weight in self.agent_weights[regime].items():
                                result = await session.execute(
                                    select(RLWeight).where(
                                        RLWeight.market == market,
                                        RLWeight.regime == regime,
                                        RLWeight.agent_name == agent
                                    )
                                )
                                db_weight = result.scalars().first()
                                if not db_weight:
                                    db_weight = RLWeight(
                                        market=market,
                                        regime=regime,
                                        agent_name=agent
                                    )
                                    session.add(db_weight)
                                db_weight.weight = float(weight)
                                db_weight.alpha = float(self.agent_alpha[regime].get(agent, 1.0))
                                db_weight.beta = float(self.agent_beta[regime].get(agent, 1.0))

                        # 2. Save metadata to Portfolio table
                        result = await session.execute(
                            select(Portfolio).where(Portfolio.market == market)
                        )
                        db_portfolio = result.scalars().first()
                        if db_portfolio:
                            state_data = db_portfolio.state_data or {}
                            state_data["rl_metadata"] = {
                                "total_closed_trades": self.total_closed_trades,
                                "winning_trades": self.winning_trades,
                                "retrain_count": self.retrain_count,
                                "_trades_since_last_retrain": self._trades_since_last_retrain,
                                "_trade_history": self._trade_history[-200:],
                                "_batch_weight_deltas": self._batch_weight_deltas
                            }
                            db_portfolio.state_data = state_data
                        
                        await session.commit()
                run_async(save_db())
            except Exception as e:
                _rl_logger.error(f"[RL Engine] Failed to save state to SQLite: {e}")

        # Always fallback to JSON as well
        try:
            state = {
                "agent_weights": self.agent_weights,
                "total_closed_trades": self.total_closed_trades,
                "winning_trades": self.winning_trades,
                "retrain_count": self.retrain_count,
                "_trades_since_last_retrain": self._trades_since_last_retrain,
                "_trade_history": self._trade_history[-200:],
                "_batch_weight_deltas": self._batch_weight_deltas,
                "agent_alpha": self.agent_alpha,
                "agent_beta": self.agent_beta,
                "_agent_trade_counts": self._agent_trade_counts
            }
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            tmp = filepath + ".tmp"
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp, filepath)
        except Exception as e:
            _rl_logger.error(f"[RL Engine] Failed to save JSON state: {e}")

    def load_state(self, filepath: str):
        """
        Reloads RL engine state from SQLite if enabled, falling back to JSON.
        """
        market = _infer_market_from_filepath(filepath)
        import os
        DB_ENABLED = os.getenv("DB_ENABLED", "false").lower() == "true"
        
        def run_async(coro):
            import asyncio
            import threading
            from concurrent.futures import Future
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            if loop.is_running():
                fut = Future()
                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        res = new_loop.run_until_complete(coro)
                        fut.set_result(res)
                    except Exception as e:
                        fut.set_exception(e)
                    finally:
                        new_loop.close()
                t = threading.Thread(target=run_in_thread)
                t.start()
                t.join()
                return fut.result()
            else:
                return loop.run_until_complete(coro)

        loaded_from_db = False
        if DB_ENABLED:
            try:
                from database.database import AsyncSessionLocal
                from database.models import RLWeight, Portfolio
                from sqlalchemy import select

                async def load_db():
                    async with AsyncSessionLocal() as session:
                        # 1. Load weights
                        result = await session.execute(
                            select(RLWeight).where(RLWeight.market == market)
                        )
                        db_weights = result.scalars().all()
                        if db_weights:
                            for db_w in db_weights:
                                regime = db_w.regime
                                agent = db_w.agent_name
                                if regime in self.agent_weights and agent in self.agent_weights[regime]:
                                    self.agent_weights[regime][agent] = db_w.weight
                                    self.agent_alpha[regime][agent] = db_w.alpha
                                    self.agent_beta[regime][agent] = db_w.beta
                            
                            # 2. Load metadata
                            port_res = await session.execute(
                                select(Portfolio).where(Portfolio.market == market)
                            )
                            db_portfolio = port_res.scalars().first()
                            if db_portfolio and db_portfolio.state_data and "rl_metadata" in db_portfolio.state_data:
                                meta = db_portfolio.state_data["rl_metadata"]
                                self.total_closed_trades = meta.get("total_closed_trades", 0)
                                self.winning_trades = meta.get("winning_trades", 0)
                                self.retrain_count = meta.get("retrain_count", 0)
                                self._trades_since_last_retrain = meta.get("_trades_since_last_retrain", 0)
                                self._trade_history = meta.get("_trade_history", [])
                                self._batch_weight_deltas = meta.get("_batch_weight_deltas", self._batch_weight_deltas)
                            return True
                        return False
                loaded_from_db = run_async(load_db())
            except Exception as e:
                _rl_logger.error(f"[RL Engine] Failed to load state from SQLite: {e}")

        # Fallback to JSON — ALSO used when the JSON snapshot has seen more
        # trades than the DB. FIX 2026-08-03: the shutdown DB write is
        # fire-and-forget on a closing loop and usually never lands, so
        # rl_metadata in the DB was stale/absent and counters restarted from 0
        # on every boot (weights half-survived via RLWeight rows, history and
        # counters were wiped). The JSON write in save_state is synchronous
        # and reliable — trust whichever source has the higher trade count.
        _json_state = None
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    _json_state = json.load(f)
            except Exception as e:
                _rl_logger.error("[RL Engine] Failed to read JSON state file: " + str(e))
        _json_is_fresher = (
            _json_state is not None
            and _json_state.get("total_closed_trades", 0) > self.total_closed_trades
        )
        if _json_state is not None and (not loaded_from_db or _json_is_fresher):
            try:
                state = _json_state
                if loaded_from_db and _json_is_fresher:
                    print(f"[RL Engine] JSON snapshot is fresher than DB "
                          f"({state.get('total_closed_trades', 0)} vs "
                          f"{self.total_closed_trades} trades) — restoring from JSON.")

                saved_weights = state.get("agent_weights", {})
                for regime in self.REGIMES:
                    if regime in saved_weights:
                        for agent in self.agent_weights[regime]:
                            if agent in saved_weights[regime]:
                                self.agent_weights[regime][agent] = saved_weights[regime][agent]

                self.total_closed_trades = state.get("total_closed_trades", 0)
                self.winning_trades = state.get("winning_trades", 0)
                self.retrain_count = state.get("retrain_count", 0)
                self._trades_since_last_retrain = state.get("_trades_since_last_retrain", 0)
                self._trade_history = state.get("_trade_history", [])

                saved_alpha = state.get("agent_alpha", {})
                for regime in self.REGIMES:
                    if regime in saved_alpha:
                        for agent in self.agent_alpha[regime]:
                            if agent in saved_alpha[regime]:
                                self.agent_alpha[regime][agent] = saved_alpha[regime][agent]

                saved_beta = state.get("agent_beta", {})
                for regime in self.REGIMES:
                    if regime in saved_beta:
                        for agent in self.agent_beta[regime]:
                            if agent in saved_beta[regime]:
                                self.agent_beta[regime][agent] = saved_beta[regime][agent]

                saved_deltas = state.get("_batch_weight_deltas", {})
                for regime in self.REGIMES:
                    if regime in saved_deltas:
                        for agent in self._batch_weight_deltas[regime]:
                            if agent in saved_deltas[regime]:
                                self._batch_weight_deltas[regime][agent] = saved_deltas[regime][agent]

                saved_counts = state.get("_agent_trade_counts", {})
                for regime in self.REGIMES:
                    if regime in saved_counts:
                        for agent in self._agent_trade_counts.get(regime, {}):
                            if agent in saved_counts[regime]:
                                self._agent_trade_counts[regime][agent] = saved_counts[regime][agent]

                # If DB is enabled but empty, seed it now!
                if DB_ENABLED and not loaded_from_db:
                    async def seed_db():
                        async with AsyncSessionLocal() as session:
                            for regime in self.REGIMES:
                                for agent, weight in self.agent_weights[regime].items():
                                    db_w = RLWeight(
                                        market=market,
                                        regime=regime,
                                        agent_name=agent,
                                        weight=float(weight),
                                        alpha=float(self.agent_alpha[regime].get(agent, 1.0)),
                                        beta=float(self.agent_beta[regime].get(agent, 1.0))
                                    )
                                    session.add(db_w)
                            await session.commit()
                    run_async(seed_db())
                    print("[RL Engine] Seeded SQLite weights from " + str(os.path.basename(filepath)))
            except Exception as e:
                print("[RL Engine] Failed to load JSON state: " + str(e))

        # Always sanitize after load, regardless of source (DB or JSON).
        self._sanitize_history()

    def _sanitize_history(self):
        """
        Drop corrupt/synthetic trade-history entries.

        The 2026 cold-start seeder fed trades without capital_allocated
        (defaulted to 1.0), inflating pnl_pct ~100x (observed: 11,686%).
        Those entries poison the rolling-30 std used for Sharpe reward
        normalization, driving every real trade's reward to ~0 and freezing
        all weight learning. Real trades never exceed a few percent, so
        anything beyond +/-50% pnl_pct is corrupt and removed.

        If contamination was heavy (>=20 entries), the alpha/beta priors and
        weights were trained on that same garbage — reset them to defaults so
        real trades start from a clean slate.
        """
        before = len(self._trade_history)
        self._trade_history = [
            t for t in self._trade_history
            if abs(t.get("pnl_pct", 0.0)) <= 50.0
        ]
        dropped = before - len(self._trade_history)
        if dropped == 0:
            return

        self.total_closed_trades = len(self._trade_history)
        self.winning_trades = sum(1 for t in self._trade_history if t.get("is_win"))
        self._trades_since_last_retrain = min(
            self._trades_since_last_retrain, self.total_closed_trades)

        if dropped >= 20:
            # Heavy contamination: priors/weights learned from synthetic data.
            for regime in self.REGIMES:
                for agent in self.agent_weights.get(regime, {}):
                    self.agent_weights[regime][agent] = 1.0
                    self.agent_alpha[regime][agent] = 1.0
                    self.agent_beta[regime][agent] = 1.0
                for agent in self._batch_weight_deltas.get(regime, {}):
                    self._batch_weight_deltas[regime][agent] = 0.0
            self.retrain_count = 0
            self._trades_since_last_retrain = 0
            print(f"[RL Engine] Sanitized: dropped {dropped} synthetic/corrupt "
                  f"trades and reset weights/priors to defaults "
                  f"({self.total_closed_trades} real trades kept)")
        else:
            print(f"[RL Engine] Sanitized: dropped {dropped} corrupt trade(s), "
                  f"{self.total_closed_trades} kept")

    def get_stats(self):
        """Returns the full RL stats for the UI -- all computed from real closed trades."""
        recent = self._trade_history[-10:]
        recent_win_rate = round(sum(1 for t in recent if t["is_win"]) / len(recent) * 100, 1) if recent else 0.0
        avg_pnl = round(sum(t["pnl"] for t in self._trade_history) / len(self._trade_history), 4) if self._trade_history else 0.0

        return {
            "total_closed_trades": self.total_closed_trades,
            "winning_trades": self.winning_trades,
            "win_rate_pct": self.win_rate,
            "recent_10_win_rate": recent_win_rate,
            "retrain_count": self.retrain_count,
            "retrain_interval": RETRAIN_INTERVAL,
            "trades_till_retrain": self.trades_till_retrain,
            "trades_since_last_retrain": self._trades_since_last_retrain,
            "retrain_progress_pct": round(self._trades_since_last_retrain / RETRAIN_INTERVAL * 100, 1),
            "avg_pnl_per_trade": avg_pnl,
            "agent_weights": self.get_current_weights(),
            "regime_agent_weights": self.agent_weights,
        }

    def get_full_state(self) -> dict:
        """Return the complete serializable alpha/beta state for persistence or merge."""
        return {
            "agent_alpha": self.agent_alpha,
            "agent_beta":  self.agent_beta,
            "total_closed_trades": self.total_closed_trades,
        }

    def merge_backtest_state(self, state: dict):
        """
        Blend backtest-trained alpha/beta values into this live engine.
        Uses a conservative 30% backtest / 70% live ratio, but falls back
        to 60/40 when the live engine is cold (< 30 real trades).
        Safe to call after every continuous backtest run.
        """
        import numpy as np
        live_trades = self.total_closed_trades
        blend = 0.60 if live_trades < 30 else 0.30

        ext_alpha = state.get("agent_alpha", {})
        ext_beta  = state.get("agent_beta",  {})

        for regime in self.REGIMES:
            if regime not in ext_alpha:
                continue
            for agent in list(self.agent_alpha.get(regime, {}).keys()):
                if agent not in ext_alpha[regime]:
                    continue
                ea = float(ext_alpha[regime][agent])
                eb = float(ext_beta.get(regime, {}).get(agent, 1.0))
                la = self.agent_alpha[regime][agent]
                lb = self.agent_beta[regime][agent]
                self.agent_alpha[regime][agent] = float(np.clip(
                    (1 - blend) * la + blend * ea, 1.0, 50.0))
                self.agent_beta[regime][agent]  = float(np.clip(
                    (1 - blend) * lb + blend * eb, 1.0, 50.0))
                new_mean = 2.0 * self.agent_alpha[regime][agent] / (
                    self.agent_alpha[regime][agent] + self.agent_beta[regime][agent])
                self.agent_weights[regime][agent] = float(np.clip(new_mean, 0.1, 2.0))

        print(f"[RL] merge_backtest_state: blended {len(ext_alpha)} regimes "
              f"(blend={blend}, live_trades={live_trades})")
