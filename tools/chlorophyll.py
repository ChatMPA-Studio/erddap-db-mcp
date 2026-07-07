"""
Chlorophyll data fetcher.
Queries NOAA CoastWatch ERDDAP using erddapy and returns xarray.Dataset.
"""

import xarray as xr
from erddapy import ERDDAP


ERDDAP_SERVER = "https://coastwatch.pfeg.noaa.gov/erddap"


async def fetch_chlorophyll(
    dataset_id: str,
    bbox: list[float],
    date_start: str,
    date_end: str,
) -> xr.Dataset:
    """
    Fetch chlorophyll-a data from ERDDAP.

    Args:
        dataset_id: ERDDAP dataset ID (e.g. 'erdMH1chla8day_R2022NRT')
        bbox: [lon_min, lon_max, lat_min, lat_max]
        date_start: ISO date string 'YYYY-MM-DD'
        date_end: ISO date string 'YYYY-MM-DD'

    Returns:
        xarray.Dataset with chlorophyll variable
    """
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

    ds = e.to_xarray()
    return ds
