"""FastMCP server for mnemo book search.

IMPORTANT: Never use print() - corrupts STDIO transport.
Use logging to stderr only.
"""

import logging
import os
import sys

from fastmcp import FastMCP

from mnemo import __version__

# Configure logging to stderr (critical for STDIO)
_level_name = os.environ.get("MNEMO_LOG_LEVEL", "INFO").upper()
_log_level = getattr(logging, _level_name, logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

mcp = FastMCP(f"mnemo v{__version__}")

# Import tools to register them (use full path to avoid circular import when running as -m)
import mnemo.mcp.tools  # noqa: F401, E402

if __name__ == "__main__":
    mcp.run()  # STDIO transport
