"""Base común de los colectores.

Cliente HTTP con límite de tasa, reintentos con backoff exponencial y respeto
del 429/Retry-After. Ninguna fuente pública tolera que la martilleemos, y la
alternativa a hacerlo bien es que nos bloqueen en producción.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from typing import Any

import httpx

from ...domain.errors import CollectorError, CollectorUnavailable
from ...domain.models import Fact, Geo, Segments

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class RateLimiter:
    """Límite de peticiones por segundo, seguro entre hilos."""

    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class HttpClient:
    def __init__(
        self,
        base_url: str = "",
        *,
        timeout: int = 60,
        max_retries: int = 4,
        rps: float = 2.0,
        headers: dict[str, str] | None = None,
        user_agent: str = "PowerGIS/1.0 (+https://powergis.es; contacto@powergis.es)",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._limiter = RateLimiter(rps)
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": user_agent, **(headers or {})},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._decode_json(self._request("GET", path, params=params))

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any:
        """Convierte «esto no es JSON» en un diagnóstico legible.

        `_request` ya ha descartado los 4xx/5xx, así que llegar aquí significa
        que la fuente contestó *bien* y aun así el cuerpo no se puede leer. Es
        el fallo más caro de diagnosticar de todos: el INE, cuando una consulta
        le viene grande, responde 200 con el cuerpo vacío en vez de un error, y
        `httpx` lo traduce a un `JSONDecodeError` pelado — «Expecting value:
        line 1 column 1 (char 0)» — que no dice ni qué URL era ni qué llegó.

        Aquí se guarda todo lo que hace falta para saberlo sin volver a
        lanzarlo: URL final (tras redirecciones), código, tipo de contenido,
        tamaño y los primeros bytes.
        """
        try:
            return response.json()
        except ValueError as exc:
            cuerpo = response.text
            muestra = cuerpo[:300].strip() or "(cuerpo vacío)"
            tipo = response.headers.get("content-type", "(sin cabecera)")
            raise CollectorError(
                f"La fuente respondió {response.status_code} pero el cuerpo no es JSON.\n"
                f"  URL:     {response.request.url}\n"
                f"  Tipo:    {tipo}\n"
                f"  Tamaño:  {len(response.content)} bytes\n"
                f"  Empieza: {muestra}",
                url=str(response.request.url),
                status=response.status_code,
                content_type=tipo,
                length=len(response.content),
                body=muestra,
                cause=str(exc),
            ) from exc

    def post_text(self, path: str, data: str, params: dict[str, Any] | None = None) -> str:
        return self._request("POST", path, params=params, content=data).text

    # ------------------------------------------------------------------ #

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            self._limiter.wait()
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                last_error = exc
                self._sleep(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS:
                if attempt >= self._max_retries:
                    if response.status_code == 429:
                        raise CollectorUnavailable(
                            "Fuente limitando la tasa de peticiones",
                            url=url, status=response.status_code,
                        )
                    raise CollectorError(
                        "Fuente no disponible tras reintentos",
                        url=url, status=response.status_code,
                    )
                self._sleep(attempt, response.headers.get("Retry-After"))
                continue

            if response.status_code >= 400:
                raise CollectorError(
                    "Respuesta de error de la fuente",
                    url=url, status=response.status_code, body=response.text[:300],
                )
            return response

        raise CollectorError("Fuente inalcanzable", url=url, cause=str(last_error))

    @staticmethod
    def _sleep(attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 60.0))
                return
            except ValueError:
                pass
        # Backoff exponencial con jitter: evita que N workers reintenten a la vez.
        # Jitter para que N workers no reintenten a la vez. No es criptografía.
        delay = min(2**attempt, 30) + random.uniform(0, 1.0)  # noqa: S311
        time.sleep(delay)


# --------------------------------------------------------------------------- #


class BaseCollector(ABC):
    """Contrato de un colector.

    `PROVIDES` declara qué indicadores sabe cargar. El planificador de ETL usa
    esa lista para enrutar; añadir una fuente nueva no toca ningún otro sitio.
    """

    name: str = "base"
    PROVIDES: tuple[str, ...] = ()

    def provides(self) -> list[str]:
        return list(self.PROVIDES)

    @abstractmethod
    def collect(
        self,
        indicators: Sequence[str],
        geos: Sequence[Geo],
        segments: Segments,
        period: date | None = None,
    ) -> list[Fact]: ...

    # -- utilidades compartidas ---------------------------------------- #

    @staticmethod
    def fact(
        geo: Geo,
        indicator: str,
        value: float | None,
        period: date,
        segment: dict[str, str] | None = None,
        source_ref: str | None = None,
    ) -> Fact:
        return Fact(
            geo_id=geo.geo_id,
            indicator=indicator,
            period=period,
            value=value,
            segment=segment or {},
            source_ref=source_ref,
        )

    @staticmethod
    def to_float(raw: Any) -> float | None:
        """Convierte respetando el hueco: '..', '', None → None, nunca 0."""
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        text = str(raw).strip()
        if text in {"", "..", ".", "-", "n/a", "N/A", "null"}:
            return None
        text = text.replace(".", "").replace(",", ".") if _looks_es(text) else text
        try:
            return float(text)
        except ValueError:
            return None


def _looks_es(text: str) -> bool:
    """'1.234,56' es español; '1234.56' no."""
    return "," in text and (text.rfind(",") > text.rfind("."))


def chunked(items: Sequence[Any], size: int):
    for i in range(0, len(items), size):
        yield list(items[i:i + size])
