# Kairos Webhook Client 设计

> 向 Hermes Webhook 推送交易信号的最佳实践与实现方案

## 核心原则

| 原则 | 说明 |
|------|------|
| **At-least-once 投递** | 重试导致重复是正常的，接收端必须幂等 |
| **仅重试瞬时错误** | 5xx、429、超时重试；4xx 直接丢弃 |
| **指数退避 + Full Jitter** | 防惊群效应 (thundering herd) |
| **幂等 Key** | 每个事件生成唯一 `event_id`，重试时复用同一 key |

## 架构

```
Detector 产生信号
    │
    ▼
event_queue (asyncio.Queue)
    │
    ▼
WebhookClient.send_signal(payload)
    │
    ├─ 正常: POST → Hermes (202 accepted)
    │
    └─ 失败: tenacity 重试 → 最终失败 → 日志告警
```

kairos 是信号生产者，Hermes 是消费者。不需要独立 DLQ — Hermes 本身就是智能过滤器，发送失败只记日志即可。

## 错误分类

```python
def _is_retriable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        # 429 (rate limit) + 5xx server errors → retry
        return status == 429 or status >= 500
    # Connection/timeout errors → retry
    return isinstance(exc, (httpx.ConnectError, httpx.ReadError,
                            httpx.TimeoutException, httpx.PoolTimeout))
```

不重试的情况：
- 400 Bad Request — 请求格式错误
- 401 Unauthorized — Secret 配置错误
- 403 Forbidden — 权限问题
- 404 Not Found — 路由不存在

## 重试策略

使用 `tenacity` + `wait_exponential_jitter`：

```python
from tenacity import (
    retry, stop_after_attempt, wait_exponential_jitter,
    retry_if_exception, before_sleep_log
)

@retry(
    stop=stop_after_attempt(5),                    # 最多 5 次尝试
    wait=wait_exponential_jitter(initial=0.5, max=45.0),  # 0.5s → 1s → 2s → 4s → 8s (±50% jitter)
    retry=retry_if_exception(_is_retriable),        # 仅重试瞬时错误
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def _send():
    ...
```

## 签名 (HMAC-SHA256)

Hermes 使用 `X-Webhook-Signature` header 验证请求来源：

```python
import hmac, hashlib, json

def sign_payload(payload: dict, secret: str) -> str:
    """生成 HMAC-SHA256 签名"""
    canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
```

关键细节：
- 必须用 `separators=(",", ":")` 确保 canonical JSON
- 必须用 `ensure_ascii=False` 保留 Unicode 字符
- 签名放在 `X-Webhook-Signature` header

## 幂等设计

```python
import uuid
from datetime import datetime, timezone

def build_signal_payload(
    event_type: str,      # "price_velocity" | "volume_spike" | "open_interest_change" | "funding_rate_anomaly"
    symbol: str,
    price: float,
    condition: str,
    exchange: str,
) -> dict:
    return {
        "event": event_type,
        "event_id": str(uuid.uuid4()),       # ← 幂等 key
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "price": price,
        "condition": condition,
        "exchange": exchange,
    }
```

- `event_id` 在信号产生的瞬间生成，重试时原样复用
- `timestamp` 保持首次产生的时间，重试时不变

## 完整实现参考

```python
# src/kairos/webhook.py — 核心 Webhook Client

import hmac
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from tenacity import (
    retry, stop_after_attempt, wait_exponential_jitter,
    retry_if_exception, before_sleep_log
)

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────
WEBHOOK_URL = os.getenv("KAIROS_WEBHOOK_URL", "http://localhost:8644/webhooks/kairos-signals")
WEBHOOK_SECRET = os.getenv("KAIROS_WEBHOOK_SECRET", "")
TIMEOUT = float(os.getenv("KAIROS_WEBHOOK_TIMEOUT", "10"))


def _is_retriable(exc: Exception) -> bool:
    """仅重试瞬时失败。4xx 除了 429 都不重试。"""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return isinstance(exc, (
        httpx.ConnectError, httpx.ReadError,
        httpx.TimeoutException, httpx.PoolTimeout,
    ))


def _sign_payload(payload: dict, secret: str) -> str:
    """HMAC-SHA256 canonical JSON 签名"""
    canonical = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class WebhookClient:
    """Kairos → Hermes Webhook 信号发送器"""

    def __init__(
        self,
        url: str = WEBHOOK_URL,
        secret: str = WEBHOOK_SECRET,
        timeout: float = TIMEOUT,
    ):
        self.url = url
        self.secret = secret
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=5),
        )

    def build_event(
        self,
        event_type: str,
        symbol: str,
        price: float,
        condition: str,
        exchange: str = "",
        **extra,
    ) -> Dict[str, Any]:
        """构建信号 payload。event_id 在此生成，重试时复用。"""
        return {
            "event": event_type,
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "price": price,
            "condition": condition,
            "exchange": exchange,
            **extra,
        }

    async def send(self, payload: Dict[str, Any]) -> bool:
        """发送信号到 Hermes Webhook。成功返回 True，失败返回 False。"""
        if not self.secret:
            logger.warning("KAIROS_WEBHOOK_SECRET not set, skipping signature")
            return False

        signature = _sign_payload(payload, self.secret)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "User-Agent": "Kairos-Webhook/1.0",
        }

        @retry(
            stop=stop_after_attempt(5),
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
                payload["event"], payload["symbol"], payload["event_id"],
            )
            return True
        except httpx.HTTPStatusError as e:
            # Permanent failure (4xx) — log and drop
            logger.error(
                "Webhook permanent failure: status=%d event=%s symbol=%s error=%s",
                e.response.status_code, payload["event"], payload["symbol"], e,
            )
            return False
        except Exception as e:
            # Retries exhausted — log and drop
            logger.error(
                "Webhook delivery exhausted: event=%s symbol=%s event_id=%s error=%s",
                payload["event"], payload["symbol"], payload["event_id"], e,
            )
            return False

    async def close(self):
        await self.client.aclose()
```

## 使用方式

```python
from kairos.webhook import WebhookClient

# 初始化 (secret 从环境变量读取)
webhook = WebhookClient()

# 探测器产生信号时调用
payload = webhook.build_event(
    event_type="price_velocity",
    symbol="BTC/USDT",
    price=71234.50,
    condition="30s_window_0.5pct_break",
    exchange="okx",
)
await webhook.send(payload)
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KAIROS_WEBHOOK_URL` | `http://localhost:8644/webhooks/kairos-signals` | Hermes Webhook URL |
| `KAIROS_WEBHOOK_SECRET` | (required) | 与 Hermes subscription 的 secret 一致 |
| `KAIROS_WEBHOOK_TIMEOUT` | `10` | HTTP 请求超时 (秒) |

## 信号格式

```json
{
  "event": "price_velocity",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-06-04T02:06:00.000000+00:00",
  "symbol": "BTC/USDT",
  "price": 71234.50,
  "condition": "30s_window_0.5pct_break",
  "exchange": "okx"
}
```

`{event}`, `{symbol}`, `{price}`, `{condition}`, `{exchange}`, `{timestamp}` 在 Hermes prompt template 中可直接引用。

## 参考

- [Hookdeck: Outbound Webhook Retry Best Practices](https://hookdeck.com/outpost/guides/outbound-webhook-retry-best-practices)
- [Svix: Webhook Retry Best Practices](https://www.svix.com/resources/webhook-best-practices/retries/)
- [Tenacity Documentation](https://tenacity.readthedocs.io/)
- [OneUptime: Exponential Backoff in Python](https://oneuptime.com/blog/post/2025-01-06-python-retry-exponential-backoff/view)
