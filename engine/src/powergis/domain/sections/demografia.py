"""Sección demográfica — el informe básico gratuito (fase 1).

Es la única sección de tier BÁSICO. Todo lo que aquí se calcula sale del
almacén: si los indicadores del ámbito ya están frescos, no se toca el INE.
"""

from __future__ import annotations

from .. import stats
from ..enums import Direction, Section, Tier, Unit
from ..models import Chart, Kpi, Subsection
from .base import (
    SectionBuilder,
    SectionContext,
    build_chart,
    build_table,
    kpi_from,
    register,
)


@register
class Demografia(SectionBuilder):
    section = Section.DEMOGRAFIA
    title = "Análisis Demográfico del Público Objetivo"
    tier = Tier.BASICO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        return [
            self._edad(ctx),
            self._genero(ctx),
            self._hogares(ctx),
            self._formacion(ctx),
            self._nacionalidades(ctx),
        ]

    # ------------------------------------------------------------------ #
    # 1. Atributos demográficos por edad
    # ------------------------------------------------------------------ #

    def _edad(self, ctx: SectionContext) -> Subsection:
        kpis = [
            kpi_from(ctx, "dem.pop.total"),
            kpi_from(ctx, "dem.pop.segment", label=self._segment_label(ctx)),
            kpi_from(ctx, "dem.age.mean"),
            kpi_from(ctx, "dem.dependency.total"),
            kpi_from(ctx, "dem.ageing.index"),
        ]

        # Valor relativo del segmento: absoluto y % sobre el total del ámbito.
        segment_total = ctx.parent_value("dem.pop.segment")
        pop_total = ctx.parent_value("dem.pop.total")
        share = stats.relative_share(segment_total, pop_total)
        kpis.append(
            Kpi(
                code="dem.pop.segment_pct",
                label="Peso del público objetivo",
                value=share,
                unit=Unit.PORCENTAJE,
                direction=Direction.HIGHER_IS_BETTER,
                decimals=1,
                note="Sobre la población total del ámbito analizado",
            )
        )

        charts = [
            build_chart(
                ctx,
                "dem.piramide",
                "Estructura de edad por zona",
                ["dem.age.0_15", "dem.age.16_64", "dem.age.65p"],
                chart_type="bar",
                stack=True,
            ),
            build_chart(
                ctx,
                "dem.segmento",
                "Público objetivo por zona",
                ["dem.pop.segment"],
                chart_type="bar",
            ),
        ]

        table = build_table(
            ctx,
            "dem.tabla_edad",
            f"Detalle por {self._children_label(ctx)}",
            [
                "dem.pop.total",
                "dem.pop.segment",
                "dem.pop.segment_pct",
                "dem.age.mean",
                "dem.age.0_15",
                "dem.age.16_64",
                "dem.age.65p",
                "dem.ageing.index",
                "dem.dependency.total",
            ],
            highlight_by="dem.pop.segment",
            footnote="Fuente: INE, Padrón continuo. Valores absolutos y relativos "
                     "sobre el segmento de edad seleccionado.",
        )

        return Subsection(
            id="demografia.edad",
            title="Atributos demográficos y rango de edad",
            kpis=kpis,
            charts=charts,
            tables=[table],
        )

    # ------------------------------------------------------------------ #
    # 2. Segmentación por género
    # ------------------------------------------------------------------ #

    def _genero(self, ctx: SectionContext) -> Subsection:
        kpis = [
            kpi_from(ctx, "dem.sex.women"),
            kpi_from(ctx, "dem.sex.men"),
            kpi_from(ctx, "dem.femininity.index"),
            kpi_from(ctx, "dem.sex.women_pct"),
        ]

        charts = [
            build_chart(
                ctx,
                "dem.genero",
                "Distribución por género",
                ["dem.sex.women", "dem.sex.men"],
                chart_type="bar",
                stack=True,
            )
        ]

        # Cruce edad × género para la zona con mayor público objetivo.
        top_geo = self._top_geo(ctx, "dem.pop.segment")
        if top_geo is not None and ctx.segments.age:
            series = []
            for sex in ("F", "M"):
                series.append({
                    "name": "Mujeres" if sex == "F" else "Hombres",
                    "code": f"dem.pop.segment[{sex}]",
                    "data": [
                        ctx.value(top_geo.geo_id, "dem.pop.segment", {"age": age, "sex": sex})
                        for age in ctx.segments.age
                    ],
                })
            charts.append(
                Chart(
                    id="dem.cruce_edad_genero",
                    title=f"Cruce edad × género — {top_geo.name}",
                    type="bar",
                    x=list(ctx.segments.age),
                    series=series,
                    unit=Unit.PERSONAS,
                    stack=True,
                )
            )

        table = build_table(
            ctx,
            "dem.tabla_genero",
            f"Género por {self._children_label(ctx)}",
            ["dem.sex.women", "dem.sex.men", "dem.sex.women_pct", "dem.femininity.index"],
            highlight_by="dem.femininity.index",
            footnote="Índice de feminidad = mujeres / hombres × 100.",
        )

        return Subsection(
            id="demografia.genero",
            title="Segmentación por género",
            kpis=kpis,
            charts=charts,
            tables=[table],
        )

    # ------------------------------------------------------------------ #
    # 3. Estado civil y estructura familiar
    # ------------------------------------------------------------------ #

    def _hogares(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "dem.civil.single_pct",
            "dem.civil.married_pct",
            "dem.birth.rate",
            "dem.children.mean",
            "dem.household.size",
            "dem.household.single_pct",
            "dem.household.with_children_pct",
            "dem.household.monoparental_pct",
        ]
        if not ctx.has_any(codes):
            ctx.warnings.append(
                "Estructura familiar no disponible: el Censo no publica a este nivel de desagregación."
            )
            return None

        return Subsection(
            id="demografia.hogares",
            title="Estado civil y estructura familiar",
            kpis=[
                kpi_from(ctx, "dem.civil.single_pct"),
                kpi_from(ctx, "dem.civil.married_pct"),
                kpi_from(ctx, "dem.birth.rate"),
                kpi_from(ctx, "dem.children.mean"),
            ],
            charts=[
                build_chart(
                    ctx, "dem.hogares", "Composición del hogar",
                    ["dem.household.single_pct", "dem.household.with_children_pct",
                     "dem.household.monoparental_pct"],
                    chart_type="bar", stack=True,
                )
            ],
            tables=[
                build_table(
                    ctx, "dem.tabla_hogares",
                    f"Hogares por {self._children_label(ctx)}", codes,
                    highlight_by="dem.household.with_children_pct",
                    footnote="Fuente: INE, Censos de Población y Viviendas.",
                )
            ],
        )

    # ------------------------------------------------------------------ #
    # 4. Nivel de formación
    # ------------------------------------------------------------------ #

    def _formacion(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "dem.edu.none_pct",
            "dem.edu.primary_pct",
            "dem.edu.secondary_pct",
            "dem.edu.university_pct",
            "dem.edu.postgrad_pct",
            "dem.edu.qualification_index",
        ]
        if not ctx.has_any(codes):
            ctx.warnings.append("Nivel de formación no disponible en este ámbito.")
            return None

        return Subsection(
            id="demografia.formacion",
            title="Nivel de formación académica",
            kpis=[
                kpi_from(ctx, "dem.edu.none_pct"),
                kpi_from(ctx, "dem.edu.university_pct"),
                kpi_from(ctx, "dem.edu.qualification_index"),
            ],
            charts=[
                build_chart(
                    ctx, "dem.formacion", "Nivel educativo por zona",
                    ["dem.edu.primary_pct", "dem.edu.secondary_pct",
                     "dem.edu.university_pct", "dem.edu.postgrad_pct"],
                    chart_type="bar", stack=True,
                )
            ],
            tables=[
                build_table(
                    ctx, "dem.tabla_formacion",
                    f"Formación por {self._children_label(ctx)}", codes,
                    highlight_by="dem.edu.qualification_index",
                    footnote="Índice de cualificación ponderado: posgrado pesa 1,5 × universitario.",
                )
            ],
        )

    # ------------------------------------------------------------------ #
    # 5. Nacionalidades y diversidad
    # ------------------------------------------------------------------ #

    def _nacionalidades(self, ctx: SectionContext) -> Subsection | None:
        codes = ["dem.nat.foreign_pct", "dem.nat.diversity_index", "dem.nat.count"]
        if not ctx.has_any(codes):
            return None

        return Subsection(
            id="demografia.nacionalidades",
            title="Nacionalidades y diversidad cultural",
            kpis=[
                kpi_from(ctx, "dem.nat.foreign_pct"),
                kpi_from(ctx, "dem.nat.diversity_index"),
                kpi_from(ctx, "dem.nat.count"),
            ],
            charts=[
                build_chart(
                    ctx, "dem.nacionalidades", "Población extranjera por zona",
                    ["dem.nat.foreign_pct"], chart_type="bar",
                )
            ],
            tables=[
                build_table(
                    ctx, "dem.tabla_nacionalidades",
                    f"Diversidad por {self._children_label(ctx)}", codes,
                    highlight_by="dem.nat.diversity_index",
                    footnote=(
                        "Índice de diversidad: entropía de Shannon normalizada "
                        "(0 = homogéneo, 1 = máxima diversidad)."
                    ),
                )
            ],
        )

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #

    @staticmethod
    def _children_label(ctx: SectionContext) -> str:
        return {
            "ccaa": "comunidad autónoma",
            "provincia": "provincia",
            "municipio": "municipio",
            "distrito": "distrito",
            "seccion": "sección censal",
        }.get(str(ctx.scope.resolve_children_level()), "zona")

    @staticmethod
    def _segment_label(ctx: SectionContext) -> str:
        parts = []
        if ctx.segments.age:
            parts.append(" / ".join(ctx.segments.age) + " años")
        if ctx.segments.sex:
            names = {"F": "mujeres", "M": "hombres"}
            parts.append(" y ".join(names.get(s, s) for s in ctx.segments.sex))
        return f"Público objetivo ({', '.join(parts)})" if parts else "Público objetivo"

    @staticmethod
    def _top_geo(ctx: SectionContext, code: str):
        pairs = [(g, ctx.value(g.geo_id, code)) for g in ctx.children]
        valid = [(g, v) for g, v in pairs if v is not None]
        if not valid:
            return None
        return max(valid, key=lambda gv: gv[1])[0]
