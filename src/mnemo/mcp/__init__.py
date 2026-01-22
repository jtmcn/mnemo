"""MCP server for Claude integration.

Exposes book search functionality via Model Context Protocol.
Run with: python -m mnemo.mcp.server
"""

from mnemo.mcp.server import mcp

__all__ = ["mcp"]
