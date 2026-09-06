"""Climatología y factores estacionales (fase 4c).

Normales climatológicas de AEMET (1991-2020) asignadas a cada geografía por
estación más cercana ponderada por altitud. Se cargan una vez y se refrescan
anualmente: no hay motivo para llamar a AEMET con un usuario esperando.
"""

from __future__ import annotations

from ..enums import Section, Tier, Unit
from ..models import Chart, Subsection
from .base import (
    SectionBuilder,
    SectionContext,
    build_table,
    kpi_from,
    register,
)

MONTHS = [
    ("01", "Ene"), ("02", "Feb"), ("03", "Mar"), ("04", "Abr"),
    ("05", "May"), ("06", "Jun"), ("07", "Jul"), ("08", "Ago"),
    ("09", "Sep"), ("10", "Oct"), ("11", "Nov"), ("12", "Dic"),
]


@register
class Clima(SectionBuilder):
    section = Section.CLIMA
    title = "Climatología y Factores Estacionales"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        codes = [
            "cli.temp.annual", "cli.precip.annual", "cli.rain.days",
            "cli.sun.days", "cli.comfort.index", "cli.seasonality.index",
        ]
        if not ctx.has_any(codes):
            ctx.warnings.append("Climatología no disponible: no hay normales de AEMET cargadas.")
            return []

        return [
            Subsection(
                id="clima.general",
                title="Condiciones climáticas del ámbito",
                kpis=[kpi_from(ctx, c) for c in codes],
                charts=[self._monthly(ctx, "cli.temp.month", "Temperatura media mensual",
                                      "line", Unit.GRADOS_C),
                        self._monthly(ctx, "cli.precip.month", "Precipitación mensual",
                                      "bar", Unit.MM)],
                tables=[
                    build_table(
                        ctx, "cli.tabla", "Clima por zona", codes,
                        highlight_by="cli.comfort.index",
                        footnote="Fuente: AEMET OpenData, normales climatológicas 1991-2020. "
                                 "© AEMET. Asignación por estación más cercana ponderada por altitud.",
                    )
                ],
            )
        ]

    def _monthly(self, ctx: SectionContext, code: str, title: str,
                 chart_type: str, unit: Unit) -> Chart:
        """Serie mensual del ámbito completo más las 3 zonas más pobladas."""
        geos = sorted(
            ctx.children,
            key=lambda g: ctx.value(g.geo_id, "dem.pop.total") or 0,
            reverse=True,
        )[:3]
        series = [{
            "name": ctx.parent.name,
            "code": code,
            "data": [ctx.parent_value(code, {"month": m}) for m, _ in MONTHS],
        }]
        for g in geos:
            series.append({
                "name": g.name,
                "code": code,
                "data": [ctx.value(g.geo_id, code, {"month": m}) for m, _ in MONTHS],
            })
        return Chart(
            id=f"{code}.chart",
            title=title,
            type=chart_type,
            x=[label for _, label in MONTHS],
            series=series,
            unit=unit,
        )
