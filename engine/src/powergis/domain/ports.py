"""Puertos: lo que el dominio necesita del exterior.

Son `Protocol`, no clases base. El dominio depende de estas firmas; los
adaptadores (SQLAlchemy, httpx, Redis, OpenAI) las implementan sin que el
dominio sepa nada de ellos. Ésta es la línea de la arquitectura hexagonal:
nada por encima de este fichero importa nada de `adapters/`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from .enums import GeoLevel, Section, Tier
from .models import (
    Fact,
    Geo,
    Indicator,
    Project,
    Report,
    ReportRun,
    Scope,
    Segments,
)


@runtime_checkable
class GeoRepository(Protocol):
    def get(self, level: GeoLevel, ine_code: str) -> Geo | None: ...

    def get_by_id(self, geo_id: int) -> Geo | None: ...

    def children(self, geo_id: int, level: GeoLevel) -> list[Geo]: ...

    def by_level(self, level: GeoLevel) -> list[Geo]:
        """Todas las geografías de un nivel. Para cargas y comprobaciones."""
        ...

    def descendants(self, geo_id: int, level: GeoLevel) -> list[Geo]:
        """Todos los descendientes a un nivel dado, saltando niveles intermedios."""
        ...

    def search(self, query: str, level: GeoLevel | None = None, limit: int = 20) -> list[Geo]: ...

    def upsert_many(self, geos: Sequence[Geo]) -> int: ...


@runtime_checkable
class IndicatorRepository(Protocol):
    def get(self, code: str) -> Indicator | None: ...

    def by_section(self, section: Section, tier: Tier | None = None) -> list[Indicator]: ...

    def all(self) -> list[Indicator]: ...

    def upsert_many(self, indicators: Sequence[Indicator]) -> int: ...


@runtime_checkable
class FactRepository(Protocol):
    def fetch(
        self,
        geo_ids: Sequence[int],
        indicators: Sequence[str],
        segments: Sequence[dict[str, str]] | None = None,
        period: date | None = None,
    ) -> list[Fact]:
        """Devuelve el último periodo disponible por (geo, indicador, segmento)."""
        ...

    def freshness(self, indicators: Sequence[str], geo_ids: Sequence[int]) -> dict[str, date | None]:
        """Periodo más reciente cargado por indicador. Sirve para decidir ETL."""
        ...

    def upsert_many(self, facts: Sequence[Fact]) -> int: ...

    def coverage(self, geo_ids: Sequence[int], indicators: Sequence[str]) -> float:
        """Fracción de celdas (geo × indicador) con valor no nulo."""
        ...


@runtime_checkable
class ProjectRepository(Protocol):
    def get(self, project_uuid: UUID) -> Project | None: ...

    def save(self, project: Project) -> Project: ...

    def set_tier(self, project_uuid: UUID, tier: Tier) -> None: ...


@runtime_checkable
class RunRepository(Protocol):
    def create(self, run: ReportRun) -> ReportRun: ...

    def get(self, run_id: int) -> ReportRun | None: ...

    def find_by_hash(self, project_uuid: UUID, input_hash: str) -> ReportRun | None: ...

    def update(self, run: ReportRun) -> ReportRun: ...

    def latest_for(self, project_uuid: UUID) -> ReportRun | None: ...


@runtime_checkable
class SnapshotRepository(Protocol):
    def save(self, project_uuid: UUID, version: int, tier: Tier, payload: dict[str, Any]) -> None: ...

    def latest(self, project_uuid: UUID) -> tuple[int, Tier, dict[str, Any]] | None: ...

    def get(self, project_uuid: UUID, version: int) -> dict[str, Any] | None: ...

    def next_version(self, project_uuid: UUID) -> int: ...


@runtime_checkable
class Collector(Protocol):
    """Una fuente externa de datos.

    `provides` declara qué indicadores sabe cargar; el planificador de ETL usa
    esa lista para decidir a quién llamar cuando falta un dato.
    """

    name: str

    def provides(self) -> list[str]: ...

    def collect(
        self,
        indicators: Sequence[str],
        geos: Sequence[Geo],
        segments: Segments,
        period: date | None = None,
    ) -> list[Fact]: ...


@runtime_checkable
class CachePort(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

    def delete(self, key: str) -> None: ...

    def lock(self, key: str, ttl_seconds: int = 60) -> bool: ...

    # `unlock` faltaba en el puerto, y por eso una implementación sin él
    # pasaba desapercibida hasta reventar en ejecución. Un cerrojo que se
    # toma y no se puede soltar no es un cerrojo.
    def unlock(self, key: str) -> None: ...


@runtime_checkable
class NarrativePort(Protocol):
    """Generación de texto. Recibe hechos ya calculados, nunca datos crudos."""

    def zone_narrative(self, facts: dict[str, Any]) -> str: ...

    def executive_summary(self, facts: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class NotifierPort(Protocol):
    """Callback firmado hacia WordPress."""

    def report_ready(
        self,
        callback_url: str,
        project_uuid: UUID,
        tier: Tier,
        version: int,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> bool: ...


@runtime_checkable
class ExporterPort(Protocol):
    extension: str
    media_type: str

    def render(self, report: Report) -> bytes: ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Agrupa los repositorios en una transacción."""

    geos: GeoRepository
    indicators: IndicatorRepository
    facts: FactRepository
    projects: ProjectRepository
    runs: RunRepository
    snapshots: SnapshotRepository

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, *exc: Any) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


__all__ = [
    "CachePort",
    "Collector",
    "ExporterPort",
    "FactRepository",
    "GeoRepository",
    "IndicatorRepository",
    "NarrativePort",
    "NotifierPort",
    "ProjectRepository",
    "RunRepository",
    "Scope",
    "SnapshotRepository",
    "UnitOfWork",
]
