"""Densidad de tráfico peatonal y vehicular (fase 4d).

Honestidad metodológica: sin aforos reales no se puede publicar un número de
peatones/hora. Lo que se entrega es un ÍNDICE RELATIVO dentro del ámbito
consultado, construido con la jerarquía viaria, el transporte público y los
POIs generadores de OpenStreetMap. La metodología viaja con la sección y
aparece en el anexo del informe: un índice declarado es defendible, un aforo
inventado no.
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

DISCLAIMER = (
    "Índice relativo normalizado 0-100 dentro del ámbito consultado. "
    "NO es un aforo: no debe interpretarse como número de personas o vehículos. "
    "Construido con jerarquía viaria, paradas de transporte público y POIs "
    "generadores de tráfico de OpenStreetMap. © Colaboradores de OpenStreetMap (ODbL)."
)


@register
class Trafico(SectionBuilder):
    section = Section.TRAFICO
    title = "Densidad de Tráfico"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        return [self._peatonal(ctx), self._vehicular(ctx)]

    def _peatonal(self, ctx: SectionContext) -> Subsection | None:
        codes = ["tra.pedestrian.index", "tra.transit.stops", "tra.accessibility.index"]
        if not ctx.has_any(codes):
            ctx.warnings.append("Tráfico peatonal no disponible: falta el extracto de OSM.")
            return None

        return Subsection(
            id="trafico.peatonal",
            title="Tráfico peatonal",
            kpis=[kpi_from(ctx, c, note=DISCLAIMER if c.endswith("index") else None) for c in codes],
            charts=[build_chart(ctx, "tra.peatonal", "Índice de tráfico peatonal",
                                ["tra.pedestrian.index"], chart_type="bar")],
            tables=[build_table(ctx, "tra.tabla_peatonal", "Tráfico peatonal por zona", codes,
                                highlight_by="tra.pedestrian.index", footnote=DISCLAIMER)],
        )

    def _vehicular(self, ctx: SectionContext) -> Subsection | None:
        codes = ["tra.vehicle.index", "tra.road.primary_km", "tra.parking.capacity"]
        if not ctx.has_any(codes):
            return None

        return Subsection(
            id="trafico.vehicular",
            title="Tráfico vehicular",
            kpis=[kpi_from(ctx, c, note=DISCLAIMER if c.endswith("index") else None) for c in codes],
            charts=[build_chart(ctx, "tra.vehicular", "Índice de tráfico vehicular",
                                ["tra.vehicle.index"], chart_type="bar")],
            tables=[build_table(ctx, "tra.tabla_vehicular", "Tráfico vehicular por zona", codes,
                                highlight_by="tra.vehicle.index", footnote=DISCLAIMER)],
        )
