"""Errores del dominio.

Se traducen a códigos HTTP en `api/errors.py`. El dominio no conoce HTTP.
"""

from __future__ import annotations

from typing import Any


class PowerGisError(Exception):
    """Raíz de todos los errores propios."""

    code = "powergis_error"
    http_status = 500

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


class ValidationError(PowerGisError):
    code = "validation_error"
    http_status = 422


class GeoNotFound(PowerGisError):
    code = "geo_not_found"
    http_status = 404


class ProjectNotFound(PowerGisError):
    code = "project_not_found"
    http_status = 404


class ReportNotReady(PowerGisError):
    code = "report_not_ready"
    http_status = 409


class TierNotAllowed(PowerGisError):
    code = "tier_not_allowed"
    http_status = 403


class NotOwner(PowerGisError):
    """Un project_uuid filtrado no puede abrir el informe de otro usuario."""

    code = "not_owner"
    http_status = 403


class SignatureError(PowerGisError):
    code = "invalid_signature"
    http_status = 401


class ReplayError(PowerGisError):
    code = "stale_request"
    http_status = 401


class CollectorError(PowerGisError):
    """Fallo recuperable de una fuente externa: se reintenta."""

    code = "collector_error"
    http_status = 502


class CollectorUnavailable(CollectorError):
    """La fuente respondió 429/503: hay que esperar."""

    code = "collector_unavailable"


class NarrativeRejected(PowerGisError):
    """El texto generado contenía una cifra que no está en los hechos."""

    code = "narrative_rejected"
    http_status = 422
