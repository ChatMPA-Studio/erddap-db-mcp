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
from mcp_server.security import validate_get_data_args
from tools.chlorophyll import fetch_chlorophyll
from tools.pp import fetch_pp
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
    validate_get_data_args(args)
    variable = args["variable"]
    bbox = _resolve_bbox(args["bbox"])
    date_range = args["date_range"]
    source = args.get("source", "auto")
    sst_var = args.get("sst_var", "sst")
    sst_vars = args.get("sst_vars", None)
    aggregate_spatial = bool(args.get("aggregate_spatial", False))

    date_start, date_end = date_range[0], date_range[1]

    if source == "auto":
        region_key, exact_match = _bbox_to_region_key(bbox)
        ds = load_local(variable, region_key, date_start, date_end)
        if ds is not None:
            if not exact_match:
                ds = _clip_to_bbox(ds, bbox)
            return _ds_to_json(ds, variable, source="local", sst_var=sst_var,
                               sst_vars=sst_vars, aggregate_spatial=aggregate_spatial)

    dataset_id = _resolve_dataset_id(variable, source)

    cached = get_cache_path(dataset_id, bbox, date_start, date_end)
    if cached:
        import xarray as xr
        ds = xr.open_zarr(cached)
        return _ds_to_json(ds, variable, source="cache", sst_var=sst_var,
                           sst_vars=sst_vars, aggregate_spatial=aggregate_spatial)

    if variable == "chlorophyll":
        ds = await fetch_chlorophyll(dataset_id, bbox, date_start, date_end)
    elif variable == "primary_productivity":
        ds = await fetch_pp(dataset_id, bbox, date_start, date_end)
    else:
        ds = await fetch_sst(dataset_id, bbox, date_start, date_end, sst_var=sst_var)

    if source != "auto":
        from mcp_server.data_store import DATA_DIR
        cache_path = DATA_DIR / "cache" / f"{dataset_id}_{date_start}_{date_end}"
        ds.to_zarr(cache_path, mode="w")
        register_cache(dataset_id, bbox, date_start, date_end, str(cache_path))

    return _ds_to_json(ds, variable, source="erddap", sst_var=sst_var,
                       sst_vars=sst_vars, aggregate_spatial=aggregate_spatial)


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
    if source in ("auto", "erddap"):
        return CONFIG["datasets"][variable]["default"]
    on_demand = CONFIG["datasets"][variable].get("on_demand", {})
    if source not in on_demand:
        raise ValueError(f"Unknown source '{source}' for {variable}. Available: {list(on_demand.keys())}")
    return on_demand[source]


def _bbox_to_region_key(bbox: list) -> tuple[str, bool]:
    """Return (region_key, is_exact_match). Falls back to containing region for sub-bboxes."""
    for name, cfg in CONFIG["regions"].items():
        if cfg["bbox"] == bbox:
            return name, True
    for name, cfg in CONFIG["regions"].items():
        r = cfg["bbox"]  # [lon_min, lon_max, lat_min, lat_max]
        if r[0] <= bbox[0] and bbox[1] <= r[1] and r[2] <= bbox[2] and bbox[3] <= r[3]:
            return name, False
    return f"custom_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}", False


def _clip_to_bbox(ds, bbox: list):
    """Clip xarray Dataset to a lon/lat bounding box. Handles ascending/descending coords."""
    lon_min, lon_max, lat_min, lat_max = bbox
    lat_dim = "latitude" if "latitude" in ds.dims else "lat"
    lon_dim = "longitude" if "longitude" in ds.dims else "lon"
    lat_vals = ds[lat_dim].values
    lon_vals = ds[lon_dim].values
    lat_slice = slice(lat_max, lat_min) if lat_vals[0] > lat_vals[-1] else slice(lat_min, lat_max)
    lon_slice = slice(lon_max, lon_min) if lon_vals[0] > lon_vals[-1] else slice(lon_min, lon_max)
    return ds.sel({lat_dim: lat_slice, lon_dim: lon_slice})


MAX_POINTS = 500_000  # ~2MB JSON; applies only to pixel-level (non-aggregated) responses


def _ds_to_json(
    ds,
    variable: str,
    source: str,
    sst_var: str = "sst",
    sst_vars=None,
    aggregate_spatial: bool = False,
) -> str:
    import numpy as np

    if aggregate_spatial:
        return _ds_to_json_aggregated(ds, variable, source, sst_var, sst_vars)
    else:
        return _ds_to_json_pixel(ds, variable, source, sst_var)


def _ds_to_json_aggregated(ds, variable: str, source: str, sst_var: str, sst_vars) -> str:
    """Collapse lat/lon → one value per timestep. No size limit applies."""
    import numpy as np

    lat_dim = "latitude" if "latitude" in ds.dims else "lat"
    lon_dim = "longitude" if "longitude" in ds.dims else "lon"

    if variable == "sst":
        vars_to_return = sst_vars if sst_vars else [sst_var]
        vars_to_return = [v for v in vars_to_return if v in ds.data_vars]
        if not vars_to_return:
            vars_to_return = [sst_var]
    else:
        # chlorophyll / pp: use first data var, expose as the variable name (e.g. "chlorophyll")
        raw_var = next(iter(ds.data_vars))
        vars_to_return = [raw_var]

    result: dict = {"time": [str(t)[:10] for t in ds.time.values]}

    for v in vars_to_return:
        arr = ds[v].mean(dim=[lat_dim, lon_dim], skipna=True).squeeze().values
        out_key = v if variable == "sst" else variable
        result[out_key] = [None if np.isnan(x) else round(float(x), 5) for x in arr]

    return json.dumps({
        "data": result,
        "meta": {
            "variable": variable,
            "source": source,
            "aggregate_spatial": True,
            "n_timesteps": len(ds.time),
        },
    })


def _ds_to_json_pixel(ds, variable: str, source: str, sst_var: str) -> str:
    """Return 3D array format for pixel-level data (original behavior)."""
    import numpy as np

    data_var = sst_var if variable == "sst" else next(iter(ds.data_vars))
    arr = ds[data_var].squeeze().values
    n_points = arr.size
    shape = list(arr.shape)

    if n_points > MAX_POINTS:
        return json.dumps({
            "error": "response_too_large",
            "message": (
                f"Query returned {n_points:,} data points {shape}, which exceeds the "
                f"{MAX_POINTS:,}-point limit. Use aggregate_spatial=True to get a "
                f"spatial-mean time series, or narrow bbox/date_range."
            ),
            "meta": {"variable": variable, "source": source, "shape": shape},
        })

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
            "shape": shape,
        },
    })
