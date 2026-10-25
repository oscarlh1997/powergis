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

from .. import estado, stats
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
    #: Capas que el cliente apagó en el formulario (`domain.capas`). Sus
    #: indicadores ya no están en `catalog`; las secciones lo usan para no
    #: avisar de «sin datos» de algo que el cliente no pidió.
    hidden_layers: frozenset[str] = frozenset()
    #: España, para la referencia del color cuando hay menos de 5 zonas.
    national: Geo | None = None

    # -- capas ---------------------------------------------------------------

    def layer_on(self, layer: str) -> bool:
        return layer not in self.hidden_layers

    def visible(self, codes: Sequence[str]) -> list[str]:
        """`codes` sin los que pertenecen a una capa apagada."""
        from ..capas import visibles

        return visibles(codes, self.hidden_layers)

    # -- acceso a hechos ----------------------------------------------------

    @staticmethod
    def segment_key(segment: dict[str, str] | None) -> str:
        import json

        return json.dumps(segment or {}, sort_keys=True, separators=(",", ":"))

    @classmethod
    def index(cls, facts: Iterable[Fact]) -> dict[tuple[int, str, str], Fact]:
        return {(f.geo_id, f.indicator, cls.segment_key(f.segment)): f for f in facts}

    def fact(
        self,
        geo_id: int,
        indicator: str,
        segment: dict[str, str] | None = None,
    ) -> Fact | None:
        return self.facts.get((geo_id, indicator, self.segment_key(segment)))

    def flags(self, geo_id: int, indicator: str,
              segment: dict[str, str] | None = None) -> list[str]:
        return estado.de_hecho(self.fact(geo_id, indicator, segment), indicator)

    def national_value(self, indicator: str) -> float | None:
        return self.value(self.national.geo_id, indicator) if self.national else None

    def reference(self, indicator: str, segment: dict[str, str] | None = None) -> dict | None:
        """Cortes P25/P75 de las zonas (o el nacional ±5 %) para colorear."""
        heredados = sum(
            1 for g in self.children
            if estado.HEREDADOS & set(self.flags(g.geo_id, indicator, segment))
        )
        return estado.referencia(self.values(indicator, segment),
                                 self.national_value(indicator), heredados=heredados)

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
        if any(g.geo_id == self.parent.geo_id for g in self.children):
            # El ámbito es una de las filas (municipio comparado con su
            # provincia): agregar las filas daría el dato de la provincia.
            return None
        ind = self.catalog.get(indicator)
        vals = self.values(indicator, segment)
        if ind is not None and ind.unit in {Unit.PERSONAS, Unit.UNIDADES, Unit.MM}:
            return stats.total(vals)
        weights = [self.value(g.geo_id, "dem.pop.total") for g in self.children]
        if any(w is not None for w in weights):
            return stats.weighted_mean(vals, weights)
        return stats.mean(vals)

    def con_dato(self, indicator: str) -> bool:
        """¿Tiene valor en alguna zona o en el ámbito?"""
        return self.has_any([indicator]) or self.parent_value(indicator) is not None

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
    Unit.HORAS: "int",
    Unit.POR_MIL: "float",
}


def column_for(ind: Indicator, key: str | None = None, label: str | None = None) -> Column:
    return Column(
        key=key or ind.code,
        label=label or ind.label,
        type=_TYPE_BY_UNIT.get(ind.unit, "float"),
        decimals=ind.decimals,
        direction=ind.direction,
    )


_NIVEL_NOMBRE = {
    "pais": "país", "ccaa": "comunidad autónoma", "provincia": "provincia",
    "municipio": "municipio", "distrito": "distrito", "seccion": "sección censal",
}


def sin_datos_de_capa(ctx: SectionContext, codes: Sequence[str], que: str) -> bool:
    """¿No hay nada que enseñar de una capa? Si es así, dice por qué.

    Distingue «la fuente no llega a este nivel» (p. ej. turismo por sección
    censal) de «todavía no se ha cargado» (la plantilla del equipo de datos
    está vacía): son dos avisos distintos para quien lee el informe.
    """
    if ctx.has_any(codes) or any(ctx.parent_value(c) is not None for c in codes):
        return False
    if not any(c in ctx.catalog for c in codes):
        nivel = _NIVEL_NOMBRE.get(str(ctx.scope.resolve_children_level()), "este nivel")
        ctx.warnings.append(f"{que}: la fuente no se publica por {nivel}; no se muestra en "
                            "este ámbito.")
    else:
        ctx.warnings.append(f"{que}: todavía no hay datos cargados para este ámbito "
                            "(plantilla del equipo de datos).")
    return True


def kpi_from(
    ctx: SectionContext,
    code: str,
    *,
    segment: dict[str, str] | None = None,
    label: str | None = None,
    note: str | None = None,
) -> Kpi:
    """KPI del ámbito completo, con su percentil, sus marcas y sus cortes de color."""
    from .. import indicators as catalog_mod

    # Fuera del catálogo filtrado (no se publica al nivel de las zonas) la
    # etiqueta sigue siendo la del catálogo: nunca el código en crudo.
    ind = ctx.catalog.get(code) or catalog_mod.BY_CODE.get(code)
    value = ctx.parent_value(code, segment)
    unit = ind.unit if ind else Unit.INDICE
    direction = ind.direction if ind else Direction.NEUTRAL
    child_values = ctx.values(code, segment)
    direct = ctx.fact(ctx.parent.geo_id, code, segment)
    if direct is not None and direct.value is not None:
        flags = estado.de_hecho(direct, code)
    else:
        # Agregado desde las zonas: lleva las marcas de lo que suma (menos
        # «heredado», que es de cada zona, no del total).
        flags = sorted({f for g in ctx.children for f in ctx.flags(g.geo_id, code, segment)}
                       - estado.HEREDADOS, key=list(estado.ETIQUETAS).index)
    # Un total (personas, unidades) no se compara con sus partes: el
    # percentil saldría siempre 100 y el color no diría nada.
    es_total = unit in {Unit.PERSONAS, Unit.UNIDADES}
    reference = None if es_total else ctx.reference(code, segment)
    hecho = direct or next((ctx.fact(g.geo_id, code, segment) for g in ctx.children
                            if ctx.fact(g.geo_id, code, segment) is not None), None)
    return Kpi(
        code=code,
        label=label or (ind.label if ind else code),
        value=value,
        unit=unit,
        direction=direction,
        delta_vs_parent=None,
        percentile=(stats.percentile_of(value, child_values)
                    if child_values and not es_total else None),
        decimals=ind.decimals if ind else 2,
        note=note or (_missing_note(child_values) if value is None
                      else _nota_del_ambito(ctx, code, child_values)),
        flags=flags,
        reference=reference,
        rating=estado.clase(value, reference, int(direction)),
        period=hecho.period.isoformat() if hecho and hecho.period else None,
    )


def _nota_del_ambito(ctx: SectionContext, code: str,
                     child_values: Sequence[float | None]) -> str | None:
    """El KPI es del ámbito entero y las zonas no tienen el suyo: se dice.

    Sin esto el KPI (municipio) y la tabla (distritos, en blanco) parecían
    contradecirse: 11,4 % arriba y «n. d.» abajo.
    """
    if any(v is not None for v in child_values) or ctx.fact(ctx.parent.geo_id, code) is None:
        return None
    nivel = _NIVEL_NOMBRE.get(str(ctx.scope.resolve_children_level()), "zona")
    return f"Dato del conjunto de {ctx.parent.name}; no hay dato propio por {nivel}"


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
    for c in codes:
        if c in ctx.catalog:
            col = column_for(ctx.catalog[c])
            if ctx.catalog[c].unit not in {Unit.PERSONAS, Unit.UNIDADES}:
                col.reference = ctx.reference(c, segment)
            columns.append(col)
    columns += [col for col, _ in extra_columns]

    rows: list[dict[str, Any]] = []
    for geo in ctx.children:
        row: dict[str, Any] = {
            "geo_code": geo.ine_code,
            "geo_id": geo.geo_id,
            "zona": geo.name,
        }
        marcas: dict[str, list[str]] = {}
        for code in codes:
            if code in ctx.catalog:
                row[code] = ctx.value(geo.geo_id, code, segment)
                if f := ctx.flags(geo.geo_id, code, segment):
                    marcas[code] = f
        if marcas:
            row["_flags"] = marcas
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
    limit: int | None = None,
    segment: dict[str, str] | None = None,
) -> Chart:
    """Gráfico con una serie por indicador y una categoría por zona.

    Las zonas van ordenadas por el valor de la primera serie, de mayor a menor
    y los huecos al final. Antes eran las 25 primeras por orden alfabético: el
    gráfico enseñaba las zonas que empiezan por A, no las que importan. El
    recorte (top 15 + la zona analizada) lo hace el front.
    """
    primera = codes[0] if codes else None
    geos = sorted(
        ctx.children,
        key=lambda g: (ctx.value(g.geo_id, primera, segment) is None,
                       -(ctx.value(g.geo_id, primera, segment) or 0.0)),
    ) if primera else list(ctx.children)
    geos = geos[:limit] if limit else geos
    x = [g.name for g in geos]
    series: list[dict[str, Any]] = []
    for code in codes:
        datos = [ctx.value(g.geo_id, code, segment) for g in geos]
        # Una serie sin un solo valor no se dibuja. Antes entraba igual y la
        # leyenda nombraba indicadores que no estaban en el gráfico: el lector
        # buscaba la barra y no la encontraba.
        if all(v is None for v in datos):
            continue
        ind = ctx.catalog.get(code)
        series.append({"name": ind.label if ind else code, "code": code, "data": datos})

    # La unidad sale de la primera serie que SOBREVIVE, no de la primera
    # declarada: si ésa se cayó, el eje se rotularía con una unidad que no es
    # la de ninguna barra dibujada.
    unit = next(
        (ctx.catalog[s["code"]].unit for s in series if s["code"] in ctx.catalog), None
    )
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

    def preview_labels(self, limit: int = 6, hidden: frozenset[str] = frozenset()) -> list[str]:
        """Índice de venta de una sección bloqueada.

        Sale del CATÁLOGO, no del contexto: son los nombres de los indicadores
        que la sección contiene ("Renta media por hogar"), no sus valores para
        esta consulta. Por eso no recibe `ctx` — no tiene con qué filtrar un
        dato aunque alguien lo intente.
        """
        from .. import indicators as catalog
        from ..capas import capa_de

        labels: list[str] = []
        for ind in catalog.by_section(self.section):
            if capa_de(ind.code) in hidden:
                continue
            label = (ind.label or "").strip()
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
        return labels

    def hidden(self, hidden_layers: frozenset[str]) -> bool:
        """¿Ha apagado el cliente TODAS las capas de las que vive esta sección?

        Las secciones de siempre (demografía, clima…) no dependen de ninguna
        capa y nunca se ocultan.
        """
        from ..capas import capas_de_seccion

        if self.section not in _SOLO_CAPAS:
            return False
        capas = capas_de_seccion(self.section)
        return bool(capas) and all(c in hidden_layers for c in capas)

    def build(self, ctx: SectionContext) -> SectionResult:
        if not self.allowed(ctx.tier):
            return SectionResult(
                id=self.section,
                title=self.title,
                available=False,
                locked_reason="tier",
                preview=self.preview_labels(hidden=ctx.hidden_layers),
            )
        antes = len(ctx.warnings)
        subsections = self.subsections(ctx)
        notes = list(dict.fromkeys(ctx.warnings[antes:]))
        codes = self.indicator_codes
        # Sólo las fuentes de lo que se enseña: el pie de Demografía citaba el
        # Padrón y el Atlas sin un solo dato de ellos en la sección.
        sources = sorted({
            ctx.catalog[c].source for c in codes
            if c in ctx.catalog and ctx.catalog[c].source and ctx.con_dato(c)
        })
        return SectionResult(
            id=self.section,
            title=self.title,
            available=True,
            subsections=[s for s in subsections if s is not None],
            sources=sources,
            coverage=ctx.coverage(codes),
            notes=notes,
        )

    @abstractmethod
    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        """Devuelve las subsecciones. Es lo único que cada sección implementa."""


REGISTRY: dict[Section, SectionBuilder] = {}

#: Secciones que sólo existen por sus capas: con todas apagadas, no se pintan.
_SOLO_CAPAS = frozenset({Section.CONTEXTO, Section.TURISMO, Section.INMOBILIARIO})


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
