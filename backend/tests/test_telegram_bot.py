"""
Tests for Telegram Bot Controller and Notifier.
"""
import asyncio
from unittest.mock import patch, AsyncMock
from utils.telegram_bot import TelegramBotController


def test_system_metrics_failure_is_reported_honestly():
    """
    Regression test for a finding in the 2026-08-21 audit: when
    `_get_system_metrics_text()` hit ANY exception (missing psutil,
    permission error, etc.) it returned a message headlined "CPU & RAM
    operational" with the real error truncated into a "Diagnostics:" suffix
    — an operator scanning the message would see "operational" and move on
    during a real outage. The fallback text must not claim things are
    operational when metrics collection actually failed.
    """
    bot = TelegramBotController()
    with patch("builtins.__import__", side_effect=ModuleNotFoundError("No module named 'psutil'")):
        text = bot._get_system_metrics_text()
    assert "operational" not in text.lower()
    assert "unavailable" in text.lower() or "error" in text.lower() or "fail" in text.lower()
    assert "psutil" in text


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


def test_telegram_bot_var_command():
    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
            fake_msg = {
                "chat": {"id": 12345678},
                "text": "🎲 VaR"
            }
            await bot._handle_message(fake_msg)
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert "Monte Carlo" in args[0]

    asyncio.run(_run())


def test_telegram_bot_backup_command(tmp_path):
    """
    Regression note (2026-08-21 audit): this test previously exercised the
    REAL `AutomatedBackupEngine.instance()` singleton unmocked — its
    `/backup` handler calls `create_backup()` with the default
    `max_retention=30`, which both writes a new real zip into the git-tracked
    `backend/data/backups/` directory AND deletes the oldest backups once the
    count exceeds 30. Running this test repeatedly (exactly what happened
    across this audit session) creates real backups and, once past the
    retention threshold, silently DELETES real ones — confirmed directly:
    a git-tracked backup zip was deleted mid-session and had to be restored
    with `git checkout`. Isolate the engine to a temp directory so the test
    can no longer touch production backup state.
    """
    from scripts.automated_backup import AutomatedBackupEngine
    isolated_engine = AutomatedBackupEngine(base_dir=str(tmp_path))
    mock_state = tmp_path / "mock_state.json"
    mock_state.write_text('{"balance": 100000.0}')
    isolated_engine.get_backup_targets = lambda: [str(mock_state)]

    async def _run():
        bot = TelegramBotController()
        bot.bot_token = "mock_token"
        bot.allowed_chat_id = "12345678"

        with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send, \
             patch("scripts.automated_backup.AutomatedBackupEngine.instance", return_value=isolated_engine):
            fake_msg = {
                "chat": {"id": 12345678},
                "text": "/backup"
            }
            await bot._handle_message(fake_msg)
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert "Backup" in args[0]

    asyncio.run(_run())




