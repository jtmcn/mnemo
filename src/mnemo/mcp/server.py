"""FastMCP server for mnemo book search.

IMPORTANT: Never use print() - corrupts STDIO transport.
Use logging to stderr only.
"""

import atexit
import logging
import math
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

# Import domain tool modules to trigger @mcp.tool registration
import mnemo.mcp.tools_books  # noqa: F401, E402
import mnemo.mcp.tools_metadata  # noqa: F401, E402
import mnemo.mcp.tools_search  # noqa: F401, E402

DEFAULT_VECTOR_IDLE_SECONDS = 300.0


def vector_idle_seconds() -> float:
    """MNEMO_VECTOR_IDLE_SECONDS: idle time before the vector worker stops; 0 disables."""
    raw = os.environ.get("MNEMO_VECTOR_IDLE_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_VECTOR_IDLE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not value >= 0.0 or math.isinf(value):
        logger.warning(
            "MNEMO_VECTOR_IDLE_SECONDS=%r is not a non-negative number; using %s",
            raw,
            DEFAULT_VECTOR_IDLE_SECONDS,
        )
        return DEFAULT_VECTOR_IDLE_SECONDS
    return value


def run() -> None:
    """Serve over STDIO, keeping Chroma in a worker process that stops when idle."""
    from mnemo.vectors import backend

    idle = vector_idle_seconds()
    if idle > 0:
        backend.configure("worker", idle)
    else:
        backend.configure("shared")
    # atexit only: cached store handles are dead after shutdown().
    atexit.register(backend.shutdown)
    mcp.run()  # STDIO transport


if __name__ == "__main__":
    run()
