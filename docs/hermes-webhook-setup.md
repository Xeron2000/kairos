# Hermes Webhook 配置教程

> 从零配置 Hermes Webhook，接收 Kairos 交易信号

## 前置条件

- Hermes Agent 已安装 (`hermes` 命令可用)
- Gateway 服务正在运行 (`hermes gateway run`)
- Telegram Bot 已配置（通知投递通道）

## Step 1: 启用 Webhook Platform

编辑 `~/.hermes/config.yaml`，添加以下配置：

```yaml
platforms:
  webhook:
    enabled: true
    extra:
      host: "0.0.0.0"
      port: 8644
      secret: "<your-hmac-secret>"  # 平台级别 secret，非 subscription secret
```

生成 HMAC Secret：

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

确认配置已添加：

```bash
tail -6 ~/.hermes/config.yaml
```

## Step 2: 重启 Gateway

```bash
systemctl --user restart hermes-gateway.service

# 等待启动
sleep 5

# 验证 Webhook 端口已监听
curl http://localhost:8644/health
# 预期输出: {"status": "ok", "platform": "webhook"}
```

## Step 3: 注册 Webhook Subscription

```bash
hermes webhook subscribe kairos-signals \
  --prompt '收到 Kairos futures anomaly:

- 信号类型: {event}
- 交易对: {symbol}
- 当前价格: {price}
- 触发条件: {condition}
- 交易所: {exchange}

完整 payload:
{__raw__}

请判断这个信号是否值得通知用户:
1. Webhook 异动只是候选提示，不是交易信号。
2. 必须先调用 `evaluate_trade_opportunity(symbol)`；只有 `push_allowed == true` 才允许推送。
3. Hermes 可以 veto，但不能把 `watch` / `prepare` / `no_trade` 提升成交易提醒。
4. 非 `push_allowed`、噪音、重复、缺少入场/止损/目标/RR 的情况，只输出 `KAIROS_NO_SIGNAL`。
5. 真正可交易时，再调用 cycle/sentiment/box/signal 做确认和解释，输出简洁中文 KISS 提醒。' \
  --description "Kairos 交易系统——实时异动信号" \
  --skills kairos-harness \
  --deliver telegram \
  --deliver-chat-id "<your-chat-id>"
```

**注意**：Hermes 会自动生成 subscription 专用 secret（在创建 subscription 的输出中显示），不需要用 `--secret` 参数。`platforms.webhook.extra.secret` 是平台级别的备用密钥。

| 参数 | 说明 |
|------|------|
| `name` | 路由名，最终 URL 为 `/webhooks/<name>` |
| `--prompt` | Agent prompt 模板，支持 `{event}`, `{symbol}`, `{price}` 等变量 |
| `--events` | (可选) 限定事件类型，如 `price_velocity,volume_spike,open_interest_change,funding_rate_anomaly`。不指定则接受所有 |
| `--description` | 简短描述，在 list 中展示 |
| `--deliver` | 投递通道：`telegram`, `discord`, `slack`, `log` 等 |
| `--deliver-chat-id` | 目标 Chat ID |
| `--deliver-only` | 跳过 LLM，直接投递 prompt（零 LLM 成本） |

## Step 4: 验证 Subscription

查看已注册的 subscriptions：

```bash
hermes webhook list
```

预期输出：

```
◆ kairos-signals
  Kairos 交易系统——实时异动信号
  URL:     http://localhost:8644/webhooks/kairos-signals
  Events:  (all)
  Deliver: telegram
```

## Step 5: 测试 Webhook

```bash
export KAIROS_WEBHOOK_SECRET="<subscription-secret>"

python3 -c "
import json, hmac, hashlib, urllib.request

secret = '<subscription-secret>'
url = 'http://localhost:8644/webhooks/kairos-signals'

payload = {
    'event': 'price_velocity',
    'event_id': 'test-001',
    'timestamp': '2026-06-04T02:00:00Z',
    'symbol': 'BTC/USDT',
    'price': 71234.50,
    'condition': 'test_signal',
    'exchange': 'okx'
}
body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
sig = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()

req = urllib.request.Request(url, data=body, headers={
    'Content-Type': 'application/json',
    'X-Webhook-Signature': sig
}, method='POST')

resp = urllib.request.urlopen(req, timeout=30)
print('Status:', resp.status)
print('Body:', resp.read().decode())
"
```

预期响应：

```json
{"status": "accepted", "route": "kairos-signals", "delivery_id": "..."}
```

## Step 6: 查看处理日志

```bash
tail -f ~/.hermes/logs/gateway.log | grep webhook
```

关键日志行：

```
[webhook] POST route=kairos-signals delivery=...
inbound message: platform=webhook msg='收到交易信号: ...'
response ready: platform=webhook time=12.0s response=4 chars  ← "静默"
[Webhook] Sending response to webhook:kairos-signals:...
```

## Kairos 侧配置

Kairos 侧设置环境变量：

```bash
export KAIROS_WEBHOOK_URL="http://localhost:8644/webhooks/kairos-signals"
export KAIROS_WEBHOOK_SECRET="<subscription-secret>"
```

> Secret 必须与 Hermes subscription 匹配。每次重新创建 subscription 都会生成新 secret，需要同步更新。

## 故障排查

### Webhook 返回 404

Subscription 未注册或路由名不匹配：

```bash
hermes webhook list    # 确认路由名
curl http://localhost:8644/health  # 确认 Webhook 可用
```

### Webhook 返回 "event": "unknown"

不影响处理。Hermes 不解析 payload 结构中的 event 字段，仅用于 prompt 模板中的 `{event}` 替换。

### Gateway 重启后 Subscription 丢失

Subscription 持久化在 `~/.hermes/` 中，重启不会丢失。如果丢失，重新执行 Step 3。

### Telegram 收不到通知

检查 Telegram 是否已连接：

```bash
hermes gateway status
```

确认 `deliver-chat-id` 正确，且 Telegram Bot 已加入该 chat。

## 完整流程

```
┌──────────┐   POST /webhooks/kairos-signals   ┌──────────┐
│  Kairos  │ ──────────────────────────────────> │  Hermes  │
│ Detector │   X-Webhook-Signature: <hmac>      │ Webhook  │
└──────────┘                                     └────┬─────┘
                                                      │
                                                      ▼
                                               ┌──────────┐
                                               │ LLM 过滤  │
                                               │ 噪音→静默  │
                                               │ 机会→分析  │
                                               └────┬─────┘
                                                    │
                                         ┌──────────┴──────────┐
                                         ▼                     ▼
                                    "静默"               ┌──────────┐
                                    (无通知)             │ Telegram │
                                                         │  推送     │
                                                         └──────────┘
```
