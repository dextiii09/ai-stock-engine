"""
Interactive Telegram Bot for AI Stock Engine.
Provides real-time notifications and two-way remote commands:
/status, /pnl, /positions, /regime, /halt, /resume, /retrain, /help
"""
import os
import json
import asyncio
import logging
import urllib.request
import urllib.parse
import ssl
from typing import Optional, Dict, Any

logger = logging.getLogger("uvicorn.error")

_ssl_ctx = ssl._create_unverified_context()


class TelegramBotController:
    """
    Two-way interactive Telegram Bot polling engine.
    Listens for authorized user commands and executes engine actions.
    """

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.is_running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._last_update_id = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.allowed_chat_id)

    async def send_message(self, text: str, parse_mode: str = "Markdown", chat_id: Optional[str] = None) -> bool:
        """Sends a message to the authorized Telegram chat."""
        target_chat = chat_id or self.allowed_chat_id
        if not self.bot_token or not target_chat:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "AiStockTelegramBot/3.0"},
            method="POST",
        )

        def _do_send():
            try:
                with urllib.request.urlopen(req, context=_ssl_ctx, timeout=8) as resp:
                    return resp.status == 200
            except Exception as e:
                logger.warning(f"[TelegramBot] Send error: {e}")
                return False

        return await asyncio.to_thread(_do_send)

    async def start(self):
        """Starts the long-polling loop if configured."""
        if not self.is_configured:
            logger.info("[TelegramBot] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Bot polling idle.")
            return

        self.is_running = True
        self._poll_task = asyncio.create_task(self._polling_loop())
        logger.info("[TelegramBot] Interactive Telegram Bot listener started successfully.")
        await self.send_message("🤖 *AI Stock Engine Online*\nTelegram Bot initialized and connected to 5 market loops. Type /help for commands.")

    async def stop(self):
        """Stops the polling loop."""
        self.is_running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("[TelegramBot] Interactive Telegram Bot stopped.")

    async def _polling_loop(self):
        """Long-polling update loop for incoming Telegram messages."""
        while self.is_running:
            try:
                updates = await self._fetch_updates(offset=self._last_update_id + 1)
                for update in updates:
                    up_id = update.get("update_id", 0)
                    if up_id > self._last_update_id:
                        self._last_update_id = up_id

                    msg = update.get("message") or update.get("edited_message")
                    if msg:
                        await self._handle_message(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[TelegramBot] Polling loop exception: {e}")
                await asyncio.sleep(5)
            await asyncio.sleep(1.0)

    async def _fetch_updates(self, offset: int) -> list:
        """Fetches pending updates from Telegram API."""
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?offset={offset}&timeout=10"
        req = urllib.request.Request(url, headers={"User-Agent": "AiStockTelegramBot/3.0"})

        def _do_get():
            try:
                with urllib.request.urlopen(req, context=_ssl_ctx, timeout=15) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    if res.get("ok"):
                        return res.get("result", [])
                    return []
            except Exception:
                return []

        return await asyncio.to_thread(_do_get)

    async def _handle_message(self, message: dict):
        """Handles incoming user message with authorization check."""
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = message.get("text", "").strip()

        if not text:
            return

        # Security check: only authorized chat_id can issue commands
        if str(chat_id) != str(self.allowed_chat_id):
            logger.warning(f"[TelegramBot] Unauthorized message attempt from chat_id: {chat_id}")
            await self.send_message(f"⛔ *Unauthorized Access Denied*\nYour Chat ID: `{chat_id}`", chat_id=chat_id)
            return

        cmd = text.split()[0].lower() if text else ""

        # Import system components dynamically to avoid circular dependencies
        from api.routes import (
            execution_engine, execution_engine_in, execution_engine_st,
            execution_engine_cx, execution_engine_fx,
            engine_state, engine_state_in, engine_state_st,
            engine_state_cx, engine_state_fx,
            engine_heartbeats, global_risk,
            regime_detector, regime_detector_in,
            regime_detector_st, regime_detector_cx, regime_detector_fx,
            trigger_retrain_all_models,
        )
        from analytics import performance_metrics

        if cmd in ("/start", "/help"):
            reply = (
                "🤖 *AI Stock Engine Control Panel*\n\n"
                "*Available Commands:*\n"
                "📊 /status — 5-Market live engine status & tick latency\n"
                "💰 /pnl — Overall & 30d PnL, Win Rate, Sharpe, Drawdown\n"
                "📈 /positions — List all open holdings across markets\n"
                "👻 /shadow — Shadow Trading accuracy & avoided losses\n"
                "🌐 /regime — Current HMM market regime detections\n"
                "🧪 /backtest `<symbol>` — Run instant 1y backtest\n"
                "🚨 /halt — *EMERGENCY KILL-SWITCH* (Halts & liquidates)\n"
                "▶️ /resume — Resume trading loops & reset baselines\n"
                "🔄 /retrain — Trigger background MetaGate AutoML retrain\n"
                "ℹ️ /help — Show this help message"
            )
            await self.send_message(reply)


        elif cmd == "/status":
            import time
            now = time.time()
            engines = [
                ("US (Core)", engine_state, execution_engine, "US"),
                ("INDIA (NSE)", engine_state_in, execution_engine_in, "INDIA"),
                ("STOCKS (Tech)", engine_state_st, execution_engine_st, "STOCKS"),
                ("CRYPTO", engine_state_cx, execution_engine_cx, "CRYPTO"),
                ("FOREX", engine_state_fx, execution_engine_fx, "FOREX"),
            ]
            lines = ["⚡ *5-Market Engine Health Snapshot:*\n"]
            for name, st, eng, mkt in engines:
                running = "🟢 RUNNING" if st.get("is_running") else "🔴 STOPPED"
                pos_cnt = len(eng.active_holdings)
                hb = engine_heartbeats.get(mkt)
                secs = f"{round(now - hb, 1)}s ago" if hb else "N/A"
                lines.append(f"• *{name}*: {running} | Open: `{pos_cnt}` | Tick: `{secs}`")

            lines.append(f"\n🛡️ *Global Halt*: `{'YES ⛔' if global_risk.global_halt else 'NO ✅'}`")
            if global_risk.global_halt:
                lines.append(f"Reason: _{global_risk.halt_reason}_")
            lines.append(f"💵 *Combined Equity*: `${global_risk.total_equity():,.2f}`")
            await self.send_message("\n".join(lines))

        elif cmd in ("/pnl", "/performance"):
            all_closed = (
                execution_engine.closed_trades +
                execution_engine_in.closed_trades +
                execution_engine_st.closed_trades +
                execution_engine_cx.closed_trades +
                execution_engine_fx.closed_trades
            )
            engines_map = {
                "US": execution_engine,
                "INDIA": execution_engine_in,
                "STOCKS": execution_engine_st,
                "CRYPTO": execution_engine_cx,
                "FOREX": execution_engine_fx,
            }
            stats = performance_metrics.get_comprehensive_performance_breakdown(
                all_closed, initial_capital=100000.0, engines_map=engines_map
            )
            ov = stats.get("overall", {})
            r30 = stats.get("rolling_30d", {})

            reply = (
                "📊 *Quantitative Performance Breakdown:*\n\n"
                f"• *Total Closed Trades*: `{ov.get('total_trades', 0)}`\n"
                f"• *Win Rate*: `{ov.get('win_rate_pct', 0.0)}%` (Loss: `{ov.get('loss_rate_pct', 0.0)}%`)\n"
                f"• *Net Realized PnL*: `${ov.get('net_pnl', 0.0):,.2f}`\n"
                f"• *Gross Profit*: `${ov.get('gross_profit', 0.0):,.2f}`\n"
                f"• *Gross Loss*: `${ov.get('gross_loss', 0.0):,.2f}`\n"
                f"• *Profit Factor*: `{ov.get('profit_factor', 0.0)}`\n"
                f"• *Avg Win / Avg Loss*: `${ov.get('avg_win', 0.0):.2f}` / `${ov.get('avg_loss', 0.0):.2f}`\n"
                f"• *Realized R:R*: `{ov.get('realized_risk_reward', 0.0)}:1`\n"
                f"• *Expectancy per Trade*: `${ov.get('expectancy_per_trade', 0.0):.2f}`\n"
                f"• *Sharpe Ratio*: `{ov.get('sharpe_ratio', 0.0)}`\n"
                f"• *Sortino Ratio*: `{ov.get('sortino_ratio', 0.0)}`\n"
                f"• *Max Drawdown*: `{ov.get('max_drawdown_pct', 0.0)}%` (30d: `{r30.get('max_drawdown_pct', 0.0)}%`)"
            )
            await self.send_message(reply)

        elif cmd in ("/positions", "/holdings"):
            engines = [
                ("US", execution_engine, "$"),
                ("INDIA", execution_engine_in, "₹"),
                ("STOCKS", execution_engine_st, "$"),
                ("CRYPTO", execution_engine_cx, "$"),
                ("FOREX", execution_engine_fx, "$"),
            ]
            lines = ["📋 *Active Open Positions Across Universe:*\n"]
            total_open = 0
            for mkt, eng, sym_pfx in engines:
                holdings = getattr(eng, "active_holdings", [])
                if holdings:
                    lines.append(f"*{mkt} Market* ({len(holdings)} open):")
                    for h in holdings:
                        total_open += 1
                        sym = h.get("symbol")
                        entry = h.get("entry_price", 0.0)
                        curr = h.get("current_price", entry)
                        pnl = h.get("unrealized_pnl", (curr - entry) * h.get("shares", 0.0))
                        sl = h.get("stop_loss", 0.0)
                        tp1 = h.get("tp1_target", 0.0)
                        tp1_hit = "✅ TP1 HIT" if h.get("tp1_hit") else "⏳ TP1 Pending"
                        lines.append(
                            f"  • *{sym}*: Entry `{sym_pfx}{entry:.2f}` | Cur `{sym_pfx}{curr:.2f}` | PnL: `{sym_pfx}{pnl:+.2f}`\n"
                            f"    SL: `{sym_pfx}{sl:.2f}` | TP1: `{sym_pfx}{tp1:.2f}` ({tp1_hit})"
                        )
            if total_open == 0:
                lines.append("No active open positions. Capital is 100% in safe cash.")
            await self.send_message("\n".join(lines))

        elif cmd == "/regime":
            detectors = [
                ("US Index (SPY)", regime_detector),
                ("India (NIFTYBEES)", regime_detector_in),
                ("US Tech (QQQ)", regime_detector_st),
                ("Crypto (BTC-USD)", regime_detector_cx),
                ("Forex (EURUSD=X)", regime_detector_fx),
            ]
            lines = ["🌐 *Market HMM Volatility Regimes:*\n"]
            for name, det in detectors:
                reg = getattr(det, "current_regime", "Unknown")
                lines.append(f"• *{name}*: `{reg}`")
            await self.send_message("\n".join(lines))

        elif cmd in ("/halt", "/stop", "/kill"):
            res = await global_risk.trigger_emergency_kill_switch(reason="Operator Remote Telegram Command")
            await self.send_message(
                f"🚨 *EMERGENCY KILL-SWITCH EXECUTED*\n\n"
                f"• Status: `HALTED`\n"
                f"• Liquidated Positions: `{res.get('liquidated_positions_count', 0)}`\n"
                f"• Total Safe Equity: `${res.get('total_equity', 0.0):,.2f}`\n"
                f"All market trading loops are now locked. Use /resume to restart."
            )

        elif cmd == "/resume":
            res = global_risk.resume_trading(reason="Operator Remote Telegram Command")
            await self.send_message(
                f"✅ *Trading Resumed Successfully*\n\n"
                f"• Global Halt Cleared: `{res.get('halt_cleared', False)}`\n"
                f"• New Baseline Equity: `${res.get('new_baseline', 0.0):,.2f}`\n"
                f"Autonomous trading loops across all 5 markets are active."
            )

        elif cmd == "/shadow":
            from api.routes import (
                shadow_engine, shadow_engine_in, shadow_engine_st,
                shadow_engine_cx, shadow_engine_fx
            )
            all_opps = (
                shadow_engine.get_missed_opportunities() +
                shadow_engine_in.get_missed_opportunities() +
                shadow_engine_st.get_missed_opportunities() +
                shadow_engine_cx.get_missed_opportunities() +
                shadow_engine_fx.get_missed_opportunities()
            )
            missed_profits = [o for o in all_opps if o.get("outcome") == "Missed Profit"]
            avoided_losses = [o for o in all_opps if o.get("outcome") == "Avoided Loss"]
            active_cnt = (
                len(shadow_engine.shadow_portfolio) +
                len(shadow_engine_in.shadow_portfolio) +
                len(shadow_engine_st.shadow_portfolio) +
                len(shadow_engine_cx.shadow_portfolio) +
                len(shadow_engine_fx.shadow_portfolio)
            )
            total = len(missed_profits) + len(avoided_losses)
            acc = round(len(avoided_losses) / total * 100, 1) if total > 0 else 100.0

            reply = (
                "👻 *Shadow Trading & AI Veto Intelligence:*\n\n"
                f"• *Active Virtual Tracking*: `{active_cnt}` trades\n"
                f"• *🛡️ Avoided Losing Trades*: `{len(avoided_losses)}` (Saved Capital)\n"
                f"• *⚠️ Missed Winning Trades*: `{len(missed_profits)}`\n"
                f"• *Veto Accuracy Score*: `{acc}%`\n\n"
                f"_{ 'AI Gates correctly prevented losing trades.' if acc >= 70 else 'RL engine adapting strictness.' }_"
            )
            await self.send_message(reply)

        elif cmd.startswith("/backtest"):
            parts = text.split()
            sym = parts[1].upper() if len(parts) > 1 else "AAPL"
            await self.send_message(f"⏳ *Running Walk-Forward Backtest for {sym} (1y, AI Committee)...*")
            from backtesting.engine import BacktestEngine
            def _run_bt():
                eng = BacktestEngine(symbol=sym, strategy="AI Committee", period="1y", initial_capital=100000.0)
                return eng.run()
            try:
                res = await asyncio.to_thread(_run_bt)
                if "error" in res:
                    await self.send_message(f"❌ *Backtest Error*: {res['error']}")
                else:
                    curr = res.get("currency", "USD")
                    pfx = "₹" if curr == "INR" else "$"
                    reply = (
                        f"🧪 *Backtest Results: {sym}*\n\n"
                        f"• *Strategy*: `{res.get('strategy')}` (1 Year)\n"
                        f"• *Total Trades*: `{res.get('total_trades', 0)}` (Wins: `{res.get('winning_trades', 0)}` | Losses: `{res.get('losing_trades', 0)}`)\n"
                        f"• *Win Rate*: `{res.get('win_rate_pct', 0.0)}%`\n"
                        f"• *Total Return*: `{res.get('total_return_pct', 0.0)}%`\n"
                        f"• *Profit Factor*: `{res.get('profit_factor', 0.0)}`\n"
                        f"• *Sharpe Ratio*: `{res.get('sharpe_ratio', 0.0)}`\n"
                        f"• *Max Drawdown*: `{res.get('max_drawdown_pct', 0.0)}%`"
                    )
                    await self.send_message(reply)
            except Exception as e:
                await self.send_message(f"❌ *Backtest Failed*: {str(e)}")

        else:
            await self.send_message(f"❓ Unknown command `{text}`. Type /help for available commands.")



# Global instance
telegram_bot = TelegramBotController()
