# Logging Guidelines

> Structured logging, log levels, and logging patterns.

---

## Overview

pwatch使用Python标准logging模块，支持结构化日志和不同级别。

---

## Log Levels

### DEBUG
- 详细的调试信息
- 变量值、函数参数
- 仅在开发环境启用

### INFO
- 关键操作记录
- 状态变化
- 交易执行结果

### WARNING
- 非关键问题
- 配置警告
- 性能警告

### ERROR
- 功能失败
- 异常捕获
- 需要关注的问题

### CRITICAL
- 系统级错误
- 数据损坏
- 安全问题

---

## Logging Patterns

### 1. 组件日志
```python
logger = logging.getLogger("pwatch.trades.executor")
logger.info(f"Executing order: {order.symbol} {order.side} {order.amount}")
```

### 2. 交易日志
```python
logger.info(
    f"Position opened: {pos_id} "
    f"symbol={symbol} side={side} "
    f"entry={entry_price} amount={amount} "
    f"leverage={leverage}"
)
```

### 3. 错误日志
```python
logger.error(
    f"Order execution failed: {error}",
    extra={
        "component": "TradeExecutor",
        "operation": "execute_order",
        "symbol": symbol,
        "error_type": type(error).__name__
    }
)
```

### 4. 性能日志
```python
start = time.time()
# ... operation ...
elapsed = time.time() - start
logger.debug(f"Operation completed in {elapsed:.3f}s")
```

---

## Structured Logging

### 日志格式
```python
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
```

### 日志配置
```python
def setup_logging(level: str = "INFO", console: bool = True):
    """Setup logging configuration."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    handlers = []
    if console:
        handlers.append(logging.StreamHandler())
    
    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=handlers
    )
```

---

## Log File Management

### 日志文件位置
- 后台运行日志：`~/.config/pwatch/pwatch.log`
- 交易日志：`~/.config/pwatch/trades.log`

### 日志轮转
```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    log_path,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
```

---

## Best Practices

### 1. 使用正确的级别
- DEBUG：详细调试信息
- INFO：关键操作记录
- WARNING：非关键问题
- ERROR：功能失败
- CRITICAL：系统级错误

### 2. 包含上下文信息
```python
# ❌ 错误
logger.error("Order failed")

# ✅ 正确
logger.error(
    f"Order failed for {symbol}: {error}",
    extra={"symbol": symbol, "error": str(error)}
)
```

### 3. 避免敏感信息
```python
# ❌ 错误
logger.info(f"API Key: {api_key}")

# ✅ 正确
logger.info(f"API Key: {api_key[:8]}...")
```

### 4. 性能考虑
```python
# ❌ 错误：总是计算
logger.debug(f"Data: {expensive_calculation()}")

# ✅ 正确：仅在DEBUG级别计算
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(f"Data: {expensive_calculation()}")
```

---

## CLI输出格式

### 成功输出
```
✅ <success message>
📊 <data>
```

### 错误输出
```
❌ <error message>
💡 <suggestion>
```

### 警告输出
```
⚠️ <warning message>
```

### 信息输出
```
ℹ️ <info message>
```
