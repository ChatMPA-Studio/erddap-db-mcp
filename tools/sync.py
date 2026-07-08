"""
Sync logic: downloads default datasets for configured regions.
Downloads year by year for resumability — if interrupted, the next run
picks up from the last successfully downloaded year.
Called by the scheduler and by the update_data tool.
"""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from mcp_server.data_store import (
    get_local_coverage,
    register_download,
    save_to_store,
)
from tools.chlorophyll import fetch_chlorophyll
from tools.sst import fetch_sst

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.yml"

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

# Full historical start dates per variable
HISTORY_START = {
    "chlorophyll": date(2003, 1, 1),   # MODIS Aqua available from 2003
    "sst": date(1981, 9, 1),           # OISST available from Sep 1981
}


async def run_sync(variable: str = "all", region: str = "all") -> dict:
    """
    Download missing data from ERDDAP for the default datasets, year by year.

    Args:
        variable: 'chlorophyll', 'sst', or 'all'
        region: region name from config or 'all'
    """
    variables = ["chlorophyll", "sst"] if variable == "all" else [variable]
    regions = list(CONFIG["regions"].keys()) if region == "all" else [region]

    results = []
    for var in variables:
        dataset_id = CONFIG["datasets"][var]["default"]
        for reg in regions:
            bbox = CONFIG["regions"][reg]["bbox"]
            year_results = await _sync_by_year(var, dataset_id, reg, bbox)
            results.extend(year_results)

    return {"results": results, "synced_at": datetime.utcnow().isoformat()}


async def _sync_by_year(
    variable: str,
    dataset_id: str,
    region: str,
    bbox: list,
) -> list[dict]:
    """Download missing years one at a time. Skips years already in the store."""
    today = date.today()
    results = []

    downloaded_years = _get_downloaded_years(variable, region)
    start_year = HISTORY_START[variable].year
    current_year = today.year

    for year in range(start_year, current_year + 1):
        if year in downloaded_years:
            logger.debug("Skipping %s %s %d — already downloaded.", variable, region, year)
            continue

        # Clip to actual availability start and today
        year_start = max(date(year, 1, 1), HISTORY_START[variable])
        year_end = min(date(year, 12, 31), today)

        if year_start > today:
            break

        logger.info("Downloading %s | %s | %d...", variable, region, year)
        try:
            if variable == "chlorophyll":
                ds = await fetch_chlorophyll(
                    dataset_id, bbox,
                    year_start.isoformat(),
                    year_end.isoformat(),
                )
            else:
                ds = await fetch_sst(
                    dataset_id, bbox,
                    year_start.isoformat(),
                    year_end.isoformat(),
                )

            save_to_store(ds, variable, region)
            zarr_path = str(Path(__file__).parent.parent / "data" / variable / region)
            register_download(
                variable, dataset_id, region,
                year_start.isoformat(), year_end.isoformat(),
                zarr_path,
            )
            results.append({
                "variable": variable,
                "region": region,
                "year": year,
                "status": "downloaded",
            })
            logger.info("OK %s | %s | %d", variable, region, year)

        except Exception as exc:
            logger.error("FAILED %s | %s | %d: %s", variable, region, year, exc)
            results.append({
                "variable": variable,
                "region": region,
                "year": year,
                "status": "error",
                "error": str(exc),
            })
            # Continue to next year rather than aborting

    if not results:
        results.append({"variable": variable, "region": region, "status": "up_to_date"})

    return results


def _get_downloaded_years(variable: str, region: str) -> set[int]:
    """Return the set of years already in the local store for this variable+region."""
    records = [
        r for r in get_local_coverage(variable)
        if r["region"] == region
    ]
    years = set()
    for r in records:
        start_year = datetime.fromisoformat(r["date_start"]).year
        end_year = datetime.fromisoformat(r["date_end"]).year
        # Mark a year as complete only if the record covers the full year
        # (or it's the current year, which is always partial)
        today_year = date.today().year
        for y in range(start_year, end_year + 1):
            if y == today_year or _is_full_year_covered(r, y):
                years.add(y)
    return years


def _is_full_year_covered(record: dict, year: int) -> bool:
    """Check if a download record covers a full calendar year."""
    start = datetime.fromisoformat(record["date_start"]).date()
    end = datetime.fromisoformat(record["date_end"]).date()
    return start <= date(year, 1, 1) and end >= date(year, 12, 31)
