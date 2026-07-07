"""
Main tool dispatcher. Implements cache-first logic:
1. Check local Zarr store
2. If missing, fetch from ERDDAP and cache
3. Return JSON with data + metadata
"""

import json
from pathlib import Path

import yaml

from mcp_server.data_store import (
    get_cache_path,
    get_local_coverage,
    init_db,
    load_local,
    register_cache,
)
from tools.chlorophyll import fetch_chlorophyll
from tools.sst import fetch_sst

CONFIG_PATH = Path(__file__).parent.parent / "config.yml"

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

init_db()


def _resolve_bbox(bbox) -> list[float]:
    if isinstance(bbox, str):
        region = CONFIG["regions"].get(bbox)
        if not region:
            raise ValueError(f"Unknown region shorthand: '{bbox}'. Use 'pacific_mexico' or 'gulf_mexico'.")
        return region["bbox"]
    return bbox


async def get_data(args: dict) -> str:
    variable = args["variable"]
    bbox = _resolve_bbox(args["bbox"])
    date_range = args["date_range"]
    source = args.get("source", "auto")
    sst_var = args.get("sst_var", "sst")

    date_start, date_end = date_range[0], date_range[1]

    if source == "auto":
        ds = load_local(variable, _bbox_to_region_key(bbox), date_start, date_end)
        if ds is not None:
            return _ds_to_json(ds, variable, source="local", sst_var=sst_var)

    dataset_id = _resolve_dataset_id(variable, source)

    cached = get_cache_path(dataset_id, bbox, date_start, date_end)
    if cached:
        import xarray as xr
        ds = xr.open_zarr(cached)
        return _ds_to_json(ds, variable, source="cache", sst_var=sst_var)

    if variable == "chlorophyll":
        ds = await fetch_chlorophyll(dataset_id, bbox, date_start, date_end)
    else:
        ds = await fetch_sst(dataset_id, bbox, date_start, date_end, sst_var=sst_var)

    if source != "auto":
        from mcp_server.data_store import DATA_DIR
        cache_path = DATA_DIR / "cache" / f"{dataset_id}_{date_start}_{date_end}"
        ds.to_zarr(cache_path, mode="w")
        register_cache(dataset_id, bbox, date_start, date_end, str(cache_path))

    return _ds_to_json(ds, variable, source="erddap", sst_var=sst_var)


async def list_coverage(args: dict) -> str:
    variable = args.get("variable")
    records = get_local_coverage(variable)
    return json.dumps({"data": records, "meta": {"count": len(records)}}, indent=2)


async def update_data(args: dict) -> str:
    from tools.sync import run_sync
    variable = args["variable"]
    region = args.get("region", "all")
    result = await run_sync(variable=variable, region=region)
    return json.dumps(result, indent=2)


async def list_datasets(args: dict) -> str:
    import httpx
    variable = args["variable"]
    query_extra = args.get("query", "")
    keyword = f"{variable} {query_extra}".strip()
    server = CONFIG["erddap"]["server"]
    url = f"{server}/search/index.json?searchFor={keyword.replace(' ', '+')}&page=1&itemsPerPage=20"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    rows = raw.get("table", {}).get("rows", [])
    cols = raw.get("table", {}).get("columnNames", [])
    datasets = [dict(zip(cols, row)) for row in rows]
    return json.dumps({"data": datasets, "meta": {"count": len(datasets)}}, indent=2)


async def get_dataset_info(args: dict) -> str:
    import httpx
    dataset_id = args["dataset_id"]
    server = CONFIG["erddap"]["server"]
    url = f"{server}/info/{dataset_id}/index.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    rows = raw.get("table", {}).get("rows", [])
    cols = raw.get("table", {}).get("columnNames", [])
    info = [dict(zip(cols, row)) for row in rows]
    return json.dumps({"data": info, "meta": {"dataset_id": dataset_id}}, indent=2)


# --- helpers ---

def _resolve_dataset_id(variable: str, source: str) -> str:
    if source == "auto":
        return CONFIG["datasets"][variable]["default"]
    on_demand = CONFIG["datasets"][variable].get("on_demand", {})
    if source not in on_demand:
        raise ValueError(f"Unknown source '{source}' for {variable}. Available: {list(on_demand.keys())}")
    return on_demand[source]


def _bbox_to_region_key(bbox: list) -> str:
    for name, cfg in CONFIG["regions"].items():
        if cfg["bbox"] == bbox:
            return name
    return f"custom_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}"


def _ds_to_json(ds, variable: str, source: str, sst_var: str = "sst") -> str:
    import numpy as np
    data_var = next(iter(ds.data_vars)) if variable == "chlorophyll" else sst_var
    arr = ds[data_var].values
    return json.dumps({
        "data": {
            "values": np.where(np.isnan(arr), None, arr).tolist(),
            "times": [str(t)[:10] for t in ds.time.values],
            "lat": ds.latitude.values.tolist() if "latitude" in ds.coords else [],
            "lon": ds.longitude.values.tolist() if "longitude" in ds.coords else [],
        },
        "meta": {
            "variable": variable,
            "source": source,
            "shape": list(arr.shape),
        },
    })
