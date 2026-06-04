# 提升测试覆盖率到80%以上

## Goal
提升三个核心模块的测试覆盖率到80%以上：
1. 交易所模块：17-58% → 需要模拟WebSocket连接
2. 交易模块：35-47% → 需要模拟交易所API
3. 工具模块：16-51% → 需要模拟外部依赖

## What I already know
- 项目是加密货币期货价格监控和交易系统
- 现有测试文件结构：
  - `tests/test_exchanges_base.py`
  - `tests/test_exchanges_binance.py`
  - `tests/test_exchanges_okx.py`
  - `tests/test_utils_get_exchange.py`
  - `tests/test_utils_load_config.py`
  - `tests/test_utils_match_symbols.py`
  - `tests/test_utils_parse_timeframe.py`
  - `tests/test_trading_cli.py`

## Requirements
1. 交易所模块测试：
   - 模拟WebSocket连接
   - 测试连接建立、断开、重连逻辑
   - 测试消息接收和处理

2. 交易模块测试：
   - 模拟交易所API调用
   - 测试下单、撤单、查询等操作
   - 测试错误处理和重试逻辑

3. 工具模块测试：
   - 模拟外部依赖（如配置文件、网络请求等）
   - 测试各种边界条件和错误情况

## Acceptance Criteria
- [ ] 交易所模块测试覆盖率 ≥ 80%
- [ ] 交易模块测试覆盖率 ≥ 80%
- [ ] 工具模块测试覆盖率 ≥ 80%
- [ ] 所有现有测试通过
- [ ] 新测试代码质量良好，易于维护

## Definition of Done
- 所有测试通过
- 覆盖率达标
- 代码清晰可读
- 无冗余测试

## Technical Approach
使用 pytest + pytest-cov 进行测试和覆盖率测量。
使用 unittest.mock 模拟外部依赖。

## Out of Scope
- 性能测试
- 集成测试（需要真实交易所连接）

## Technical Notes
- 需要查看当前覆盖率报告确定具体需要补充的测试
- 需要分析现有代码结构确定模拟策略