"""Entidades y objetos de valor del dominio.

Dataclasses puras: sin SQLAlchemy, sin Pydantic, sin FastAPI. Esto es lo que
permite testear toda la lógica de negocio sin levantar base de datos.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from .enums import (
    DEFAULT_DIMENSION_WEIGHTS,
    Dimension,
    Direction,
    GeoLevel,
    RunStatus,
    ScoreCategory,
    Section,
    Tier,
    Unit,
)

# --------------------------------------------------------------------------- #
# Geografía
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Geo:
    """Una unidad territorial. `ine_code` es la clave natural."""

    geo_id: int
    level: GeoLevel
    ine_code: str
    name: str
    parent_id: int | None = None
    population: int | None = None
    area_km2: float | None = None

    def __str__(self) -> str:  # pragma: no cover - representación
        return f"{self.name} ({self.level}:{self.ine_code})"


@dataclass(frozen=True, slots=True)
class Scope:
    """Ámbito del análisis: una geografía y el nivel en que se desagrega.

    `children_level` es el nivel de las filas de las «tablas avanzadas».
    Si el usuario pide una CCAA, las filas son sus provincias.
    """

    level: GeoLevel
    ine_code: str
    children_level: GeoLevel | None = None

    def resolve_children_level(self) -> GeoLevel:
        if self.children_level is not None:
            return self.children_level
        child = self.level.child
        if child is None:
            raise ValueError(f"El nivel {self.level} no admite desagregación")
        return child

    def key(self) -> str:
        return f"{self.level}:{self.ine_code}:{self.resolve_children_level()}"


@dataclass(frozen=True, slots=True)
class Segments:
    """Segmentación solicitada por el usuario.

    Se normaliza al construirse para que el hash de idempotencia sea estable
    independientemente del orden en que el formulario mande los valores.
    """

    age: tuple[str, ...] = ()
    sex: tuple[str, ...] = ()
    nationality: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> Segments:
        data = data or {}

        def norm(key: str) -> tuple[str, ...]:
            raw = data.get(key) or []
            if isinstance(raw, str):
                raw = [raw]
            return tuple(sorted({str(v).strip() for v in raw if str(v).strip()}))

        return cls(age=norm("age"), sex=norm("sex"), nationality=norm("nationality"))

    def as_dict(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if self.age:
            out["age"] = list(self.age)
        if self.sex:
            out["sex"] = list(self.sex)
        if self.nationality:
            out["nationality"] = list(self.nationality)
        return out

    def is_empty(self) -> bool:
        return not (self.age or self.sex or self.nationality)


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    """Datos del negocio que el usuario declara en el formulario."""

    sector: str | None = None
    avg_ticket: float | None = None
    surface_m2: float | None = None
    horizon_months: int | None = None
    company_name: str | None = None
    candidate_address: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sector": self.sector,
            "avg_ticket": self.avg_ticket,
            "surface_m2": self.surface_m2,
            "horizon_months": self.horizon_months,
            "company_name": self.company_name,
            "candidate_address": self.candidate_address,
        }


# --------------------------------------------------------------------------- #
# Indicadores y hechos
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Indicator:
    """Definición de un indicador. Es *dato*, no código: vive en dim_indicator."""

    code: str
    section: Section
    subsection: str
    label: str
    unit: Unit
    direction: Direction = Direction.NEUTRAL
    source: str = ""
    min_level: GeoLevel = GeoLevel.MUNICIPIO
    tier: Tier = Tier.AVANZADO
    dimension: Dimension | None = None
    formula: str | None = None
    decimals: int = 2
    description: str = ""

    def available_at(self, level: GeoLevel) -> bool:
        """¿Hay dato de este indicador al nivel pedido?

        `min_level` es la granularidad MÁS FINA publicada. Un indicador
        municipal se puede agregar hacia arriba (provincia, CCAA) pero nunca
        desagregar hacia abajo: pedirlo por sección censal devuelve False.
        """
        return level.rank <= self.min_level.rank


@dataclass(frozen=True, slots=True)
class Fact:
    """Un valor observado. Es la fila de fact_indicator."""

    geo_id: int
    indicator: str
    period: date
    value: float | None
    segment: dict[str, str] = field(default_factory=dict)
    source_ref: str | None = None
    ingested_at: datetime | None = None

    @property
    def is_missing(self) -> bool:
        """`None` significa «no publicado» (secreto estadístico), nunca cero."""
        return self.value is None

    def segment_key(self) -> str:
        return json.dumps(self.segment, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Piezas del informe
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Kpi:
    code: str
    label: str
    value: float | None
    unit: Unit
    direction: Direction = Direction.NEUTRAL
    delta_vs_parent: float | None = None
    percentile: float | None = None
    decimals: int = 2
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "label": self.label,
            "value": self.value,
            "unit": str(self.unit),
            "direction": int(self.direction),
            "delta_vs_parent": self.delta_vs_parent,
            "percentile": self.percentile,
            "decimals": self.decimals,
            "note": self.note,
            "missing": self.value is None,
        }


@dataclass(slots=True)
class Column:
    key: str
    label: str
    type: str = "float"  # text | int | float | pct | eur | index
    decimals: int = 2
    direction: Direction = Direction.NEUTRAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "decimals": self.decimals,
            "direction": int(self.direction),
        }


@dataclass(slots=True)
class Table:
    """La «tabla avanzada» del final de cada sección."""

    id: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    highlights: dict[str, list[str]] = field(default_factory=dict)
    footnote: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "columns": [c.as_dict() for c in self.columns],
            "rows": self.rows,
            "highlights": self.highlights,
            "footnote": self.footnote,
        }


@dataclass(slots=True)
class Chart:
    id: str
    title: str
    type: str  # bar | bar-stacked | line | area | pie | radar | scatter | heatmap
    x: list[str]
    series: list[dict[str, Any]]
    unit: Unit | None = None
    stack: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "x": self.x,
            "series": self.series,
            "unit": str(self.unit) if self.unit else None,
            "stack": self.stack,
        }


@dataclass(slots=True)
class Subsection:
    id: str
    title: str
    kpis: list[Kpi] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    narrative: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kpis": [k.as_dict() for k in self.kpis],
            "charts": [c.as_dict() for c in self.charts],
            "tables": [t.as_dict() for t in self.tables],
            "narrative": self.narrative,
        }


@dataclass(slots=True)
class SectionResult:
    id: Section
    title: str
    available: bool = True
    locked_reason: str | None = None
    subsections: list[Subsection] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    coverage: float = 1.0  # fracción de indicadores con dato
    # Sólo para secciones bloqueadas: QUÉ contiene, nunca CUÁNTO vale.
    # Son etiquetas del catálogo (metadatos del producto), no hechos del
    # cliente. Es el índice de lo que se compra, no una muestra de los datos.
    preview: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        if not self.available:
            # Una sección bloqueada NO lleva datos dentro. Ni uno.
            # `preview` son nombres de indicador del catálogo: si algún día
            # alguien mete aquí un valor calculado, rompe el modelo de negocio
            # y regala el informe. Esa es la razón de que sea list[str].
            return {
                "id": str(self.id),
                "title": self.title,
                "available": False,
                "locked_reason": self.locked_reason or "tier",
                "preview": list(self.preview),
            }
        return {
            "id": str(self.id),
            "title": self.title,
            "available": True,
            "coverage": round(self.coverage, 3),
            "sources": self.sources,
            "subsections": [s.as_dict() for s in self.subsections],
        }


@dataclass(slots=True)
class GeoLensLayer:
    id: str
    label: str
    indicator: str
    level: GeoLevel
    type: str = "choropleth"
    unit: Unit | None = None
    breaks: list[float] = field(default_factory=list)
    palette: str = "sequential-1"
    values: dict[str, float | None] = field(default_factory=dict)
    default_on: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "indicator": self.indicator,
            "level": str(self.level),
            "type": self.type,
            "unit": str(self.unit) if self.unit else None,
            "breaks": self.breaks,
            "palette": self.palette,
            "values": self.values,
            "default_on": self.default_on,
        }


@dataclass(slots=True)
class PlaceRankRow:
    geo_code: str
    geo_name: str
    score: float
    category: ScoreCategory
    dimensions: dict[Dimension, float]
    contributions: dict[str, float] = field(default_factory=dict)
    narrative: str | None = None
    rank: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "geo_code": self.geo_code,
            "geo_name": self.geo_name,
            "score": round(self.score, 2),
            "category": str(self.category),
            "dimensions": {str(k): round(v, 2) for k, v in self.dimensions.items()},
            "contributions": {k: round(v, 4) for k, v in self.contributions.items()},
            "narrative": self.narrative,
        }


@dataclass(slots=True)
class PlaceRankResult:
    weights: dict[Dimension, float] = field(default_factory=lambda: dict(DEFAULT_DIMENSION_WEIGHTS))
    rows: list[PlaceRankRow] = field(default_factory=list)
    method: str = "percentil normalizado dentro del ámbito consultado"

    def as_dict(self) -> dict[str, Any]:
        return {
            "weights": {str(k): v for k, v in self.weights.items()},
            "method": self.method,
            "rows": [r.as_dict() for r in self.rows],
        }


@dataclass(slots=True)
class Report:
    """El payload que consume el front. Una sola forma para todas las secciones."""

    project_uuid: UUID
    tier: Tier
    version: int
    engine_version: str
    generated_at: datetime
    scope: dict[str, Any]
    segments: dict[str, list[str]]
    business: dict[str, Any]
    sections: list[SectionResult] = field(default_factory=list)
    geolens: dict[str, Any] = field(default_factory=dict)
    placerank: dict[str, Any] | None = None
    executive_summary: dict[str, Any] | None = None
    glossary: list[dict[str, str]] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_uuid": str(self.project_uuid),
            "tier": str(self.tier),
            "version": self.version,
            "engine_version": self.engine_version,
            "generated_at": self.generated_at.isoformat(),
            "scope": self.scope,
            "segments": self.segments,
            "business": self.business,
            "sections": [s.as_dict() for s in self.sections],
            "geolens": self.geolens,
            "placerank": self.placerank,
            "executive_summary": self.executive_summary,
            "glossary": self.glossary,
            "sources": self.sources,
            "warnings": self.warnings,
        }


# --------------------------------------------------------------------------- #
# Proyecto y ejecución
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Project:
    project_uuid: UUID
    wp_user_id: int
    scope: Scope
    segments: Segments
    business: BusinessProfile
    tier: Tier = Tier.BASICO
    wp_post_id: int | None = None
    created_at: datetime | None = None
    # Perfil de cliente objetivo declarado en el formulario. Alimenta la
    # dimensión Match del PlaceRank (`domain.target.TargetProfile`).
    target: Any = None

    def input_hash(self, tier: Tier | None = None) -> str:
        """Hash estable de las entradas. Base de la idempotencia."""
        payload = {
            "scope": {
                "level": str(self.scope.level),
                "ine_code": self.scope.ine_code,
                "children_level": str(self.scope.resolve_children_level()),
            },
            "segments": self.segments.as_dict(),
            "sector": self.business.sector,
            # Si cambia el perfil objetivo, cambia el Match% y por tanto el
            # informe: tiene que entrar en la idempotencia.
            "target": self.target.as_dict() if self.target else None,
            "tier": str(tier or self.tier),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ReportRun:
    run_id: int | None
    project_uuid: UUID
    tier: Tier
    status: RunStatus
    engine_version: str
    input_hash: str
    sections_done: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def mark_section(self, section: Section) -> None:
        if str(section) not in self.sections_done:
            self.sections_done.append(str(section))

    def pending(self, wanted: list[Section]) -> list[Section]:
        done = set(self.sections_done)
        return [s for s in wanted if str(s) not in done]
