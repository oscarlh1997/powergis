"""Cliente LLM compatible con OpenAI (AI Router de Hostinger, OpenAI, etc.).

Dos modelos: uno rápido y barato para las descripciones por zona (son decenas
por informe) y uno grande solo para el resumen ejecutivo y las recomendaciones
finales. Nunca en el camino crítico: la generación va en cola aparte y el
informe se publica sin ella.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ...config import get_settings
from ...domain.errors import CollectorError

log = logging.getLogger(__name__)


class LlmClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ) -> None:
        cfg = get_settings()
        self._base_url = (base_url or cfg.llm_base_url).rstrip("/")
        self._api_key = api_key or cfg.llm_api_key
        self._timeout = timeout or cfg.llm_timeout
        self._retries = cfg.llm_max_retries
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def close(self) -> None:
        self._client.close()

    def complete_json(
        self,
        model: str,
        system: str,
        user: dict[str, Any] | str,
        *,
        schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> dict[str, Any]:
        """Pide salida estructurada. Devuelve dict o lanza CollectorError."""
        content = user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "powergis", "strict": True, "schema": schema},
            }
        else:
            payload["response_format"] = {"type": "json_object"}

        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = self._client.post(f"{self._base_url}/chat/completions", json=payload)
                if response.status_code >= 400:
                    raise CollectorError(
                        "El proveedor de LLM devolvió error",
                        status=response.status_code, body=response.text[:300],
                    )
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                return json.loads(text)
            except (httpx.RequestError, KeyError, json.JSONDecodeError, CollectorError) as exc:
                last = exc
                log.warning("LLM intento %s falló: %s", attempt + 1, exc)
        raise CollectorError("LLM inalcanzable tras reintentos", cause=str(last))


class NullLlmClient:
    """Sustituto cuando no hay API key. Nunca rompe el informe."""

    enabled = False

    def complete_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise CollectorError("LLM deshabilitado")

    def close(self) -> None:
        return None


def build_client() -> LlmClient | NullLlmClient:
    cfg = get_settings()
    if not cfg.llm_enabled or not cfg.llm_api_key:
        return NullLlmClient()
    return LlmClient()
