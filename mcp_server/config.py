"""
Configuration — reads environment variables at import time.
"""

import logging
import os
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ── Server -------------------------------------------------------------------

PORT: int          = int(_get("PORT", "8000"))
MCP_BASE_PATH: str = _get("MCP_BASE_PATH", "/mcp")
LOG_LEVEL: str     = _get("LOG_LEVEL", "INFO")

# ── Data directory -----------------------------------------------------------

ERDDAP_DATA_DIR: str = _get("ERDDAP_DATA_DIR", "data")

# ── Logging -----------------------------------------------------------------


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_startup_summary() -> None:
    logger = logging.getLogger("erddap_mcp.config")
    logger.info("=" * 60)
    logger.info("  ERDDAP MCP Server")
    logger.info(f"  Data dir : {ERDDAP_DATA_DIR}")
    logger.info(f"  Port     : {PORT}  |  Path: {MCP_BASE_PATH}")
    logger.info("=" * 60)
