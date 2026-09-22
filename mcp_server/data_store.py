"""
Storage manager — Fase 1 de la migración a AWS.

Los datos (arrays de clorofila/SST) siguen siendo Zarr — solo cambia dónde
viven: de disco local a un bucket S3, vía s3fs/fsspec (Zarr es el backend
nativo del formato para object storage, no un workaround).

La metadata (antes SQLite: tablas `downloads` y `cache`) pasa a una sola
tabla de DynamoDB con tres formas de ítem, distinguidas por `item_type`:
  - "download":  catálogo permanente. PK "{variable}#{region}", SK date_start.
                 Muchas filas por variable+región (una por año/chunk ya
                 descargado), todas apuntando al mismo store de Zarr.
  - "cache":     cache on-demand con TTL nativo. PK "cache#{dataset_id}#{bbox_hash}",
                 SK "{date_start}#{date_end}". `expires_at` es el atributo TTL
                 de la tabla (debe ser epoch en segundos, no ISO string). Cada
                 combinación de parámetros tiene su propio store de Zarr, así
                 que la fila que registra el cache y el "candado" que evita
                 escribirlo dos veces son la misma fila (ver register_cache).
  - "sync_lock": candado transitorio para el catálogo permanente. PK
                 "synclock#{variable}#{region}", SK fija "lock" — una sola
                 fila posible por variable+región, sin importar cuántas filas
                 de "download" (años distintos) haya. Hace falta aparte de
                 "download" porque el catálogo permanente no tiene una fila
                 cuya llave ignore la fecha: dos escrituras a años distintos
                 (2024 vs 2025) tienen SK distinto, así que una condición
                 sobre la fila de "download" nunca chocaría entre ellas —
                 pero ambas escriben al mismo store de Zarr igual. A
                 diferencia de "download"/"cache", esta fila no es un
                 registro permanente: se crea justo antes de escribir el
                 Zarr y se borra apenas termina (ver acquire_sync_lock /
                 release_sync_lock).

Mismo estilo que la versión de disco local que reemplaza: llamadas síncronas
directas — sin executors todavía (Fase 2, en curso). El candado de sync sí
se agrega ahora porque protege contra corrupción de datos (Zarr no tiene
ninguna protección propia contra escritores concurrentes al mismo store),
no es una optimización de rendimiento que se pueda posponer con ese mismo
criterio.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import boto3
import numpy as np
import s3fs
import xarray as xr
from boto3.dynamodb.conditions import Attr

from mcp_server.config import AWS_REGION, ERDDAP_DYNAMODB_TABLE, ERDDAP_S3_BUCKET, ERDDAP_S3_PREFIX

S3_BUCKET = ERDDAP_S3_BUCKET
S3_PREFIX = ERDDAP_S3_PREFIX.strip("/")
DYNAMODB_TABLE = ERDDAP_DYNAMODB_TABLE

# xarray/zarr usan storage_options (formato fsspec) para autenticar contra S3.
# En Fargate esto viene del task role — no hace falta poner llaves aquí.
STORAGE_OPTIONS = {"client_kwargs": {"region_name": AWS_REGION}}


def _s3fs_fs() -> s3fs.S3FileSystem:
    # skip_instance_cache evita que fsspec reutilice un cliente creado bajo un
    # mock de AWS distinto (relevante en tests con moto).
    return s3fs.S3FileSystem(**STORAGE_OPTIONS, skip_instance_cache=True)


def _s3_key(*parts: str) -> str:
    return "/".join([S3_PREFIX, *parts])


def _s3_uri(*parts: str) -> str:
    return f"s3://{S3_BUCKET}/{_s3_key(*parts)}"


def _dynamodb_table():
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(DYNAMODB_TABLE)


def _bbox_hash(bbox: list) -> str:
    return hashlib.sha1(json.dumps(bbox).encode()).hexdigest()[:12]


def cache_zarr_uri(dataset_id: str, bbox: list, date_start: str, date_end: str) -> str:
    """S3 URI para un store de cache on-demand. Usa el mismo hash de bbox que
    la llave de DynamoDB, para que ambos lados coincidan."""
    name = f"{dataset_id}_{_bbox_hash(bbox)}_{date_start}_{date_end}"
    return _s3_uri("cache", name)


def store_zarr_uri(variable: str, region: str) -> str:
    """S3 URI del store permanente de una variable+región — lo que save_to_store
    usa por dentro. Expuesta para que quien registre el catálogo (tools/sync.py)
    no necesite conocer _s3_uri (privada) para saber dónde quedó guardado."""
    return _s3_uri(variable, region)


def init_db():
    """Verifica que la tabla de DynamoDB y el bucket S3 ya existan.

    No los crea: eso es trabajo de Terraform/infra (arquitectura-resultante-mcp.pdf,
    sección 07) — el task role de esta app solo debería tener permiso de leer/
    escribir ítems y objetos, no de crear tablas o buckets. Si algo falta,
    falla rápido y con un mensaje claro en vez de intentar arreglarlo solo.
    """
    ddb_client = boto3.client("dynamodb", region_name=AWS_REGION)
    try:
        ddb_client.describe_table(TableName=DYNAMODB_TABLE)
    except ddb_client.exceptions.ResourceNotFoundException:
        raise RuntimeError(
            f"La tabla DynamoDB '{DYNAMODB_TABLE}' no existe. Debe crearla la "
            f"infraestructura (Terraform), no esta app."
        )

    s3_client = boto3.client("s3", region_name=AWS_REGION)
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET)
    except Exception as exc:
        raise RuntimeError(
            f"El bucket S3 '{S3_BUCKET}' no existe o no es accesible. Debe "
            f"crearlo la infraestructura (Terraform), no esta app."
        ) from exc


# --- catálogo permanente (downloads) ---

def get_local_coverage(variable: str | None = None) -> list[dict]:
    """Return list of locally available data records."""
    table = _dynamodb_table()
    filter_expr = Attr("item_type").eq("download")
    if variable:
        filter_expr = filter_expr & Attr("variable").eq(variable)

    items: list[dict] = []
    resp = table.scan(FilterExpression=filter_expr)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(FilterExpression=filter_expr, ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))

    items.sort(key=lambda r: (r.get("variable", ""), r["date_start"]))
    return [
        {
            "variable": i["variable"],
            "dataset_id": i["dataset_id"],
            "region": i["region"],
            "date_start": i["date_start"],
            "date_end": i["date_end"],
            "downloaded_at": i["downloaded_at"],
            "zarr_path": i["zarr_path"],
        }
        for i in items
    ]


def register_download(
    variable: str,
    dataset_id: str,
    region: str,
    date_start: str,
    date_end: str,
    zarr_path: str,
):
    """Record a completed download in the metadata catalog."""
    table = _dynamodb_table()
    table.put_item(Item={
        "pk": f"{variable}#{region}",
        "sk": date_start,
        "item_type": "download",
        "variable": variable,
        "dataset_id": dataset_id,
        "region": region,
        "date_start": date_start,
        "date_end": date_end,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "zarr_path": zarr_path,
    })


def acquire_sync_lock(variable: str, region: str, ttl_seconds: int = 3600) -> bool:
    """Intenta tomar el candado de escritura del store de Zarr permanente de
    esta variable+región. Devuelve True si lo tomó (el caller debe escribir y
    después llamar a release_sync_lock), False si ya lo tiene otro escritor
    — otra réplica, o (una vez que la Fase 2 use un executor) otro hilo del
    mismo proceso.

    Mismo mecanismo que register_cache: put_item condicional. `ttl_seconds`
    es solo una red de seguridad — si quien lo tomó se cae sin soltarlo, otro
    lo puede reclamar en cuanto pase ese tiempo, sin depender del borrado
    perezoso del TTL nativo de DynamoDB (hasta ~48h de rezago real).
    """
    table = _dynamodb_table()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    try:
        table.put_item(
            Item={
                "pk": f"synclock#{variable}#{region}",
                "sk": "lock",
                "item_type": "sync_lock",
                "acquired_at": now.isoformat(),
                "expires_at": int(expires.timestamp()),
            },
            ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
            ExpressionAttributeValues={":now": int(now.timestamp())},
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def release_sync_lock(variable: str, region: str):
    """Suelta el candado tomado por acquire_sync_lock. Se llama siempre en un
    finally, así que el candado no depende de esperar el TTL para liberarse
    en el caso normal (sin caídas)."""
    table = _dynamodb_table()
    table.delete_item(Key={"pk": f"synclock#{variable}#{region}", "sk": "lock"})


# --- datos (Zarr sobre S3) ---

def load_local(variable: str, region: str, date_start: str, date_end: str) -> xr.Dataset | None:
    """
    Load data from the S3 Zarr store if available for the requested range.
    Returns None if not found.
    """
    zarr_path = _s3_uri(variable, region)
    fs = _s3fs_fs()
    if not fs.exists(zarr_path):
        return None
    try:
        ds = xr.open_zarr(zarr_path, storage_options=STORAGE_OPTIONS)
        ds_slice = ds.sel(time=slice(date_start, date_end))
        if len(ds_slice.time) == 0:
            return None
        return ds_slice
    except Exception:
        return None


def save_to_store(ds: xr.Dataset, variable: str, region: str):
    """Append or create the Zarr store for a variable+region, en S3."""
    zarr_path = _s3_uri(variable, region)
    fs = _s3fs_fs()
    if fs.exists(zarr_path):
        # Drop timestamps already in the store before appending to avoid duplicates.
        # (8-day composites at year boundaries can fall in two annual downloads.)
        existing_times = xr.open_zarr(zarr_path, storage_options=STORAGE_OPTIONS).time.values
        ds = ds.sel(time=~np.isin(ds.time.values, existing_times))
        if len(ds.time) == 0:
            return
        ds.to_zarr(zarr_path, append_dim="time", storage_options=STORAGE_OPTIONS)
    else:
        # Sin encoding explícito por ahora — igual que en master, se deja que
        # Zarr elija el chunking solo. El chunking de 365 días medido antes se
        # validó solo con datos diarios (SST); chlorophyll/pp son composites de
        # 8 días, y "365" ahí significaría ~8 años por chunk, no ~1 — pendiente
        # de recalcular por variable antes de fijarlo (ver plan, próxima etapa).
        ds.to_zarr(zarr_path, mode="w", storage_options=STORAGE_OPTIONS)


# --- cache on-demand ---

def get_cache_path(dataset_id: str, bbox: list, date_start: str, date_end: str) -> str | None:
    """Check if a valid on-demand cache entry exists. Returns its S3 URI, or None."""
    table = _dynamodb_table()
    resp = table.get_item(Key={
        "pk": f"cache#{dataset_id}#{_bbox_hash(bbox)}",
        "sk": f"{date_start}#{date_end}",
    })
    item = resp.get("Item")
    if not item:
        return None

    now_epoch = int(datetime.now(timezone.utc).timestamp())
    if int(item["expires_at"]) <= now_epoch:
        return None

    zarr_path = item["zarr_path"]
    if not _s3fs_fs().exists(zarr_path):
        return None
    return zarr_path


def register_cache(
    dataset_id: str,
    bbox: list,
    date_start: str,
    date_end: str,
    zarr_path: str,
    ttl_days: int = 7,
) -> bool:
    """Register an on-demand cache entry, solo si nadie más ya registró uno vigente
    para esta misma llave. `expires_at` es el atributo TTL de la tabla.

    El put_item es condicional (attribute_not_exists(pk), o vencido) para que dos
    réplicas que hacen cache-miss al mismo tiempo no puedan las dos "ganar" — eso
    dejaría a las dos escribiendo el mismo store de Zarr en S3 a la vez, y Zarr no
    tiene ninguna protección contra escritores concurrentes (metadata corrupta).
    Devuelve True si esta llamada registró el ítem (el caller debe escribir el Zarr
    real), False si ya había uno vigente (el caller NO debe escribir — otra réplica
    ya se encargó o se está encargando).
    """
    table = _dynamodb_table()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=ttl_days)
    try:
        table.put_item(
            Item={
                "pk": f"cache#{dataset_id}#{_bbox_hash(bbox)}",
                "sk": f"{date_start}#{date_end}",
                "item_type": "cache",
                "dataset_id": dataset_id,
                "bbox": json.dumps(bbox),
                "date_start": date_start,
                "date_end": date_end,
                "cached_at": now.isoformat(),
                "expires_at": int(expires.timestamp()),
                "zarr_path": zarr_path,
            },
            ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
            ExpressionAttributeValues={":now": int(now.timestamp())},
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def write_cache_zarr(ds: xr.Dataset, zarr_path: str):
    """Escribe un Dataset al store de cache on-demand, en S3. Solo debe llamarse
    después de que register_cache devuelva True (ver docstring de register_cache)."""
    ds.to_zarr(zarr_path, mode="w", storage_options=STORAGE_OPTIONS)
