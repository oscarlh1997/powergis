"""Infraestructura común de las secciones del informe.

`SectionBuilder` recibe un `SectionContext` (geografías + hechos ya cargados)
y devuelve un `SectionResult`. No sabe de base de datos ni de HTTP: se le dan
los hechos y devuelve estructura. Eso permite testear una sección entera con
un diccionario en memoria.

Registrar una sección nueva:

    @register
    class MiSeccion(SectionBuilder):
        section = Section.LO_QUE_SEA
        title = "..."
        def build(self, ctx): ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .. import stats
from ..enums import Direction, GeoLevel, Section, Tier, Unit
from ..models import (
    Chart,
    Column,
    Fact,
    Geo,
    Indicator,
    Kpi,
    Scope,
    SectionResult,
    Segments,
    Subsection,
    Table,
)

# --------------------------------------------------------------------------- #
# Contexto
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class SectionContext:
    """Todo lo que una sección necesita, ya resuelto."""

    scope: Scope
    parent: Geo
    children: list[Geo]
    segments: Segments
    tier: Tier
    catalog: dict[str, Indicator]
    facts: dict[tuple[int, str, str], Fact] = field(default_factory=dict)
    business: dict[str, Any] = field(default_factory=dict)
    target: Any = None          # domain.target.TargetProfile
    warnings: list[str] = field(default_factory=list)

    # -- acceso a hechos ----------------------------------------------------

    @staticmethod
    def segment_key(segment: dict[str, str] | None) -> str:
        import json

        return json.dumps(segment or {}, sort_keys=True, separators=(",", ":"))

    @classmethod
    def index(cls, facts: Iterable[Fact]) -> dict[tuple[int, str, str], Fact]:
        return {(f.geo_id, f.indicator, cls.segment_key(f.segment)): f for f in facts}

    def value(
        self,
        geo_id: int,
        indicator: str,
        segment: dict[str, str] | None = None,
    ) -> float | None:
        fact = self.facts.get((geo_id, indicator, self.segment_key(segment)))
        return fact.value if fact else None

    def series(
        self,
        indicator: str,
        segment: dict[str, str] | None = None,
    ) -> list[tuple[Geo, float | None]]:
        """El indicador para todas las zonas hijas, en orden de la tabla."""
        return [(g, self.value(g.geo_id, indicator, segment)) for g in self.children]

    def values(self, indicator: str, segment: dict[str, str] | None = None) -> list[float | None]:
        return [v for _, v in self.series(indicator, segment)]

    def parent_value(self, indicator: str, segment: dict[str, str] | None = None) -> float | None:
        """Valor del ámbito completo. Si no está cargado, se agrega desde los hijos."""
        direct = self.value(self.parent.geo_id, indicator, segment)
        if direct is not None:
            return direct
        ind = self.catalog.get(indicator)
        vals = self.values(indicator, segment)
        if ind is not None and ind.unit in {Unit.PERSONAS, Unit.UNIDADES, Unit.MM}:
            return stats.total(vals)
        weights = [self.value(g.geo_id, "dem.pop.total") for g in self.children]
        if any(w is not None for w in weights):
            return stats.weighted_mean(vals, weights)
        return stats.mean(vals)

    def has_any(self, indicators: Sequence[str]) -> bool:
        return any(v is not None for code in indicators for v in self.values(code))

    def coverage(self, indicators: Sequence[str]) -> float:
        cells = len(self.children) * len(indicators)
        if cells == 0:
            return 0.0
        filled = sum(1 for code in indicators for v in self.values(code) if v is not None)
        return filled / cells


# --------------------------------------------------------------------------- #
# Ayudas de construcción
# --------------------------------------------------------------------------- #

_TYPE_BY_UNIT: dict[Unit, str] = {
    Unit.PERSONAS: "int",
    Unit.UNIDADES: "int",
    Unit.PORCENTAJE: "pct",
    Unit.EUROS: "eur",
    Unit.INDICE: "index",
    Unit.RATIO: "float",
    Unit.ANIOS: "float",
    Unit.GRADOS_C: "float",
    Unit.MM: "float",
    Unit.DIAS: "int",
    Unit.KM2: "float",
}


def column_for(ind: Indicator, key: str | None = None, label: str | None = None) -> Column:
    return Column(
        key=key or ind.code,
        label=label or ind.label,
        type=_TYPE_BY_UNIT.get(ind.unit, "float"),
        decimals=ind.decimals,
        direction=ind.direction,
    )


def kpi_from(
    ctx: SectionContext,
    code: str,
    *,
    segment: dict[str, str] | None = None,
    label: str | None = None,
    note: str | None = None,
) -> Kpi:
    """KPI del ámbito completo, con su delta y percentil contra las zonas hijas."""
    ind = ctx.catalog.get(code)
    value = ctx.parent_value(code, segment)
    unit = ind.unit if ind else Unit.INDICE
    child_values = ctx.values(code, segment)
    return Kpi(
        code=code,
        label=label or (ind.label if ind else code),
        value=value,
        unit=unit,
        direction=ind.direction if ind else Direction.NEUTRAL,
        delta_vs_parent=None,
        percentile=stats.percentile_of(value, child_values) if child_values else None,
        decimals=ind.decimals if ind else 2,
        note=note or (_missing_note(child_values) if value is None else None),
    )


def _missing_note(child_values: Sequence[float | None]) -> str | None:
    if child_values and all(v is None for v in child_values):
        return "Dato no disponible por secreto estadístico en este ámbito"
    return "Dato no disponible"


def build_table(
    ctx: SectionContext,
    table_id: str,
    title: str,
    codes: Sequence[str],
    *,
    segment: dict[str, str] | None = None,
    highlight_by: str | None = None,
    footnote: str | None = None,
    extra_columns: Sequence[tuple[Column, Callable[[Geo], Any]]] = (),
) -> Table:
    """La «tabla avanzada»: una fila por zona hija, una columna por indicador.

    `highlight_by` marca las 3 mejores y las 3 peores según la dirección del
    indicador elegido. Es lo que alimenta el bloque de conclusiones.
    """
    columns: list[Column] = [Column(key="zona", label="Zona", type="text")]
    columns += [column_for(ctx.catalog[c]) for c in codes if c in ctx.catalog]
    columns += [col for col, _ in extra_columns]

    rows: list[dict[str, Any]] = []
    for geo in ctx.children:
        row: dict[str, Any] = {
            "geo_code": geo.ine_code,
            "geo_id": geo.geo_id,
            "zona": geo.name,
        }
        for code in codes:
            if code in ctx.catalog:
                row[code] = ctx.value(geo.geo_id, code, segment)
        for col, fn in extra_columns:
            row[col.key] = fn(geo)
        rows.append(row)

    highlights: dict[str, list[str]] = {}
    if highlight_by and highlight_by in ctx.catalog:
        direction = ctx.catalog[highlight_by].direction or Direction.HIGHER_IS_BETTER
        pairs = [(r["geo_code"], r.get(highlight_by)) for r in rows]
        highlights = stats.top_bottom(pairs, n=3, direction=direction)

    return Table(id=table_id, title=title, columns=columns, rows=rows,
                 highlights=highlights, footnote=footnote)


def build_chart(
    ctx: SectionContext,
    chart_id: str,
    title: str,
    codes: Sequence[str],
    *,
    chart_type: str = "bar",
    stack: bool = False,
    limit: int = 25,
    segment: dict[str, str] | None = None,
) -> Chart:
    """Gráfico con una serie por indicador y una categoría por zona."""
    geos = ctx.children[:limit]
    x = [g.name for g in geos]
    series: list[dict[str, Any]] = []
    for code in codes:
        ind = ctx.catalog.get(code)
        series.append({
            "name": ind.label if ind else code,
            "code": code,
            "data": [ctx.value(g.geo_id, code, segment) for g in geos],
        })
    unit = ctx.catalog[codes[0]].unit if codes and codes[0] in ctx.catalog else None
    return Chart(id=chart_id, title=title, type=chart_type, x=x, series=series,
                 unit=unit, stack=stack)


# --------------------------------------------------------------------------- #
# Builder + registro
# --------------------------------------------------------------------------- #


class SectionBuilder(ABC):
    section: Section
    title: str
    tier: Tier = Tier.AVANZADO
    min_level: GeoLevel = GeoLevel.MUNICIPIO

    @property
    def indicator_codes(self) -> list[str]:
        from .. import indicators as catalog

        return [i.code for i in catalog.by_section(self.section)]

    def allowed(self, tier: Tier) -> bool:
        return self.tier in tier.includes

    def preview_labels(self, limit: int = 6) -> list[str]:
        """Índice de venta de una sección bloqueada.

        Sale del CATÁLOGO, no del contexto: son los nombres de los indicadores
        que la sección contiene ("Renta media por hogar"), no sus valores para
        esta consulta. Por eso no recibe `ctx` — no tiene con qué filtrar un
        dato aunque alguien lo intente.
        """
        from .. import indicators as catalog

        labels: list[str] = []
        for ind in catalog.by_section(self.section):
            label = (ind.label or "").strip()
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    def build(self, ctx: SectionContext) -> SectionResult:
        if not self.allowed(ctx.tier):
            return SectionResult(
                id=self.section,
                title=self.title,
                available=False,
                locked_reason="tier",
                preview=self.preview_labels(),
            )
        subsections = self.subsections(ctx)
        codes = self.indicator_codes
        sources = sorted({
            ctx.catalog[c].source for c in codes if c in ctx.catalog and ctx.catalog[c].source
        })
        return SectionResult(
            id=self.section,
            title=self.title,
            available=True,
            subsections=[s for s in subsections if s is not None],
            sources=sources,
            coverage=ctx.coverage(codes),
        )

    @abstractmethod
    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        """Devuelve las subsecciones. Es lo único que cada sección implementa."""


REGISTRY: dict[Section, SectionBuilder] = {}


def register(cls: type[SectionBuilder]) -> type[SectionBuilder]:
    REGISTRY[cls.section] = cls()
    return cls


def get_builder(section: Section) -> SectionBuilder | None:
    return REGISTRY.get(section)


def builders_for(tier: Tier, order: Sequence[Section]) -> list[SectionBuilder]:
    return [REGISTRY[s] for s in order if s in REGISTRY]


def latest_period(facts: Iterable[Fact]) -> date | None:
    periods = [f.period for f in facts if f.period]
    return max(periods) if periods else None
