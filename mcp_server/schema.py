"""
Shared type definitions used across tools.
"""

from typing import TypedDict


class DataMeta(TypedDict):
    variable: str
    source: str       # 'local' | 'cache' | 'erddap'
    shape: list[int]


class DataPayload(TypedDict):
    values: list      # nested list [time][lat][lon]
    times: list[str]  # ['YYYY-MM-DD', ...]
    lat: list[float]
    lon: list[float]


class ToolResponse(TypedDict):
    data: DataPayload
    meta: DataMeta


class CoverageRecord(TypedDict):
    variable: str
    dataset_id: str
    region: str
    date_start: str
    date_end: str
    downloaded_at: str
    zarr_path: str
