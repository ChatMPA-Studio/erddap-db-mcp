"""
Configuration — reads environment variables at import time.
"""

import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ── config.yml (datasets, regiones, servidor de ERDDAP) ----------------------
# Un solo loader compartido — antes tools/data_access.py y tools/sync.py (y,
# separado, tools/sst.py/chlorophyll.py/pp.py con la URL de ERDDAP hardcodeada
# 3 veces en vez de leerla de acá) cada uno abría este mismo archivo por su
# cuenta con el mismo boilerplate.

CONFIG_YML_PATH = Path(__file__).parent.parent / "config.yml"

with open(CONFIG_YML_PATH) as _f:
    CONFIG: dict = yaml.safe_load(_f)


# ── Server -------------------------------------------------------------------

PORT: int          = int(_get("PORT", "8000"))
MCP_BASE_PATH: str = _get("MCP_BASE_PATH", "/mcp")
LOG_LEVEL: str     = _get("LOG_LEVEL", "INFO")

# ── Storage (S3 + DynamoDB) — Fase 1 de la migración a AWS -------------------

AWS_REGION: str          = _get("AWS_REGION", "us-west-2")
ERDDAP_S3_BUCKET: str    = _get("ERDDAP_S3_BUCKET", "erddap-mcp-data")
ERDDAP_S3_PREFIX: str    = _get("ERDDAP_S3_PREFIX", "erddap")
ERDDAP_DYNAMODB_TABLE: str = _get("ERDDAP_DYNAMODB_TABLE", "erddap-catalog")

# ── Autenticación por API-key — tabla compartida entre los 3 MCP de ChatMPA --
# (ltem/conapesca/erddap; la administra el panel admin del orchestrator, esta
# app solo lee — ver mcp_server/auth.py)

AUTH_DYNAMODB_TABLE: str = _get("AUTH_DYNAMODB_TABLE", "chatmpa-investigator-keys")

# Interruptor para los primeros deploys de prueba en ECS: con "false" el
# servidor no valida el Bearer contra la tabla de auth y el único control de
# acceso es el header X-MCP-Api-Key del listener rule del ALB (mismo esquema
# que ltem/conapesca). Default "true" -- apagarlo tiene que ser explícito.
AUTH_ENABLED: bool = _get("ERDDAP_AUTH_ENABLED", "true").lower() not in ("0", "false", "no", "off")

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
    if AUTH_ENABLED:
        logger.info(f"  Auth table (compartida): {AUTH_DYNAMODB_TABLE}")
    else:
        logger.warning("  Auth DESACTIVADO (ERDDAP_AUTH_ENABLED=false) -- solo protege el ALB")
    logger.info(f"  Port     : {PORT}  |  Path: {MCP_BASE_PATH}")
    logger.info("=" * 60)
