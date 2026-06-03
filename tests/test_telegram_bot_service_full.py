"""Comprehensive tests for TelegramBotService."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kairos.notifications.telegram_bot_service import (
    HELP_MESSAGE,
    WELCOME_MESSAGE,
    TelegramBotService,
)


@pytest.fixture
def bot_service():
    """Create a TelegramBotService with token."""
    return TelegramBotService("test_token_123")


@pytest.fixture
def bot_service_no_token():
    """Create a TelegramBotService without token."""
    return TelegramBotService(None)


class TestTelegramBotServiceInit:
    """Test TelegramBotService initialization."""

    def test_init_with_token(self, bot_service):
        assert bot_service._token == "test_token_123"
        assert bot_service._running is False
        assert bot_service._application is None

    def test_init_without_token(self, bot_service_no_token):
        assert bot_service_no_token._token == ""
        assert bot_service_no_token._running is False

    def test_init_with_empty_string(self):
        service = TelegramBotService("")
        assert service._token == ""


class TestTelegramBotServiceStart:
    """Test TelegramBotService.start method."""

    @pytest.mark.asyncio
    async def test_start_no_token(self, bot_service_no_token):
        """Test that start does nothing without token."""
        await bot_service_no_token.start()
        assert bot_service_no_token._running is False

    @pytest.mark.asyncio
    async def test_start_already_running(self, bot_service):
        """Test that start does nothing if already running."""
        bot_service._running = True
        await bot_service.start()
        # Should return early without doing anything

    @pytest.mark.asyncio
    async def test_start_success(self, bot_service):
        """Test successful start."""
        mock_app = AsyncMock()
        mock_app.updater = AsyncMock()

        with patch("kairos.notifications.telegram_bot_service.Application") as mock_app_cls:
            mock_builder = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.rate_limiter.return_value = mock_builder
            mock_builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = mock_builder

            await bot_service.start()

        assert bot_service._running is True
        assert bot_service._application is not None

    @pytest.mark.asyncio
    async def test_start_polling_retry(self, bot_service):
        """Test that polling retries on network error."""
        mock_app = AsyncMock()
        mock_app.updater = AsyncMock()
        mock_app.updater.start_polling = AsyncMock(
            side_effect=[Exception("Network error"), None]
        )

        with patch("kairos.notifications.telegram_bot_service.Application") as mock_app_cls:
            mock_builder = MagicMock()
            mock_builder.token.return_value = mock_builder
            mock_builder.rate_limiter.return_value = mock_builder
            mock_builder.build.return_value = mock_app
            mock_app_cls.builder.return_value = mock_builder

            with patch("kairos.notifications.telegram_bot_service.asyncio.sleep", new_callable=AsyncMock):
                await bot_service.start()

        assert bot_service._running is True


class TestTelegramBotServiceStop:
    """Test TelegramBotService.stop method."""

    @pytest.mark.asyncio
    async def test_stop_not_running(self, bot_service):
        """Test that stop does nothing if not running."""
        await bot_service.stop()
        assert bot_service._running is False

    @pytest.mark.asyncio
    async def test_stop_success(self, bot_service):
        """Test successful stop."""
        mock_app = AsyncMock()
        mock_app.updater = AsyncMock()
        bot_service._application = mock_app
        bot_service._running = True

        await bot_service.stop()

        assert bot_service._running is False
        assert bot_service._application is None

    @pytest.mark.asyncio
    async def test_stop_no_updater(self, bot_service):
        """Test stop when application has no updater."""
        mock_app = AsyncMock()
        mock_app.updater = None
        bot_service._application = mock_app
        bot_service._running = True

        await bot_service.stop()

        assert bot_service._running is False


class TestHandleStart:
    """Test _handle_start method."""

    @pytest.mark.asyncio
    async def test_handle_start(self, bot_service):
        """Test /start command handler."""
        mock_update = MagicMock()
        mock_update.effective_chat.id = 12345
        mock_context = AsyncMock()

        await bot_service._handle_start(mock_update, mock_context)

        mock_context.bot.send_message.assert_called_once_with(
            chat_id=12345,
            text=WELCOME_MESSAGE,
        )

    @pytest.mark.asyncio
    async def test_handle_start_no_chat(self, bot_service):
        """Test /start command with no effective chat."""
        mock_update = MagicMock()
        mock_update.effective_chat = None
        mock_context = AsyncMock()

        await bot_service._handle_start(mock_update, mock_context)

        mock_context.bot.send_message.assert_not_called()


class TestHandleHelp:
    """Test _handle_help method."""

    @pytest.mark.asyncio
    async def test_handle_help(self, bot_service):
        """Test /help command handler."""
        mock_update = MagicMock()
        mock_update.effective_chat.id = 12345
        mock_context = AsyncMock()

        await bot_service._handle_help(mock_update, mock_context)

        mock_context.bot.send_message.assert_called_once_with(
            chat_id=12345,
            text=HELP_MESSAGE,
        )

    @pytest.mark.asyncio
    async def test_handle_help_no_chat(self, bot_service):
        """Test /help command with no effective chat."""
        mock_update = MagicMock()
        mock_update.effective_chat = None
        mock_context = AsyncMock()

        await bot_service._handle_help(mock_update, mock_context)

        mock_context.bot.send_message.assert_not_called()


class TestHandleFreeText:
    """Test _handle_free_text method."""

    @pytest.mark.asyncio
    async def test_handle_private_chat(self, bot_service):
        """Test free text in private chat."""
        mock_update = MagicMock()
        mock_update.effective_chat.id = 12345
        mock_update.effective_chat.type = "private"
        mock_context = AsyncMock()

        await bot_service._handle_free_text(mock_update, mock_context)

        mock_context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_group_chat(self, bot_service):
        """Test free text in group chat."""
        mock_update = MagicMock()
        mock_update.effective_chat.id = 12345
        mock_update.effective_chat.type = "group"
        mock_context = AsyncMock()

        await bot_service._handle_free_text(mock_update, mock_context)

        mock_context.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_channel_post(self, bot_service):
        """Test free text in channel (should be ignored)."""
        mock_update = MagicMock()
        mock_update.effective_chat.id = 12345
        mock_update.effective_chat.type = "channel"
        mock_context = AsyncMock()

        await bot_service._handle_free_text(mock_update, mock_context)

        mock_context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_no_chat(self, bot_service):
        """Test free text with no effective chat."""
        mock_update = MagicMock()
        mock_update.effective_chat = None
        mock_context = AsyncMock()

        await bot_service._handle_free_text(mock_update, mock_context)

        mock_context.bot.send_message.assert_not_called()


class TestPollingErrorCallback:
    """Test _polling_error_callback method."""

    def test_network_error(self, bot_service):
        """Test that network errors are logged as warning."""
        from telegram.error import NetworkError

        error = NetworkError("Connection lost")
        # Should not raise
        bot_service._polling_error_callback(error)

    def test_timed_out(self, bot_service):
        """Test that timeout errors are logged as warning."""
        from telegram.error import TimedOut

        error = TimedOut()
        # Should not raise
        bot_service._polling_error_callback(error)

    def test_other_error(self, bot_service):
        """Test that other errors are logged as error."""
        error = RuntimeError("Unexpected error")
        # Should not raise
        bot_service._polling_error_callback(error)
