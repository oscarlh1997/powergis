"""Callback firmado hacia WordPress.

Cuando el informe está listo, el motor avisa a `saas/v1/projects/callback`.
WordPress verifica la firma, publica el CPT, asigna `report_tier` / `sector` /
`location` y purga la caché de LiteSpeed.

Reintentos: 3 intentos con backoff. Si aun así falla, WordPress puede
recuperar el estado por sondeo (`GET /v1/reports/{uuid}`), así que un callback
perdido nunca deja un proyecto colgado para siempre.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import UUID

import httpx

from ..api.security import sign
from ..config import get_settings
from ..domain.enums import Tier

log = logging.getLogger(__name__)


class WordPressNotifier:
    def __init__(self, timeout: int = 15, retries: int = 3) -> None:
        self._timeout = timeout
        self._retries = retries
        self._client = httpx.Client(timeout=httpx.Timeout(timeout))

    def close(self) -> None:
        self._client.close()

    def report_ready(
        self,
        callback_url: str,
        project_uuid: UUID,
        tier: Tier,
        version: int,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> bool:
        cfg = get_settings()
        payload = {
            "project_uuid": str(project_uuid),
            "tier": str(tier),
            "version": version,
            "status": status,
            "engine_version": cfg.engine_version,
            "error": error,
        }
        return self._post(callback_url or cfg.callback_url, payload)

    def narrative_ready(self, callback_url: str, project_uuid: UUID, version: int) -> bool:
        return self._post(callback_url, {
            "project_uuid": str(project_uuid),
            "version": version,
            "status": "narrative_ready",
        })

    # ------------------------------------------------------------------ #

    def _post(self, url: str, payload: dict[str, Any]) -> bool:
        # Serializar UNA vez y firmar exactamente esos bytes.
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", **sign(body).as_dict()}

        for attempt in range(self._retries):
            try:
                response = self._client.post(url, content=body, headers=headers)
                if response.status_code < 300:
                    return True
                log.warning(
                    "Callback a WordPress devolvió %s (%s/%s): %s",
                    response.status_code, attempt + 1, self._retries, response.text[:200],
                )
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    return False  # error del cliente: reintentar no arregla nada
            except httpx.RequestError as exc:
                log.warning("Callback a WordPress falló (%s/%s): %s", attempt + 1, self._retries, exc)
            time.sleep(2 ** attempt)
        return False


class NullNotifier:
    def report_ready(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def narrative_ready(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def close(self) -> None:
        return None
