"""
Input validation for MCP tool arguments.
"""

from datetime import date


VALID_VARIABLES = {"chlorophyll", "sst"}
VALID_SST_VARS = {"sst", "anom", "err", "ice"}
VALID_REGIONS = {"pacific_mexico", "gulf_mexico", "all"}

LON_RANGE = (-180.0, 180.0)
LAT_RANGE = (-90.0, 90.0)
MAX_DATE_SPAN_DAYS = 365 * 5  # 5 years max per query


def validate_variable(variable: str):
    if variable not in VALID_VARIABLES:
        raise ValueError(f"Invalid variable '{variable}'. Must be one of {VALID_VARIABLES}.")


def validate_sst_var(sst_var: str):
    if sst_var not in VALID_SST_VARS:
        raise ValueError(f"Invalid sst_var '{sst_var}'. Must be one of {VALID_SST_VARS}.")


def validate_bbox(bbox: list):
    if len(bbox) != 4:
        raise ValueError("bbox must have exactly 4 values: [lon_min, lon_max, lat_min, lat_max].")
    lon_min, lon_max, lat_min, lat_max = bbox
    if not (LON_RANGE[0] <= lon_min < lon_max <= LON_RANGE[1]):
        raise ValueError(f"Invalid longitude range: [{lon_min}, {lon_max}].")
    if not (LAT_RANGE[0] <= lat_min < lat_max <= LAT_RANGE[1]):
        raise ValueError(f"Invalid latitude range: [{lat_min}, {lat_max}].")


def validate_date_range(date_range: list):
    if len(date_range) != 2:
        raise ValueError("date_range must have exactly 2 values: ['YYYY-MM-DD', 'YYYY-MM-DD'].")
    try:
        d_start = date.fromisoformat(date_range[0])
        d_end = date.fromisoformat(date_range[1])
    except ValueError:
        raise ValueError("date_range values must be in 'YYYY-MM-DD' format.")
    if d_start >= d_end:
        raise ValueError("date_range start must be before end.")
    if (d_end - d_start).days > MAX_DATE_SPAN_DAYS:
        raise ValueError(f"date_range span exceeds maximum of {MAX_DATE_SPAN_DAYS} days.")
    if d_end > date.today():
        raise ValueError("date_range end cannot be in the future.")


def validate_get_data_args(args: dict):
    validate_variable(args.get("variable", ""))
    bbox = args.get("bbox")
    if isinstance(bbox, list):
        validate_bbox(bbox)
    validate_date_range(args.get("date_range", []))
    if args.get("sst_var"):
        validate_sst_var(args["sst_var"])
