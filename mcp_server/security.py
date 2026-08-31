"""
Input validation for MCP tool arguments.
"""

from datetime import date


VALID_VARIABLES = {"chlorophyll", "primary_productivity", "sst"}
VALID_SST_VARS = {"sst", "anom", "err", "ice"}
VALID_REGIONS = {"pacific_mexico", "gulf_mexico", "all"}

LON_RANGE = (-180.0, 180.0)
LAT_RANGE = (-90.0, 90.0)
MAX_DATE_SPAN_DAYS = 365 * 5        # 5 years max for pixel-level queries
MAX_DATE_SPAN_DAYS_AGGREGATED = 365 * 60  # 60 years max when aggregate_spatial=True


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


def validate_date_range(date_range: list, aggregate_spatial: bool = False):
    if len(date_range) != 2:
        raise ValueError("date_range must have exactly 2 values: ['YYYY-MM-DD', 'YYYY-MM-DD'].")
    try:
        d_start = date.fromisoformat(date_range[0])
        d_end = date.fromisoformat(date_range[1])
    except ValueError:
        raise ValueError("date_range values must be in 'YYYY-MM-DD' format.")
    if d_start >= d_end:
        raise ValueError("date_range start must be before end.")
    limit = MAX_DATE_SPAN_DAYS_AGGREGATED if aggregate_spatial else MAX_DATE_SPAN_DAYS
    if (d_end - d_start).days > limit:
        raise ValueError(f"date_range span exceeds maximum of {limit} days.")


def validate_get_data_args(args: dict):
    validate_variable(args.get("variable", ""))
    bbox = args.get("bbox")
    if isinstance(bbox, list):
        validate_bbox(bbox)
    aggregate_spatial = bool(args.get("aggregate_spatial", False))
    validate_date_range(args.get("date_range", []), aggregate_spatial=aggregate_spatial)
    if args.get("sst_var"):
        validate_sst_var(args["sst_var"])
    if args.get("sst_vars"):
        for v in args["sst_vars"]:
            validate_sst_var(v)
