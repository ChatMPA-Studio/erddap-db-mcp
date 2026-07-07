"""
Sync logic: downloads default datasets for configured regions.
Called by the scheduler and by the update_data tool.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from mcp_server.data_store import (
    get_local_coverage,
    register_download,
    save_to_store,
)
from tools.chlorophyll import fetch_chlorophyll
from tools.sst import fetch_sst

CONFIG_PATH = Path(__file__).parent.parent / "config.yml"

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)


async def run_sync(variable: str = "all", region: str = "all") -> dict:
    """
    Download missing data from ERDDAP for the default datasets.

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
            date_start, date_end = _get_missing_range(var, reg)

            if date_start is None:
                results.append({"variable": var, "region": reg, "status": "up_to_date"})
                continue

            try:
                if var == "chlorophyll":
                    ds = await fetch_chlorophyll(dataset_id, bbox, date_start, date_end)
                else:
                    ds = await fetch_sst(dataset_id, bbox, date_start, date_end)

                save_to_store(ds, var, reg)
                register_download(var, dataset_id, reg, date_start, date_end, str(
                    Path(__file__).parent.parent / "data" / var / reg
                ))
                results.append({
                    "variable": var,
                    "region": reg,
                    "status": "updated",
                    "date_start": date_start,
                    "date_end": date_end,
                })
            except Exception as exc:
                results.append({
                    "variable": var,
                    "region": reg,
                    "status": "error",
                    "error": str(exc),
                })

    return {"results": results, "synced_at": datetime.utcnow().isoformat()}


def _get_missing_range(variable: str, region: str) -> tuple[str | None, str | None]:
    """Determine what date range needs to be downloaded."""
    today = datetime.utcnow().date()
    records = [
        r for r in get_local_coverage(variable)
        if r["region"] == region
    ]

    if not records:
        # No data at all — download last 2 years as initial seed
        start = (today - timedelta(days=730)).isoformat()
        return start, today.isoformat()

    latest = max(r["date_end"] for r in records)
    latest_date = datetime.fromisoformat(latest).date()

    if latest_date >= today:
        return None, None

    return (latest_date + timedelta(days=1)).isoformat(), today.isoformat()
