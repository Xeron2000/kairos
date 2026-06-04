# Directory Structure

> How backend code is organized in this project.

---

## Overview

kairos是MCP服务器项目，通过anyio异步运行时驱动。主要模块包括交易所WebSocket连接、异常检测器、技术分析、Webhook信号推送。

**入口**：`uv run kairos-mcp` → `mcp_server.py:main()` → DataManager bootstrap → FastMCP stdio。

---

## Directory Layout

```
src/kairos/
├── __init__.py
├── config.py                  # YAML配置加载
├── mcp_server.py              # MCP服务器主入口（7个工具）
├── paths.py                   # XDG路径配置
├── webhook.py                 # Hermes Webhook客户端
├── analysis/                  # 技术分析
│   ├── __init__.py
│   ├── box_pattern.py         # 箱体识别算法
│   ├── cycle.py               # 春夏秋冬周期判断
│   └── support_resistance.py  # 支撑阻力位
├── data/                      # 数据管理
│   ├── __init__.py
│   └── data_manager.py        # WS编排 + 探测器 + Webhook分发
├── detectors/                 # 异常检测器
│   ├── __init__.py
│   ├── base.py                # 基础检测器 + AnomalyEvent
│   ├── price_velocity.py      # 价格速度检测
│   └── volume_spike.py        # 成交量异常检测
├── exchanges/                 # 交易所接口
│   ├── __init__.py
│   ├── base.py                # 基础交易所类（CCXT封装）
│   ├── binance.py             # Binance WS实现
│   ├── bybit.py               # Bybit WS实现
│   └── okx.py                 # OKX WS实现
├── mcp/                       # MCP子服务器（独立进程）
│   ├── __init__.py
│   ├── analysis_server.py     # 分析服务
│   ├── chart_server.py        # 图表生成服务
│   └── coinglass_server.py    # Coinglass RSI热力图
└── utils/                     # 工具模块
    ├── __init__.py
    ├── cache_manager.py        # 缓存管理
    ├── error_handler.py        # 错误处理 + 断路器 + 重试
    ├── get_exchange.py         # 交易所工厂函数
    └── performance_monitor.py  # 性能监控
```

---

## Data Flow

```
OKX/Binance/Bybit WS feeds
    │
    ▼
DataManager (WebSocket threads)
    │
    ▼
PriceVelocityDetector · VolumeSpikeDetector (per-exchange)
    │  AnomalyEvent callback
    ▼
DataManager._on_anomaly_event (5s dedup + webhook send)
    │
    ▼
Hermes Webhook → LLM filter → Telegram
    │
    ▼
Hermes skills call MCP tools (get_market_cycle, detect_box_pattern, etc.)
```

---

## Removed Modules

以下模块已删除（转为纯MCP架构，无CLI/交易/Telegram通知）：

- `app/` — CLI入口、监控运行器
- `core/` — 配置管理、通知器、价格哨兵
- `notifications/` — Telegram通知
- `trades/` — 交易执行
- `arbitrage/` — 套利策略
- `utils/send_notifications.py` — 通知分发
- `utils/config_validator.py` — 配置验证器
- `utils/default_symbols.py` — 默认交易对

---

## Naming Conventions

- 文件名：`snake_case.py`
- 类名：`PascalCase`
- 函数名：`snake_case`
- 私有属性：`_leading_underscore`
