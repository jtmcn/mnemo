"""MCP server for Claude integration.

Exposes book search functionality via Model Context Protocol.
Run with: python -m mnemo.mcp.server
"""

from typing import Any


def __getattr__(name: str) -> Any:
    """Lazy import to avoid circular import when running as -m."""
    if name == "mcp":
        from mnemo.mcp.server import mcp

        return mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["mcp"]
