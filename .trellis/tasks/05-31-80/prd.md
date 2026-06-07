# 提升测试覆盖率到80%以上

## Goal

把测试工作从旧的“泛泛提升三个模块覆盖率”收敛为：用 mock-based pytest 补齐当前真实代码中最容易导致运行链路失效的回归测试，并保证关键后端模块维持 ≥80% 覆盖率。当前仓库整体覆盖率已达 88%，但 `src/kairos/mcp_server.py` 仍只有 57%，且用户审查指出的若干 P0/P1 风险需要通过测试固化。

## What I already know

- 项目是加密货币期货价格监控和 Hermes Agent / MCP trading signal harness。
- 当前任务目录：`.trellis/tasks/05-31-80/`。
- 现有测试数量已经很多，当前 `uv run pytest --cov=src/kairos --cov-report=term-missing` 结果：659 passed, 1 skipped, total coverage 88%。
- 当前模块覆盖率快照（2026-06-06 本地运行）：
  - `src/kairos/exchanges/base.py`: 83%
  - `src/kairos/exchanges/binance.py`: 85%
  - `src/kairos/exchanges/bybit.py`: 86%
  - `src/kairos/exchanges/okx.py`: 94%
  - `src/kairos/data/data_manager.py`: 83%
  - `src/kairos/scanner.py`: 85%
  - `src/kairos/utils/get_exchange.py`: 100%
  - `src/kairos/utils/blacklist.py`: 92%
  - `src/kairos/utils/cache_manager.py`: 97%
  - `src/kairos/utils/error_handler.py`: 92%
  - `src/kairos/utils/performance_monitor.py`: 91%
  - `src/kairos/config.py`: 100%
  - `src/kairos/webhook.py`: 100%
  - `src/kairos/mcp_server.py`: 57%（当前主要缺口）
- 用户审查结论中部分风险已被当前源码修复或演进：
  - `src/kairos/data/data_manager.py` 已存在，已有基础生命周期测试。
  - `src/kairos/config.py` 已使用 `deepcopy(_DEFAULT_CONFIG)`，覆盖率已 100%。
- 用户审查结论中仍可从当前源码验证的风险：
  - `pyproject.toml` 仍把 `mcp` 放在 optional extra `hermes`，但 `kairos-mcp = "kairos.mcp_server:main"` 且 `run.sh` 使用 `uv run --directory "$SCRIPT_DIR" kairos-mcp`，存在默认安装 / launcher 依赖不一致风险。
  - `src/kairos/mcp_server.py::scan_symbols` 仍只真正应用 `min_volume`，没有真正过滤 `min_oi` / `min_age` / `max_volatility`，并且只扫描 `usdt_symbols[:100]`。
  - `src/kairos/webhook.py::SignalEvent.to_payload()` 仍未输出 `change_pct` 和 `severity`，虽然字段存在。
  - `src/kairos/mcp_server.py` 多处 helper / tool 分支未覆盖，是当前 80% 目标的最大缺口。

## Open Questions

- MVP 范围已确认：完整实现并详尽测试，目标是严格把 `mcp_server.py` 拉到 ≥80%，同时固化用户审查中的 P0/P1 回归点。

## Requirements (evolving)

1. 保留原始测试目标作为质量门槛：
   - 交易所 / data manager / scanner / utils 等关键后端模块不得低于 80%。
   - 新测试必须 mock 外部依赖，不访问真实交易所 / webhook / 网络。
2. 补齐当前真实缺口：
   - `mcp_server.py` 的 MCP tool / helper / error branch 应增加单元测试，优先覆盖 `scan_symbols`、entrypoint、异常分支和 signal 工具分支。
   - `scan_symbols` 必须有回归测试证明过滤参数是否真正生效；若实现缺失，则测试应驱动修复。
   - `SignalEvent.to_payload()` 必须有回归测试证明 `severity` 和 `change_pct` 被发送；若实现缺失，则测试应驱动修复。
   - MCP 入口依赖安装 / launcher 行为需要至少有导入或脚本级回归测试，避免 `kairos-mcp` 在默认路径下启动失败。
3. 测试风格：
   - 使用 `pytest`、`pytest-cov`、`unittest.mock` / `pytest-mock`。
   - 禁止 live API / integration 测试进入默认单测路径。
   - 优先添加行为测试和回归测试，避免为覆盖率而写无意义断言。
4. 如实现代码必须为测试通过而修复，改动应保持最小：
   - `scan_symbols`：真实应用过滤参数或显式返回 unsupported warning，不能假装过滤。
   - `webhook`：payload 补齐已有 dataclass 字段，并保持签名测试稳定。
   - `run.sh` / dependency path：保持 README / pyproject / launcher 一致。

## Acceptance Criteria

- [ ] `uv run pytest` 全部通过。
- [ ] `uv run pytest --cov=src/kairos --cov-report=term-missing` 全部通过，整体覆盖率保持 ≥80%。
- [ ] `src/kairos/exchanges/*`、`src/kairos/data/data_manager.py`、`src/kairos/scanner.py`、`src/kairos/utils/*` 等当前已达标模块不回退到 80% 以下。
- [ ] `src/kairos/mcp_server.py` 覆盖率达到 ≥80%。
- [ ] 新增测试覆盖 `scan_symbols` 对 `min_volume`、`min_oi`、`max_volatility`、unsupported `min_age` 行为的约束。
- [ ] 新增测试覆盖 `SignalEvent.to_payload()` 包含 `severity` 和 `change_pct`，且 webhook 签名使用 canonical JSON 保持稳定。
- [ ] 新增测试或验证覆盖 `kairos-mcp` entrypoint / launcher dependency path，避免缺 `mcp` 依赖时静默失败。
- [ ] 默认测试不访问真实交易所、不发送真实 webhook、不依赖外部网络。

## Definition of Done

- 所有默认测试通过。
- 覆盖率门槛达标且无关键模块回退。
- 新测试清晰可读、mock 边界明确、无冗余覆盖率填充。
- 若修复生产代码，改动最小且有对应回归测试。
- 如发现可复用的测试约定或架构约束，更新 `.trellis/spec/`。

## Technical Approach

使用 pytest + pytest-cov 做覆盖率测量；使用 mock/stub 交易所对象、ticker/market 数据、HTTP client、环境变量和 launcher subprocess/import 行为。优先以当前真实覆盖率缺口为导向：`mcp_server.py` 和用户审查中的 P0/P1 运行链路风险优先，其次再补交易所 / data manager / utils 的边界分支。

## Decision (ADR-lite)

**Context**: 原始 PRD 基于旧覆盖率和旧文件结构；当前仓库已演进，整体覆盖率已经 88%，多数原始目标模块已 ≥80%，但 `mcp_server.py` 仍明显低覆盖，且审查指出的 P0/P1 风险更适合作为高价值测试目标。

**Decision**: 用户确认使用工作流完整实现并详尽测试保证覆盖率。本任务采用严格范围：`mcp_server.py` 必须达到 ≥80%，同时完成 P0/P1 回归点（`scan_symbols` filters、webhook payload/signature、MCP launcher/dependency path）的最小实现修复和测试固化。

**Consequences**: 需要覆盖较多 MCP tool/helper/error 分支并可能进行小范围生产代码修复；交付标准更强，但必须避免借覆盖率重构过大范围或引入 live API 依赖。

## Out of Scope

- 性能测试。
- 真实交易所集成测试 / live API 测试。
- 真实 webhook 发送。
- 完整生产化改造（Docker、systemd、storage、backtest、paper trading）除非为测试通过需要最小修复。
- 大规模重构 scanner / signal scoring / market model；本任务只允许最小行为修复和回归测试。

## Technical Notes

- 已读取：`.pi/skills/trellis-brainstorm/SKILL.md`。
- 已读取：`.trellis/tasks/05-31-80/prd.md`。
- 已读取：`pyproject.toml`、`.coveragerc`、`run.sh`。
- 已读取：`src/kairos/mcp_server.py`、`src/kairos/data/data_manager.py`、`src/kairos/config.py`、`src/kairos/webhook.py`。
- 已读取部分现有测试：`tests/test_mcp_server.py`、`tests/test_data_manager.py`。
- 已运行覆盖率命令：`COVERAGE_FILE=/tmp/kairos-task80-coverage uv run pytest -q --cov=src/kairos --cov-report=term-missing --cov-report= --disable-warnings`。
- 最终验证（2026-06-07）：`uv run pytest` → 680 passed, 1 skipped, 3 warnings。
- 最终验证（2026-06-07）：`COVERAGE_FILE=/tmp/kairos-task80-coverage-final uv run pytest -q --cov=src/kairos --cov-report=term-missing --cov-report= --disable-warnings` → 680 passed, 1 skipped, total coverage 92%，`src/kairos/mcp_server.py` 95%。
- 最终验证（2026-06-07）：`uv run ruff check src/kairos/mcp_server.py src/kairos/webhook.py tests/test_mcp_server.py tests/test_mcp_server_regression.py tests/test_webhook.py` → passed。
- 尝试验证：`uv run pyright src/kairos/mcp_server.py tests/test_mcp_server_regression.py`，当前环境未安装 `pyright` 可执行文件（spawn failed），未产生类型诊断。
- 当前 `.coveragerc` 排除 `src/kairos/mcp/*` 子目录，但不排除 `src/kairos/mcp_server.py`。
- Phase 1.3 前置要求：在 `task.py start` 前必须 curate `.trellis/tasks/05-31-80/implement.jsonl` 和 `check.jsonl`，当前仍只有 `_example` seed row。
