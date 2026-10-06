"""
SST data fetcher.
Queries NOAA CoastWatch ERDDAP using erddapy and returns xarray.Dataset.
"""

import xarray as xr
from erddapy import ERDDAP

from mcp_server.config import CONFIG

SST_VARS = ("sst", "anom", "err", "ice")

# Los datasets on-demand de MUR nombran distinto las variables que OISST. Se
# renombran a los nombres lógicos (SST_VARS) justo después de descargar, para
# que el resto del pipeline (serializador, cache) no tenga que saber de datasets.
# Solo se listan los datasets que difieren; OISST ya usa los nombres lógicos.
DATASET_VAR_RENAMES = {
    "jplMURSST41": {"analysed_sst": "sst", "analysis_error": "err", "sea_ice_fraction": "ice"},
    "jplMURSST41anom1day": {"sstAnom": "anom"},
}


async def fetch_sst(
    dataset_id: str,
    bbox: list[float],
    date_start: str,
    date_end: str,
    sst_var: str = "sst",
) -> xr.Dataset:
    """
    Fetch SST data from ERDDAP.

    Args:
        dataset_id: ERDDAP dataset ID (e.g. 'ncdcOisst21Agg_LonPM180')
        bbox: [lon_min, lon_max, lat_min, lat_max]
        date_start: ISO date string 'YYYY-MM-DD'
        date_end: ISO date string 'YYYY-MM-DD'
        sst_var: variable to extract — 'sst' (default), 'anom', 'err', or 'ice'

    Returns:
        xarray.Dataset with the requested variable
    """
    if sst_var not in SST_VARS:
        raise ValueError(f"sst_var must be one of {SST_VARS}, got '{sst_var}'")

    lon_min, lon_max, lat_min, lat_max = bbox

    e = ERDDAP(server=CONFIG["erddap"]["server"], protocol="griddap")
    e.dataset_id = dataset_id
    e.griddap_initialize()

    e.constraints["time>="] = date_start
    e.constraints["time<="] = date_end
    e.constraints["latitude>="] = lat_min
    e.constraints["latitude<="] = lat_max
    e.constraints["longitude>="] = lon_min
    e.constraints["longitude<="] = lon_max

    # griddap_initialize() already sets all variables (sst, anom, err, ice).
    # Do not override e.variables — it breaks erddapy's internal query construction.
    # The caller selects the specific variable via sst_var when reading.
    ds = e.to_xarray()

    renames = {k: v for k, v in DATASET_VAR_RENAMES.get(dataset_id, {}).items() if k in ds.data_vars}
    if renames:
        ds = ds.rename(renames)

    if sst_var not in ds.data_vars:
        available = [v for v in SST_VARS if v in ds.data_vars]
        raise ValueError(
            f"Dataset '{dataset_id}' has no '{sst_var}' variable. "
            f"Available sst_var values for this dataset: {available}."
        )
    return ds
