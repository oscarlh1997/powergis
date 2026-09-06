"""Sondas de salud y preparación."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ...adapters.cache import get_cache
from ...adapters.db.session import ping as db_ping
from ...adapters.db.session import schema_ready
from ...application.dto import HealthOut
from ...config import get_settings

router = APIRouter(tags=["salud"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Liveness: responde aunque las dependencias estén caídas."""
    cfg = get_settings()
    return HealthOut(
        status="ok",
        engine_version=cfg.engine_version,
        database=True,
        redis=True,
        checks={"env": cfg.env},
    )


@router.get("/ready", response_model=HealthOut)
def ready(response: Response) -> HealthOut:
    """Readiness: comprueba de verdad base de datos y Redis."""
    cfg = get_settings()
    database = db_ping()
    redis_ok = get_cache().ping()
    problems = cfg.check_production_ready()

    # Conectar no es estar listo. Una base de datos sin migrar responde al
    # ping y devuelve 500 en cada consulta; si readiness no lo mira, el proxy
    # manda tráfico a un motor que no puede servir nada.
    esquema = schema_ready() if database else "sin conexión a la base de datos"
    if esquema:
        problems = [*problems, esquema]

    ok = database and redis_ok and not problems
    if not ok:
        response.status_code = 503
    return HealthOut(
        status="ok" if ok else "degraded",
        engine_version=cfg.engine_version,
        database=database and esquema is None,
        redis=redis_ok,
        checks={"config_problems": problems},
    )
