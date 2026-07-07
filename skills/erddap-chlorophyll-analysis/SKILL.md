---
name: erddap-chlorophyll-analysis
description: Analyze chlorophyll-a patterns, trends, and anomalies for Mexican seas using MODIS Aqua data
domain: erddap
data-source: erdMH1chla8day_R2022NRT (NOAA CoastWatch ERDDAP)
output-type: text interpretation with data summary
tags: [chlorophyll, ocean-color, pacific-mexico, gulf-mexico, productivity]
status: draft
version: 0.1.0
---

## Purpose

Guide analysis of chlorophyll-a concentration data for Mexican Pacific and Gulf of Mexico waters,
including seasonal patterns, interannual variability, and bloom detection.

## When to Use

- Investigating primary productivity in Mexican seas
- Detecting phytoplankton blooms or low-productivity events
- Comparing chlorophyll between seasons or years
- Analyzing spatial gradients (coastal vs. oceanic)

## MCP Tools

| Tool | Purpose |
|------|---------|
| `get_data` | Extract chlorophyll values for a region and time range |
| `list_coverage` | Check what chlorophyll data is locally available |
| `update_data` | Refresh local chlorophyll data if needed |

## Workflow

1. Call `list_coverage` with `variable: "chlorophyll"` to confirm data availability.
2. If coverage is insufficient, call `update_data` with `variable: "chlorophyll"`.
3. Call `get_data` with `variable: "chlorophyll"`, target region, and date range.
4. Interpret the returned values: typical range for Mexican seas is 0.05–5 mg/m³.
   - Coastal upwelling zones (Baja California): 1–10 mg/m³
   - Oligotrophic open ocean: < 0.1 mg/m³
   - Bloom events: > 5 mg/m³
5. For higher spatial detail in the Pacific, use `source: "viirs_750m_npac"`.

## Interpretation Guide

- **Seasonal cycle:** Chlorophyll peaks in winter (Nov–Feb) in the California Current System;
  summer upwelling drives productivity along Baja California.
- **Gulf of Mexico:** Lower baseline (~0.1–0.3 mg/m³ offshore); river plumes (Mississippi, Grijalva)
  create coastal enrichment.
- **Gaps in data:** Daily and 8-day composites show NaN over cloud cover; this is expected.

## Success Criteria

- Data returned covers the requested spatial and temporal extent
- Values are within physically plausible range (0.001–100 mg/m³)
- Interpretation includes seasonal context and comparison to regional baseline
