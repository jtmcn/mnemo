"""MCP server for Claude integration.

Exposes book search functionality via Model Context Protocol.
Run with: python -m mnemo.mcp.server
"""


def __getattr__(name: str):
    """Lazy import to avoid circular import when running as -m."""
    if name == "mcp":
        from mnemo.mcp.server import mcp

        return mcp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["mcp"]
