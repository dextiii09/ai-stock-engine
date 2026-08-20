"""
Interactive Telegram Bot for AI Stock Engine.
Provides real-time notifications, 1-tap quick action keyboard,
two-way remote commands, automated EOD digest, and macro blackout alerts.
"""
import os
import json
import asyncio
import logging
import urllib.request
import urllib.parse
import ssl
import time
from datetime import datetime, date
from typing import Optional, Dict, Any, List

logger = logging.getLogger("uvicorn.error")

_ssl_ctx = ssl._create_unverified_context()

DEFAULT_KEYBOARD = {
    "keyboard": [
        [{"text": "📊 Status"}, {"text": "💰 PnL"}, {"text": "📈 Positions"}],
        [{"text": "🖥️ System"}, {"text": "👻 Shadow"}, {"text": "🌐 Regime"}],
        [{"text": "📬 EOD Digest"}, {"text": "🔄 Retrain"}, {"text": "🚨 Halt"}]
    ],
    "resize_keyboard": True,
    "persistent": True
}


class TelegramBotController:
    """
    Two-way interactive Telegram Bot polling engine.
    Listens for authorized user commands, handles 1-tap buttons,
    schedules daily EOD digests, and delivers real-time trading alerts.
    """

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.is_running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._eod_task: Optional[asyncio.Task] = None
        self._macro_task: Optional[asyncio.Task] = None
        self._last_update_id = 0
        self._last_notified_blackout: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.allowed_chat_id)

    async def send_message(
        self,
        text: str,
        parse_mode: str = "Markdown",
        chat_id: Optional[str] = None,
        with_keyboard: bool = True
    ) -> bool:
        """Sends a message to the authorized Telegram chat with optional 1-tap keyboard."""
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
        if with_keyboard:
            payload["reply_markup"] = DEFAULT_KEYBOARD

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
        """Starts the long-polling loop and scheduled background monitors."""
        if not self.is_configured:
            logger.info("[TelegramBot] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Bot polling idle.")
            return

        self.is_running = True
        self._poll_task = asyncio.create_task(self._polling_loop())
        self._eod_task = asyncio.create_task(self._daily_eod_loop())
        self._macro_task = asyncio.create_task(self._macro_blackout_monitor())
        logger.info("[TelegramBot] Interactive Telegram Bot listener & schedulers started.")
        await self.send_message(
            "🤖 *AI Stock Engine Online*\n"
            "Interactive Telegram Control Panel active across 5 market loops.\n"
            "Use the quick action buttons below or type /help for commands.",
            with_keyboard=True
        )

    async def stop(self):
        """Stops the polling loop and scheduled tasks."""
        self.is_running = False
        for task in (self._poll_task, self._eod_task, self._macro_task):
            if task:
                task.cancel()
                try:
                    await task
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

    async def _daily_eod_loop(self):
        """Runs daily at 18:00 UTC (23:30 IST) to auto-push the EOD PnL digest."""
        while self.is_running:
            try:
                now = datetime.utcnow()
                # Target: 18:00 UTC (23:30 IST market close)
                target = now.replace(hour=18, minute=0, second=0, microsecond=0)
                if now >= target:
                    # Move to tomorrow's 18:00 UTC
                    target = target.replace(day=target.day + 1)
                wait_secs = (target - now).total_seconds()
                await asyncio.sleep(wait_secs)
                
                # Deliver digest
                report = await self.generate_eod_digest()
                await self.send_message(report, with_keyboard=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[TelegramBot] EOD loop error: {e}")
                await asyncio.sleep(60)

    async def _macro_blackout_monitor(self):
        """Monitors upcoming high-impact economic events and sends alerts."""
        while self.is_running:
            try:
                from data.event_awareness import EventAwarenessEngine, IndianEventAwarenessEngine
                us_event = EventAwarenessEngine().check_today()
                in_event = IndianEventAwarenessEngine().check_today()
                
                blackout_active = us_event.get("trading_blackout") or in_event.get("trading_blackout")
                reason = us_event.get("blackout_reason") or in_event.get("blackout_reason") or "High Impact Macro Release"

                if blackout_active and self._last_notified_blackout != reason:
                    self._last_notified_blackout = reason
                    await self.send_message(
                        f"⚠️ *MACRO EVENT BLACKOUT ACTIVATED*\n\n"
                        f"• Reason: `{reason}`\n"
                        f"• Action: *New trade entries paused* to avoid high-volatility slippage.\n"
                        f"• Active stops & targets remain fully protected.",
                        with_keyboard=True
                    )
                elif not blackout_active and self._last_notified_blackout is not None:
                    self._last_notified_blackout = None
                    await self.send_message(
                        "✅ *MACRO EVENT BLACKOUT CLEARED*\n"
                        "Normal autonomous trading loops have resumed across all markets.",
                        with_keyboard=True
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[TelegramBot] Macro monitor error: {e}")
            await asyncio.sleep(300)  # check every 5 minutes

    async def generate_eod_digest(self) -> str:
        """Generates a comprehensive End-of-Day PnL recap across all 5 markets."""
        from api.routes import (
            execution_engine, execution_engine_in, execution_engine_st,
            execution_engine_cx, execution_engine_fx, global_risk
        )
        engines = [
            ("US", execution_engine, "$"),
            ("INDIA", execution_engine_in, "₹"),
            ("STOCKS", execution_engine_st, "$"),
            ("CRYPTO", execution_engine_cx, "$"),
            ("FOREX", execution_engine_fx, "$"),
        ]

        today_date = date.today()
        today_trades: List[Dict[str, Any]] = []
        total_open_count = 0
        total_unrealized_pnl = 0.0

        for mkt, eng, sym_pfx in engines:
            # Closed trades
            for t in getattr(eng, "closed_trades", []):
                # Try parsing timestamp
                t_time = t.get("exit_time") or t.get("timestamp") or 0
                if isinstance(t_time, (int, float)):
                    if date.fromtimestamp(t_time) == today_date:
                        today_trades.append({**t, "market": mkt, "currency": sym_pfx})
                elif isinstance(t_time, str):
                    if str(today_date) in t_time:
                        today_trades.append({**t, "market": mkt, "currency": sym_pfx})

            # Open holdings
            for h in getattr(eng, "active_holdings", []):
                total_open_count += 1
                entry = h.get("entry_price", 0.0)
                curr = h.get("current_price", entry)
                shares = h.get("shares", 0.0)
                pnl = (curr - entry) * shares if h.get("direction") == "LONG" else (entry - curr) * shares
                total_unrealized_pnl += pnl

        wins = [t for t in today_trades if t.get("profit", 0) > 0 or t.get("pnl", 0) > 0]
        losses = [t for t in today_trades if t.get("profit", 0) <= 0 and t.get("pnl", 0) < 0]
        
        tot_closed = len(today_trades)
        win_rate = round(len(wins) / tot_closed * 100, 1) if tot_closed > 0 else 0.0
        
        net_pnl_usd = sum(t.get("profit", t.get("pnl", 0.0)) for t in today_trades if t.get("currency") != "₹")
        net_pnl_inr = sum(t.get("profit", t.get("pnl", 0.0)) for t in today_trades if t.get("currency") == "₹")

        best_t = max(today_trades, key=lambda x: x.get("profit", x.get("pnl", 0)), default=None)
        worst_t = min(today_trades, key=lambda x: x.get("profit", x.get("pnl", 0)), default=None)

        lines = [
            "📬 *DAILY END-OF-DAY PERFORMANCE RECAP*",
            f"📅 Date: `{today_date.strftime('%d %B %Y')}`\n",
            f"• *Closed Trades Today*: `{tot_closed}` (Wins: `{len(wins)}` | Losses: `{len(losses)}`)",
            f"• *Today's Win Rate*: `{win_rate}%`",
            f"• *Realized USD PnL*: `${net_pnl_usd:+,.2f}`",
        ]
        if net_pnl_inr != 0:
            lines.append(f"• *Realized INR PnL*: `₹{net_pnl_inr:+,.2f}`")

        if best_t:
            lines.append(f"• *🌟 Best Trade*: {best_t.get('symbol')} (`{best_t.get('currency')}{best_t.get('profit', best_t.get('pnl', 0)):+,.2f}`)")
        if worst_t and worst_t != best_t:
            lines.append(f"• *⚠️ Worst Trade*: {worst_t.get('symbol')} (`{worst_t.get('currency')}{worst_t.get('profit', worst_t.get('pnl', 0)):+,.2f}`)")

        lines.append(f"\n🌙 *Overnight Position Book:*")
        lines.append(f"• Open Holdings: `{total_open_count}` positions")
        lines.append(f"• Unrealized Float: `${total_unrealized_pnl:+,.2f}`")
        lines.append(f"• Combined Safe Equity: `${global_risk.total_equity():,.2f}`")
        lines.append(f"• Global Halt: `{'HALTED ⛔' if global_risk.global_halt else 'ACTIVE ✅'}`")

        return "\n".join(lines)

    async def _handle_message(self, message: dict):
        """Handles incoming user message with authorization check and 1-tap normalization."""
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        raw_text = message.get("text", "").strip()

        if not raw_text:
            return

        # Security check: only authorized chat_id can issue commands
        if str(chat_id) != str(self.allowed_chat_id):
            logger.warning(f"[TelegramBot] Unauthorized message attempt from chat_id: {chat_id}")
            await self.send_message(f"⛔ *Unauthorized Access Denied*\nYour Chat ID: `{chat_id}`", chat_id=chat_id, with_keyboard=False)
            return

        # Normalize 1-tap button labels to commands
        text_lower = raw_text.lower()
        if "status" in text_lower:
            cmd = "/status"
        elif "system" in text_lower or "cpu" in text_lower or "ram" in text_lower or "server" in text_lower or "vps" in text_lower:
            cmd = "/system"
        elif "pnl" in text_lower or "performance" in text_lower:
            cmd = "/pnl"
        elif "position" in text_lower or "holding" in text_lower:
            cmd = "/positions"
        elif "shadow" in text_lower:
            cmd = "/shadow"
        elif "regime" in text_lower:
            cmd = "/regime"
        elif "digest" in text_lower or "eod" in text_lower or "recap" in text_lower:
            cmd = "/digest"
        elif "retrain" in text_lower:
            cmd = "/retrain"
        elif "halt" in text_lower or "stop" in text_lower or "kill" in text_lower:
            cmd = "/halt"
        elif "resume" in text_lower:
            cmd = "/resume"
        elif "help" in text_lower or "start" in text_lower:
            cmd = "/help"
        elif raw_text.startswith("/backtest"):
            cmd = "/backtest"
        else:
            cmd = raw_text.split()[0].lower()

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
                "*Tap any button below or type a command:*\n\n"
                "📊 `/status` — 5-Market live engine status & tick latency\n"
                "🖥️ `/system` — Real-time CPU, RAM, Disk & Process health\n"
                "💰 `/pnl` — Overall & 30d PnL, Win Rate, Sharpe, Drawdown\n"
                "📈 `/positions` — List all open holdings across markets\n"
                "👻 `/shadow` — Shadow Trading accuracy & avoided losses\n"
                "🌐 `/regime` — Current HMM market regime detections\n"
                "📬 `/digest` — Today's End-of-Day PnL & Trade Recap\n"
                "🧪 `/backtest <symbol>` — Run instant 1y walk-forward backtest\n"
                "🚨 `/halt` — *EMERGENCY KILL-SWITCH* (Halts & liquidates)\n"
                "▶️ `/resume` — Resume trading loops & reset baselines\n"
                "🔄 `/retrain` — Trigger background MetaGate AutoML retrain"
            )
            await self.send_message(reply)

        elif cmd == "/status":
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

        elif cmd == "/system":
            try:
                import psutil
                import platform

                cpu_pct = psutil.cpu_percent(interval=0.2)
                cpu_count = psutil.cpu_count(logical=True)
                
                vmem = psutil.virtual_memory()
                ram_total_gb = vmem.total / (1024 ** 3)
                ram_used_gb = vmem.used / (1024 ** 3)
                ram_free_gb = vmem.available / (1024 ** 3)
                ram_pct = vmem.percent
                
                disk = psutil.disk_usage('/')
                disk_total_gb = disk.total / (1024 ** 3)
                disk_used_gb = disk.used / (1024 ** 3)
                disk_free_gb = disk.free / (1024 ** 3)
                disk_pct = disk.percent
                
                proc = psutil.Process(os.getpid())
                proc_mem_mb = proc.memory_info().rss / (1024 ** 2)
                proc_cpu = proc.cpu_percent(interval=0.1)
                proc_threads = proc.num_threads()
                
                proc_create_time = proc.create_time()
                uptime_secs = int(time.time() - proc_create_time)
                days, rem = divmod(uptime_secs, 86400)
                hours, rem = divmod(rem, 3600)
                mins, secs = divmod(rem, 60)
                uptime_str = f"{days}d {hours}h {mins}m" if days > 0 else f"{hours}h {mins}m {secs}s"
                
                cpu_bar = "🟢" if cpu_pct < 60 else "🟡" if cpu_pct < 85 else "🔴"
                ram_bar = "🟢" if ram_pct < 70 else "🟡" if ram_pct < 90 else "🔴"
                disk_bar = "🟢" if disk_pct < 75 else "🟡" if disk_pct < 90 else "🔴"

                reply = (
                    "🖥️ *VPS & Trading Engine System Health*\n\n"
                    f"*{cpu_bar} CPU Usage*: `{cpu_pct:.1f}%` ({cpu_count} Cores)\n"
                    f"*{ram_bar} RAM Memory*: `{ram_pct:.1f}%`\n"
                    f"   • Used: `{ram_used_gb:.2f} GB` / `{ram_total_gb:.2f} GB`\n"
                    f"   • Free: `{ram_free_gb:.2f} GB`\n\n"
                    f"*{disk_bar} Disk Storage*: `{disk_pct:.1f}%`\n"
                    f"   • Used: `{disk_used_gb:.1f} GB` / `{disk_total_gb:.1f} GB` (Free: `{disk_free_gb:.1f} GB`)\n\n"
                    f"⚡ *Python Trading Process:*\n"
                    f"   • RAM Consumption: `{proc_mem_mb:.1f} MB`\n"
                    f"   • Process CPU: `{proc_cpu:.1f}%`\n"
                    f"   • Active Threads: `{proc_threads}`\n"
                    f"   • Process Uptime: `{uptime_str}`\n"
                    f"   • Host OS: `{platform.system()} {platform.release()}`"
                )
                await self.send_message(reply)
            except Exception as e:
                await self.send_message(f"❌ *Failed to fetch system metrics*: {str(e)}")

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

        elif cmd in ("/digest", "/eod", "/recap"):
            digest_msg = await self.generate_eod_digest()
            await self.send_message(digest_msg)

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

        elif cmd.startswith("/backtest"):
            parts = raw_text.split()
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

        elif cmd in ("/halt", "/stop", "/kill"):
            res = await global_risk.trigger_emergency_kill_switch(reason="Operator Remote Telegram Command")
            await self.send_message(
                f"🚨 *EMERGENCY KILL-SWITCH EXECUTED*\n\n"
                f"• Status: `HALTED`\n"
                f"• Liquidated Positions: `{res.get('liquidated_positions_count', 0)}`\n"
                f"• Total Safe Equity: `${res.get('total_equity', 0.0):,.2f}`\n"
                f"All market trading loops are now locked. Tap /resume to restart."
            )

        elif cmd == "/resume":
            res = global_risk.resume_trading(reason="Operator Remote Telegram Command")
            await self.send_message(
                f"✅ *Trading Resumed Successfully*\n\n"
                f"• Global Halt Cleared: `{res.get('halt_cleared', False)}`\n"
                f"• New Baseline Equity: `${res.get('new_baseline', 0.0):,.2f}`\n"
                f"Autonomous trading loops across all 5 markets are active."
            )

        elif cmd == "/retrain":
            await self.send_message("⏳ *Launching background AutoML retrain for all MetaGate models...*")
            res = await trigger_retrain_all_models()
            await self.send_message(f"✅ *Retrain Triggered*: {res.get('message', 'Active in background')}")

        else:
            await self.send_message(f"❓ Unknown command `{raw_text}`. Type /help for available commands.")


# Global instance
telegram_bot = TelegramBotController()
