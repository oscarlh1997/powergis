"""Núcleo de dominio de PowerGIS.

Regla de la arquitectura hexagonal, verificada en tests:
NADA dentro de `domain/` importa de `adapters/`, `api/` ni `workers/`.
"""

from . import errors, geolens, indicators, placerank, report, stats
from .enums import (
    BreakMethod,
    Dimension,
    Direction,
    GeoLevel,
    RunStatus,
    ScoreCategory,
    Section,
    Tier,
    Unit,
)
from .models import (
    BusinessProfile,
    Fact,
    Geo,
    Indicator,
    Kpi,
    Project,
    Report,
    ReportRun,
    Scope,
    SectionResult,
    Segments,
    Subsection,
    Table,
)
from .sections import REGISTRY, SectionContext

__all__ = [
    "REGISTRY",
    "BreakMethod",
    "BusinessProfile",
    "Dimension",
    "Direction",
    "Fact",
    "Geo",
    "GeoLevel",
    "Indicator",
    "Kpi",
    "Project",
    "Report",
    "ReportRun",
    "RunStatus",
    "Scope",
    "ScoreCategory",
    "Section",
    "SectionContext",
    "SectionResult",
    "Segments",
    "Subsection",
    "Table",
    "Tier",
    "Unit",
    "errors",
    "geolens",
    "indicators",
    "placerank",
    "report",
    "stats",
]
