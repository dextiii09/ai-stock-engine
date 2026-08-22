"""
Unit tests for Telegram Interactive Add-ons & Route TTL Caching.
"""
import pytest
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.telegram_bot import TelegramBotController


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class TestTelegramChartAndAlerts:
    def test_trade_chart_generates_valid_png_bytes(self):
        bot = TelegramBotController()
        chart_bytes = bot.generate_trade_chart(
            symbol="BTC-USD",
            direction="LONG",
            entry_price=50000.0,
            stop_loss=48000.0,
            take_profit=54000.0,
            tp2_target=58000.0,
            sparkline=[49000, 49200, 49800, 50000]
        )
        assert chart_bytes is not None
        assert isinstance(chart_bytes, bytes)
        assert len(chart_bytes) > 1000
        # Check PNG header magic bytes (\x89PNG\r\n\x1a\n)
        assert chart_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_trade_chart_short_generates_valid_png(self):
        bot = TelegramBotController()
        chart_bytes = bot.generate_trade_chart(
            symbol="AAPL",
            direction="SHORT",
            entry_price=150.0,
            stop_loss=155.0,
            take_profit=140.0
        )
        assert chart_bytes is not None
        assert len(chart_bytes) > 1000
        assert chart_bytes[:4] == b"\x89PNG"

    def test_pre_market_briefing_formatter(self):
        bot = TelegramBotController()
        brief = _run(bot.generate_pre_market_brief())
        assert "PRE-MARKET GLOBAL BRIEFING" in brief
        assert "Portfolio Equity" in brief


class TestRouteTTLCache:
    def test_live_tick_cache_returns_fast(self):
        from api.routes import _live_tick_cache, get_live_tick
        _live_tick_cache["TEST_SYM"] = {
            "ts": time.time(),
            "data": {"symbol": "TEST_SYM", "price": 123.45}
        }
        res = _run(get_live_tick("TEST_SYM"))
        assert res == {"symbol": "TEST_SYM", "price": 123.45}
