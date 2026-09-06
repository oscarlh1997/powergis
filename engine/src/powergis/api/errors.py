"""Traducción de errores de dominio a HTTP.

El dominio no sabe qué es un 404. Aquí, y solo aquí, se hace el mapeo.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from ..config import get_settings
from ..domain.errors import PowerGisError

log = logging.getLogger(__name__)


def install(app: FastAPI) -> None:
    @app.exception_handler(PowerGisError)
    async def _domain(request: Request, exc: PowerGisError) -> JSONResponse:
        log.info("error de dominio %s en %s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(status_code=exc.http_status, content=exc.as_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "El cuerpo de la petición no cumple el contrato",
                "context": {"errors": _clean(exc.errors())},
            },
        )

    @app.exception_handler(PydanticValidationError)
    async def _manual_validation(request: Request, exc: PydanticValidationError) -> JSONResponse:
        """Validación hecha a mano dentro del handler.

        Los endpoints firmados no pueden declarar el cuerpo como modelo (los
        bytes crudos son lo que se firma), así que llaman a `model_validate`
        ellos mismos. Sin este handler, un formulario mal montado daría un 500
        «Error interno del motor» en vez de decir qué campo falla.
        """
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "El cuerpo de la petición no cumple el contrato",
                "context": {"errors": _clean(exc.errors())},
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Nunca se filtra la traza al cliente. Se devuelve un identificador
        # para poder cruzarlo con el log y con Sentry.
        incident = uuid.uuid4().hex[:12]
        log.exception("error no controlado [%s] en %s", incident, request.url.path)
        cfg = get_settings()
        payload = {
            "code": "internal_error",
            "message": "Error interno del motor",
            "context": {"incident": incident},
        }
        if cfg.debug:
            payload["context"]["detail"] = str(exc)[:500]
        return JSONResponse(status_code=500, content=payload)


def _clean(errors: list[dict]) -> list[dict]:
    out = []
    for error in errors[:20]:
        out.append({
            "field": ".".join(str(p) for p in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        })
    return out
