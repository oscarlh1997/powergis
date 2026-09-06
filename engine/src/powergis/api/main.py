"""Aplicación FastAPI.

Punto de entrada del motor. Cuatro endpoints públicos y los de operación
detrás de clave interna. Todo lo demás vive en los workers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from ..config import get_settings
from ..logging_setup import setup_logging
from . import errors
from .routers import geo, health, internal, reports

log = logging.getLogger(__name__)

DESCRIPTION = """
Motor de informes de geomarketing de PowerGIS.

El informe **no** es un documento que se genera: es una consulta contra un
almacén de indicadores precalculado. Por eso el informe básico responde en
segundos y su coste marginal es casi nulo.

* `POST /v1/reports` — crear ejecución (firmada, idempotente)
* `GET  /v1/reports/{uuid}` — payload del informe según el tier contratado
* `POST /v1/reports/{uuid}/upgrade` — promover a avanzado (webhook de Stripe)
* `GET  /v1/geo/search` — autocompletado del formulario
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    setup_logging(cfg.log_level, cfg.log_json)

    problems = cfg.check_production_ready()
    if problems:
        for problem in problems:
            log.error("CONFIGURACIÓN INSEGURA: %s", problem)
        raise RuntimeError(
            "El motor no arranca en producción con esta configuración: "
            + "; ".join(problems)
        )

    if cfg.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=cfg.sentry_dsn, environment=cfg.env, traces_sample_rate=0.1)
            log.info("Sentry activo")
        except ImportError:
            log.warning("SENTRY_DSN configurado pero sentry_sdk no está instalado")

    # El catálogo del código es la fuente de verdad: se sincroniza al arrancar
    # para que dim_indicator nunca se quede atrás respecto al motor.
    try:
        from ..adapters.db.session import uow_factory
        from ..domain import indicators as catalog_mod

        with uow_factory() as uow:
            uow.indicators.upsert_many(catalog_mod.CATALOG)
            uow.commit()
        log.info("Catálogo sincronizado: %s indicadores", len(catalog_mod.CATALOG))
    except Exception as exc:
        log.warning("No se pudo sincronizar el catálogo al arrancar: %s", exc)

    log.info("PowerGIS motor %s listo (env=%s)", cfg.engine_version, cfg.env)
    yield
    log.info("PowerGIS motor detenido")


def _registrar_esquemas_firmados(app: FastAPI) -> None:
    """Mete en `components.schemas` los modelos de los endpoints firmados.

    Esos endpoints leen el cuerpo CRUDO para poder verificar la firma sobre
    los bytes exactos, así que FastAPI nunca ve el modelo y no lo registra.
    Sus rutas lo declaran a mano con `openapi_extra`, pero un `$ref` a un
    esquema que no existe hace que Swagger falle al cargar:

        Could not resolve reference: Invalid object key "CreateReportIn"

    Aquí se generan esos esquemas y se añaden al documento, junto con los
    modelos anidados que arrastran (`$defs`).
    """
    from ..application.dto import (
        CreateReportIn,
        GeoLensQuery,
        RebalanceIn,
        UpgradeIn,
    )

    modelos = (CreateReportIn, UpgradeIn, RebalanceIn, GeoLensQuery)
    original = app.openapi

    def openapi_con_esquemas() -> dict[str, Any]:
        spec = original()
        componentes = spec.setdefault("components", {}).setdefault("schemas", {})

        for modelo in modelos:
            esquema = modelo.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            # Pydantic devuelve los modelos anidados en `$defs`; en OpenAPI
            # tienen que vivir en `components.schemas` o el `$ref` cuelga.
            for nombre, anidado in esquema.pop("$defs", {}).items():
                componentes.setdefault(nombre, anidado)
            componentes[modelo.__name__] = esquema

        app.openapi_schema = spec
        return spec

    app.openapi = openapi_con_esquemas  # type: ignore[method-assign]


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title="PowerGIS Engine",
        version=cfg.engine_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url=None if cfg.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if cfg.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-PG-Timestamp", "X-PG-Signature", "Idempotency-Key"],
        max_age=600,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    errors.install(app)

    app.include_router(health.router)
    app.include_router(reports.router)
    app.include_router(geo.router)
    app.include_router(internal.router)

    _registrar_esquemas_firmados(app)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app


app = create_app()
