"""Kairos → Hermes Webhook signal sender.

HMAC-SHA256 signing, tenacity exponential-backoff retry, idempotent event IDs.
"""

import hashlib
import hmac
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

# ── Defaults (override via env vars) ────────────────────────
DEFAULT_URL = "http://localhost:8644/webhooks/kairos-signals"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 5


@dataclass
class SignalEvent:
    """A trading signal ready to be sent to Hermes."""

    event: str
    symbol: str
    price: float
    condition: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    exchange: str = ""
    change_pct: float = 0.0
    severity: str = "LOW"

    def to_payload(self) -> Dict[str, Any]:
        """Canonical JSON payload for Hermes webhook."""
        return {
            "event": self.event,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "price": self.price,
            "condition": self.condition,
            "exchange": self.exchange,
        }


def _sign(payload: dict, secret: str) -> str:
    """HMAC-SHA256 over canonical JSON."""
    canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _is_retriable(exc: BaseException) -> bool:
    """Only retry transient failures (5xx, 429, connection/timeout)."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.TimeoutException,
            httpx.PoolTimeout,
        ),
    )


class WebhookClient:
    """Reliable delivery of trading signals to Hermes webhook."""

    def __init__(
        self,
        url: str = "",
        secret: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.url = url or os.getenv("KAIROS_WEBHOOK_URL", DEFAULT_URL)
        self.secret = secret or os.getenv("KAIROS_WEBHOOK_SECRET", "")
        self.timeout = httpx.Timeout(timeout, connect=5.0)
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_keepalive_connections=5),
        )

    def is_configured(self) -> bool:
        """Check if the webhook is properly configured."""
        return bool(self.secret)

    async def send(self, event: SignalEvent) -> bool:
        """Send a signal event to Hermes. Returns True on success."""
        if not self.secret:
            logger.warning("KAIROS_WEBHOOK_SECRET not set — dropping signal")
            return False

        payload = event.to_payload()
        signature = _sign(payload, self.secret)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "User-Agent": "Kairos-Webhook/1.0",
        }

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential_jitter(initial=0.5, max=45.0),
            retry=retry_if_exception(_is_retriable),
            before_sleep=before_sleep_log(logger, logging.WARNING),
        )
        async def _send():
            resp = await self.client.post(self.url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp

        try:
            await _send()
            logger.info(
                "Signal delivered: event=%s symbol=%s event_id=%s",
                event.event,
                event.symbol,
                event.event_id,
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                "Webhook permanent failure: status=%d event=%s symbol=%s",
                e.response.status_code,
                event.event,
                event.symbol,
            )
            return False
        except Exception:
            logger.exception(
                "Webhook exhausted: event=%s symbol=%s event_id=%s",
                event.event,
                event.symbol,
                event.event_id,
            )
            return False

    async def close(self) -> None:
        await self.client.aclose()
