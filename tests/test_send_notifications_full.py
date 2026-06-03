"""Comprehensive tests for send_notifications."""

import os
from unittest.mock import MagicMock, patch

import pytest

from kairos.utils.send_notifications import (
    _resolve_telegram_targets,
    _result,
    send_notifications,
)


class TestResolveTelegramTargets:
    """Test _resolve_telegram_targets function."""

    def test_with_chat_id(self):
        config = {"chatId": "12345"}
        result = _resolve_telegram_targets(config)
        assert result == ["12345"]

    def test_without_chat_id(self):
        config = {}
        result = _resolve_telegram_targets(config)
        assert result == []

    def test_numeric_chat_id(self):
        config = {"chatId": 12345}
        result = _resolve_telegram_targets(config)
        assert result == ["12345"]


class TestResult:
    """Test _result function."""

    def test_success(self):
        result = _result(True, "sent", False)
        assert result == {"success": True, "reason": "sent", "retryable": False}

    def test_failure(self):
        result = _result(False, "error", True)
        assert result == {"success": False, "reason": "error", "retryable": True}


class TestSendNotifications:
    """Test send_notifications function."""

    @patch("kairos.utils.send_notifications.send_telegram_message")
    def test_success(self, mock_send):
        mock_send.return_value = True

        with patch.dict(os.environ, {"PWATCH_TELEGRAM_TOKEN": "token123"}):
            result = send_notifications("Test", ["telegram"], {"chatId": "12345"})

        assert result["success"] is True
        assert result["reason"] == "sent"

    def test_no_channels(self):
        result = send_notifications("Test", [], {})
        assert result["success"] is False
        assert result["reason"] == "no_channels"

    def test_missing_token(self):
        with patch.dict(os.environ, {}, clear=True):
            result = send_notifications("Test", ["telegram"], {"chatId": "12345"})

        assert result["success"] is False
        assert result["reason"] == "missing_token"

    def test_missing_chat_id(self):
        with patch.dict(os.environ, {"PWATCH_TELEGRAM_TOKEN": "token123"}):
            result = send_notifications("Test", ["telegram"], {})

        assert result["success"] is False
        assert result["reason"] == "missing_chat_id"

    @patch("kairos.utils.send_notifications.send_telegram_message")
    def test_send_failure(self, mock_send):
        mock_send.return_value = False

        with patch.dict(os.environ, {"PWATCH_TELEGRAM_TOKEN": "token123"}):
            result = send_notifications("Test", ["telegram"], {"chatId": "12345"})

        assert result["success"] is False
        assert result["reason"] == "telegram_send_failed"

    @patch("kairos.utils.send_notifications.send_telegram_message")
    def test_send_exception(self, mock_send):
        mock_send.side_effect = Exception("Network error")

        with patch.dict(os.environ, {"PWATCH_TELEGRAM_TOKEN": "token123"}):
            result = send_notifications("Test", ["telegram"], {"chatId": "12345"})

        assert result["success"] is False
        assert result["reason"] == "telegram_send_exception"

    def test_unsupported_channel(self):
        result = send_notifications("Test", ["email"], {})
        assert result["success"] is False
        assert result["reason"] == "unsupported_channel"

    @patch("kairos.utils.send_notifications.send_telegram_message")
    def test_token_from_config(self, mock_send):
        mock_send.return_value = True

        result = send_notifications("Test", ["telegram"], {"token": "config_token", "chatId": "12345"})

        assert result["success"] is True
        mock_send.assert_called_once_with("Test", "config_token", "12345")

    @patch("kairos.utils.send_notifications.send_telegram_message")
    def test_env_token_takes_precedence(self, mock_send):
        mock_send.return_value = True

        with patch.dict(os.environ, {"PWATCH_TELEGRAM_TOKEN": "env_token"}):
            result = send_notifications("Test", ["telegram"], {"token": "config_token", "chatId": "12345"})

        assert result["success"] is True
        mock_send.assert_called_once_with("Test", "env_token", "12345")
