"""Entry point for running MCP server as a module.

Usage: python -m mnemo.mcp
"""

# Import tools to ensure they're registered
import mnemo.mcp.tools  # noqa: F401
from mnemo.mcp.server import mcp

if __name__ == "__main__":
    mcp.run()
