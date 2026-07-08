"""
Initial historical data sync. Logs progress to sync.log.
Run once to populate the local Zarr store.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("sync.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

from mcp_server.data_store import init_db
from tools.sync import run_sync


async def main():
    init_db()
    logging.info("=== Starting full historical sync ===")
    result = await run_sync(variable="all", region="all")
    for r in result["results"]:
        logging.info("%s", r)
    logging.info("=== Sync finished at %s ===", result["synced_at"])


if __name__ == "__main__":
    asyncio.run(main())
