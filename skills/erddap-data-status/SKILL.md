---
name: erddap-data-status
description: Report local data coverage and trigger updates for chlorophyll and SST datasets
domain: erddap
data-source: local Zarr store + NOAA CoastWatch ERDDAP
output-type: text status report
tags: [status, sync, coverage, maintenance]
status: draft
version: 0.1.0
---

## Purpose

Check the state of locally stored oceanographic data and trigger updates when needed.
Use this before any analysis to confirm data is current and complete.

## When to Use

- Before starting any chlorophyll or SST analysis
- When uncertain whether local data is up to date
- After a long period without updates
- When a user explicitly asks to refresh the data

## MCP Tools

| Tool | Purpose |
|------|---------|
| `list_coverage` | Show what is stored locally (variables, regions, date ranges) |
| `update_data` | Trigger manual sync for a specific variable and region |

## Workflow

1. Call `list_coverage` with no arguments to get a full inventory.
2. Review the date ranges for each variable and region:
   - Is the most recent date within the last 14 days? If yes, data is current.
   - Are both `chlorophyll` and `sst` present for `pacific_mexico` and `gulf_mexico`?
3. If data is missing or outdated, call `update_data` for the affected variable(s).
4. Report status to the user: what is available, what was updated, what failed.

## Success Criteria

- User has a clear picture of local data availability
- Any gaps are identified and resolved or flagged
- Update operations complete without errors
