"""
Local data store manager.
Handles Zarr stores for raster data and SQLite for download metadata.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import os

import numpy as np
import xarray as xr
import zarr

DATA_DIR = Path(os.environ.get("ERDDAP_DATA_DIR", "C:/Users/carol/erddap-data/data"))
META_DB = DATA_DIR / "metadata.db"


def init_db():
    """Initialize SQLite metadata database."""
    META_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(META_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                variable TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                region TEXT NOT NULL,
                date_start TEXT NOT NULL,
                date_end TEXT NOT NULL,
                downloaded_at TEXT NOT NULL,
                zarr_path TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset_id TEXT NOT NULL,
                bbox TEXT NOT NULL,
                date_start TEXT NOT NULL,
                date_end TEXT NOT NULL,
                cached_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                zarr_path TEXT NOT NULL
            )
        """)
        conn.commit()


def get_local_coverage(variable: str | None = None) -> list[dict]:
    """Return list of locally available data records."""
    with sqlite3.connect(META_DB) as conn:
        conn.row_factory = sqlite3.Row
        if variable:
            rows = conn.execute(
                "SELECT * FROM downloads WHERE variable = ? ORDER BY date_start",
                (variable,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM downloads ORDER BY variable, date_start"
            ).fetchall()
    return [dict(r) for r in rows]


def register_download(
    variable: str,
    dataset_id: str,
    region: str,
    date_start: str,
    date_end: str,
    zarr_path: str,
):
    """Record a completed download in the metadata DB."""
    with sqlite3.connect(META_DB) as conn:
        conn.execute(
            """
            INSERT INTO downloads
                (variable, dataset_id, region, date_start, date_end, downloaded_at, zarr_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                variable,
                dataset_id,
                region,
                date_start,
                date_end,
                datetime.utcnow().isoformat(),
                zarr_path,
            ),
        )
        conn.commit()


def load_local(variable: str, region: str, date_start: str, date_end: str) -> xr.Dataset | None:
    """
    Load data from local Zarr store if available for the requested range.
    Returns None if not found.
    """
    zarr_path = DATA_DIR / variable / region
    if not zarr_path.exists():
        return None
    try:
        ds = xr.open_zarr(zarr_path)
        ds_slice = ds.sel(time=slice(date_start, date_end))
        if len(ds_slice.time) == 0:
            return None
        return ds_slice
    except Exception:
        return None


def save_to_store(ds: xr.Dataset, variable: str, region: str):
    """Append or create Zarr store for a variable+region."""
    import numpy as np
    zarr_path = DATA_DIR / variable / region
    if zarr_path.exists():
        # Drop timestamps already in the store before appending to avoid duplicates.
        # (8-day composites at year boundaries can fall in two annual downloads.)
        existing_times = xr.open_zarr(zarr_path).time.values
        ds = ds.sel(time=~np.isin(ds.time.values, existing_times))
        if len(ds.time) == 0:
            return
        ds.to_zarr(zarr_path, append_dim="time")
    else:
        zarr_path.mkdir(parents=True, exist_ok=True)
        ds.to_zarr(zarr_path, mode="w")


def get_cache_path(dataset_id: str, bbox: list, date_start: str, date_end: str) -> Path | None:
    """Check if a valid on-demand cache entry exists."""
    bbox_key = json.dumps(bbox)
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(META_DB) as conn:
        row = conn.execute(
            """
            SELECT zarr_path FROM cache
            WHERE dataset_id = ? AND bbox = ? AND date_start = ? AND date_end = ?
              AND expires_at > ?
            """,
            (dataset_id, bbox_key, date_start, date_end, now),
        ).fetchone()
    if row:
        p = Path(row[0])
        return p if p.exists() else None
    return None


def register_cache(
    dataset_id: str,
    bbox: list,
    date_start: str,
    date_end: str,
    zarr_path: str,
    ttl_days: int = 7,
):
    """Register an on-demand cache entry."""
    from datetime import timedelta
    bbox_key = json.dumps(bbox)
    now = datetime.utcnow()
    expires = (now + timedelta(days=ttl_days)).isoformat()
    with sqlite3.connect(META_DB) as conn:
        conn.execute(
            """
            INSERT INTO cache
                (dataset_id, bbox, date_start, date_end, cached_at, expires_at, zarr_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (dataset_id, bbox_key, date_start, date_end, now.isoformat(), expires, zarr_path),
        )
        conn.commit()
