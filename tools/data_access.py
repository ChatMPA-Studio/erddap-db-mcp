"""
Main tool dispatcher. Implements cache-first logic:
1. Check local Zarr store
2. If missing, fetch from ERDDAP and cache
3. Return JSON with data + metadata
"""

import json

from mcp_server.config import CONFIG
from mcp_server.data_store import (
    cache_zarr_uri,
    get_cache_path,
    get_local_coverage,
    load_cached_zarr,
    load_local,
    register_cache,
    write_cache_zarr,
)
from mcp_server.security import validate_get_data_args, validate_update_data_args
from tools.chlorophyll import fetch_chlorophyll
from tools.erddap_client import fetch_dataset_info_rows, search_datasets
from tools.pp import fetch_pp
from tools.sst import fetch_sst


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
                               sst_vars=sst_vars, aggregate_spatial=aggregate_spatial,
                               date_range=date_range)

    dataset_id = _resolve_dataset_id(variable, source)

    cached = get_cache_path(dataset_id, bbox, date_start, date_end)
    if cached:
        ds = load_cached_zarr(cached)
        if ds is not None:
            return _ds_to_json(ds, variable, source="cache", sst_var=sst_var,
                               sst_vars=sst_vars, aggregate_spatial=aggregate_spatial,
                               date_range=date_range)
        # load_cached_zarr ya logueó la falla — se sigue de largo al fetch de
        # ERDDAP, igual que si no hubiera habido cache (ver su docstring).

    try:
        if variable == "chlorophyll":
            ds = await fetch_chlorophyll(dataset_id, bbox, date_start, date_end)
        elif variable == "primary_productivity":
            ds = await fetch_pp(dataset_id, bbox, date_start, date_end)
        else:
            ds = await fetch_sst(dataset_id, bbox, date_start, date_end, sst_var=sst_var)
    except Exception as e:
        # ERDDAP responde 404 "no matching results" cuando el rango (o el bbox) no tiene
        # datos; el texto crudo nombra una variable interna que no tiene que ver con lo
        # pedido y no dice qué sí hay.
        if "no matching results" not in str(e) and "code=404" not in str(e):
            raise
        raise ValueError(
            f"No data for {variable} between {date_start} and {date_end} in the requested "
            f"area (dataset '{dataset_id}'; ERDDAP returned no matching results). "
            f"Local coverage — {_coverage_summary(variable)}."
        ) from e

    if source != "auto":
        cache_path = cache_zarr_uri(dataset_id, bbox, date_start, date_end)
        # Primero reclama la llave en DynamoDB; solo si gana escribe a S3 — evita
        # que dos réplicas con el mismo cache-miss escriban el mismo store de Zarr
        # a la vez (ver docstring de register_cache).
        if register_cache(dataset_id, bbox, date_start, date_end, cache_path):
            write_cache_zarr(ds, cache_path, dataset_id, bbox, date_start, date_end)

    return _ds_to_json(ds, variable, source="erddap", sst_var=sst_var,
                       sst_vars=sst_vars, aggregate_spatial=aggregate_spatial,
                       date_range=date_range)


async def list_coverage(args: dict) -> str:
    variable = args.get("variable")
    records = get_local_coverage(variable)
    return json.dumps({"data": records, "meta": {"count": len(records)}}, indent=2)


async def update_data(args: dict) -> str:
    validate_update_data_args(args)
    from tools.sync import run_sync
    variable = args["variable"]
    region = args.get("region", "all")
    result = await run_sync(variable=variable, region=region)
    return json.dumps(result, indent=2)


async def list_datasets(args: dict) -> str:
    variable = args["variable"]
    query_extra = args.get("query", "")
    keyword = f"{variable} {query_extra}".strip()
    server = CONFIG["erddap"]["server"]
    datasets = await search_datasets(server, keyword)
    return json.dumps({"data": datasets, "meta": {"count": len(datasets)}}, indent=2)


async def get_dataset_info(args: dict) -> str:
    dataset_id = args["dataset_id"]
    server = CONFIG["erddap"]["server"]
    info = await fetch_dataset_info_rows(server, dataset_id)
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


# Cadencia típica (días) por variable, solo para decidir la tolerancia cuando la
# respuesta trae un único paso de tiempo y no se puede medir de los propios datos.
DEFAULT_STEP_DAYS = {"sst": 2, "chlorophyll": 8, "primary_productivity": 8}


def _range_meta(ds, variable: str, date_range) -> dict:
    """Qué rango se pidió, cuál se devolvió realmente, y si la respuesta es más
    corta que lo pedido (`truncated`). Sin esto, un rango que se pasa del final
    de la cobertura vuelve con menos datos y sin ningún aviso.

    Los productos no son diarios (clorofila: 8 días; OISST de 1995: cada 2), así
    que "más corto" se mide con una tolerancia de un paso de los propios datos
    devueltos — si no, toda consulta normal saldría marcada como truncada."""
    from datetime import date, timedelta

    requested = [str(date_range[0])[:10], str(date_range[1])[:10]]
    times = sorted(str(t)[:10] for t in ds.time.values)
    if not times:
        return {"date_range_requested": requested, "date_range_returned": None, "truncated": True}

    days = [date.fromisoformat(t) for t in times]
    step = max(((b - a).days for a, b in zip(days, days[1:])), default=DEFAULT_STEP_DAYS.get(variable, 8))
    tol = timedelta(days=max(step, 1))
    start, end = date.fromisoformat(requested[0]), date.fromisoformat(requested[1])
    return {
        "date_range_requested": requested,
        "date_range_returned": [times[0], times[-1]],
        "truncated": bool(days[0] > start + tol or days[-1] < end - tol),
    }


def _coverage_summary(variable: str) -> str:
    """Cobertura local por región, en una línea, para los mensajes de error."""
    by_region: dict = {}
    for r in get_local_coverage(variable):
        a = by_region.setdefault(r["region"], [str(r["date_start"])[:10], str(r["date_end"])[:10]])
        a[0], a[1] = min(a[0], str(r["date_start"])[:10]), max(a[1], str(r["date_end"])[:10])
    if not by_region:
        return "no local data for this variable"
    return "; ".join(f"{reg}: {a[0]} to {a[1]}" for reg, a in sorted(by_region.items()))


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
    date_range=None,
) -> str:
    range_meta = _range_meta(ds, variable, date_range) if date_range else {}
    if aggregate_spatial:
        return _ds_to_json_aggregated(ds, variable, source, sst_var, sst_vars, range_meta)
    else:
        return _ds_to_json_pixel(ds, variable, source, sst_var, range_meta)


# Nombres conocidos de la data var "principal" por variable, en orden de
# preferencia, para datasets que traen más de una (p. ej. erdMH1pp8day expone
# "productivity" Y "nobs" — conteo de observaciones, no la métrica). ERDDAP no
# garantiza el orden entre ellas, así que next(iter(ds.data_vars)) no es
# confiable por sí solo. Cada producto nombra distinto la misma magnitud: MODIS
# usa "chlor_a" y VIIRS (erdVHNchla1day / erdVHNchla8day) usa "chla".
PREFERRED_DATA_VAR = {
    "primary_productivity": ("productivity",),
    "chlorophyll": ("chlor_a", "chla"),
}


def _resolve_data_var(ds, variable: str) -> str:
    """Elige la data var a usar para variables no-SST (chlorophyll/pp): el
    primer nombre conocido que esté presente en el Dataset, y solo cae al
    primero disponible como último recurso."""
    for name in PREFERRED_DATA_VAR.get(variable, ()):
        if name in ds.data_vars:
            return name
    return next(iter(ds.data_vars))


def _ds_to_json_aggregated(ds, variable: str, source: str, sst_var: str, sst_vars, range_meta: dict) -> str:
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
        # chlorophyll / pp: expose as the variable name (e.g. "chlorophyll").
        vars_to_return = [_resolve_data_var(ds, variable)]

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
            **range_meta,
        },
    })


def _ds_to_json_pixel(ds, variable: str, source: str, sst_var: str, range_meta: dict) -> str:
    """Return 3D array format for pixel-level data (original behavior)."""
    import numpy as np

    data_var = sst_var if variable == "sst" else _resolve_data_var(ds, variable)
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
            "meta": {"variable": variable, "source": source, "shape": shape, **range_meta},
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
            **range_meta,
        },
    })
