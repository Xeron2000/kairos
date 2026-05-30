# Bit浪浪交易系统 Hermes Agent集成

## Goal

将pwatch仓库改造成一个完整的交易agent系统，通过Hermes Agent集成，实现Bit浪浪交易哲学的自动化执行。系统提供CLI工具和skill，让hermes agent能够自主分析市场、生成信号、执行交易。

## Requirements

### 核心需求
1. **CLI工具扩展**：pwatch扩展为包含交易执行能力的CLI工具
2. **Hermes Agent Skill**：创建模块化skill，让hermes agent了解如何使用pwatch
3. **数据输出**：pwatch输出结构化数据，hermes定时拉取
4. **LLM分离**：pwatch不做LLM调用，hermes负责所有智能判断

### 交易范围
- **品种**：只做合约（永续合约）
- **交易所**：Binance、OKX、Bybit
- **执行模式**：可选切换（信号/半自动/全自动）

### 策略实现
- **周期判断**：量化指标 + LLM推理（混合方式）
- **选币逻辑**：量化筛选候选池 + agent深度分析
- **箱体识别**：算法初步识别 + agent确认和细化
- **套利能力**：保留可选，极端行情时使用

### 风险约束
- 山寨币：33%仓位，最多5倍杠杆（全仓1倍）
- BTC/ETH：33%仓位，最多10倍杠杆（全仓3倍）
- 最多同时持有2个仓位
- 单日连续亏损3次暂停交易

### 学习机制
- 每N笔交易后回顾
- 每日/周总结
- 人工反馈通过Telegram

## Acceptance Criteria

- [ ] pwatch CLI支持所有交易相关命令
- [ ] hermes agent可以通过skill了解如何使用pwatch
- [ ] 周期判断、选币、箱体识别算法实现
- [ ] 风险约束正确实施
- [ ] 交易执行功能完整
- [ ] 输出格式适合hermes读取

## Definition of Done

- 代码通过lint和typecheck
- 单元测试覆盖核心功能
- skill文档完整
- CLI命令可用
- 集成测试通过

## Technical Approach

### 架构分离
```
pwatch (CLI工具)                    hermes agent
├── 数据获取                        ├── 读取skill
├── 技术分析算法                    ├── 调用CLI获取数据
├── 交易执行                        ├── LLM判断（周期、选币、信号）
├── 风险控制                        ├── 决定是否执行交易
└── 输出结构化数据                  └── 学习和复盘
```

### Skill模块化设计
```
skills/
├── bitlanglang-cycle/      # 市场周期判断
├── bitlanglang-scanner/    # 选币扫描
├── bitlanglang-box/        # 箱体识别
├── bitlanglang-signal/     # 交易信号
├── bitlanglang-position/   # 仓位管理
├── bitlanglang-risk/       # 风险控制
└── bitlanglang-review/     # 复盘学习
```

### CLI命令设计
```bash
# 市场分析
pwatch cycle                    # 市场周期
pwatch scan                     # 扫描标的
pwatch box-detect --symbol BTC/USDT  # 箱体检测
pwatch signal --symbol BTC/USDT      # 交易信号
pwatch sr --symbol BTC/USDT          # 支撑阻力

# 交易执行
pwatch position status          # 仓位状态
pwatch order --symbol BTC/USDT --side long --size 1000
pwatch close --symbol BTC/USDT

# 风险管理
pwatch risk status              # 风险状态
pwatch history                  # 交易历史
pwatch stats                    # 统计数据
```

## Decision (ADR-lite)

**Context**: 需要将pwatch从监控系统扩展为交易agent系统
**Decision**: 采用CLI+Skill架构，pwatch提供工具，hermes提供智能
**Consequences**: 
- pwatch保持简单，不做LLM调用
- hermes agent负责所有判断和决策
- 通过skill传递知识，通过CLI传递数据

## Out of Scope

- LLM调用和推理（由hermes负责）
- 交易所API密钥管理（环境变量）
- 部署和运维（用户负责）
- 监控告警（hermes定时拉取）

## Technical Notes

### 现有代码结构
- `src/pwatch/exchanges/` - 交易所接口（已有）
- `src/pwatch/detectors/` - 检测器（已有）
- `src/pwatch/notifications/` - 通知（已有）
- `src/pwatch/trades/` - 交易执行（新增）
- `src/pwatch/analysis/` - 技术分析（新增）
- `src/pwatch/app/trade_cli.py` - 交易CLI（新增）

### 依赖
- ccxt（已有）
- numpy（新增）
- pandas（可选，用于数据分析）

### 配置
- `~/.config/pwatch/trading.yaml` - 交易配置
- 环境变量 - 交易所API密钥
