"""
Tests for Telegram Bot Controller and Notifier.
"""
import asyncio
from unittest.mock import patch, AsyncMock
from utils.telegram_bot import TelegramBotController


def test_telegram_bot_unauthorized_rejection():
    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
            # Message from unauthorized stranger
            fake_msg = {
                "chat": {"id": 99999999},
                "text": "/pnl"
            }
            await bot._handle_message(fake_msg)
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert "Unauthorized" in args[0]

    asyncio.run(_run())


def test_telegram_bot_authorized_help():
    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
            fake_msg = {
                "chat": {"id": 12345678},
                "text": "/help"
            }
            await bot._handle_message(fake_msg)
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert "AI Stock Engine Control Panel" in args[0]
            assert "/status" in args[0]
            assert "/pnl" in args[0]
            assert "/halt" in args[0]

    asyncio.run(_run())


def test_telegram_bot_system_command():
    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
            fake_msg = {
                "chat": {"id": 12345678},
                "text": "/system"
            }
            await bot._handle_message(fake_msg)
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert "CPU Usage" in args[0]
            assert "RAM Memory" in args[0]
            assert "Disk Storage" in args[0]

    asyncio.run(_run())


def test_telegram_bot_button_normalization():
    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
            # User tapped "📊 Status" button
            fake_msg = {
                "chat": {"id": 12345678},
                "text": "📊 Status"
            }
            await bot._handle_message(fake_msg)
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert "Engine Health Snapshot" in args[0]

    asyncio.run(_run())


def test_telegram_bot_eod_digest():
    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_photo", new_callable=AsyncMock) as mock_photo, \
             patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
            fake_msg = {
                "chat": {"id": 12345678},
                "text": "📬 EOD Digest"
            }
            await bot._handle_message(fake_msg)
            # EOD digest delivers photo with caption if chart generation succeeds
            if mock_photo.called:
                kwargs = mock_photo.call_args.kwargs
                caption = kwargs.get("caption", "")
                assert "PERFORMANCE RECAP" in caption
            else:
                mock_send.assert_called_once()
                args = mock_send.call_args[0]
                assert "PERFORMANCE RECAP" in args[0]

    asyncio.run(_run())


def test_telegram_bot_chart_command():
    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_photo", new_callable=AsyncMock) as mock_photo:
            fake_msg = {
                "chat": {"id": 12345678},
                "text": "📉 Chart"
            }
            await bot._handle_message(fake_msg)
            mock_photo.assert_called_once()
            kwargs = mock_photo.call_args.kwargs
            assert "AI Stock Engine" in kwargs.get("caption", "")

    asyncio.run(_run())



