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

# ── Storage (S3 + DynamoDB) — Fase 1 de la migración a AWS -------------------

AWS_REGION: str          = _get("AWS_REGION", "us-west-2")
ERDDAP_S3_BUCKET: str    = _get("ERDDAP_S3_BUCKET", "erddap-mcp-data")
ERDDAP_S3_PREFIX: str    = _get("ERDDAP_S3_PREFIX", "erddap")
ERDDAP_DYNAMODB_TABLE: str = _get("ERDDAP_DYNAMODB_TABLE", "erddap-catalog")

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
    logger.info(f"  S3 bucket: s3://{ERDDAP_S3_BUCKET}/{ERDDAP_S3_PREFIX}  |  DynamoDB: {ERDDAP_DYNAMODB_TABLE}")
    logger.info(f"  Port     : {PORT}  |  Path: {MCP_BASE_PATH}")
    logger.info("=" * 60)
