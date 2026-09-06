"""Dependencias de FastAPI: firma, idempotencia, límites y casos de uso."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import Depends, Header, Request

from ..adapters.cache import get_cache
from ..adapters.db.session import SqlUnitOfWork, uow_factory
from ..adapters.wordpress import WordPressNotifier
from ..application.build_report import BuildReport
from ..application.create_report import CreateReport
from ..application.upgrade_report import DowngradeReport, UpgradeReport
from ..config import Settings, get_settings
from ..domain.errors import NotOwner, PowerGisError, SignatureError, ValidationError
from .security import (
    HEADER_IDEMPOTENCY,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    compute_signature,
    verify,
    verify_get,
    verify_internal_key,
)

log = logging.getLogger(__name__)


class RateLimited(PowerGisError):
    code = "rate_limited"
    http_status = 429


# --------------------------------------------------------------------------- #
# Firma
# --------------------------------------------------------------------------- #


def _explicar_fallo_de_firma(
    body: bytes, timestamp: str | None, signature: str | None
) -> None:
    """Deja en el log POR QUÉ no casó la firma. Sólo con DEBUG activo.

    Una firma que no casa da siempre el mismo 401, y desde fuera no hay forma
    de saber si el problema es el secreto, el reloj o —lo más habitual— que
    los bytes firmados no son los que llegaron. Swagger reformatea el cuerpo:
    si firmas la versión compacta y el editor manda la indentada, o al revés,
    la firma es correcta y aun así se rechaza.

    Esto imprime los bytes EXACTOS que han llegado y la firma que les
    correspondía, para poder compararlos con lo que dijo el firmador.

    Nunca en producción: `check_production_ready()` impide arrancar con DEBUG,
    así que este bloque no puede ejecutarse ahí. Aun así, el secreto no se
    imprime jamás.
    """
    cfg = get_settings()
    if not cfg.debug:
        return

    esperada = compute_signature(cfg.hmac_secret, timestamp or "", body)
    log.warning(
        "FIRMA NO VÁLIDA — comparación (sólo en desarrollo)\n"
        "  timestamp recibido : %s\n"
        "  firma recibida     : %s\n"
        "  firma esperada     : %s\n"
        "  cuerpo: %d bytes, %s\n"
        "  cuerpo recibido, byte a byte:\n%s\n"
        "  → Si las firmas difieren pero el cuerpo es el que firmaste, revisa\n"
        "    el secreto. Si el cuerpo NO es idéntico al que firmaste (mira los\n"
        "    espacios y los saltos de línea), el problema es el reformateo:\n"
        "    copia el cuerpo DESDE Swagger AL firmador, no al revés.",
        timestamp,
        signature,
        esperada,
        len(body),
        "con CRLF" if b"\r\n" in body else "sin CRLF",
        body.decode("utf-8", errors="replace"),
    )


async def require_signature(
    request: Request,
    x_pg_timestamp: Annotated[str | None, Header(alias=HEADER_TIMESTAMP)] = None,
    x_pg_signature: Annotated[str | None, Header(alias=HEADER_SIGNATURE)] = None,
) -> bytes:
    """Verifica la firma sobre el CUERPO CRUDO y lo devuelve.

    Devolver los bytes evita que el endpoint vuelva a leerlos (el stream de
    Starlette se consume una sola vez).
    """
    body = await request.body()
    try:
        verify(body, x_pg_timestamp, x_pg_signature)
    except SignatureError:
        _explicar_fallo_de_firma(body, x_pg_timestamp, x_pg_signature)
        raise
    return body


async def require_signature_get(
    request: Request,
    x_pg_timestamp: Annotated[str | None, Header(alias=HEADER_TIMESTAMP)] = None,
    x_pg_signature: Annotated[str | None, Header(alias=HEADER_SIGNATURE)] = None,
) -> None:
    """Firma de las lecturas.

    `GET /v1/reports/{uuid}` sin firma sería una puerta abierta: `wp_user_id`
    lo pone quien llama, así que bastaría conocer un UUID para leer el informe
    de pago de otro. Aquí se firma `GET\\nruta?query`, y WordPress —que es
    quien tiene la sesión— es el único que puede construir esa firma.
    """
    verify_get(request.url.path, request.url.query, x_pg_timestamp, x_pg_signature)


async def require_internal_key(
    x_internal_key: Annotated[str | None, Header(alias="X-Internal-Key")] = None,
) -> None:
    verify_internal_key(x_internal_key)


async def idempotency_key(
    key: Annotated[str | None, Header(alias=HEADER_IDEMPOTENCY)] = None,
) -> str | None:
    if key and len(key) > 200:
        raise ValidationError("Idempotency-Key demasiado larga")
    return key


# --------------------------------------------------------------------------- #
# Límite de uso del tier gratuito
# --------------------------------------------------------------------------- #


def enforce_free_quota(wp_user_id: int, tier: str) -> None:
    """El informe básico es gratis; también es la superficie de abuso.

    Con el modelo de almacén su coste marginal es casi cero, así que el límite
    es generoso: está para frenar bots, no para frenar clientes.
    """
    if tier != "basico":
        return
    cfg = get_settings()
    cache = get_cache()
    hourly = cache.incr_window(f"user:{wp_user_id}:h", 3600)
    daily = cache.incr_window(f"user:{wp_user_id}:d", 86400)
    if hourly > cfg.rate_limit_free_per_hour or daily > cfg.rate_limit_free_per_day:
        raise RateLimited(
            "Has alcanzado el límite de informes gratuitos",
            per_hour=cfg.rate_limit_free_per_hour,
            per_day=cfg.rate_limit_free_per_day,
        )


def assert_owner(project_wp_user_id: int, requester_wp_user_id: int | None) -> None:
    """Comprobación de propiedad.

    Segunda barrera. La primera es la firma HMAC: sin ella, `wp_user_id` lo
    pondría quien llama y bastaría conocer un UUID para leer el informe de otro.
    Como la firma cubre la query completa, este valor ya no es manipulable.
    """
    if requester_wp_user_id is None:
        # Llamada máquina-a-máquina: la firma HMAC ya la ha autenticado.
        return
    if project_wp_user_id != requester_wp_user_id:
        raise NotOwner(
            "El proyecto no pertenece a este usuario",
            project_owner=project_wp_user_id,
        )


# --------------------------------------------------------------------------- #
# Fábricas de casos de uso
# --------------------------------------------------------------------------- #


def enqueue_report(run_id: int, queue: str) -> None:
    from ..workers.tasks_reports import build_report_task

    build_report_task.apply_async(args=[run_id], queue=queue)


def request_ingest(indicators: list[str], level: str, parent_code: str) -> None:
    from ..workers.tasks_etl import ingest_indicators_task

    ingest_indicators_task.apply_async(
        args=[indicators, level, parent_code], queue="etl"
    )


def get_uow() -> SqlUnitOfWork:
    return uow_factory()


def get_create_report(settings: Annotated[Settings, Depends(get_settings)]) -> CreateReport:
    return CreateReport(uow_factory, settings.engine_version, enqueue_report)


def get_upgrade_report(settings: Annotated[Settings, Depends(get_settings)]) -> UpgradeReport:
    return UpgradeReport(uow_factory, settings.engine_version, enqueue_report)


def get_downgrade_report() -> DowngradeReport:
    return DowngradeReport(uow_factory, get_cache())


def get_build_report(settings: Annotated[Settings, Depends(get_settings)]) -> BuildReport:
    return BuildReport(
        uow_factory,
        settings.engine_version,
        cache=get_cache(),
        notifier=WordPressNotifier(),
        request_ingest=request_ingest,
        max_children=settings.max_children,
        cache_ttl=settings.report_cache_ttl,
    )


CreateReportDep = Annotated[CreateReport, Depends(get_create_report)]
UpgradeReportDep = Annotated[UpgradeReport, Depends(get_upgrade_report)]
DowngradeReportDep = Annotated[DowngradeReport, Depends(get_downgrade_report)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SignedBody = Annotated[bytes, Depends(require_signature)]
SignedGet = Annotated[None, Depends(require_signature_get)]
InternalKey = Annotated[None, Depends(require_internal_key)]


def parse_signed_json(body: bytes) -> dict[str, Any]:
    import json

    try:
        return json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("Cuerpo JSON no válido") from exc
