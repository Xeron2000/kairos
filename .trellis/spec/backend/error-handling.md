# Error Handling

> How errors are handled in this project.

---

## Overview

pwatch使用分层错误处理策略，包括自定义异常类、错误处理器和日志记录。

---

## Error Types

### 自定义异常类
```python
class PwatchError(Exception):
    """Base exception for pwatch."""
    pass

class ExchangeError(PwatchError):
    """Exchange API errors."""
    pass

class ConfigError(PwatchError):
    """Configuration errors."""
    pass

class TradeError(PwatchError):
    """Trade execution errors."""
    pass

class RiskError(PwatchError):
    """Risk management errors."""
    pass
```

---

## Error Handling Patterns

### 1. 交易所错误处理
```python
try:
    result = await exchange.create_order(...)
except ccxt.InsufficientFunds as e:
    raise TradeError(f"Insufficient funds: {e}")
except ccxt.InvalidOrder as e:
    raise TradeError(f"Invalid order: {e}")
except ccxt.NetworkError as e:
    raise ExchangeError(f"Network error: {e}")
except Exception as e:
    error_handler.handle_config_error(e, context, ErrorSeverity.ERROR)
    raise
```

### 2. 配置错误处理
```python
validation_result = config_validator.validate_config(config)
if not validation_result.is_valid:
    error_handler.handle_config_error(
        Exception("Configuration validation failed"),
        {"component": "PriceSentry", "operation": "config_validation"},
        ErrorSeverity.CRITICAL
    )
    raise ValueError(f"Configuration validation failed: {validation_result.errors}")
```

### 3. 风险控制错误处理
```python
def check_position_allowed(self, capital, symbol, position_value):
    if abs(self.daily_pnl) > capital * self.config.max_daily_loss_pct:
        return False, f"Daily loss limit reached ({self.daily_pnl:.2f})"
    if self.consecutive_losses >= self.config.max_consecutive_losses:
        return False, f"Max consecutive losses reached ({self.consecutive_losses})"
    return True, "OK"
```

---

## Error Severity Levels

```python
class ErrorSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
```

---

## API Error Responses

CLI命令错误输出格式：
```
❌ Error: <error message>
💡 Suggestion: <suggestion>
```

成功输出格式：
```
✅ Success: <message>
📊 Data: <data>
```

---

## Common Mistakes

1. **不捕获特定异常**：使用裸`except Exception`会隐藏真实错误
2. **不记录错误上下文**：错误日志应包含组件、操作、参数等信息
3. **不区分错误严重性**：所有错误都用相同级别处理
4. **不提供恢复建议**：错误消息应包含如何修复的建议

---

## Best Practices

1. **使用自定义异常类**：便于区分不同类型的错误
2. **记录完整上下文**：包括组件、操作、参数、堆栈跟踪
3. **区分错误严重性**：DEBUG/INFO/WARNING/ERROR/CRITICAL
4. **提供恢复建议**：帮助用户快速解决问题
5. **优雅降级**：非关键功能失败不应影响核心功能
