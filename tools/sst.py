"""
SST data fetcher.
Queries NOAA CoastWatch ERDDAP using erddapy and returns xarray.Dataset.
"""

import xarray as xr
from erddapy import ERDDAP


ERDDAP_SERVER = "https://coastwatch.pfeg.noaa.gov/erddap"

SST_VARS = ("sst", "anom", "err", "ice")


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

    e = ERDDAP(server=ERDDAP_SERVER, protocol="griddap")
    e.dataset_id = dataset_id
    e.griddap_initialize()

    e.constraints["time>="] = date_start
    e.constraints["time<="] = date_end
    e.constraints["latitude>="] = lat_min
    e.constraints["latitude<="] = lat_max
    e.constraints["longitude>="] = lon_min
    e.constraints["longitude<="] = lon_max

    e.variables = [sst_var]
    ds = e.to_xarray()
    return ds
