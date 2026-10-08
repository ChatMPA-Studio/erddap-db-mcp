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
import logging
import uuid
from datetime import datetime, timedelta, timezone

import boto3
import numpy as np
import s3fs
import xarray as xr
from boto3.dynamodb.conditions import Attr

from mcp_server.config import AWS_REGION, ERDDAP_DYNAMODB_TABLE, ERDDAP_S3_BUCKET, ERDDAP_S3_PREFIX

logger = logging.getLogger(__name__)

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


def acquire_sync_lock(variable: str, region: str, ttl_seconds: int = 3600) -> str | None:
    """Intenta tomar el candado de escritura del store de Zarr permanente de
    esta variable+región. Devuelve un lease_id único si lo tomó (el caller
    debe escribir y después llamar a release_sync_lock con ese mismo
    lease_id), None si ya lo tiene otro escritor — otra réplica, o (una vez
    que la Fase 2 use un executor) otro hilo del mismo proceso.

    Mismo mecanismo que register_cache: put_item condicional. `ttl_seconds`
    es solo una red de seguridad — si quien lo tomó se cae sin soltarlo, otro
    lo puede reclamar en cuanto pase ese tiempo, sin depender del borrado
    perezoso del TTL nativo de DynamoDB (hasta ~48h de rezago real).

    El lease_id es un fencing token: protege la fila de DynamoDB (no la
    escritura a S3 en sí) contra un escritor que termina tarde — si su
    candado ya expiró y otro lo reclamó mientras tanto, su release, al
    exigir que el lease_id siga siendo el suyo, no le borra el candado
    nuevo al que ya está escribiendo.
    """
    table = _dynamodb_table()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    lease_id = uuid.uuid4().hex
    try:
        table.put_item(
            Item={
                "pk": f"synclock#{variable}#{region}",
                "sk": "lock",
                "item_type": "sync_lock",
                "lease_id": lease_id,
                "acquired_at": now.isoformat(),
                "expires_at": int(expires.timestamp()),
            },
            ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
            ExpressionAttributeValues={":now": int(now.timestamp())},
        )
        return lease_id
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def release_sync_lock(variable: str, region: str, lease_id: str):
    """Suelta el candado tomado por acquire_sync_lock, solo si el lease_id
    todavía coincide con el que está en la fila. Se llama siempre en un
    finally, así que el candado no depende de esperar el TTL para liberarse
    en el caso normal (sin caídas).

    Si ya no coincide (alguien más lo reclamó porque este escritor tardó más
    que ttl_seconds), no hace nada — borrarlo igual le quitaría el candado a
    quien ya está escribiendo ahora, dejando la puerta abierta para un
    tercero.
    """
    table = _dynamodb_table()
    try:
        table.delete_item(
            Key={"pk": f"synclock#{variable}#{region}", "sk": "lock"},
            ConditionExpression="lease_id = :mine",
            ExpressionAttributeValues={":mine": lease_id},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


# --- datos (Zarr sobre S3) ---

# Stores permanentes ya abiertos, por ruta: {zarr_path: (huella de _store_version, dataset)}.
# Abrir un store lee el eje time completo para decodificarlo — con el chunking
# actual (~135 chunks de 122 días en SST) son ~135 GETs y ~9 s por llamada. El
# dataset abierto es perezoso: guarda metadata y el eje time, no los datos.
_OPEN_STORES: dict[str, tuple[tuple, xr.Dataset]] = {}
# Chunk del eje time en stores nuevos: cabe toda la historia (~16 500 días de
# SST, ~130 KB) en uno solo; cada append reescribe ese chunk, que es barato.
TIME_CHUNK = 100_000
_READ_FS: s3fs.S3FileSystem | None = None


def _read_fs() -> s3fs.S3FileSystem:
    """Un solo cliente S3 para las lecturas del servidor, así las conexiones
    keep-alive se reutilizan entre llamadas (_s3fs_fs crea uno nuevo cada vez).
    Se crea con _s3fs_fs para que los tests que la reemplazan también cubran esto."""
    global _READ_FS
    if _READ_FS is None:
        _READ_FS = _s3fs_fs()
    return _READ_FS


def _etag(fs: s3fs.S3FileSystem, zarr_path: str, keys: tuple[str, ...]) -> str | None:
    """ETag de la primera llave que exista (v3 o v2); None si ninguna existe. Los
    filesystems sin ETag (memory:// de los tests, disco) usan tamaño + fecha."""
    for key in keys:
        try:
            info = fs.info(f"{zarr_path}/{key}", refresh=True)
        except FileNotFoundError:
            continue
        return info.get("ETag") or repr((info.get("size"), info.get("created"), info.get("mtime")))
    return None


def _store_version(fs: s3fs.S3FileSystem, zarr_path: str) -> tuple | None:
    """Huella del store para saber si alguien lo escribió. None si no existe.

    Hacen falta las dos llaves: un append escribe time/zarr.json al principio y la
    metadata consolidada de la raíz al final, y open_zarr lee la consolidada. Con
    solo la de time, una réplica que abriera a mitad de un sync guardaría la vista
    vieja con el ETag nuevo y no vería el append hasta el siguiente sync. Con solo
    la raíz, un store sin metadata consolidada nunca cambiaría de huella."""
    time_etag = _etag(fs, zarr_path, ("time/zarr.json", "time/.zarray"))
    if time_etag is None:
        return None
    return time_etag, _etag(fs, zarr_path, ("zarr.json", ".zmetadata"))


def _open_store(zarr_path: str) -> xr.Dataset | None:
    """Dataset del store permanente, reutilizado mientras nadie lo haya escrito.
    Dos HEAD (los ETag) por llamada en vez de reabrirlo: el sync puede correr en
    otro proceso (tarea programada de ECS), así que no basta con invalidar en
    save_to_store."""
    fs = _read_fs()
    version = _store_version(fs, zarr_path)
    if version is None:
        _OPEN_STORES.pop(zarr_path, None)
        return None
    hit = _OPEN_STORES.get(zarr_path)
    if hit and hit[0] == version:
        return hit[1]
    ds = xr.open_zarr(fs.get_mapper(zarr_path))
    _OPEN_STORES[zarr_path] = (version, ds)
    return ds


def load_local(variable: str, region: str, date_start: str, date_end: str) -> xr.Dataset | None:
    """
    Load data from the S3 Zarr store if available for the requested range.
    Returns None if not found.
    """
    zarr_path = _s3_uri(variable, region)
    try:
        ds = _open_store(zarr_path)
        if ds is None:
            return None
        ds_slice = ds.sel(time=slice(date_start, date_end))
        if len(ds_slice.time) == 0:
            return None
        return ds_slice
    except Exception as exc:
        # El path existe (_open_store lo chequeó con el ETag), pero abrirlo falló — puede
        # ser throttling de S3, un permiso mal configurado, o metadata
        # corrupta. Se trata igual como cache-miss (get_data sigue la cadena
        # cache on-demand -> ERDDAP), pero logueado — sin esto, un problema
        # real quedaría indistinguible de "no hay datos en ese rango".
        logger.warning("load_local: no se pudo abrir %s: %s — se trata como cache-miss", zarr_path, exc)
        return None


def load_cached_zarr(zarr_path: str) -> xr.Dataset | None:
    """Abre un store de cache on-demand cuya ruta ya pasó get_cache_path (fila
    vigente en DynamoDB + fs.exists() ya confirmados). Mismo criterio que
    load_local: "la ruta existe" no es lo mismo que "se puede leer sin
    problemas" — si falla, se loguea y se trata como cache-miss en vez de
    romper toda la llamada."""
    try:
        return xr.open_zarr(zarr_path, storage_options=STORAGE_OPTIONS)
    except Exception as exc:
        logger.warning("load_cached_zarr: no se pudo abrir %s: %s — se trata como cache-miss", zarr_path, exc)
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
        # Sin encoding explícito para las variables de datos — igual que en
        # master, se deja que Zarr elija el chunking solo. El chunking de 365
        # días medido antes se validó solo con datos diarios (SST);
        # chlorophyll/pp son composites de 8 días, y "365" ahí significaría ~8
        # años por chunk, no ~1 — pendiente de recalcular por variable antes de
        # fijarlo (ver plan, próxima etapa).
        # El eje time sí va en un solo chunk: abrir el store lo lee completo, y
        # con un chunk por append son cientos de GETs (ver _OPEN_STORES).
        ds.to_zarr(zarr_path, mode="w", encoding={"time": {"chunks": (TIME_CHUNK,)}},
                   storage_options=STORAGE_OPTIONS)
    # Este proceso ya sabe que el store cambió; el ETag lo detectaría igual.
    _OPEN_STORES.pop(zarr_path, None)


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


def write_cache_zarr(
    ds: xr.Dataset,
    zarr_path: str,
    dataset_id: str,
    bbox: list,
    date_start: str,
    date_end: str,
):
    """Escribe un Dataset al store de cache on-demand, en S3. Solo debe llamarse
    después de que register_cache devuelva True (ver docstring de register_cache).

    Si la escritura falla, borra la fila que register_cache ya había creado —
    sin esto, quedaría marcada como válida hasta por ttl_days apuntando a un
    store roto o a medio escribir. Esto es seguro sin fencing token: register_cache
    reclama la llave por ttl_days completos desde el principio (no hay una ventana
    corta en la que otro escritor pueda haber entrado mientras este seguía
    trabajando), así que en el momento en que esta función corre, nadie más pudo
    haber reclamado la misma llave — no hay a quién pisarle el trabajo al borrar.
    """
    try:
        ds.to_zarr(zarr_path, mode="w", storage_options=STORAGE_OPTIONS)
    except Exception:
        table = _dynamodb_table()
        table.delete_item(Key={
            "pk": f"cache#{dataset_id}#{_bbox_hash(bbox)}",
            "sk": f"{date_start}#{date_end}",
        })
        raise
