"""Entry point for running MCP server as a module.

Usage: python -m mnemo.mcp
"""

from mnemo.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
