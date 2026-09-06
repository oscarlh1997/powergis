"""Ecosistema comercial: competencia, anclas y saturación (fase 4b).

AVISO LEGAL incorporado al código: los indicadores de valoración y reseñas de
competidores NO se calculan aquí. Los términos de Google Maps Platform
restringen almacenar y reutilizar ese contenido fuera de un mapa de Google, y
este informe se vende. Todo lo que sale de esta sección proviene de
OpenStreetMap (ODbL, atribución obligatoria), Catastro e INE/DIRCE.

Si en el futuro se incorporan valoraciones con una licencia que lo permita,
basta con añadir los indicadores al catálogo y un colector: esta sección no
cambia.
"""

from __future__ import annotations

from ..enums import Section, Tier
from ..models import Subsection
from .base import (
    SectionBuilder,
    SectionContext,
    build_chart,
    build_table,
    kpi_from,
    register,
)

ATTRIBUTION = "© Colaboradores de OpenStreetMap (ODbL)"


@register
class Competencia(SectionBuilder):
    section = Section.COMPETENCIA
    title = "Ecosistema Comercial y Entorno Inmediato"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        return [
            self._competencia(ctx),
            self._anclas(ctx),
            self._saturacion(ctx),
        ]

    def _competencia(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "cmp.count", "cmp.count_indirect", "cmp.density_km2", "cmp.per_1000hab",
            "cmp.hhi", "cmp.age.mean", "cmp.opportunity.index",
        ]
        if not ctx.has_any(codes):
            ctx.warnings.append(
                "Competencia no disponible: no hay extracto de OSM cargado para este ámbito."
            )
            return None

        return Subsection(
            id="competencia.directa",
            title="Presencia de competencia directa e indirecta",
            kpis=[
                kpi_from(ctx, "cmp.count"),
                kpi_from(ctx, "cmp.density_km2"),
                kpi_from(ctx, "cmp.per_1000hab"),
                kpi_from(ctx, "cmp.hhi"),
                kpi_from(ctx, "cmp.opportunity.index"),
            ],
            charts=[
                build_chart(ctx, "cmp.densidad", "Densidad competitiva por zona",
                            ["cmp.density_km2"], chart_type="bar"),
                build_chart(ctx, "cmp.directa_indirecta", "Competencia directa e indirecta",
                            ["cmp.count", "cmp.count_indirect"], chart_type="bar", stack=True),
            ],
            tables=[
                build_table(
                    ctx, "cmp.tabla_competencia", "Competencia por zona", codes,
                    highlight_by="cmp.opportunity.index",
                    footnote=(
                        f"Recuentos derivados de OpenStreetMap. {ATTRIBUTION}. No se incluyen "
                        "valoraciones ni reseñas de terceros por restricciones de licencia."
                    ),
                )
            ],
        )

    def _anclas(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "anc.supermarkets", "anc.schools", "anc.health", "anc.green",
            "anc.admin", "anc.hotels", "anc.poi.count",
            "anc.diversity.index", "anc.attraction.index",
        ]
        if not ctx.has_any(codes):
            return None

        return Subsection(
            id="competencia.anclas",
            title="Atractivos y anclas de la zona",
            kpis=[
                kpi_from(ctx, "anc.poi.count"),
                kpi_from(ctx, "anc.supermarkets"),
                kpi_from(ctx, "anc.diversity.index"),
                kpi_from(ctx, "anc.attraction.index"),
            ],
            charts=[
                build_chart(ctx, "anc.equipamientos", "Equipamientos generadores de tráfico",
                            ["anc.supermarkets", "anc.schools", "anc.health",
                             "anc.admin", "anc.hotels"],
                            chart_type="bar", stack=True)
            ],
            tables=[
                build_table(ctx, "anc.tabla_anclas", "Anclas y sinergias por zona", codes,
                            highlight_by="anc.attraction.index",
                            footnote=f"Fuente: OpenStreetMap. {ATTRIBUTION}.")
            ],
        )

    def _saturacion(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "sat.isc", "sat.demand_supply", "sat.occupancy", "sat.available_units",
            "sat.rent_m2", "sat.turnover", "sat.survival3y", "sat.opportunity.index",
        ]
        if not ctx.has_any(codes):
            return None

        modelled = [c for c in ("sat.rent_m2",) if ctx.has_any([c])]
        note = ""
        if modelled:
            note = (" El precio de alquiler es una ESTIMACIÓN MODELADA: no existe fuente "
                    "abierta con esta granularidad.")
            ctx.warnings.append("Precio de alquiler por m²: valor estimado, no observado.")

        return Subsection(
            id="competencia.saturacion",
            title="Índice de saturación comercial",
            kpis=[
                kpi_from(ctx, "sat.isc"),
                kpi_from(ctx, "sat.demand_supply"),
                kpi_from(ctx, "sat.occupancy"),
                kpi_from(ctx, "sat.survival3y"),
                kpi_from(ctx, "sat.opportunity.index"),
            ],
            charts=[
                build_chart(ctx, "sat.isc_chart", "Saturación frente a oportunidad",
                            ["sat.isc", "sat.opportunity.index"], chart_type="bar")
            ],
            tables=[
                build_table(ctx, "sat.tabla_saturacion", "Saturación comercial por zona", codes,
                            highlight_by="sat.opportunity.index",
                            footnote="Fuentes: Catastro (locales), INE/DIRCE (rotación y "
                                     "supervivencia empresarial)." + note)
            ],
        )
