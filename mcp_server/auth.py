"""
Autenticación por API-key — TokenVerifier nativo de FastMCP
(fastmcp.server.auth), no middleware ASGI a mano. Confirmado leyendo la
versión instalada (fastmcp-slim==4.0.4): ya expone esta extensión, así que no
hace falta escribir el middleware Starlette que el PDF dejaba como fallback.

La tabla de DynamoDB (AUTH_DYNAMODB_TABLE) es compartida entre los 3 MCP de
ChatMPA (ltem/conapesca/erddap) y la administra el panel del orchestrator —
esta app solo lee (GetItem), nunca escribe ni crea la tabla (mismo criterio
que ya se usa para el bucket S3 y la tabla de catálogo: se asume que ya
existe, y si no, falla al primer intento de lectura en vez de crearla).

Item shape (PK key_hash, sin SK — una fila por llave):
    {key_hash, investigator_id, scopes: [...], created_at, revoked_at}
Se guarda el hash SHA-256 de la llave, nunca la llave en sí — si la tabla se
filtrara, lo que se filtra son hashes, no credenciales reutilizables.
"""

import hashlib
import time
from collections import OrderedDict

import boto3
from fastmcp.server.auth import AccessToken, TokenVerifier

from mcp_server.config import AUTH_DYNAMODB_TABLE, AWS_REGION

# Mismo número que ya está en el PDF (sección 04) — no es una decisión nueva.
CACHE_TTL_SECONDS = 60

# Tope del cache en memoria. Con uso normal (investigadores reales, dados de
# alta a mano por el panel admin) esto nunca se acerca a este número — el
# límite es contra alguien mandando muchos tokens distintos e inválidos a
# propósito, que si no, harían crecer el diccionario sin límite (cacheamos
# también los resultados negativos, ver docstring de la clase).
MAX_CACHE_ENTRIES = 10_000


def _auth_table():
    return boto3.resource("dynamodb", region_name=AWS_REGION).Table(AUTH_DYNAMODB_TABLE)


def _hash_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ErddapApiKeyVerifier(TokenVerifier):
    """Valida llaves de investigador contra la tabla de auth compartida.

    Cachea en memoria por ~CACHE_TTL_SECONDS tanto los resultados válidos
    como los inválidos (llave inexistente o revocada) — sin cachear los
    inválidos, una llave mal escrita a propósito (o un intento de fuerza
    bruta lento) le pegaría a DynamoDB en cada intento. El cache vive en el
    proceso, sin compartir entre réplicas: cada una tarda hasta
    CACHE_TTL_SECONDS en darse cuenta de una revocación, por su cuenta, sin
    coordinarse con las demás.
    """

    def __init__(self):
        super().__init__(required_scopes=["erddap"])
        self._cache: OrderedDict[str, tuple[AccessToken | None, float]] = OrderedDict()

    async def verify_token(self, token: str) -> AccessToken | None:
        key_hash = _hash_key(token)

        cached = self._cache.get(key_hash)
        if cached is not None:
            result, expires_at = cached
            if time.monotonic() < expires_at:
                self._cache.move_to_end(key_hash)
                return result

        result = self._lookup(token, key_hash)
        self._cache[key_hash] = (result, time.monotonic() + CACHE_TTL_SECONDS)
        self._cache.move_to_end(key_hash)
        if len(self._cache) > MAX_CACHE_ENTRIES:
            self._cache.popitem(last=False)  # descarta la usada hace más tiempo
        return result

    def _lookup(self, token: str, key_hash: str) -> AccessToken | None:
        item = _auth_table().get_item(Key={"key_hash": key_hash}).get("Item")
        if not item or item.get("revoked_at") is not None:
            return None
        return AccessToken(
            token=token,
            client_id=item["investigator_id"],
            subject=item["investigator_id"],
            scopes=list(item.get("scopes", [])),
        )
