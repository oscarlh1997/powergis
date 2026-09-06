"""Registro de colectores.

Añadir una fuente nueva es: escribir la clase, declarar `PROVIDES` y
registrarla aquí. Ni el planificador de ETL ni las secciones cambian.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from ...domain.ports import Collector
from .aemet import AemetCollector
from .base import BaseCollector, HttpClient
from .catastro import CatastroCollector
from .derived import DerivedCollector
from .ine import IneCollector
from .ine_adrh import AdrhCollector
from .osm import OsmCollector

log = logging.getLogger(__name__)

_FACTORIES: dict[str, Callable[..., BaseCollector]] = {
    "ine": IneCollector,
    "ine_adrh": AdrhCollector,
    "osm": OsmCollector,
    "aemet": AemetCollector,
    "catastro": CatastroCollector,
    "derived": DerivedCollector,
}


def build_registry(
    session: Session | None = None,
    *,
    sector: str = "generico",
    facts_lookup=None,
    centroids: dict[int, tuple[float, float, float]] | None = None,
) -> dict[str, Collector]:
    """Instancia los colectores con lo que cada uno necesita."""
    registry: dict[str, Collector] = {
        "ine": IneCollector(),
        "ine_adrh": AdrhCollector(),
        "aemet": AemetCollector(centroids=centroids),
        "catastro": CatastroCollector(),
        "osm": OsmCollector(session=session, sector=sector),
        "derived": DerivedCollector(facts_lookup=facts_lookup, sector=sector),
    }
    return registry


def available() -> list[str]:
    return sorted(_FACTORIES)


def indicator_owner(code: str, registry: dict[str, Collector]) -> str | None:
    for name, collector in registry.items():
        if code in collector.provides():
            return name
    return None


def coverage_report(registry: dict[str, Collector]) -> dict[str, list[str]]:
    """Qué indicadores del catálogo no tienen colector. Se ejecuta en CI."""
    from ...domain import indicators as catalog

    routed: set[str] = set()
    for collector in registry.values():
        routed.update(collector.provides())

    orphans = [i.code for i in catalog.CATALOG if i.code not in routed]
    return {
        "routed": sorted(routed),
        "orphans": sorted(orphans),
    }


__all__ = [
    "AdrhCollector",
    "AemetCollector",
    "CatastroCollector",
    "DerivedCollector",
    "HttpClient",
    "IneCollector",
    "OsmCollector",
    "available",
    "build_registry",
    "coverage_report",
    "indicator_owner",
]
