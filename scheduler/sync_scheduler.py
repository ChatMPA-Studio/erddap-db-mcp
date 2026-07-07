"""
APScheduler-based sync scheduler.
Runs sync every N days as configured in config.yml.
"""

import asyncio
import logging
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from tools.sync import run_sync

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.yml"

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

INTERVAL_DAYS = CONFIG["sync"]["interval_days"]


async def scheduled_sync():
    logger.info("Starting scheduled sync...")
    result = await run_sync(variable="all", region="all")
    logger.info("Sync completed: %s", result)


def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_sync,
        trigger=IntervalTrigger(days=INTERVAL_DAYS),
        id="erddap_sync",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started — sync every %d days.", INTERVAL_DAYS)
    return scheduler
