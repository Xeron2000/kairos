# Agent Instructions

> Scope: This file is the entrypoint. It keeps only always-on rules; task details live in docs/.

## Project Overview

pwatch is a cryptocurrency futures price monitor & trading system with Hermes Agent integration.

## Core Principles

- **Research first**: Unfamiliar tech/architecture → research before coding
- **Tool priority**: MCP ace-tool for code search, built-in tools for web search
- **Reasoning**: Complex → deep thinking, simple → direct response
- **Code quality**: Handle errors, add type annotations, document large files

## Read-On-Demand Index

| Task type | Read first | Trigger |
| --- | --- | --- |
| Research & investigation | `docs/research.md` | Unfamiliar tech, architecture decisions, complex integration |
| Tool usage & search | `docs/tool-priority.md` | Code search, web search, text search, Python tools |
| Problem solving | `docs/reasoning.md` | Complex problems, stuck situations, first principles |
| Code standards | `docs/code-quality.md` | Error handling, type annotations, documentation |

## Trading System

### Architecture
- **pwatch (CLI)**: Data fetching, technical analysis, trade execution, risk control
- **hermes agent**: Reads skills, calls CLI, LLM judgment, learning & review

### Skills
- `bitlanglang-cycle` - Market cycle analysis (春夏秋冬 theory)
- `bitlanglang-scanner` - Symbol scanning (quantitative + agent analysis)
- `bitlanglang-box` - Box pattern detection (algorithm + agent confirmation)
- `bitlanglang-signal` - Trading signals (breakout/pullback/reversal)
- `bitlanglang-position` - Position management (fixed sizing, leverage limits)
- `bitlanglang-risk` - Risk control (stop-loss, consecutive loss limits)
- `bitlanglang-review` - Trade review (history, statistics, learning)

### CLI Commands
```bash
pwatch cycle                    # Market cycle phase
pwatch scan                     # Scan for symbols
pwatch box-detect --symbol BTC/USDT  # Box pattern detection
pwatch signal --symbol BTC/USDT      # Trading signals
pwatch sr --symbol BTC/USDT          # Support/resistance levels
pwatch position status          # Current positions
pwatch risk status              # Risk status
pwatch history                  # Trade history
pwatch stats                    # Trading statistics
```

### Risk Constraints
- Altcoins: 33% position, max 5x leverage
- BTC/ETH: 33% position, max 10x leverage
- Max 2 simultaneous positions
- Pause after 3 consecutive daily losses

## Always-On Rules

- **Language**: Default to Chinese for user communication
- **Evidence**: Verify high-risk claims before citing
- **Efficiency**: Batch operations, avoid redundant reads

## Priority

1. User's current explicit instruction.
2. Nearest project instruction file.
3. This file.
4. Routed docs details.

<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
