# Directory Structure

> How backend code is organized in this project.

---

## Overview

pwatch是单仓库Python项目，采用src-layout结构。主要模块包括交易所接口、检测器、通知、交易执行、技术分析等。

---

## Directory Layout

```
src/pwatch/
├── __init__.py
├── paths.py                    # 路径配置
├── app/                        # CLI和应用入口
│   ├── __init__.py
│   ├── cli.py                  # 主CLI入口
│   ├── runner.py               # 监控运行器
│   └── trade_cli.py            # 交易CLI命令
├── core/                       # 核心功能
│   ├── __init__.py
│   ├── config_manager.py       # 配置管理
│   ├── notifier.py             # 通知器
│   └── sentry.py               # 价格哨兵
├── exchanges/                  # 交易所接口
│   ├── __init__.py
│   ├── base.py                 # 基础交易所类
│   ├── binance.py              # Binance实现
│   ├── bybit.py                # Bybit实现
│   └── okx.py                  # OKX实现
├── detectors/                  # 检测器
│   ├── __init__.py
│   ├── base.py                 # 基础检测器
│   ├── price_velocity.py       # 价格速度检测
│   └── volume_spike.py         # 成交量异常检测
├── notifications/              # 通知系统
│   ├── __init__.py
│   ├── telegram.py             # Telegram通知
│   └── telegram_bot_service.py # Telegram Bot服务
├── trades/                     # 交易执行（新增）
│   ├── __init__.py
│   ├── executor.py             # 交易执行器
│   ├── position.py             # 仓位管理
│   └── risk.py                 # 风险控制
├── analysis/                   # 技术分析（新增）
│   ├── __init__.py
│   ├── box_pattern.py          # 箱体识别
│   ├── cycle.py                # 市场周期判断
│   └── support_resistance.py   # 支撑阻力位
├── arbitrage/                  # 套利模块（新增）
│   ├── __init__.py
│   ├── funding_monitor.py      # 资金费率监控
│   └── funding_arb.py          # 资金费率套利
└── utils/                      # 工具函数
    ├── __init__.py
    ├── cache_manager.py        # 缓存管理
    ├── config_io.py            # 配置读写
    ├── config_validator.py     # 配置验证
    ├── default_symbols.py      # 默认交易对
    ├── error_handler.py        # 错误处理
    ├── get_exchange.py         # 获取交易所
    ├── load_config.py          # 加载配置
    ├── load_symbols_from_file.py
    ├── match_symbols.py        # 匹配交易对
    ├── monitor_top_movers.py   # 监控涨幅榜
    ├── parse_timeframe.py      # 解析时间周期
    ├── performance_monitor.py  # 性能监控
    ├── send_notifications.py   # 发送通知
    ├── setup_logging.py        # 日志配置
    ├── supported_markets.py    # 支持的市场
    └── top_volume_symbols.py   # 成交量排名
```

---

## Module Organization

### 新增模块规则
1. **trades/**：交易执行相关，包括下单、平仓、仓位管理
2. **analysis/**：技术分析算法，如箱体识别、周期判断
3. **arbitrage/**：套利策略，如资金费率套利

### 命名规范
- 文件名：小写字母+下划线（snake_case）
- 类名：大驼峰（PascalCase）
- 函数名：小写字母+下划线
- 常量：大写字母+下划线

---

## Examples

**良好示例**：
- `src/pwatch/exchanges/base.py` - 基础类定义清晰
- `src/pwatch/detectors/price_velocity.py` - 检测器模块独立

**避免**：
- 单个文件超过500行
- 循环导入
- 硬编码配置
