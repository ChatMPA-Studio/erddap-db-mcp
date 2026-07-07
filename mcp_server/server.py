"""
ERDDAP MCP Server
Serves chlorophyll and SST data from NOAA CoastWatch ERDDAP.
"""

import mcp.server.stdio
from mcp.server import Server
from mcp.server.models import InitializationOptions
import mcp.types as types

from tools.data_access import (
    get_data,
    list_coverage,
    update_data,
    list_datasets,
    get_dataset_info,
)
from mcp_server.prompts import load_skills

app = Server("erddap-db-mcp")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_data",
            description=(
                "Extract chlorophyll or SST data for a bounding box and date range. "
                "Queries local store first; falls back to ERDDAP if data is missing. "
                "Args:\n"
                "  variable (str): 'chlorophyll' or 'sst'\n"
                "  bbox (list): [lon_min, lon_max, lat_min, lat_max] or region shorthand "
                "('pacific_mexico', 'gulf_mexico')\n"
                "  date_range (list): ['YYYY-MM-DD', 'YYYY-MM-DD']\n"
                "  source (str, optional): 'auto' (default), or on-demand dataset key "
                "from config (e.g. 'mur_1km', 'viirs_s3_2km')\n"
                "  sst_var (str, optional): for SST only — which variable to extract: "
                "'sst' (default), 'anom' (anomaly vs climatology), 'err' (measurement error), "
                "'ice' (sea ice concentration)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "variable": {"type": "string", "enum": ["chlorophyll", "sst"]},
                    "bbox": {
                        "oneOf": [
                            {"type": "string", "enum": ["pacific_mexico", "gulf_mexico"]},
                            {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 4,
                                "maxItems": 4,
                            },
                        ]
                    },
                    "date_range": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                    "source": {"type": "string", "default": "auto"},
                    "sst_var": {
                        "type": "string",
                        "enum": ["sst", "anom", "err", "ice"],
                        "default": "sst",
                    },
                },
                "required": ["variable", "bbox", "date_range"],
            },
        ),
        types.Tool(
            name="list_coverage",
            description=(
                "Report what data is available in the local store. "
                "Returns variables, date ranges, and regions currently downloaded. "
                "Args:\n"
                "  variable (str, optional): filter by 'chlorophyll' or 'sst'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "variable": {"type": "string", "enum": ["chlorophyll", "sst"]},
                },
            },
        ),
        types.Tool(
            name="update_data",
            description=(
                "Manually trigger a data refresh from ERDDAP for a variable and region. "
                "Downloads data up to the current date. "
                "Args:\n"
                "  variable (str): 'chlorophyll' or 'sst'\n"
                "  region (str, optional): 'pacific_mexico', 'gulf_mexico', or 'all' (default)"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "variable": {"type": "string", "enum": ["chlorophyll", "sst"]},
                    "region": {"type": "string", "default": "all"},
                },
                "required": ["variable"],
            },
        ),
        types.Tool(
            name="list_datasets",
            description=(
                "Search for available datasets on NOAA CoastWatch ERDDAP for a variable. "
                "Args:\n"
                "  variable (str): 'chlorophyll' or 'sst'\n"
                "  query (str, optional): additional search keywords"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "variable": {"type": "string", "enum": ["chlorophyll", "sst"]},
                    "query": {"type": "string"},
                },
                "required": ["variable"],
            },
        ),
        types.Tool(
            name="get_dataset_info",
            description=(
                "Get metadata for a specific ERDDAP dataset: spatial resolution, "
                "temporal coverage, and geographic bounds. "
                "Args:\n"
                "  dataset_id (str): ERDDAP dataset ID (e.g. 'erdMH1chla8day_R2022NRT')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                },
                "required": ["dataset_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    handlers = {
        "get_data": get_data,
        "list_coverage": list_coverage,
        "update_data": update_data,
        "list_datasets": list_datasets,
        "get_dataset_info": get_dataset_info,
    }
    result = await handlers[name](arguments)
    return [types.TextContent(type="text", text=result)]


@app.list_prompts()
async def list_prompts() -> list[types.Prompt]:
    return load_skills()


@app.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
    from mcp_server.prompts import get_skill
    return get_skill(name, arguments)


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="erddap-db-mcp",
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
