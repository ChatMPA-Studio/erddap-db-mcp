"""ERDDAP MCP Server — FastMCP entry point.

Supports two transports:
- stdio  (default, for Claude Desktop)
- streamable-http (when PORT env var is set, for droplet deployment)
"""

import logging
from contextlib import asynccontextmanager
from typing import Union

from fastmcp import FastMCP

from tools.data_access import (
    get_data as _get_data,
    list_coverage as _list_coverage,
    update_data as _update_data,
    list_datasets as _list_datasets,
    get_dataset_info as _get_dataset_info,
)
from mcp_server.prompts import discover_prompts
from scheduler.sync_scheduler import start_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP):
    scheduler = start_scheduler()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


mcp = FastMCP("erddap-db-mcp", lifespan=lifespan)


@mcp.tool()
async def get_data(
    variable: str,
    bbox: Union[str, list],
    date_range: list[str],
    source: str = "auto",
    sst_var: str = "sst",
) -> str:
    """Extract chlorophyll or SST data for a bounding box and date range.

    variable: 'chlorophyll' or 'sst'
    bbox: [lon_min, lon_max, lat_min, lat_max] or 'pacific_mexico'/'gulf_mexico'
    date_range: ['YYYY-MM-DD', 'YYYY-MM-DD']
    source: 'auto' (default) or on-demand dataset key (e.g. 'mur_1km')
    sst_var: 'sst' (default), 'anom', 'err', or 'ice'
    """
    return await _get_data({
        "variable": variable,
        "bbox": bbox,
        "date_range": date_range,
        "source": source,
        "sst_var": sst_var,
    })


@mcp.tool()
async def list_coverage(variable: str = None) -> str:
    """Report what data is available in the local store.

    variable: optional filter — 'chlorophyll' or 'sst'
    """
    args = {}
    if variable:
        args["variable"] = variable
    return await _list_coverage(args)


@mcp.tool()
async def update_data(variable: str, region: str = "all") -> str:
    """Manually trigger a data refresh from ERDDAP for a variable and region.

    variable: 'chlorophyll' or 'sst'
    region: 'pacific_mexico', 'gulf_mexico', or 'all' (default)
    """
    return await _update_data({"variable": variable, "region": region})


@mcp.tool()
async def list_datasets(variable: str, query: str = None) -> str:
    """Search for available datasets on NOAA CoastWatch ERDDAP.

    variable: 'chlorophyll' or 'sst'
    query: optional additional search keywords
    """
    args = {"variable": variable}
    if query:
        args["query"] = query
    return await _list_datasets(args)


@mcp.tool()
async def get_dataset_info(dataset_id: str) -> str:
    """Get metadata for a specific ERDDAP dataset.

    dataset_id: ERDDAP dataset ID (e.g. 'erdMH1chla8day_R202SQ')
    """
    return await _get_dataset_info({"dataset_id": dataset_id})


discover_prompts(mcp)
