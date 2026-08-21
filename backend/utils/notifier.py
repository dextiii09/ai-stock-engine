import os
import asyncio
import json
import urllib.request
import urllib.error
import ssl

class Notifier:
    def __init__(self):
        self.discord_url = os.getenv("DISCORD_WEBHOOK_URL", "")
        self.telegram_bot = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat = os.getenv("TELEGRAM_CHAT_ID", "")
        # IV&V finding 2026-08-21: was ssl._create_unverified_context(), which
        # disables TLS certificate validation entirely — every alert sent to
        # Discord/Telegram was vulnerable to MITM interception or spoofing.
        # create_default_context() is Python's proper secure default (uses
        # the system trust store), matching what a bare urlopen() call
        # without an explicit context already does correctly elsewhere in
        # this codebase.
        self.ssl_context = ssl.create_default_context()

    async def send_alert(self, message: str, parse_mode: str = "Markdown"):
        """Asynchronously send an alert to configured webhooks."""
        tasks = []
        if self.discord_url:
            tasks.append(self._send_discord(message))
        if self.telegram_bot and self.telegram_chat:
            tasks.append(self._send_telegram(message, parse_mode=parse_mode))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_discord(self, message: str):
        payload = {"content": message}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            self.discord_url, 
            data=data, 
            headers={'Content-Type': 'application/json', 'User-Agent': 'AiStockBot'},
            method='POST'
        )
        try:
            await asyncio.to_thread(urllib.request.urlopen, req, context=self.ssl_context)
        except Exception as e:
            print(f"[Notifier] Discord Error: {e}")

    async def _send_telegram(self, message: str, parse_mode: str = "Markdown"):
        url = f"https://api.telegram.org/bot{self.telegram_bot}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, 
            data=data, 
            headers={'Content-Type': 'application/json', 'User-Agent': 'AiStockBot'},
            method='POST'
        )
        try:
            await asyncio.to_thread(urllib.request.urlopen, req, context=self.ssl_context)
        except Exception as e:
            print(f"[Notifier] Telegram Error: {e}")

# Global instance
notifier = Notifier()

