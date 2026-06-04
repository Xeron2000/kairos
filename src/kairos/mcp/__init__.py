"""MCP servers for kairos trading system.

Provides external tool capabilities for hermes-agent via MCP protocol.

Servers:
    coinglass_server: Coinglass RSI heatmap tools for hot coin discovery.
    chart_server: mplfinance chart generation with trading annotations.
"""

from kairos.mcp import chart_server, coinglass_server  # noqa: F401

__all__ = ["coinglass_server", "chart_server"]
