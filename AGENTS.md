# Agent Instructions

> Scope: This file is the entrypoint. It keeps only always-on rules; task details live in docs/.

## Project Overview

kairos is a human-controlled cryptocurrency futures alert system.

It scans futures markets, detects hard-data anomalies, scores deterministic setup candidates, and pushes Telegram alerts. It does not use LLMs and does not place orders.

## Core Principles

- **Research first**: Unfamiliar tech/architecture → research before coding
- **Tool priority**: use fast code search first, built-in tools for web search
- **Reasoning**: Complex → deep thinking, simple → direct response
- **Code quality**: Handle errors, add type annotations, document large files

## Read-On-Demand Index

| Task type | Read first | Trigger |
| --- | --- | --- |
| Architecture changes | `docs/architecture.md` | Runtime boundary, alert delivery, risk output |
| Strategy changes | `docs/trading-system.md` | Trading philosophy, setup logic, risk discipline |
| Config changes | `config/config.yaml.example` | Detector thresholds, scanner limits, Telegram settings |

## Trading System Boundary

### Architecture

- **kairos-watch**: realtime WebSocket anomaly watcher -> Telegram
- **kairos-alert**: one-shot deterministic scanner summary -> Telegram
- **human**: final chart review, trade selection, sizing, entries, exits

### CLI Commands
```bash
uv run kairos-watch             # Realtime hard-data Telegram alerts
uv run kairos-alert             # One-shot scanner candidate Telegram alert
uv run kairos-alert --dry-run   # Preview scanner alert text
uv run kairos-backtest --help   # Backtest utilities
```

### Risk Constraints
- Altcoins: 33% position, max 5x leverage
- BTC/ETH: 33% position, max 10x leverage
- Scanner risk output is a bound, not a trade instruction
- No automatic order placement

## Always-On Rules

- **Language**: Default to Chinese for user communication
- **Evidence**: Verify high-risk claims before citing
- **Efficiency**: Batch operations, avoid redundant reads
- **Commit messages**: Conventional Commits — `type(scope): description`, e.g. `feat(scanner): add volume confirmation gate`. Types: feat/fix/refactor/docs/test/chore. Scope is the module name (scanner, base, blacklist, etc). Keep under 72 chars. If you need more detail, use the body (blank line after subject).

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
