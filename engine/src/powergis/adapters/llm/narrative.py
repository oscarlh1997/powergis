"""Generación de textos con verificación de cifras.

Las cinco reglas de ingeniería, todas implementadas aquí:

1. **La IA no ve datos crudos.** Recibe hechos ya calculados: 10-20 valores
   con nombre, unidad, percentil y contribución al score.
2. **Caché por hash de los hechos**, no por proyecto. Dos usuarios que pidan
   Madrid con el mismo perfil comparten el texto.
3. **Salida estructurada validada** con Pydantic. Si no valida, reintento; a
   los dos fallos, plantilla determinista. Un informe de pago no se queda sin
   texto.
4. **Verificación de cifras**: se extraen los números del texto generado y se
   comprueba que existen en los hechos de entrada. Si aparece uno que no está,
   se rechaza. Es barato y evita el peor fallo posible.
5. **Modelo pequeño para las zonas, grande solo para el resumen.**
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ...config import get_settings
from .client import LlmClient, NullLlmClient, build_client

log = logging.getLogger(__name__)

_NUMBER = re.compile(r"-?\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|-?\d+(?:\.\d+)?")

SYSTEM_ZONE = """Eres analista de geomarketing. Redactas en español de España,
en tono profesional y directo, para un empresario que evalúa dónde abrir.

REGLAS ABSOLUTAS:
- Usa ÚNICAMENTE las cifras que aparecen en los datos que recibes.
- NO inventes ningún número, porcentaje, ranking, nombre de zona ni fecha.
- Si un dato no está, no lo menciones. No lo estimes. No lo redondees a un
  valor distinto del que se te da.
- No hagas promesas de rentabilidad ni recomendaciones de inversión.
- Máximo 90 palabras por campo de texto.
Devuelve exclusivamente JSON válido con el esquema pedido."""

SYSTEM_SUMMARY = """Eres analista senior de geomarketing. Redactas el resumen
ejecutivo de un informe de localización comercial, en español de España.

REGLAS ABSOLUTAS:
- Usa ÚNICAMENTE las cifras de los datos recibidos. Cero invenciones.
- Señala también los riesgos, no solo lo positivo.
- Si la cobertura de datos es baja, dilo explícitamente.
- No garantices resultados económicos.
Devuelve exclusivamente JSON válido con el esquema pedido."""


class ZoneNarrative(BaseModel):
    resumen: str = Field(max_length=700)
    fortalezas: list[str] = Field(default_factory=list, max_length=4)
    riesgos: list[str] = Field(default_factory=list, max_length=4)


class ExecutiveNarrative(BaseModel):
    resumen: str = Field(max_length=1400)
    fortalezas: list[str] = Field(default_factory=list, max_length=6)
    riesgos: list[str] = Field(default_factory=list, max_length=6)
    recomendacion: str = Field(max_length=900)


ZONE_SCHEMA = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "fortalezas": {"type": "array", "items": {"type": "string"}},
        "riesgos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["resumen", "fortalezas", "riesgos"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "fortalezas": {"type": "array", "items": {"type": "string"}},
        "riesgos": {"type": "array", "items": {"type": "string"}},
        "recomendacion": {"type": "string"},
    },
    "required": ["resumen", "fortalezas", "riesgos", "recomendacion"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Verificación de cifras
# --------------------------------------------------------------------------- #


def extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    for raw in _NUMBER.findall(text or ""):
        cleaned = raw.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            out.append(float(cleaned))
        except ValueError:
            continue
    return out


def allowed_numbers(facts: Any) -> set[float]:
    """Todos los números presentes en los hechos, más sus redondeos razonables."""
    found: set[float] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            found.add(float(node))

    walk(facts)

    expanded: set[float] = set()
    for value in found:
        expanded.add(value)
        expanded.add(round(value))
        expanded.add(round(value, 1))
        expanded.add(round(value, 2))
        if abs(value) >= 1000:
            expanded.add(round(value / 1000.0, 1))  # «1,5 millones» / miles
            expanded.add(round(value / 1000.0))
    # Ordinales y cifras de uso común que no son afirmaciones de datos.
    expanded.update({0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 100.0})
    return expanded


def verify_numbers(text: str, facts: Any, tolerance: float = 0.02) -> list[float]:
    """Devuelve las cifras del texto que NO están respaldadas por los hechos."""
    allowed = allowed_numbers(facts)
    unsupported: list[float] = []
    for number in extract_numbers(text):
        if any(_close(number, candidate, tolerance) for candidate in allowed):
            continue
        unsupported.append(number)
    return unsupported


def _close(a: float, b: float, tolerance: float) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) / scale <= tolerance


def facts_hash(facts: Any, kind: str, model: str) -> str:
    blob = json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{kind}|{model}|{blob}".encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Servicio
# --------------------------------------------------------------------------- #


class NarrativeService:
    def __init__(
        self,
        client: LlmClient | NullLlmClient | None = None,
        cache=None,
    ) -> None:
        cfg = get_settings()
        self._client = client or build_client()
        self._cache = cache
        self._fast = cfg.llm_model_fast
        self._deep = cfg.llm_model_deep
        self._ttl = cfg.llm_cache_ttl

    # ------------------------------------------------------------------ #

    def zone_narrative(self, facts: dict[str, Any]) -> str:
        result = self._generate(
            facts, kind="zone", model=self._fast,
            system=SYSTEM_ZONE, schema=ZONE_SCHEMA, validator=ZoneNarrative,
            fallback=_template_zone,
        )
        return result.get("resumen", "")

    def zone_full(self, facts: dict[str, Any]) -> dict[str, Any]:
        return self._generate(
            facts, kind="zone", model=self._fast,
            system=SYSTEM_ZONE, schema=ZONE_SCHEMA, validator=ZoneNarrative,
            fallback=_template_zone,
        )

    def executive_summary(self, facts: dict[str, Any]) -> dict[str, Any]:
        return self._generate(
            facts, kind="summary", model=self._deep,
            system=SYSTEM_SUMMARY, schema=SUMMARY_SCHEMA, validator=ExecutiveNarrative,
            fallback=_template_summary,
        )

    # ------------------------------------------------------------------ #

    def _generate(
        self,
        facts: dict[str, Any],
        *,
        kind: str,
        model: str,
        system: str,
        schema: dict[str, Any],
        validator: type[BaseModel],
        fallback,
    ) -> dict[str, Any]:
        key = facts_hash(facts, kind, model)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        if not getattr(self._client, "enabled", False):
            return fallback(facts)

        attempts = 2
        for attempt in range(attempts):
            try:
                raw = self._client.complete_json(model, system, facts, schema=schema)
                parsed = validator.model_validate(raw)
            except ValidationError as exc:
                log.warning("Narrativa %s: salida no válida (%s/%s): %s", kind, attempt + 1, attempts, exc)
                continue
            except Exception as exc:
                log.warning("Narrativa %s: fallo del proveedor (%s/%s): %s", kind, attempt + 1, attempts, exc)
                continue

            payload = parsed.model_dump()
            unsupported = self._audit(payload, facts)
            if unsupported:
                log.warning(
                    "Narrativa %s RECHAZADA: cifras no respaldadas %s", kind, unsupported[:5]
                )
                continue

            self._cache_put(key, payload)
            return payload

        log.info("Narrativa %s: se usa plantilla determinista", kind)
        return fallback(facts)

    def _audit(self, payload: dict[str, Any], facts: Any) -> list[float]:
        texts: list[str] = []
        for value in payload.values():
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                texts.extend(v for v in value if isinstance(v, str))
        unsupported: list[float] = []
        for text in texts:
            unsupported.extend(verify_numbers(text, facts))
        return unsupported

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        if self._cache is None:
            return None
        try:
            return self._cache.get(f"narrative:{key}")
        except Exception:
            return None

    def _cache_put(self, key: str, payload: dict[str, Any]) -> None:
        if self._cache is None:
            return
        try:
            self._cache.set(f"narrative:{key}", payload, self._ttl)
        except Exception as exc:
            log.debug("operación auxiliar falló: %s", exc)


# --------------------------------------------------------------------------- #
# Plantillas deterministas — el informe nunca se queda sin texto
# --------------------------------------------------------------------------- #


def _template_zone(facts: dict[str, Any]) -> dict[str, Any]:
    zona = facts.get("zona", "La zona")
    posicion = facts.get("posicion")
    score = facts.get("score")
    categoria = facts.get("categoria", "")
    drivers: Iterable[dict] = facts.get("factores", []) or []

    positivos = [d["label"] for d in drivers if d.get("contribution", 0) > 0][:3]
    negativos = [d["label"] for d in drivers if d.get("contribution", 0) <= 0][:3]

    partes = [f"{zona} obtiene una puntuación de {score} sobre 100"]
    if categoria:
        partes.append(f"y se clasifica como «{categoria}»")
    if posicion:
        partes.append(f"ocupando la posición {posicion} del ámbito analizado")
    resumen = ", ".join(partes) + "."
    if positivos:
        resumen += f" Los factores que más aportan son: {', '.join(positivos)}."

    return {
        "resumen": resumen,
        "fortalezas": positivos,
        "riesgos": negativos,
        "generated_by": "plantilla",
    }


def _template_summary(facts: dict[str, Any]) -> dict[str, Any]:
    ambito = facts.get("ambito", "el ámbito analizado")
    zonas = facts.get("zonas_comparadas")
    mejores = [z.get("zona") for z in (facts.get("mejores_zonas") or [])][:3]
    peores = [z.get("zona") for z in (facts.get("peores_zonas") or [])][:3]

    resumen = f"Análisis de {ambito}"
    if zonas:
        resumen += f" sobre {zonas} zonas comparables"
    resumen += "."
    if mejores:
        resumen += f" Zonas mejor valoradas: {', '.join(m for m in mejores if m)}."
    if peores:
        resumen += f" Zonas con menor puntuación: {', '.join(p for p in peores if p)}."

    return {
        "resumen": resumen,
        "fortalezas": [f"Mejor posicionada: {mejores[0]}"] if mejores else [],
        "riesgos": ["Cobertura de datos parcial en algunas secciones"]
        if facts.get("cobertura_baja") else [],
        "recomendacion": (
            "Revise las tablas comparativas de cada sección antes de decidir. "
            "Este resumen se ha generado con plantilla determinista porque la "
            "generación asistida no estaba disponible."
        ),
        "generated_by": "plantilla",
    }
