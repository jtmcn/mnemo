"""FastMCP server for mnemo book search.

IMPORTANT: Never use print() - corrupts STDIO transport.
Use logging to stderr only.
"""

import logging
import sys

from fastmcp import FastMCP

# Configure logging to stderr (critical for STDIO)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

mcp = FastMCP("mnemo")

# Import tools to register them
from mnemo.mcp import tools  # noqa: F401, E402

if __name__ == "__main__":
    mcp.run()  # STDIO transport
