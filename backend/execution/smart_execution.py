import time
import os
import asyncio
import json
import random as _random   # IV&V Low: hoisted from force_close (was a per-call import)
from typing import Dict, Any, List

from sqlalchemy import select
try:
    from database.database import AsyncSessionLocal
    from database.models import Order, Trade, Holding, Portfolio, RLWeight, Symbol, SYSTEM_USER_ID
except ImportError:
    SYSTEM_USER_ID = None

DB_ENABLED = os.getenv("DB_ENABLED", "false").lower() == "true"


async def _ensure_symbol_id(session, symbol: str):
    """Return the DB id for `symbol`, creating the Symbol row if it doesn't
    exist yet.

    IV&V DB gap: the `symbols` table was never seeded, so every order-write
    did `select(Symbol.id)` → None → the Order insert was silently skipped and
    the `orders`/`trades` audit trail stayed empty. Auto-creating the symbol on
    first use makes order persistence self-healing for any market/symbol.
    """
    sym_id = (await session.execute(
        select(Symbol.id).where(Symbol.symbol == symbol)
    )).scalar()
    if sym_id is not None:
        return sym_id
    _cur = "INR" if str(symbol).upper().endswith((".NS", ".BO")) else "USD"
    session.add(Symbol(symbol=symbol, active=True, currency=_cur))
    try:
        await session.flush()   # assign PK without committing the whole tx
    except Exception:
        # Concurrent insert of the same symbol from another engine — re-read.
        await session.rollback()
    return (await session.execute(
        select(Symbol.id).where(Symbol.symbol == symbol)
    )).scalar()


async def _persist_fill(session, symbol: str, side: str, quantity: float,
                        price: float, trade: dict = None):
    """Insert a FILLED Order (auto-creating the symbol). When `trade` is given
    — i.e. this fill CLOSES a round-trip — also insert a linked Trade row so
    the relational `trades` table mirrors the JSON closed_trades ledger.

    `trade` keys: entry, exit, stop_loss, target, profit, commission,
    strategy, confidence (all optional).
    """
    sym_id = await _ensure_symbol_id(session, symbol)
    if not sym_id:
        return
    order = Order(symbol_id=sym_id, side=side, quantity=quantity,
                  price=price, status="FILLED")
    session.add(order)
    if trade is not None:
        await session.flush()   # populate order.id for the FK
        session.add(Trade(
            order_id=order.id,
            entry=float(trade.get("entry", price) or price),
            exit=trade.get("exit", price),
            stop_loss=trade.get("stop_loss"),
            target=trade.get("target"),
            profit=trade.get("profit"),
            commission=trade.get("commission"),
            strategy=trade.get("strategy", "committee"),
            confidence=trade.get("confidence"),
        ))
    await session.commit()


from risk.position_sizing import PositionSizer
from risk.adaptive_stops import AdaptiveStopLoss
from analytics.simulator import AITradeSimulator
from analytics.journal import AIJournal
from analytics.rl_engine import ReinforcementLearningEngine
from execution.broker import SmartOrderRouter

# M-2: Per-market SHORT margin rates.
# SEBI SPAN minimum for Indian equities/futures is 15-25%; we use 20% (conservative).
# CME US futures: ~10% initial; Reg-T stocks: 15% (paper); Crypto: 20%; Forex: 5%.
_SHORT_MARGIN_RATES = {
    "INDIA":  0.20,
    "STOCKS": 0.15,
    "CRYPTO": 0.20,
    "FOREX":  0.05,
    "US":     0.10,
}


class SmartExecutionEngine:
    """
    Simulates Broker Intelligence (TWAP/VWAP, Iceberg) and maintains
    portfolio state for the engine.

    Key invariants enforced here:
      A-2  DB saves are fire-and-forget (asyncio.ensure_future) in the trade
           hot-path — the event loop is never blocked waiting for SQLite.
      A-3  active_holdings is guarded by _holdings_lock; balance is credited
           ONLY after a holding is confirmed removed from the list.
      E-1  For live brokers, the broker call is made FIRST; state is updated
           only after the broker confirms the order.
      M-2  SHORT margin is per-market (SEBI-compliant 20% for INDIA).
    """

    def __init__(
        self,
        state_filename="portfolio_state.json",
        rl_state_filename="rl_state.json",
        initial_balance=100000.0,
        journal_filename="journal.json",
    ):
        self.sizer     = PositionSizer()
        self.stops     = AdaptiveStopLoss()
        self.simulator = AITradeSimulator()
        self.journal   = AIJournal(filepath=journal_filename)
        self.rl_engine = ReinforcementLearningEngine()
        self.router    = SmartOrderRouter(strategy="VWAP", slices=5)

        self.state_file    = os.path.join(os.path.dirname(__file__), "..", "data", state_filename)
        self.rl_seed_file  = os.path.join(os.path.dirname(__file__), "..", "scripts", "rl_seed_trades.json")
        self.rl_state_file = os.path.join(os.path.dirname(__file__), "..", "data", rl_state_filename)

        self.portfolio_balance = initial_balance
        self._initial_balance  = initial_balance   # for cross-market reset
        self.active_holdings: List[Dict] = []
        self.execution_logs:  List[Dict] = []
        self.closed_trades:   List[Dict] = []
        self.latest_sim_result = None

        # CRITICAL FIX 2026-07-20: was `"_st" in state_filename` etc. —
        # but "portfolio_state.json", "portfolio_state_cx.json" and
        # "portfolio_state_fx.json" ALL contain "_st" (inside "_state"!),
        # so US/STOCKS/CRYPTO/FOREX all resolved to market="STOCKS" and
        # shared ONE DB portfolio row + RLWeight rows. This cross-wrote
        # holdings/trades between engines (observed: forex book was an
        # exact alias of the US book; crypto engine held MSFT). Use
        # suffix-of-stem matching, which is unambiguous.
        _stem = state_filename.rsplit(".", 1)[0]
        self.market = (
            "INDIA"  if _stem.endswith("_in") else
            "STOCKS" if _stem.endswith("_st") else
            "CRYPTO" if _stem.endswith("_cx") else
            "FOREX"  if _stem.endswith("_fx") else
            "US"
        )
        self._stop_cooldown: dict = {}   # symbol -> timestamp of last stop-out

        # A-3: All mutations of active_holdings are serialized through this lock.
        # Lazy-init so it is created inside the running event loop.
        self._holdings_lock: asyncio.Lock = None

        from execution.broker_factory import get_broker
        self.broker = get_broker(market=self.market)
        print(f"[SmartExecution] Broker: {self.broker.name} (live={self.broker.is_live})")

        self._load_state()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_lock(self) -> asyncio.Lock:
        """A-3: Lazy-init the holdings lock inside the running event loop."""
        if self._holdings_lock is None:
            self._holdings_lock = asyncio.Lock()
        return self._holdings_lock

    def _get_db_lock(self) -> asyncio.Lock:
        """Serializes DB saves for this engine. Concurrent fire-and-forget
        save tasks raced between SELECT and INSERT on the portfolio row
        (UNIQUE constraint failed: portfolio.market)."""
        if getattr(self, "_db_save_lock", None) is None:
            self._db_save_lock = asyncio.Lock()
        return self._db_save_lock

    def _get_realized_b(self) -> float:
        """
        Realized R:R from RL trade history.  Falls back to 2.0 when thin.
        """
        history = self.rl_engine._trade_history
        wins    = [t["pnl"] for t in history if t.get("is_win") and t["pnl"] > 0]
        losses  = [abs(t["pnl"]) for t in history if not t.get("is_win") and t["pnl"] < 0]
        if wins and losses:
            return round((sum(wins) / len(wins)) / (sum(losses) / len(losses)), 3)
        return 2.0

    def _apply_risk_caps(self, symbol: str, side: str, shares: float, price: float):
        """
        IV&V H4: enforce portfolio-level risk limits as a HARD ENTRY GATE.

        Previously `max_single_position_pct` (15%) and `min_cash_reserve_pct`
        (10%) were only computed for display; nothing stopped the book from
        concentrating past them. This clamps the order down to fit both limits
        and rejects it if nothing tradeable remains.

        Returns: (adjusted_shares, reject_reason_or_None). adjusted_shares<=0
        means "reject".
        """
        from risk.portfolio_risk import RISK_LIMITS

        equity = self.get_total_equity()
        if equity <= 0:
            return 0.0, "Non-positive equity — new entries blocked."

        max_pos_frac  = RISK_LIMITS.get("max_single_position_pct", 15.0) / 100.0
        min_cash_frac = RISK_LIMITS.get("min_cash_reserve_pct", 10.0) / 100.0
        cash          = self.portfolio_balance
        min_cash      = min_cash_frac * equity
        spendable     = max(0.0, cash - min_cash)   # cash usable without breaching the floor

        # 1. Single-position notional cap.
        max_notional = max_pos_frac * equity
        if shares * price > max_notional:
            shares = max_notional / max(price, 1e-9)

        # 2. Cash-reserve floor. BUY consumes full notional; SHORT consumes margin.
        if side == "BUY":
            if shares * price > spendable:
                shares = spendable / max(price, 1e-9)
        else:  # SHORT
            margin_rate = _SHORT_MARGIN_RATES.get(self.market, 0.15)
            outflow_per_share = price * margin_rate
            if shares * outflow_per_share > spendable:
                shares = spendable / max(outflow_per_share, 1e-9)

        # Re-normalize to the broker's lot size after clamping.
        shares = self.broker.normalize_quantity(symbol, max(0.0, shares))
        if shares <= 0:
            return 0.0, ("Blocked by portfolio risk caps "
                         "(single-position 15% / cash-reserve 10%).")
        return shares, None

    # ------------------------------------------------------------------ #
    # Force close (stop-loss / take-profit)                               #
    # ------------------------------------------------------------------ #

    async def force_close(self, holding: dict, price: float, reason: str) -> tuple:
        """
        Force-close an active holding when stop-loss or take-profit fires.
        Called from the live trading loop; bypasses committee evaluation.

        A-3 fix:
          1. Acquire _holdings_lock.
          2. Confirm holding is still in the list (guards against concurrent close).
          3. Remove it from the list.
          4. Credit balance ONLY after confirmed removal — no phantom credits.
        """
        symbol    = holding["symbol"]
        direction = holding.get("direction", "LONG")
        shares    = holding["shares"]
        entry_p   = holding["entry_price"]

        # Exit slippage (1–10 bps, adverse)
        _slip = price * _random.uniform(0.0001, 0.001)
        price = round(price - _slip, 6) if direction == "LONG" else round(price + _slip, 6)

        # Exit commission (0.1%)
        _exit_comm = shares * price * 0.001

        # Pre-compute P&L values outside the lock (pure arithmetic, no shared state)
        if direction == "LONG":
            revenue     = shares * price - _exit_comm
            profit_loss = revenue - shares * entry_p
            profit_pct  = (price - entry_p) / entry_p * 100
        else:  # SHORT
            profit_loss = shares * (entry_p - price) - _exit_comm
            profit_pct  = (entry_p - price) / entry_p * 100
            _margin     = holding.get("margin_reserved", shares * entry_p)
            revenue     = _margin + profit_loss

        # A-3: Remove FIRST under lock, credit ONLY after confirmed removal.
        async with self._get_lock():
            if holding not in self.active_holdings:
                # Already closed by a concurrent tick — skip entirely.
                # If we credited here it would be a phantom balance injection.
                return False, f"[A-3] {symbol} already closed by concurrent tick — skipped."
            self.active_holdings.remove(holding)
            self.portfolio_balance += revenue   # atomic: remove confirmed, now safe to credit

        # The rest of the accounting is outside the lock (appends to separate lists)
        self.closed_trades.append({
            "symbol":      symbol,
            "shares":      shares,
            "direction":   direction,
            "entry_price": entry_p,
            "exit_price":  price,
            "profit_loss": round(profit_loss, 2),
            "profit_pct":  round(profit_pct, 2),
            "time":        time.time(),
            "reason":      reason,
        })
        self.execution_logs.append({
            "time":   time.time(),
            "action": f"FORCE_{reason}",
            "symbol": symbol,
            "shares": shares,
            "price":  price,
        })

        _stop          = holding.get("stop_loss", entry_p * (0.98 if direction == "LONG" else 1.02))
        _stop_dist_pct = abs(entry_p - _stop) / max(entry_p, 1e-9) * 100
        trade_result   = {
            "profit_loss":       profit_loss,
            "capital_allocated": shares * entry_p,
            "action":            "BUY" if direction == "LONG" else "SELL",
            "regime":            holding.get("regime", "Sideways"),
            "stop_distance_pct": round(_stop_dist_pct, 4),
        }
        # IV&V Medium: attribute stop/TP outcomes to the entry committee so the
        # RL engine learns from the MAJORITY of exits (stops/TPs), not only from
        # committee-driven manual closes. Falls back to {} if none was stashed.
        self.rl_engine.process_trade_outcome(
            trade_result, holding.get("committee_breakdown", {}) or {})
        self.journal.log_trade(symbol, f"FORCE_{reason}", price, {"reason": reason})

        if DB_ENABLED:
            try:
                async with AsyncSessionLocal() as session:
                    side = "SELL" if direction == "LONG" else "BUY"
                    await _persist_fill(session, symbol, side, shares, price, trade={
                        "entry":      entry_p,
                        "exit":       price,
                        "stop_loss":  holding.get("stop_loss"),
                        "target":     holding.get("take_profit"),
                        "profit":     round(profit_loss, 2),
                        "commission": round(_exit_comm, 4),
                        "strategy":   f"FORCE_{reason}",
                    })
            except Exception as e:
                print(f"[force_close] DB write failed: {e}")

        if "STOP_LOSS" in reason:
            self._stop_cooldown[symbol] = time.time()

        await self._save_state_async()   # A-2: non-blocking
        return True, f"PnL: ${profit_loss:.2f} ({profit_pct:.2f}%)"

    async def partial_close(self, holding: dict, price: float, fraction: float = 0.5, reason: str = "TP1_1.5R") -> tuple:
        """
        Execute partial scale-out (e.g. 50% at 1.5R) and immediately ratchet the remaining position's
        stop loss to Breakeven (entry_price + fee buffer).
        """
        symbol       = holding["symbol"]
        direction    = holding.get("direction", "LONG")
        total_shares = holding["shares"]
        entry_p      = holding["entry_price"]
        is_fractional = any(c in symbol for c in ["-USD", "BTC", "ETH", "SOL", "EUR", "GBP", "=X", "=F"])

        if is_fractional:
            close_shares = round(total_shares * fraction, 4)
        else:
            close_shares = int(total_shares * fraction)

        if close_shares <= 0 or close_shares >= total_shares:
            # Fallback for small integer positions
            if total_shares > 1 and close_shares == 0:
                close_shares = 1
            else:
                return False, f"Sub-lot partial quantity ({close_shares}) for {symbol}."

        remaining_shares = total_shares - close_shares

        # Exit slippage (1–10 bps, adverse)
        _slip = price * _random.uniform(0.0001, 0.001)
        effective_p = round(price - _slip, 6) if direction == "LONG" else round(price + _slip, 6)
        _exit_comm = close_shares * effective_p * 0.001

        if direction == "LONG":
            revenue     = close_shares * effective_p - _exit_comm
            profit_loss = revenue - close_shares * entry_p
            profit_pct  = (effective_p - entry_p) / entry_p * 100
        else:  # SHORT
            profit_loss = close_shares * (entry_p - effective_p) - _exit_comm
            profit_pct  = (entry_p - effective_p) / entry_p * 100
            _margin_rel = (holding.get("margin_reserved", total_shares * entry_p) / max(total_shares, 1e-9)) * close_shares
            revenue     = _margin_rel + profit_loss

        # Broker call for live
        if hasattr(self, "broker") and getattr(self.broker, "is_live", False):
            _fn = getattr(self.broker, "sell" if direction == "LONG" else "cover", None)
            if _fn:
                _ok, _b_msg, _oid = _fn(symbol, close_shares, effective_p)
                if not _ok:
                    return False, f"Broker rejected partial {direction}: {_b_msg}"

        async with self._get_lock():
            if holding not in self.active_holdings:
                return False, f"{symbol} already closed."


            holding["shares"] = remaining_shares
            holding["value"]  = round(remaining_shares * effective_p, 4)
            if "margin_reserved" in holding:
                holding["margin_reserved"] = max(0.0, holding["margin_reserved"] - _margin_rel)

            # Mark TP1 hit and ratchet remaining stop to Breakeven
            holding["tp1_hit"] = True
            be_buffer = entry_p * 0.001  # cover round-trip commission
            if direction == "LONG":
                holding["stop_loss"] = max(holding.get("stop_loss", 0.0), round(entry_p + be_buffer, 4))
            else:
                holding["stop_loss"] = min(holding.get("stop_loss", 999999.0), round(entry_p - be_buffer, 4))

            self.portfolio_balance += revenue

        self.closed_trades.append({
            "symbol":      symbol,
            "shares":      close_shares,
            "direction":   direction,
            "entry_price": entry_p,
            "exit_price":  effective_p,
            "profit_loss": round(profit_loss, 2),
            "profit_pct":  round(profit_pct, 2),
            "time":        time.time(),
            "reason":      f"PARTIAL_{reason}",
        })
        self.execution_logs.append({
            "time":   time.time(),
            "action": f"PARTIAL_{reason}",
            "symbol": symbol,
            "shares": close_shares,
            "price":  effective_p,
        })

        if DB_ENABLED:
            try:
                async with AsyncSessionLocal() as session:
                    side = "SELL" if direction == "LONG" else "BUY"
                    await _persist_fill(session, symbol, side, close_shares, effective_p, trade={
                        "entry":      entry_p,
                        "exit":       effective_p,
                        "stop_loss":  holding.get("stop_loss"),
                        "target":     holding.get("tp1_target"),
                        "profit":     round(profit_loss, 2),
                        "commission": round(_exit_comm, 4),
                        "strategy":   f"PARTIAL_{reason}",
                    })
            except Exception as e:
                print(f"[partial_close] DB write failed: {e}")

        await self._save_state_async()
        return True, f"Scale-out 50% ({close_shares:.4g}) @ ${effective_p:.2f} (Realized: +${profit_loss:.2f}), SL moved to Breakeven (${holding['stop_loss']:.2f})"


    # ------------------------------------------------------------------ #
    # Async-safe state persistence (A-2)                                  #
    # ------------------------------------------------------------------ #

    async def _save_state_async(self):
        """
        A-2 fix: JSON save is synchronous (fast, ~1 ms); DB save is fired as
        a background asyncio task so the event loop is NEVER blocked waiting
        for SQLite during execute_trade or force_close.
        """
        self._save_state_json()
        # FIX 2026-08-03: persist RL state on the hot path too. Previously the
        # RL counters/history/weights only hit disk in _save_state() (graceful
        # shutdown), and even there the DB write is fire-and-forget on a dying
        # loop — so every crash/kill rolled RL learning back to the previous
        # boot (observed: all 5 engines' counters restarted from 0 each
        # session; retrain arithmetic proved it). save_state is cheap: sync
        # JSON dump (~ms) + DB task on the LIVE loop, which does complete.
        # Note: the RL DB task and _save_state_db use different locks, so the
        # rl_metadata blob can lag by one trade under a race — the sync JSON
        # copy is always current and load_state now prefers the fresher one.
        try:
            self.rl_engine.save_state(self.rl_state_file)
        except Exception as e:
            print(f"[SmartExecution] RL hot-path save failed: {e}")
        if DB_ENABLED:
            asyncio.ensure_future(self._save_state_db())

    def _save_state_json(self):
        """Atomic JSON write — always fast (<5 ms)."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            payload = {
                "portfolio_balance": self.portfolio_balance,
                "active_holdings":   self.active_holdings,
                "execution_logs":    self.execution_logs[-500:],  # cap log size
                "closed_trades":     self.closed_trades,
            }
            tmp = self.state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, self.state_file)
        except Exception as e:
            print(f"[SmartExecution] JSON save failed: {e}")

    async def _save_state_db(self):
        """Background DB save — runs as asyncio task, does not block tick loop.

        Serialized via _get_db_lock(): without it, two queued save tasks both
        SELECT (no row yet), then both INSERT → UNIQUE constraint failure on
        portfolio.market. The lock makes the select-or-insert atomic per
        engine; an IntegrityError fallback covers any remaining insert race
        with the startup seeder.
        """
        if not DB_ENABLED:
            return
        try:
            async with self._get_db_lock():
                async with AsyncSessionLocal() as session:
                    payload = {
                        "active_holdings": self.active_holdings,
                        "execution_logs":  self.execution_logs[-500:],
                        "closed_trades":   self.closed_trades,
                    }
                    result = await session.execute(
                        select(Portfolio).where(Portfolio.market == self.market)
                    )
                    db_portfolio = result.scalars().first()
                    if not db_portfolio:
                        db_portfolio = Portfolio(user_id=SYSTEM_USER_ID, market=self.market)
                        session.add(db_portfolio)
                    # FIX 2026-07-20: preserve rl_metadata written into the same
                    # state_data blob by rl_engine.save_state — replacing
                    # state_data wholesale silently wiped the RL trade history
                    # on every trade save (observed: no portfolio row had
                    # rl_metadata despite the RL engine writing it).
                    _existing = db_portfolio.state_data or {}
                    if "rl_metadata" in _existing:
                        payload["rl_metadata"] = _existing["rl_metadata"]
                    db_portfolio.cash = self.portfolio_balance
                    db_portfolio.state_data = payload
                    try:
                        await session.commit()
                    except Exception:
                        # Row appeared between SELECT and INSERT (e.g. startup
                        # seeder committed concurrently) — retry as UPDATE.
                        await session.rollback()
                        result = await session.execute(
                            select(Portfolio).where(Portfolio.market == self.market)
                        )
                        db_portfolio = result.scalars().first()
                        if db_portfolio:
                            _existing = db_portfolio.state_data or {}
                            if "rl_metadata" in _existing and "rl_metadata" not in payload:
                                payload["rl_metadata"] = _existing["rl_metadata"]
                            db_portfolio.cash = self.portfolio_balance
                            db_portfolio.state_data = payload
                            await session.commit()
        except Exception as e:
            print(f"[DB ERROR] Background save failed: {e}")

    # ------------------------------------------------------------------ #
    # Synchronous _run_async (startup / shutdown only — NOT hot-path)     #
    # ------------------------------------------------------------------ #

    def _run_async(self, coro):
        """
        Run a coroutine from a synchronous context (startup/shutdown only).
        NEVER call from execute_trade or force_close — use _save_state_async().
        """
        import threading
        from concurrent.futures import Future
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if loop.is_running():
            # We're being called synchronously FROM the running loop's thread
            # (e.g. a sync helper inside a FastAPI handler). The old approach
            # ran the coroutine on a brand-new loop in a thread — but the
            # aiosqlite engine's connection pool is bound to THIS loop, so it
            # died with "Queue is bound to a different event loop" and the
            # save silently never happened. Fire-and-forget on the running
            # loop instead: same loop as the DB pool, no deadlock.
            task = loop.create_task(coro)
            def _on_done(t):
                if not t.cancelled():
                    exc = t.exception()
                    if exc:
                        print(f"[_run_async] task failed: {exc}")
            task.add_done_callback(_on_done)
            return None

        else:
            return loop.run_until_complete(coro)


    # ------------------------------------------------------------------ #
    # State load / save (sync paths — startup and graceful shutdown)      #
    # ------------------------------------------------------------------ #

    def _load_state(self):
        # 1. RL state
        self.rl_engine.load_state(self.rl_state_file)

        # 2. RL seed trades (cold-start only)
        if self.rl_engine.total_closed_trades == 0 and os.path.exists(self.rl_seed_file):
            try:
                with open(self.rl_seed_file) as f:
                    seed_trades = json.load(f)
                    if seed_trades:
                        self.rl_engine.pre_seed_from_backtest(seed_trades)
            except Exception as e:
                print(f"Failed to load RL seed trades: {e}")

        # 3. Portfolio state
        loaded_from_db = False
        if DB_ENABLED:
            try:
                async def _load_db():
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(Portfolio).where(Portfolio.market == self.market)
                        )
                        db_portfolio = result.scalars().first()
                        if db_portfolio:
                            self.portfolio_balance = db_portfolio.cash
                            state_data = db_portfolio.state_data or {}
                            self.active_holdings = state_data.get("active_holdings", [])
                            self.execution_logs  = state_data.get("execution_logs", [])
                            self.closed_trades   = state_data.get("closed_trades", [])
                            return True
                        return False
                loaded_from_db = self._run_async(_load_db())
            except Exception as e:
                print(f"[DB ERROR] Failed to load state: {e}")

        if not loaded_from_db and os.path.exists(self.state_file):
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                self.portfolio_balance = state.get("portfolio_balance", self.portfolio_balance)
                self.active_holdings   = state.get("active_holdings", [])
                self.execution_logs    = state.get("execution_logs", [])
                self.closed_trades     = state.get("closed_trades", [])

                if DB_ENABLED:
                    # IV&V: reuse the lock-protected, upsert-safe save path
                    # instead of a blind INSERT. The old _seed_db did an
                    # unconditional INSERT with no existence check and, under
                    # fire-and-forget scheduling, raced the first tick save for
                    # the same market → "UNIQUE constraint failed: portfolio.market".
                    # _save_state_db serializes on the per-engine DB lock and
                    # does select-or-insert with an IntegrityError retry.
                    self._run_async(self._save_state_db())
                    print(f"[DB INIT] Seeded SQLite from {os.path.basename(self.state_file)}")
            except Exception as e:
                print(f"Failed to load portfolio state: {e}")
        elif DB_ENABLED and not loaded_from_db:
            try:
                # Same idempotent path for the empty-default case.
                self._run_async(self._save_state_db())
                print(f"[DB INIT] Created default portfolio for {self.market}")
            except Exception as e:
                print(f"[DB ERROR] Failed to create default portfolio: {e}")

        # 4. Cross-market cleanup (always, regardless of load source)
        self._sanitize_cross_market()

    @staticmethod
    def _symbol_market(symbol: str) -> str:
        """Classify a symbol into the engine market it belongs to."""
        s = symbol or ""
        if s.endswith(".NS"):
            return "INDIA"
        if s.endswith("=F"):
            return "US"       # futures universe (MNQ=F, MGC=F)
        if s.endswith("=X"):
            return "FOREX"
        if s.endswith("-USD"):
            return "CRYPTO"
        return "STOCKS"

    def _sanitize_cross_market(self):
        """
        FIX 2026-07-20: before the market-inference fix, US/STOCKS/CRYPTO/
        FOREX all shared one DB portfolio row, so each engine inherited other
        markets' holdings and closed trades (observed: forex book held NVDA,
        crypto engine managed MSFT positions). Drop any holding/closed trade
        whose symbol belongs to a different market's engine. If the entire
        book turns out to be foreign (forex: 35/35 foreign), reset the
        balance to the engine's initial value — it never truly traded.
        """
        ct_before = len(self.closed_trades)
        h_before  = len(self.active_holdings)
        self.closed_trades = [
            t for t in self.closed_trades
            if self._symbol_market(t.get("symbol", "")) == self.market
        ]
        self.active_holdings = [
            h for h in self.active_holdings
            if self._symbol_market(h.get("symbol", "")) == self.market
        ]
        dropped_ct = ct_before - len(self.closed_trades)
        dropped_h  = h_before - len(self.active_holdings)
        if dropped_ct or dropped_h:
            if not self.closed_trades and not self.active_holdings:
                # Book was 100% foreign — this engine never actually traded.
                print(f"[SmartExecution:{self.market}] Book was entirely "
                      f"foreign ({dropped_ct} trades, {dropped_h} holdings "
                      f"dropped) — resetting balance to initial "
                      f"{self._initial_balance}")
                self.portfolio_balance = self._initial_balance
            else:
                print(f"[SmartExecution:{self.market}] Dropped {dropped_ct} "
                      f"foreign closed trades and {dropped_h} foreign "
                      f"holdings inherited via the shared-DB-row bug")

    def _save_state(self):
        """
        Synchronous save — used ONLY at shutdown (save_portfolio_state).
        The hot-path (execute_trade / force_close) uses _save_state_async().
        """
        if DB_ENABLED:
            try:
                # Single code path: _save_state_db carries the per-engine DB
                # lock + IntegrityError retry (upsert semantics).
                self._run_async(self._save_state_db())
            except Exception as e:
                print(f"[DB ERROR] Sync save failed: {e}")
        self._save_state_json()
        self.rl_engine.save_state(self.rl_state_file)

    # ------------------------------------------------------------------ #
    # Trade execution                                                      #
    # ------------------------------------------------------------------ #

    async def execute_trade(self, symbol: str, price: float, decision: Dict[str, Any]) -> tuple:
        """
        Execute a BUY/SELL signal from MasterAgent.

        E-1 fix: for live brokers the broker call is made FIRST.  State
        (portfolio_balance, active_holdings) is only mutated after the broker
        confirms the order.  For paper brokers (is_live=False) the order is
        always accepted so the order of operations does not matter — state is
        updated as before.
        """
        signal     = decision["signal"]
        confidence = decision["confidence"]

        # Cooldown: block new entries for 60 s after a stop-out
        if signal in ("BUY", "SELL"):
            last_stop = self._stop_cooldown.get(symbol, 0)
            if time.time() - last_stop < 60.0:
                return False, f"Cooldown active for {symbol} after stop-out."

        # ── BUY ──────────────────────────────────────────────────────── #
        if signal == "BUY":
            # Check for an open SHORT to cover
            short_holding = next(
                (h for h in self.active_holdings
                 if h["symbol"] == symbol and h.get("direction") == "SHORT"),
                None,
            )

            if short_holding:
                # ── BUY TO COVER ──
                # Exit slippage (1–10 bps, adverse)
                _slip = price * _random.uniform(0.0001, 0.001)
                price = round(price + _slip, 6)
                _exit_comm  = short_holding["shares"] * price * 0.001
                profit_loss = short_holding["shares"] * (short_holding["entry_price"] - price) - _exit_comm
                profit_pct  = (short_holding["entry_price"] - price) / short_holding["entry_price"] * 100
                _margin     = short_holding.get("margin_reserved",
                                                short_holding["shares"] * short_holding["entry_price"])
                revenue     = _margin + profit_loss


                # E-1: broker first for live.
                # IV&V C2: normalize to broker lot size (never int()-truncate to 0).
                # This is an EXIT — if the normalized qty is 0 we still must close
                # internal state (an entry that rounded to 0 would have been
                # rejected, so a live position at this size should not exist);
                # log and skip only the broker leg.
                if self.broker.is_live:
                    _cover_qty = self.broker.normalize_quantity(symbol, short_holding["shares"])
                    if _cover_qty > 0:
                        _ok, _msg, _oid = self.broker.cover(symbol, _cover_qty, price)
                        if not _ok:
                            return False, f"Broker rejected COVER: {_msg}"
                    else:
                        print(f"[COVER] Sub-lot live qty for {symbol} "
                              f"({short_holding['shares']}) — closing internal state only.")

                # A-3: remove then credit under lock
                async with self._get_lock():
                    if short_holding not in self.active_holdings:
                        return False, f"[A-3] SHORT on {symbol} already closed (concurrent)."
                    self.active_holdings.remove(short_holding)
                    self.portfolio_balance += revenue

                self.execution_logs.append({
                    "time": time.time(), "action": "FILLED_COVER",
                    "symbol": symbol, "shares": short_holding["shares"], "price": price,
                })
                self.journal.log_trade(symbol, "BUY", price, decision)

                if DB_ENABLED:
                    try:
                        async with AsyncSessionLocal() as session:
                            await _persist_fill(session, symbol, "BUY",
                                                short_holding["shares"], price, trade={
                                "entry":      short_holding.get("entry_price"),
                                "exit":       price,
                                "stop_loss":  short_holding.get("stop_loss"),
                                "target":     short_holding.get("take_profit"),
                                "profit":     round(profit_loss, 2),
                                "commission": round(_exit_comm, 4),
                                "strategy":   "COVER",
                                "confidence": decision.get("confidence"),
                            })
                    except Exception as e:
                        print(f"Failed to write DB order (COVER): {e}")

                _sh_entry        = short_holding.get("entry_price", price)
                _sh_stop         = short_holding.get("stop_loss", _sh_entry * 1.02)
                _sh_stop_dist    = abs(_sh_entry - _sh_stop) / max(_sh_entry, 1e-9) * 100
                trade_result     = {
                    "profit_loss":       profit_loss,
                    "capital_allocated": short_holding["shares"] * _sh_entry,
                    "action":            "SELL",
                    "regime":            short_holding.get("regime", "Sideways"),
                    "stop_distance_pct": round(_sh_stop_dist, 4),
                }
                self.closed_trades.append({
                    "symbol": symbol, "shares": short_holding["shares"],
                    "direction": "SHORT",
                    "entry_price": short_holding["entry_price"], "exit_price": price,
                    "profit_loss": round(profit_loss, 2), "profit_pct": round(profit_pct, 2),
                    "time": time.time(), "reason": decision.get("reason", "Unknown"),
                })
                if "committee_breakdown" in decision:
                    self.rl_engine.process_trade_outcome(trade_result, decision["committee_breakdown"])
                await self._save_state_async()
                return True, f"FILLED BUY-TO-COVER {short_holding['shares']} @ ${price:.2f} (PnL: ${profit_loss:.2f})"

            else:
                # ── OPEN LONG ──
                # Prevent duplicate
                async with self._get_lock():
                    if any(h["symbol"] == symbol and h.get("direction", "LONG") == "LONG"
                           for h in self.active_holdings):
                        return False, f"Already in LONG on {symbol}."

                regime     = decision.get("regime", "Sideways")
                realized_b = self._get_realized_b()
                _atr       = decision.get("entry_features", {}).get("atr_14") or decision.get("atr_14", 0.0)
                _atr_pct   = float(_atr) / max(float(price), 1.0) * 100 if _atr else 0.0
                size_data  = self.sizer.calculate_size(
                    confidence, self.portfolio_balance, price,
                    regime=regime,
                    recent_win_rate=self.rl_engine.win_rate / 100.0,
                    n_closed_trades=self.rl_engine.total_closed_trades,
                    realized_b=realized_b, atr_pct=_atr_pct,
                )
                shares = size_data["shares"]
                if shares <= 0:
                    return False, f"Kelly sizer returned 0 shares (conf={confidence:.2f})"

                # IV&V C2: normalize to broker lot size UP FRONT so fill/cost/
                # margin are all computed on the tradeable quantity. Paper/crypto
                # keep fractional; integer-lot brokers round (sub-lot → reject).
                shares = self.broker.normalize_quantity(symbol, shares)
                if shares <= 0:
                    return False, (f"Sub-lot BUY suppressed for {symbol}: sized quantity "
                                   f"rounds to 0 tradeable units.")

                # IV&V H4: enforce single-position + cash-reserve caps as a gate.
                shares, _cap_reject = self._apply_risk_caps(symbol, "BUY", shares, price)
                if shares <= 0:
                    return False, _cap_reject

                # Spread & Slippage Guard
                _bid = float(decision.get("bid") or decision.get("entry_features", {}).get("bid") or 0.0)
                _ask = float(decision.get("ask") or decision.get("entry_features", {}).get("ask") or 0.0)
                if _bid > 0 and _ask > 0:
                    _ok_spread, _spread_pct, _spread_msg = self.router.check_spread(_bid, _ask)
                    if not _ok_spread:
                        return False, f"Spread veto: {_spread_msg}"

                # Phase 3 CONFIRMED meta-label veto gate — BTC-USD LONG entries only
                # (the exact scope the model was trained + CPCV-validated on:
                # 15/15 splits uplift-positive, +0.166R mean net of costs, DSR 1.0).
                # VETO FILTER ONLY: blocks entries with P(win) < GATE_THRESHOLD (0.65); never
                # used to size up. Fail-open: p=None -> proceed normally.
                if self.market == "CRYPTO" and symbol.upper() == "BTC-USD":
                    try:
                        from analytics.meta_gate import MetaGate, GATE_THRESHOLD
                        _p = await asyncio.to_thread(MetaGate.instance().p_win, symbol)
                        if _p is not None and _p < GATE_THRESHOLD:
                            return False, (f"Meta-label veto: P(win)={_p:.3f} < "
                                           f"{GATE_THRESHOLD} (unfavorable macro regime)")
                    except Exception as _mg_e:
                        print(f"[MetaGate] gate error (fail-open): {_mg_e}")



                _atr_raw   = decision.get("entry_features", {}).get("atr_14") or 0.0
                _vol_proxy = (_atr_raw / max(price, 1e-9)) if _atr_raw > 0 else 0.02
                stop_data  = self.stops.calculate(price, signal, volatility_proxy=_vol_proxy, regime=regime)
                p_win_frac = self.rl_engine.regime_win_rate(regime)
                # IV&V H3: run the 5k-path MC + any vol fetch in a worker thread
                # so the trading loop (and every other market's stop checks) is
                # never blocked by CPU or network here.
                sim_result = await asyncio.to_thread(
                    self.simulator.simulate,
                    current_price=price, stop_loss=stop_data["stop_loss"],
                    take_profit=stop_data["take_profit"], symbol=symbol,
                    session_quality=decision.get("session_quality", "NORMAL"),
                    direction="LONG", p_win=p_win_frac,
                )
                self.latest_sim_result = sim_result
                if p_win_frac is not None and not sim_result["is_viable"]:
                    ev = sim_result.get("expected_value", 0.0)
                    return False, f"AI Trade Simulator veto (Monte Carlo EV={ev*100:.3f}%)"

                fill_result    = self.router.execute(symbol, shares, price, decision.get("volume", 50000))
                avg_fill_price = fill_result["avg_fill_price"]
                cost           = fill_result["total_cost"]

                # E-1: live broker call BEFORE modifying state.
                # `shares` is already broker-normalized (see sizing block above).
                if self.broker.is_live:
                    _ok, _msg, _oid = self.broker.buy(symbol, shares, avg_fill_price)
                    if not _ok:
                        return False, f"Broker rejected BUY: {_msg}"

                holding = {
                    "symbol":        symbol,
                    "shares":        shares,
                    "entry_price":   round(avg_fill_price, 4),
                    "current_price": round(avg_fill_price, 4),
                    "value":         round(cost, 4),
                    "change":        0.0,
                    "stop_loss":     round(stop_data["stop_loss"], 4),
                    "initial_stop":  round(stop_data["stop_loss"], 4),
                    "take_profit":   round(stop_data["take_profit"], 4),
                    "tp1_target":    round(stop_data.get("tp1_target", stop_data["take_profit"]), 4),
                    "tp2_target":    round(stop_data.get("tp2_target", stop_data["take_profit"]), 4),
                    "breakeven_trigger": round(stop_data.get("breakeven_trigger", avg_fill_price), 4),
                    "tp1_hit":       False,
                    "best_price":    round(avg_fill_price, 4),
                    "sparkline":     [round(avg_fill_price, 4)],
                    "regime":        decision.get("regime", "Sideways"),
                    "direction":     "LONG",
                    # IV&V Medium: stash the entry committee vote so a later
                    # stop/TP force_close can attribute the outcome to the RL
                    # agents (previously stops taught the model nothing).
                    "committee_breakdown": decision.get("committee_breakdown", []),
                    "metagate_score": decision.get("metagate_score")
                }

                # A-3: update state under lock
                async with self._get_lock():
                    self.portfolio_balance -= cost
                    self.active_holdings.append(holding)

                if DB_ENABLED:
                    try:
                        async with AsyncSessionLocal() as session:
                            # Open — Order only (no round-trip Trade row yet).
                            await _persist_fill(session, symbol, "BUY", shares, avg_fill_price)
                    except Exception as e:
                        print(f"Failed to write DB order (BUY): {e}")

                self.execution_logs.append({
                    "time": time.time(), "action": "FILLED_BUY",
                    "symbol": symbol, "shares": shares, "price": price,
                })
                self.journal.log_trade(symbol, "BUY", price, decision)
                await self._save_state_async()
                return True, f"FILLED BUY {shares} @ ${avg_fill_price:.2f}"

        # ── SELL ─────────────────────────────────────────────────────── #
        elif signal == "SELL":
            long_holding = next(
                (h for h in self.active_holdings
                 if h["symbol"] == symbol and h.get("direction", "LONG") == "LONG"),
                None,
            )

            if long_holding:
                # ── LIQUIDATE LONG ──
                # Exit slippage (1–10 bps, adverse)
                _slip = price * _random.uniform(0.0001, 0.001)
                price = round(price - _slip, 6)
                _exit_comm  = long_holding["shares"] * price * 0.001
                revenue     = long_holding["shares"] * price - _exit_comm
                profit_loss = revenue - long_holding["shares"] * long_holding["entry_price"]
                profit_pct  = (price - long_holding["entry_price"]) / long_holding["entry_price"] * 100


                # E-1: live broker first.
                # IV&V C2: EXIT — normalize; close internal state even if sub-lot.
                if self.broker.is_live:
                    _sell_qty = self.broker.normalize_quantity(symbol, long_holding["shares"])
                    if _sell_qty > 0:
                        _ok, _msg, _oid = self.broker.sell(symbol, _sell_qty, price)
                        if not _ok:
                            return False, f"Broker rejected SELL: {_msg}"
                    else:
                        print(f"[SELL] Sub-lot live qty for {symbol} "
                              f"({long_holding['shares']}) — closing internal state only.")

                # A-3: remove then credit under lock
                async with self._get_lock():
                    if long_holding not in self.active_holdings:
                        return False, f"[A-3] LONG on {symbol} already closed (concurrent)."
                    self.active_holdings.remove(long_holding)
                    self.portfolio_balance += revenue

                self.execution_logs.append({
                    "time": time.time(), "action": "FILLED_SELL",
                    "symbol": symbol, "shares": long_holding["shares"], "price": price,
                })
                self.journal.log_trade(symbol, "SELL", price, decision)

                if DB_ENABLED:
                    try:
                        async with AsyncSessionLocal() as session:
                            await _persist_fill(session, symbol, "SELL",
                                                long_holding["shares"], price, trade={
                                "entry":      long_holding.get("entry_price"),
                                "exit":       price,
                                "stop_loss":  long_holding.get("stop_loss"),
                                "target":     long_holding.get("take_profit"),
                                "profit":     round(profit_loss, 2),
                                "commission": round(_exit_comm, 4),
                                "strategy":   "SELL",
                                "confidence": decision.get("confidence"),
                            })
                    except Exception as e:
                        print(f"Failed to write DB order (SELL): {e}")

                _lg_entry     = long_holding.get("entry_price", price)
                _lg_stop      = long_holding.get("stop_loss", _lg_entry * 0.98)
                _lg_stop_dist = abs(_lg_entry - _lg_stop) / max(_lg_entry, 1e-9) * 100
                trade_result  = {
                    "profit_loss":       profit_loss,
                    "capital_allocated": long_holding["shares"] * long_holding["entry_price"],
                    "action":            "BUY",
                    "regime":            long_holding.get("regime", "Sideways"),
                    "stop_distance_pct": round(_lg_stop_dist, 4),
                }
                self.closed_trades.append({
                    "symbol": symbol, "shares": long_holding["shares"],
                    "direction": "LONG",
                    "entry_price": long_holding["entry_price"], "exit_price": price,
                    "profit_loss": round(profit_loss, 2), "profit_pct": round(profit_pct, 2),
                    "time": time.time(), "reason": decision.get("reason", "Unknown"),
                })
                if "committee_breakdown" in decision:
                    self.rl_engine.process_trade_outcome(trade_result, decision["committee_breakdown"])
                await self._save_state_async()
                return True, f"FILLED SELL {long_holding['shares']:.4g} @ ${price:.2f} (PnL: ${profit_loss:.2f})"

            else:
                # ── OPEN SHORT ──
                # Prevent duplicate
                async with self._get_lock():
                    if any(h["symbol"] == symbol and h.get("direction") == "SHORT"
                           for h in self.active_holdings):
                        return False, f"Already in SHORT on {symbol}."

                regime     = decision.get("regime", "Sideways")
                realized_b = self._get_realized_b()
                _atr       = decision.get("entry_features", {}).get("atr_14") or decision.get("atr_14", 0.0)
                _atr_pct   = float(_atr) / max(float(price), 1.0) * 100 if _atr else 0.0
                size_data  = self.sizer.calculate_size(
                    confidence, self.portfolio_balance, price,
                    regime=regime,
                    recent_win_rate=self.rl_engine.win_rate / 100.0,
                    n_closed_trades=self.rl_engine.total_closed_trades,
                    realized_b=realized_b, atr_pct=_atr_pct,
                )
                shares = size_data["shares"]
                if shares <= 0:
                    return False, f"Kelly sizer returned 0 shares (conf={confidence:.2f})"

                # IV&V C2: normalize to broker lot size up front (see BUY branch).
                shares = self.broker.normalize_quantity(symbol, shares)
                if shares <= 0:
                    return False, (f"Sub-lot SHORT suppressed for {symbol}: sized quantity "
                                   f"rounds to 0 tradeable units.")

                # IV&V H4: enforce single-position + cash-reserve caps on SHORTs as well.
                shares, _cap_reject = self._apply_risk_caps(symbol, "SHORT", shares, price)
                if shares <= 0:
                    return False, _cap_reject

                # Spread & Slippage Guard
                _bid = float(decision.get("bid") or decision.get("entry_features", {}).get("bid") or 0.0)
                _ask = float(decision.get("ask") or decision.get("entry_features", {}).get("ask") or 0.0)
                if _bid > 0 and _ask > 0:
                    _ok_spread, _spread_pct, _spread_msg = self.router.check_spread(_bid, _ask)
                    if not _ok_spread:
                        return False, f"Spread veto: {_spread_msg}"

                _atr_raw   = decision.get("entry_features", {}).get("atr_14") or 0.0
                _vol_proxy = (_atr_raw / max(price, 1e-9)) if _atr_raw > 0 else 0.02
                stop_data  = self.stops.calculate(price, signal, volatility_proxy=_vol_proxy, regime=regime)
                p_win_frac = self.rl_engine.regime_win_rate(regime)
                # IV&V H3: run MC off-loop (see LONG branch).
                sim_result = await asyncio.to_thread(
                    self.simulator.simulate,
                    current_price=price, stop_loss=stop_data["stop_loss"],
                    take_profit=stop_data["take_profit"], symbol=symbol,
                    session_quality=decision.get("session_quality", "NORMAL"),
                    direction="SHORT", p_win=p_win_frac,
                )
                self.latest_sim_result = sim_result
                if p_win_frac is not None and not sim_result["is_viable"]:
                    ev = sim_result.get("expected_value", 0.0)
                    return False, f"AI Trade Simulator veto (Monte Carlo EV={ev*100:.3f}%)"

                fill_result    = self.router.execute(symbol, shares, price, decision.get("volume", 50000))
                avg_fill_price = fill_result["avg_fill_price"]
                cost           = fill_result["total_cost"]

                # M-2: Per-market margin rate (SEBI-compliant 20% for INDIA)
                _SHORT_MARGIN_RATE = _SHORT_MARGIN_RATES.get(self.market, 0.15)
                margin_reserved    = round(cost * _SHORT_MARGIN_RATE, 4)

                # E-1: live broker first.
                # `shares` is already broker-normalized (see sizing block above).
                if self.broker.is_live:
                    _ok, _msg, _oid = self.broker.short(symbol, shares, avg_fill_price)
                    if not _ok:
                        return False, f"Broker rejected SHORT: {_msg}"

                holding = {
                    "symbol":          symbol,
                    "shares":          shares,
                    "entry_price":     round(avg_fill_price, 4),
                    "current_price":   round(avg_fill_price, 4),
                    "value":           round(cost, 4),
                    "change":          0.0,
                    "stop_loss":       round(stop_data["stop_loss"], 4),
                    "initial_stop":    round(stop_data["stop_loss"], 4),
                    "take_profit":     round(stop_data["take_profit"], 4),
                    "tp1_target":      round(stop_data.get("tp1_target", stop_data["take_profit"]), 4),
                    "tp2_target":      round(stop_data.get("tp2_target", stop_data["take_profit"]), 4),
                    "breakeven_trigger": round(stop_data.get("breakeven_trigger", avg_fill_price), 4),
                    "tp1_hit":         False,
                    "best_price":      round(avg_fill_price, 4),
                    "sparkline":       [round(avg_fill_price, 4)],
                    "regime":          decision.get("regime", "Sideways"),
                    "direction":       "SHORT",
                    "margin_reserved": margin_reserved,
                    # IV&V Medium: see LONG branch — enables RL attribution on
                    # stop/TP force_close.
                    "committee_breakdown": decision.get("committee_breakdown", []),
                }

                # A-3: update state under lock
                async with self._get_lock():
                    self.portfolio_balance -= margin_reserved
                    self.active_holdings.append(holding)

                if DB_ENABLED:
                    try:
                        async with AsyncSessionLocal() as session:
                            # Open — Order only (round-trip Trade recorded at cover).
                            await _persist_fill(session, symbol, "SELL", shares, avg_fill_price)
                    except Exception as e:
                        print(f"Failed to write DB order (SHORT): {e}")

                self.execution_logs.append({
                    "time": time.time(), "action": "FILLED_SHORT",
                    "symbol": symbol, "shares": shares, "price": price,
                })
                self.journal.log_trade(symbol, "SELL", price, decision)
                await self._save_state_async()
                return True, f"FILLED SHORT {shares:.4g} @ ${avg_fill_price:.2f} (margin={_SHORT_MARGIN_RATE*100:.0f}%)"

        return True, "No action required"

    # ------------------------------------------------------------------ #
    # Public helpers                                                       #
    # ------------------------------------------------------------------ #

    def save_portfolio_state(self):
        """Public alias for graceful shutdown calls from server.py lifespan."""
        self._save_state()

    def get_portfolio_status(self):
        holdings_out = []
        for h in self.active_holdings:
            hout = dict(h)
            direction = hout.get("direction", "LONG")
            entry = hout.get("entry_price", 0.0)
            sl = hout.get("stop_loss", 0.0)
            if direction == "LONG":
                hout["breakeven_triggered"] = sl >= entry
            else:
                hout["breakeven_triggered"] = sl <= entry and sl != 0.0
            
            # Extract metagate_score if it was saved in committee_breakdown or decision
            if "metagate_score" not in hout:
                hout["metagate_score"] = None
            holdings_out.append(hout)

        return {"balance": round(self.portfolio_balance, 2), "holdings": holdings_out}

    def get_total_equity(self) -> float:
        """
        Mark-to-market equity = cash + open-position value.
        LONG:  shares × current_price
        SHORT: margin_reserved + unrealized P&L (NOT full notional)
        """
        total = self.portfolio_balance
        for h in self.active_holdings:
            cur = h.get("current_price", h.get("entry_price", 0.0))
            if h.get("direction", "LONG") == "SHORT":
                pnl   = h["shares"] * (h["entry_price"] - cur)
                total += h.get("margin_reserved", h["shares"] * h["entry_price"]) + pnl
            else:
                total += h["shares"] * cur
        return round(total, 4)
