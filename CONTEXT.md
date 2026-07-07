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
| Clorofila | Default (local) | `erdMH1chla8day_R2022NRT` | 4 km, 8-day | 2003–presente |
| SST | Default (local) | `ncdcOisst21Agg_LonPM180` | 0.25°, diario | 1981–presente |
| Clorofila | On-demand | `nesdisVHNSQchlaDaily` | 4 km, diario | 2012–presente |
| Clorofila | On-demand | `noaacwNPPN20S3ASCIDINEOF2kmDaily` | 2.32 km, diario | 2018–presente |
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

## Decisiones tomadas

| Decisión | Razón |
|----------|-------|
| Python (no R) | Consistencia con ChatMPA, MCP SDK más maduro |
| MODIS 8-day como default clorofila | Balance nubosidad/resolución temporal; histórico más largo |
| OISST LonPM180 como default SST | Longitudes -180/180 compatibles con bboxes de México |
| No Copernicus ERDDAP | Conexión rechazada en pruebas |
| `sst_var` en `get_data` | OISST incluye anom/err/ice que son útiles |
| Zarr para almacenamiento local | Eficiente para queries espaciotemporales parciales |

## Estado actual

**Probado y funcionando:**
- Conexión ERDDAP para clorofila (`erdMH1chla8day_R2022NRT`) ✓
- Conexión ERDDAP para SST (`ncdcOisst21Agg_LonPM180`) con `sst_var` ✓
- Dependencias instaladas en `.venv` ✓

**Escrito pero sin probar end-to-end:**
- `tools/data_access.py` — flujo cache-first completo
- `tools/sync.py` — lógica de sincronización
- `mcp_server/server.py` — servidor MCP con 5 tools

**Bugs conocidos:**
- SST devuelve shape `(días, 1, lat, lon)` — dimensión `zlev` extra que hay que hacer squeeze en `_ds_to_json`

**No existe todavía:**
- `mcp_server/security.py`
- `mcp_server/schema.py`
- Scheduler no integrado al servidor
- `skills/contracts/` vacío
- Store Zarr sin datos (primer sync pendiente)

## Issues GitHub

Ver Project en GitHub. Issues organizados en milestone: **v0.1 — Functional MCP**.
