"""Firma HMAC bidireccional entre WordPress y el motor.

El esquema, idéntico en PHP y en Python:

    payload   = f"{timestamp}\\n{cuerpo_crudo}"
    firma     = hex( HMAC-SHA256(secreto, payload) )
    cabeceras = X-PG-Timestamp, X-PG-Signature

Reglas:
* Se firma el **cuerpo crudo**, no el JSON reserializado: dos serializadores
  distintos producen bytes distintos y la firma dejaría de casar.
* Ventana de 300 s contra reenvío.
* Comparación en **tiempo constante** (`hmac.compare_digest` / `hash_equals`).
* La misma función sirve para firmar el callback hacia WordPress.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

from ..config import get_settings
from ..domain.errors import ReplayError, SignatureError

HEADER_TIMESTAMP = "X-PG-Timestamp"
HEADER_SIGNATURE = "X-PG-Signature"
HEADER_IDEMPOTENCY = "Idempotency-Key"


@dataclass(frozen=True, slots=True)
class SignedHeaders:
    timestamp: str
    signature: str

    def as_dict(self) -> dict[str, str]:
        return {HEADER_TIMESTAMP: self.timestamp, HEADER_SIGNATURE: self.signature}


def compute_signature(secret: str, timestamp: str | int, body: bytes | str) -> str:
    if isinstance(body, str):
        body = body.encode("utf-8")
    payload = f"{timestamp}\n".encode() + body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign(body: bytes | str, secret: str | None = None) -> SignedHeaders:
    cfg = get_settings()
    secret = secret or cfg.hmac_secret
    timestamp = str(int(time.time()))
    return SignedHeaders(timestamp, compute_signature(secret, timestamp, body))


def verify(
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    *,
    secret: str | None = None,
    window_seconds: int | None = None,
) -> None:
    """Lanza SignatureError / ReplayError. No devuelve nada si es válida."""
    cfg = get_settings()
    secret = secret or cfg.hmac_secret
    window = window_seconds if window_seconds is not None else cfg.hmac_window_seconds

    if not timestamp or not signature:
        raise SignatureError("Faltan cabeceras de firma")

    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise SignatureError("Timestamp inválido") from exc

    drift = abs(int(time.time()) - sent_at)
    if drift > window:
        raise ReplayError("Petición fuera de la ventana temporal", drift_seconds=drift)

    expected = compute_signature(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("Firma no válida")


def canonical_get(path: str, query: str = "") -> str:
    """Cadena canónica que se firma en una petición GET.

    Un GET no tiene cuerpo, así que lo que se firma es `MÉTODO\\nruta?query`.
    Sin esto, `GET /v1/reports/{uuid}` quedaría abierto: bastaría conocer un
    UUID para leer el informe de pago de otro usuario, porque `wp_user_id` lo
    pone quien llama.
    """
    return f"GET\n{path}" + (f"?{query}" if query else "")


def sign_get(path: str, query: str = "", secret: str | None = None) -> SignedHeaders:
    return sign(canonical_get(path, query), secret)


def verify_get(
    path: str,
    query: str,
    timestamp: str | None,
    signature: str | None,
    *,
    secret: str | None = None,
    window_seconds: int | None = None,
) -> None:
    verify(
        canonical_get(path, query).encode("utf-8"),
        timestamp,
        signature,
        secret=secret,
        window_seconds=window_seconds,
    )


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


def verify_internal_key(provided: str | None) -> None:
    """Clave para endpoints de operación (ETL manual, reindexado)."""
    cfg = get_settings()
    if not provided or not constant_time_equals(provided, cfg.internal_api_key):
        raise SignatureError("Clave interna no válida")
