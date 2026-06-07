# Implement architecture baseline phase 1

## Goal

Land the first minimal implementation slice of `docs/architecture.md`: make Kairos MCP responses schema-consistent, define the new architecture configuration model, and expose scanner-first analysis entry points without adding automatic trade execution or real position management.

## What I already know

- `docs/architecture.md` is the authoritative architecture baseline.
- Kairos is a futures signal discovery and analysis system for Hermes Agent.
- Kairos must not place orders, manage live positions, or auto-size trades from account equity.
- The scanner is the primary workflow; WebSocket anomaly events are only candidate hints.
- OKX futures volume Top 30 is the default scanner universe.
- Kairos deterministic code owns candidate/setup scoring. Hermes/LLM may veto but must not promote below-threshold setups.
- Core MCP results should use a standardized envelope with `success`, `schema_version`, `timestamp`, optional `symbol`, `data`, `score`, `reasons`, `warnings`, and `errors`.
- Existing dirty worktree changes in `src/kairos/analysis/cycle.py`, `src/kairos/analysis/support_resistance.py`, `coverage.json`, and `progress.md` predate this task and must not be reverted or silently included unless they are required for this task.

## Requirements

- Standardize core MCP return envelopes.
- Define scanner, scoring, risk, storage, chart, webhook, and exchange configuration structures.
- Add `scan_market` and `analyze_symbol_setup` code skeletons or runnable MVP behavior.
- Keep scanner-first semantics:
  - default universe is OKX futures volume Top 30;
  - keep up to Top 20 lightweight candidates;
  - deep-analyze up to Top 10;
  - return candidates, qualified setups, chart specs, warnings, and errors;
  - do not push Telegram or generate charts by default.
- Implement deterministic scoring ownership in Kairos:
  - separate `candidate_score` from `setup_score`;
  - use explicit action states: `no_trade`, `watch`, `prepare`, `trade_candidate`;
  - require configured setup thresholds and RR constraints before returning `trade_candidate`.
- Implement `analyze_symbol_setup(symbol)` with symbol normalization and minimum liquidity behavior.
- Avoid fabricated neutral/default conclusions when critical data is missing; surface warnings/errors and withhold `trade_candidate` when required context is absent.
- Do not implement automatic execution, order placement, account-equity sizing, or real position management.
- Add focused tests for new schemas/config/scanner behavior.

## Acceptance Criteria

- [ ] `docs/architecture.md`, `AGENTS.md`, and relevant `.trellis/workflow.md` / `.trellis/spec/` files have been read and applied.
- [ ] This Trellis task is created, context is curated, and task status is moved to `in_progress` before code edits.
- [ ] Core MCP helper returns the standardized envelope and new/changed MCP tools use it.
- [ ] Architecture config structures exist with defaults for scanner, exchanges, scoring, risk, storage, charts, and webhook.
- [ ] `scan_market` exists as the high-level scanner MCP entry point or callable service and returns standardized envelope data.
- [ ] `analyze_symbol_setup` exists as the single-symbol high-level entry point or callable service and returns standardized envelope data.
- [ ] The implementation keeps Kairos signal-only and contains no new order execution or live position management path.
- [ ] New or changed behavior has focused tests.
- [ ] Relevant `pytest`, `ruff`, and `pyright` checks are run, or failures/availability issues are recorded.
- [ ] Work is committed with only task-relevant changes, leaving unrelated dirty files untouched.

## Definition of Done

- Trellis Phase 1 is complete: PRD exists, context is curated, and the task has been started.
- Implementation matches the first-phase architecture scope without overbuilding storage persistence or chart generation.
- Tests and quality checks either pass or have clear, honest failure notes.
- Spec-update review is performed; `.trellis/spec/` is updated only if useful new executable conventions were discovered.
- Git commit is created for this task's changes.

## Out of Scope

- Automatic trade execution.
- Real position lifecycle management.
- Telegram delivery decisions.
- Runtime config hot reload.
- Full SQLite persistence implementation beyond config/path structures unless needed by the MVP.
- Long-term review/statistics tools.
- Updating README, Hermes skills, or legacy CLI documentation unless required to keep tests passing.

## Technical Notes

- Applicable code-spec files:
  - `.trellis/spec/backend/index.md`
  - `.trellis/spec/backend/directory-structure.md`
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/backend/error-handling.md`
  - `.trellis/spec/backend/database-guidelines.md`
  - `.trellis/spec/backend/logging-guidelines.md`
  - `.trellis/spec/guides/index.md`
- Architecture reference: `docs/architecture.md`.
- Prior research reference: `.trellis/tasks/06-06-architecture-baseline/research/best-practices.md`.
