"""
Helpers compartidos para los endpoints JSON tabulares de ERDDAP
(/info/<dataset_id>/index.json, /search/index.json) — antes cada llamador
(tools/sync.py, tools/data_access.py) pedía su propia URL y parseaba la
misma forma de tabla (rows/columnNames) por separado.

No incluye los fetchers de datos de grilla (tools/sst.py, chlorophyll.py,
pp.py) — esos usan erddapy/griddap, una librería y un propósito distintos a
"pedir metadata y parsear una tabla"; ni el chequeo de salud del servidor
(tools/sync.py:_server_available) — es un booleano de status code, sin
ningún parseo de tabla que compartir con esto.
"""

import httpx


async def _fetch_table_rows(url: str) -> list[dict]:
    """GET una URL de ERDDAP que devuelve el formato tabular estándar
    ({"table": {"columnNames": [...], "rows": [[...], ...]}}) y la aplana a
    una lista de dicts, una fila por elemento. Deja que las excepciones de
    red/HTTP se propaguen — cada llamador decide cómo manejarlas."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
    rows = raw.get("table", {}).get("rows", [])
    cols = raw.get("table", {}).get("columnNames", [])
    return [dict(zip(cols, row)) for row in rows]


async def fetch_dataset_info_rows(server: str, dataset_id: str) -> list[dict]:
    """Pide la metadata de un dataset a ERDDAP: una fila por variable/atributo
    documentado (get_dataset_info las deja subir tal cual si falla;
    _get_dataset_max_date las atrapa, reintenta y, si sigue fallando, devuelve
    None en vez de adivinar una fecha)."""
    return await _fetch_table_rows(f"{server}/info/{dataset_id}/index.json")


async def search_datasets(server: str, keyword: str) -> list[dict]:
    """Busca datasets en ERDDAP por palabra clave: una fila por dataset
    encontrado. Mismo formato tabular que fetch_dataset_info_rows, endpoint
    distinto."""
    url = f"{server}/search/index.json?searchFor={keyword.replace(' ', '+')}&page=1&itemsPerPage=20"
    return await _fetch_table_rows(url)
