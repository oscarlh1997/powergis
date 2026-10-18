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
from .plantilla import PlantillaCollector

log = logging.getLogger(__name__)

_FACTORIES: dict[str, Callable[..., BaseCollector]] = {
    "ine": IneCollector,
    "ine_adrh": AdrhCollector,
    "osm": OsmCollector,
    "aemet": AemetCollector,
    "catastro": CatastroCollector,
    "derived": DerivedCollector,
    "plantilla": PlantillaCollector,
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
        "derived": DerivedCollector(
            facts_lookup=facts_lookup,
            sector=sector,
            # Sin esto el colector de derivados no ve el almacén y no escribe
            # nada: la renta disponible, la resistencia y el gasto en el sector no
            # llegaban a existir. Ver `DerivedCollector.__init__`.
            facts_loader=_cargador_de_hechos(session) if session is not None else None,
        ),
    }
    # La plantilla del equipo de datos va LA ÚLTIMA: el planificador enruta
    # cada indicador al primer colector que lo trae, así que lo que tiene API
    # sigue saliendo de la API. De esos indicadores la plantilla sólo rellena
    # huecos, y para saber cuáles son necesita la lista y el almacén.
    oficiales = {c for col in registry.values() for c in col.provides()}
    registry["plantilla"] = PlantillaCollector(
        facts_loader=_cargador_de_hechos(session) if session is not None else None,
        oficiales=oficiales,
    )
    return registry


def _cargador_de_hechos(session: Session):
    """Lee del almacén el último periodo de cada (geo, indicador), sin segmento."""
    from ..db.repositories import SqlFactRepository

    repo = SqlFactRepository(session)

    def cargar(geo_ids: list[int], codigos: list[str]):
        return repo.fetch(geo_ids, codigos, [{}])

    return cargar


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
    "PlantillaCollector",
    "available",
    "build_registry",
    "coverage_report",
    "indicator_owner",
]
