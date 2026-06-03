"""Comprehensive tests for telegram notifications."""

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from kairos.notifications.telegram import (
    _mask_token,
    _retry_with_backoff,
    _send_message_internal,
    send_telegram_message,
)


class TestMaskToken:
    """Test _mask_token function."""

    def test_short_token(self):
        assert _mask_token("abc") == "***"

    def test_empty_token(self):
        assert _mask_token("") == "***"

    def test_none_token(self):
        assert _mask_token(None) == "***"

    def test_valid_token(self):
        result = _mask_token("1234567890abcdef")
        assert result.startswith("123456")
        assert result.endswith("cdef")
        assert "..." in result


class TestRetryWithBackoff:
    """Test _retry_with_backoff decorator."""

    def test_success_on_first_try(self):
        mock_func = MagicMock(return_value="success")
        decorated = _retry_with_backoff(mock_func, max_retries=3)

        result = decorated()
        assert result == "success"
        assert mock_func.call_count == 1

    def test_retries_on_failure(self):
        mock_func = MagicMock(side_effect=[requests.RequestException("Error"), "success"])
        decorated = _retry_with_backoff(mock_func, max_retries=3, base_delay=0.01)

        result = decorated()
        assert result == "success"
        assert mock_func.call_count == 2

    def test_raises_after_max_retries(self):
        mock_func = MagicMock(side_effect=requests.RequestException("Error"))
        decorated = _retry_with_backoff(mock_func, max_retries=2, base_delay=0.01)

        with pytest.raises(requests.RequestException):
            decorated()
        assert mock_func.call_count == 3  # Initial + 2 retries

    def test_handles_rate_limit(self):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "0.01"}

        error = requests.RequestException("Rate limited")
        error.response = mock_response

        mock_func = MagicMock(side_effect=[error, "success"])
        decorated = _retry_with_backoff(mock_func, max_retries=3, base_delay=0.01)

        result = decorated()
        assert result == "success"


class TestSendMessageInternal:
    """Test _send_message_internal function."""

    @patch("kairos.notifications.telegram.requests.post")
    def test_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = _send_message_internal("Test", "token123", "chat123")
        assert result.status_code == 200

    @patch("kairos.notifications.telegram.requests.post")
    def test_failure(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_post.return_value = mock_response

        with pytest.raises(requests.RequestException):
            _send_message_internal("Test", "token123", "chat123")


class TestSendTelegramMessage:
    """Test send_telegram_message function."""

    @patch("kairos.notifications.telegram._send_message_internal")
    def test_success(self, mock_send):
        mock_send.return_value = MagicMock()
        result = send_telegram_message("Test", "token123", "chat123")
        assert result is True

    def test_missing_token(self):
        result = send_telegram_message("Test", "", "chat123")
        assert result is False

    def test_missing_chat_id(self):
        result = send_telegram_message("Test", "token123", "")
        assert result is False

    @patch("kairos.notifications.telegram._send_message_internal")
    def test_handles_exception(self, mock_send):
        mock_send.side_effect = Exception("Network error")
        result = send_telegram_message("Test", "token123", "chat123")
        assert result is False
