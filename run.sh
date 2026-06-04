#!/usr/bin/env bash
# kairos MCP server launcher for Hermes
# Hermes calls: hermes mcp add kairos --command ~/kairos/run.sh --env KAIROS_WEBHOOK_SECRET=...
set -euo pipefail
export KAIROS_WEBHOOK_SECRET="${KAIROS_WEBHOOK_SECRET:?KAIROS_WEBHOOK_SECRET not set}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --directory "$SCRIPT_DIR" kairos-mcp
