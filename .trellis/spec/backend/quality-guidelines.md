# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

pwatch遵循Python最佳实践，使用ruff进行代码检查，pytest进行测试。

---

## Forbidden Patterns

### 1. 硬编码配置
```python
# ❌ 错误
API_KEY = "abc123"
MAX_RETRIES = 3

# ✅ 正确
API_KEY = os.getenv("API_KEY")
MAX_RETRIES = config.get("maxRetries", 3)
```

### 2. 裸异常捕获
```python
# ❌ 错误
try:
    ...
except:
    pass

# ✅ 正确
try:
    ...
except SpecificError as e:
    logger.error(f"Failed: {e}")
    raise
```

### 3. 魔法数字
```python
# ❌ 错误
if price > 50000:
    ...

# � 正确
RESISTANCE_LEVEL = 50000
if price > RESISTANCE_LEVEL:
    ...
```

### 4. 重复代码
```python
# ❌ 错误：在多处相同逻辑
# ✅ 正确：提取为函数
def calculate_position_size(capital, risk_pct, entry_price, stop_loss):
    ...
```

---

## Required Patterns

### 1. 类型注解
```python
def calculate_pnl(entry_price: float, exit_price: float, amount: float) -> float:
    """Calculate PnL for a position."""
    return (exit_price - entry_price) * amount
```

### 2. 文档字符串
```python
class BoxDetector:
    """Detects box patterns in price data.
    
    Box patterns are consolidation zones where price oscillates
    between a high and low boundary. Detection algorithm:
    1. Find initial high/low range
    2. Extend while price stays within bounds
    3. Check for second tests (二次探顶/底)
    4. Calculate convergence
    """
```

### 3. 错误处理
```python
try:
    result = await exchange.fetch_ticker(symbol)
except ccxt.NetworkError as e:
    logger.error(f"Network error fetching {symbol}: {e}")
    raise ExchangeError(f"Failed to fetch {symbol}") from e
```

### 4. 日志记录
```python
logger.info(f"Opened position {pos_id}: {side} {amount} {symbol} @ {entry_price}")
logger.warning(f"Stop loss too tight ({risk_pct:.2f}%)")
logger.error(f"Failed to execute order: {e}")
```

---

## Testing Requirements

### 单元测试覆盖
- 核心函数：100%覆盖
- 交易执行：关键路径100%覆盖
- 错误处理：所有异常路径覆盖

### 测试命名
```python
def test_calculate_position_size_basic():
    """Test basic position size calculation."""
    ...

def test_calculate_position_size_with_leverage():
    """Test position size with leverage limit."""
    ...

def test_check_position_allowed_daily_loss():
    """Test daily loss limit check."""
    ...
```

### 测试结构
```python
class TestBoxDetector:
    """Test box pattern detection."""
    
    def test_detect_simple_box(self):
        """Test detection of simple box pattern."""
        ...
    
    def test_detect_convergence(self):
        """Test convergence detection."""
        ...
```

---

## Code Review Checklist

### 代码质量
- [ ] 类型注解完整
- [ ] 文档字符串清晰
- [ ] 错误处理完善
- [ ] 日志记录充分

### 安全性
- [ ] 无硬编码密钥
- [ ] 输入验证充分
- [ ] 权限检查正确

### 性能
- [ ] 无N+1查询
- [ ] 缓存使用合理
- [ ] 异步操作正确

### 可维护性
- [ ] 函数职责单一
- [ ] 命名清晰易懂
- [ ] 无重复代码
