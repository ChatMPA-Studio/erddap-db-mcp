---
name: erddap-sst-analysis
description: Analyze sea surface temperature patterns, anomalies, and trends for Mexican seas using OISST v2.1
domain: erddap
data-source: ncdcOisst21Agg_LonPM180 (NOAA CoastWatch ERDDAP)
output-type: text interpretation with data summary
tags: [sst, temperature, pacific-mexico, gulf-mexico, climate]
status: draft
version: 0.1.0
---

## Purpose

Guide analysis of sea surface temperature data for Mexican Pacific and Gulf of Mexico waters,
including anomaly detection, El Niño/La Niña signals, and long-term warming trends.

## When to Use

- Investigating thermal conditions for marine species habitat
- Detecting warm/cold anomalies relative to climatology
- Assessing El Niño/La Niña impacts on Mexican seas
- Analyzing seasonal SST cycles or multi-decadal trends (data from 1981)

## MCP Tools

| Tool | Purpose |
|------|---------|
| `get_data` | Extract SST values for a region and time range. Use `sst_var` to select the variable. |
| `list_coverage` | Check what SST data is locally available |
| `update_data` | Refresh local SST data if needed |

### `sst_var` options for `get_data`

| Value | Description | Typical range (Mexican seas) |
|-------|-------------|------------------------------|
| `sst` (default) | Sea surface temperature in °C | 14–32°C |
| `anom` | Anomaly vs. 1971–2000 climatology in °C | -3 to +3°C |
| `err` | Estimated measurement error in °C | 0.1–0.5°C |
| `ice` | Sea ice concentration (0–1) | Always 0 in Mexican seas |

## Workflow

1. Call `list_coverage` with `variable: "sst"` to confirm data availability.
2. If coverage is insufficient, call `update_data` with `variable: "sst"`.
3. Call `get_data` with `variable: "sst"`, target region, date range, and `sst_var`:
   - Use `sst_var: "sst"` for raw temperature (default).
   - Use `sst_var: "anom"` to detect warm/cold events relative to climatology.
   - Use `sst_var: "err"` to assess data quality before interpreting values.
4. Interpret the returned values:
   - Raw SST typical range: Gulf peak 30–32°C; Pacific winter minimum (Baja) 14–18°C.
   - Anomaly > +0.5°C or < -0.5°C is ecologically significant for most species.
5. For high spatial resolution (1km), use `source: "mur_1km"` with `sst_var: "sst"`.

## Interpretation Guide

- **OISST resolution:** 0.25° (~25 km) — suitable for regional/basin analysis.
- **Anomalies:** Compare current values against 1981–2010 climatological baseline.
  Positive anomaly > 0.5°C is ecologically significant for most species.
- **El Niño signal:** Look for sustained positive anomalies in the eastern Pacific
  from October through April.
- **Gulf loop current:** Visible as a warm tongue (>28°C) intruding from the south.

## Success Criteria

- Data returned covers the requested spatial and temporal extent
- Values are within physically plausible range (-2 to 35°C for open ocean)
- Interpretation includes anomaly context and comparison to seasonal baseline
