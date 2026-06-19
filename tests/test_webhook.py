"""Tests for kairos.webhook — SignalEvent, HMAC signing, WebhookClient."""

import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from kairos.webhook import (
    DEFAULT_URL,
    SignalEvent,
    WebhookClient,
    _is_retriable,
    _sign,
)

# ── SignalEvent ────────────────────────────────────────────────────────


class TestSignalEvent:
    """SignalEvent construction and to_payload()."""

    def test_construction_defaults(self):
        """Minimal SignalEvent gets auto-generated event_id, timestamp, defaults."""
        ev = SignalEvent(
            event="price_alert",
            symbol="BTC/USDT",
            price=68500.0,
            condition="breakout_above",
        )
        assert ev.event == "price_alert"
        assert ev.symbol == "BTC/USDT"
        assert ev.price == 68500.0
        assert ev.condition == "breakout_above"
        # auto-generated fields
        assert isinstance(ev.event_id, str)
        assert len(ev.event_id) == 36  # UUID4
        assert isinstance(ev.timestamp, str)
        assert "T" in ev.timestamp  # ISO 8601
        # defaults
        assert ev.exchange == ""
        assert ev.change_pct == 0.0
        assert ev.severity == "LOW"

    def test_to_payload_keys(self):
        """to_payload() returns exactly the expected keys."""
        ev = SignalEvent(
            event="price_alert",
            symbol="ETH/USDT",
            price=3400.0,
            condition="breakout_below",
        )
        payload = ev.to_payload()
        expected_keys = {
            "event",
            "event_type",
            "event_id",
            "timestamp",
            "symbol",
            "price",
            "condition",
            "exchange",
            "change_pct",
            "severity",
        }
        assert set(payload.keys()) == expected_keys
        assert payload["event"] == "price_alert"
        assert payload["event_type"] == "price_alert"
        assert payload["symbol"] == "ETH/USDT"
        assert payload["price"] == 3400.0
        assert payload["condition"] == "breakout_below"
        assert payload["exchange"] == ""

    def test_to_payload_includes_signal_strength_fields(self):
        """to_payload() includes severity and change_pct for Hermes routing."""
        ev = SignalEvent(
            event="price_alert",
            symbol="BNB/USDT",
            price=580.0,
            condition="box_top_touch",
            severity="HIGH",
            change_pct=3.5,
        )
        payload = ev.to_payload()
        assert payload["severity"] == "HIGH"
        assert payload["change_pct"] == 3.5

    def test_explicit_event_id(self):
        """Explicit event_id is preserved."""
        ev = SignalEvent(
            event="price_alert",
            symbol="BTC/USDT",
            price=70000.0,
            condition="divergence",
            event_id="my-custom-id-123",
        )
        assert ev.event_id == "my-custom-id-123"
        assert ev.to_payload()["event_id"] == "my-custom-id-123"

    def test_explicit_timestamp(self):
        """Explicit timestamp is preserved."""
        ev = SignalEvent(
            event="price_alert",
            symbol="BTC/USDT",
            price=70000.0,
            condition="divergence",
            timestamp="2025-01-15T10:30:00+00:00",
        )
        assert ev.timestamp == "2025-01-15T10:30:00+00:00"
        assert ev.to_payload()["timestamp"] == "2025-01-15T10:30:00+00:00"

    def test_exchange_field_in_payload(self):
        """Exchange field flows through to payload."""
        ev = SignalEvent(
            event="price_alert",
            symbol="BTC/USDT",
            price=69000.0,
            condition="whale_move",
            exchange="binance",
        )
        assert ev.to_payload()["exchange"] == "binance"


# ── _sign ──────────────────────────────────────────────────────────────


class TestSign:
    """HMAC-SHA256 signing with known test vectors."""

    def test_known_vector_empty(self):
        """HMAC with empty payload and secret."""
        # Known vector: HMAC-SHA256("", "") = b613679a...
        # RFC 4231 test case 1 adapted
        secret = ""
        payload = {}
        result = _sign(payload, secret)
        # canonical JSON: {}
        expected = hmac.new(b"", b"{}", hashlib.sha256).hexdigest()
        assert result == expected

    def test_known_vector_simple(self):
        """HMAC with simple payload — deterministic output."""
        secret = "super-secret-key"
        payload = {"event": "test", "price": 100.0}
        result = _sign(payload, secret)
        # Compute independently
        canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        assert result == expected

    def test_canonical_json_no_spaces(self):
        """Signature uses compact JSON (no spaces after separators)."""
        secret = "key"
        payload = {"a": 1, "b": 2}
        result = _sign(payload, secret)
        # Verify compact representation
        canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        # Should NOT have spaces
        assert " " not in canonical
        assert canonical == '{"a":1,"b":2}'
        expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        assert result == expected

    def test_different_secret_different_signature(self):
        """Different secrets produce different signatures for same payload."""
        payload = {"event": "alert", "symbol": "BTC/USDT"}
        sig1 = _sign(payload, "secret-A")
        sig2 = _sign(payload, "secret-B")
        assert sig1 != sig2
        assert len(sig1) == 64  # SHA-256 hexdigest
        assert len(sig2) == 64

    def test_different_payload_different_signature(self):
        """Different payloads produce different signatures with same secret."""
        secret = "shared-secret"
        sig1 = _sign({"event": "a"}, secret)
        sig2 = _sign({"event": "b"}, secret)
        assert sig1 != sig2

    def test_payload_with_severity_change_pct_signature_is_canonical(self):
        """Canonical HMAC covers severity/change_pct with compact JSON ordering preserved."""
        secret = "super-secret-key"
        payload = {
            "event": "price_alert",
            "event_id": "evt-1",
            "timestamp": "2025-01-15T10:30:00+00:00",
            "symbol": "BTC/USDT:USDT",
            "price": 68500.0,
            "condition": "30s_0.5pct",
            "exchange": "okx",
            "change_pct": 0.82,
            "severity": "MEDIUM",
        }
        canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        assert _sign(payload, secret) == expected

    def test_unicode_payload(self):
        """Payload with unicode characters signed correctly."""
        secret = "key"
        payload = {"event": "价格提醒", "symbol": "BTC/USDT"}
        result = _sign(payload, secret)
        assert len(result) == 64


# ── _is_retriable ──────────────────────────────────────────────────────


class TestIsRetriable:
    """Retry decision logic for HTTP errors and connection failures."""

    def test_429_is_retriable(self):
        """Rate limit (429) → retriable."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 429
        exc = httpx.HTTPStatusError("Rate limited", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is True

    def test_500_is_retriable(self):
        """Internal server error (500) → retriable."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        exc = httpx.HTTPStatusError("Server error", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is True

    def test_502_is_retriable(self):
        """Bad gateway (502) → retriable."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 502
        exc = httpx.HTTPStatusError("Bad gateway", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is True

    def test_503_is_retriable(self):
        """Service unavailable (503) → retriable."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 503
        exc = httpx.HTTPStatusError("Unavailable", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is True

    def test_401_is_not_retriable(self):
        """Unauthorized (401) → permanent failure, no retry."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        exc = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is False

    def test_403_is_not_retriable(self):
        """Forbidden (403) → permanent failure, no retry."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 403
        exc = httpx.HTTPStatusError("Forbidden", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is False

    def test_404_is_not_retriable(self):
        """Not found (404) → permanent failure, no retry."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 404
        exc = httpx.HTTPStatusError("Not found", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is False

    def test_400_is_not_retriable(self):
        """Bad request (400) → client error, no retry."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        exc = httpx.HTTPStatusError("Bad request", request=MagicMock(), response=resp)
        assert _is_retriable(exc) is False

    def test_connect_error_is_retriable(self):
        """ConnectError → retriable (transient network issue)."""
        assert _is_retriable(httpx.ConnectError("Connection refused")) is True

    def test_read_error_is_retriable(self):
        """ReadError → retriable (transient read failure)."""
        assert _is_retriable(httpx.ReadError("Read timed out")) is True

    def test_timeout_exception_is_retriable(self):
        """TimeoutException → retriable."""
        assert _is_retriable(httpx.TimeoutException("Timeout")) is True

    def test_pool_timeout_is_retriable(self):
        """PoolTimeout → retriable."""
        assert _is_retriable(httpx.PoolTimeout("Pool exhausted")) is True

    def test_value_error_is_not_retriable(self):
        """Unrelated exception → not retriable."""
        assert _is_retriable(ValueError("Some random error")) is False

    def test_key_error_is_not_retriable(self):
        """Unrelated exception → not retriable."""
        assert _is_retriable(KeyError("missing")) is False


# ── WebhookClient ──────────────────────────────────────────────────────


class TestWebhookClientInit:
    """WebhookClient initialization and configuration."""

    def test_default_url_when_nothing_set(self):
        """No URL, no env var → falls back to DEFAULT_URL."""
        with patch.dict(os.environ, {}, clear=True):
            client = WebhookClient()
            assert client.url == DEFAULT_URL

    def test_default_secret_when_nothing_set(self):
        """No secret, no env var → empty secret."""
        with patch.dict(os.environ, {}, clear=True):
            client = WebhookClient()
            assert client.secret == ""

    def test_explicit_url_overrides_default(self):
        """Constructor URL arg takes precedence over default."""
        client = WebhookClient(url="https://custom.example.com/webhook")
        assert client.url == "https://custom.example.com/webhook"

    def test_explicit_secret_overrides_default(self):
        """Constructor secret arg takes precedence."""
        client = WebhookClient(secret="my-hmac-secret")
        assert client.secret == "my-hmac-secret"

    def test_env_var_url(self):
        """KAIROS_WEBHOOK_URL env var sets URL when no explicit arg."""
        with patch.dict(os.environ, {"KAIROS_WEBHOOK_URL": "http://env.example.com/hook"}):
            client = WebhookClient()
            assert client.url == "http://env.example.com/hook"

    def test_env_var_secret(self):
        """KAIROS_WEBHOOK_SECRET env var sets secret when no explicit arg."""
        with patch.dict(os.environ, {"KAIROS_WEBHOOK_SECRET": "env-secret-123"}):
            client = WebhookClient()
            assert client.secret == "env-secret-123"

    def test_explicit_url_wins_over_env(self):
        """Constructor arg wins over env var for URL."""
        with patch.dict(os.environ, {"KAIROS_WEBHOOK_URL": "http://env.example.com/hook"}):
            client = WebhookClient(url="https://explicit.example.com/hook")
            assert client.url == "https://explicit.example.com/hook"

    def test_explicit_secret_wins_over_env(self):
        """Constructor arg wins over env var for secret."""
        with patch.dict(os.environ, {"KAIROS_WEBHOOK_SECRET": "env-secret-123"}):
            client = WebhookClient(secret="explicit-secret")
            assert client.secret == "explicit-secret"

    def test_timeout_default(self):
        """Default timeout is set."""
        client = WebhookClient()
        assert client.timeout is not None
        # httpx.Timeout wraps the value
        assert isinstance(client.timeout, httpx.Timeout)

    def test_custom_timeout(self):
        """Custom timeout is respected."""
        client = WebhookClient(timeout=5.0)
        assert client.timeout == httpx.Timeout(5.0, connect=5.0)

    def test_custom_max_retries(self):
        """Custom max_retries is set."""
        client = WebhookClient(max_retries=3)
        assert client.max_retries == 3


class TestWebhookClientIsConfigured:
    """is_configured() checks."""

    def test_not_configured_without_secret(self):
        """No secret → not configured."""
        with patch.dict(os.environ, {}, clear=True):
            client = WebhookClient()
            assert client.is_configured() is False

    def test_configured_with_secret(self):
        """With secret → configured."""
        client = WebhookClient(secret="some-secret")
        assert client.is_configured() is True

    def test_configured_with_env_secret(self):
        """Env var secret → configured."""
        with patch.dict(os.environ, {"KAIROS_WEBHOOK_SECRET": "env-secret"}):
            client = WebhookClient()
            assert client.is_configured() is True


# ── WebhookClient.send ─────────────────────────────────────────────────


class TestWebhookClientSend:
    """send() method behavior with mocked httpx.AsyncClient."""

    @pytest.fixture
    def event(self):
        return SignalEvent(
            event="price_alert",
            symbol="BTC/USDT",
            price=68500.0,
            condition="breakout_above",
            event_id="test-event-001",
            timestamp="2025-01-15T10:30:00+00:00",
        )

    @pytest.fixture
    def client_with_secret(self):
        """WebhookClient with a known secret."""
        return WebhookClient(
            url="https://hooks.example.com/webhook",
            secret="test-secret-abc",
        )

    @pytest.mark.asyncio
    async def test_send_success(self, client_with_secret, event):
        """Happy path: POST succeeds, returns True."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_response

        client_with_secret.client = mock_client

        result = await client_with_secret.send(event)
        assert result is True
        mock_client.post.assert_called_once()

        # Verify call args
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://hooks.example.com/webhook"
        assert call_args[1]["json"] == event.to_payload()
        headers = call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"
        assert "X-Webhook-Signature" in headers
        assert headers["X-Request-ID"] == event.event_id
        assert headers["User-Agent"] == "Kairos-Webhook/1.0"

    @pytest.mark.asyncio
    async def test_send_no_secret_returns_false(self, event):
        """No secret configured → send returns False immediately."""
        with patch.dict(os.environ, {}, clear=True):
            client = WebhookClient()
            result = await client.send(event)
            assert result is False

    @pytest.mark.asyncio
    async def test_send_401_permanent_failure(self, client_with_secret, event):
        """401 Unauthorized → permanent failure, no retry, returns False."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=resp)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = resp

        client_with_secret.client = mock_client

        result = await client_with_secret.send(event)
        assert result is False
        # Should only try once (no retry for 401)
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_send_403_permanent_failure(self, client_with_secret, event):
        """403 Forbidden → permanent failure, no retry."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 403
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("Forbidden", request=MagicMock(), response=resp)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = resp

        client_with_secret.client = mock_client

        result = await client_with_secret.send(event)
        assert result is False
        assert mock_client.post.call_count == 1

    @pytest.mark.asyncio
    async def test_send_500_retries_then_fails(self, client_with_secret, event):
        """500 errors are retried, exhausted → returns False."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("Server error", request=MagicMock(), response=resp)

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = resp

        client_with_secret.client = mock_client
        client_with_secret.max_retries = 2

        result = await client_with_secret.send(event)
        assert result is False
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_retry_then_success(self, client_with_secret, event):
        """First attempt fails 503, second succeeds → returns True."""
        fail_resp = MagicMock(spec=httpx.Response)
        fail_resp.status_code = 503
        fail_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service unavailable", request=MagicMock(), response=fail_resp
        )

        ok_resp = MagicMock(spec=httpx.Response)
        ok_resp.status_code = 200
        ok_resp.raise_for_status.return_value = None

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = [fail_resp, ok_resp]

        client_with_secret.client = mock_client

        result = await client_with_secret.send(event)
        assert result is True
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_send_connection_error_retries(self, client_with_secret, event):
        """Connection errors are retried."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        client_with_secret.client = mock_client
        client_with_secret.max_retries = 3

        result = await client_with_secret.send(event)
        assert result is False
        assert mock_client.post.call_count == 3

    @pytest.mark.asyncio
    async def test_send_verify_signature_header(self, client_with_secret, event):
        """X-Webhook-Signature header matches expected HMAC."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.return_value = mock_response

        client_with_secret.client = mock_client

        await client_with_secret.send(event)

        headers = mock_client.post.call_args[1]["headers"]
        expected_sig = _sign(event.to_payload(), "test-secret-abc")
        assert headers["X-Webhook-Signature"] == expected_sig

    @pytest.mark.asyncio
    async def test_send_unexpected_exception(self, client_with_secret, event):
        """Non-HTTP exception → returns False (exhausted log)."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post.side_effect = RuntimeError("Unexpected failure")

        client_with_secret.client = mock_client
        client_with_secret.max_retries = 1

        result = await client_with_secret.send(event)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_with_empty_secret_env(self, event):
        """Empty string secret (even if set in env) → returns False."""
        with patch.dict(os.environ, {"KAIROS_WEBHOOK_SECRET": ""}):
            client = WebhookClient(url="https://hooks.example.com/webhook")
            assert client.secret == ""
            result = await client.send(event)
            assert result is False

    @pytest.mark.asyncio
    async def test_close_acloses_client(self):
        """close() calls client.aclose()."""
        client = WebhookClient(secret="test")
        mock_aclose = AsyncMock()
        client.client.aclose = mock_aclose

        await client.close()
        mock_aclose.assert_called_once()
