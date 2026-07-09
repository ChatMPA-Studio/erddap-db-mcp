# CONTEXT — erddap-db-mcp

> Este archivo es la fuente de verdad del proyecto. Leerlo al inicio de cada sesión de trabajo.
> Actualizar la sección "Estado actual" y "Decisiones" cuando cambien.

## Qué es este proyecto

MCP server para extraer y analizar datos de clorofila-a y temperatura superficial del mar (SST)
desde NOAA CoastWatch ERDDAP. Módulo enchufable de ChatMPA. Python, sigue el TEMPLATE.md del ecosistema.

Repo: `C:\Users\carol\OneDrive\Documentos\CBMC\Projects\erddap-db-mcp`
GitHub: `https://github.com/ChatMPA-Studio/erddap-db-mcp`
Project: `https://github.com/orgs/ChatMPA-Studio/projects/3`

## Datasets confirmados

| Variable | Capa | Dataset ID | Resolución | Cobertura |
|----------|------|-----------|------------|-----------|
| Clorofila | Default (local) | `erdMH1chla8day_R202SQ` | 4 km, 8-day | 2003–presente |
| SST | Default (local) | `ncdcOisst21Agg_LonPM180` | 0.25°, diario | 1981–presente |
| Clorofila | On-demand | `erdVHNchla1day` | 750 m, diario | 2015–presente (solo Pacífico Norte) |
| SST | On-demand | `jplMURSST41` | 0.01°, diario | 2002–presente |
| SST | On-demand | `jplMURSST41anom1day` | 0.01°, diario | 2002–presente |

Servidor: `https://coastwatch.pfeg.noaa.gov/erddap`

## Arquitectura clave

- **Capa 1 (local):** Zarr store por variable/región + SQLite de metadatos. Sync cada 14 días (APScheduler).
- **Capa 2 (on-demand):** Query en vivo + cache local 7 días.
- **5 tools:** `get_data`, `list_coverage`, `update_data`, `list_datasets`, `get_dataset_info`
- **3 skills:** `erddap-chlorophyll-analysis`, `erddap-sst-analysis`, `erddap-data-status`
- **Regiones predefinidas:** `pacific_mexico [-118,-84,14,32]`, `gulf_mexico [-98,-81,18,31]`
- **`get_data` tiene parámetro `sst_var`:** `sst` (default), `anom`, `err`, `ice`
- **Datos locales en:** `C:/Users/carol/erddap-data/data/` (fuera de OneDrive para evitar conflictos de permisos)

## Decisiones tomadas

| Decisión | Razón |
|----------|-------|
| Python (no R) | Consistencia con ChatMPA, MCP SDK más maduro |
| MODIS Science Quality (`_R202SQ`) en lugar de NRT | Datos más precisos para análisis |
| OISST LonPM180 como default SST | Longitudes -180/180 compatibles con bboxes de México |
| No Copernicus ERDDAP | Conexión rechazada en pruebas |
| `sst_var` en `get_data` | OISST incluye anom/err/ice que son útiles |
| Zarr para almacenamiento local | Eficiente para queries espaciotemporales parciales |
| `append_dim="time"` en `save_to_store` | `mode="w"` causa WinError 5 en Windows al sobreescribir chunks |
| `data/` fuera de OneDrive | OneDrive pone DENY en chunks Zarr causando WinError 5 |
| `DATA_DIR` vía env var `ERDDAP_DATA_DIR` | Path hardcodeado no funciona en Docker; default local para desarrollo, `/data/zarr` en droplet `chatmpa-mcps` |
| `erddapy` no sobreescribir `e.variables` | Sobreescribir después de `griddap_initialize()` rompe la query |
| `run_stdio.py` como entry point | Sigue el patrón de otros MCPs en Claude Desktop |

## Estado actual (2026-07-08)

**Sync completo:**
| Variable | Región | Cobertura |
|---|---|---|
| Clorofila | pacific_mexico | 2003–2025 (23 años) |
| Clorofila | gulf_mexico | 2003–2025 (23 años) |
| SST | pacific_mexico | 1981–2026 (46 años) |
| SST | gulf_mexico | 1981–2026 (46 años) |

**Probado en Claude Desktop (4/5 tools):**
- `list_coverage` ✓
- `list_datasets` ✓
- `get_dataset_info` ✓
- `get_data` clorofila + SST anomaly ✓ — límite 500k puntos funciona, Claude acota bbox automáticamente

**Pendiente para próxima sesión:**
- Probar `update_data` en Claude Desktop
- Probar on-demand (`source="mur_1km"`)
- Probar los 3 skills
- Docker (#9) y ChatMPA (#10) — para después

## Issues GitHub

Ver Project en GitHub. Issues organizados en milestone: **v0.1 — Functional MCP**.
