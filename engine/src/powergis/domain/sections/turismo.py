"""Nivel turístico (capa del formulario «Incluir nivel turístico»).

Encuesta de Ocupación Hotelera del INE: nacional, comunidad, provincia y los
«puntos turísticos» que el INE elige por su relevancia. Un municipio que no es
punto turístico no tiene dato, y se queda en blanco: no es un cero.
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
    sin_datos_de_capa,
)

_CODIGOS = [
    "tur.hotel.travellers", "tur.hotel.overnight", "tur.hotel.stay_mean",
    "tur.overnight_per_1000hab",
]


@register
class Turismo(SectionBuilder):
    section = Section.TURISMO
    title = "Nivel turístico"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        if not ctx.layer_on("nivel_turistico"):
            return []
        if sin_datos_de_capa(ctx, _CODIGOS, "Nivel turístico"):
            return []
        return [
            Subsection(
                id="turismo.hotelero",
                title="Ocupación hotelera",
                layer="nivel_turistico",
                kpis=[kpi_from(ctx, c) for c in _CODIGOS],
                charts=[build_chart(ctx, "tur.intensidad", "Pernoctaciones por 1.000 habitantes",
                                    ["tur.overnight_per_1000hab"], chart_type="bar")],
                tables=[build_table(
                    ctx, "tur.tabla", "Turismo por zona", _CODIGOS,
                    highlight_by="tur.overnight_per_1000hab",
                    footnote="Fuente: INE, Encuesta de Ocupación Hotelera. Por municipio sólo "
                             "hay dato en los puntos turísticos del INE; el resto queda en "
                             "blanco, no a cero.",
                )],
            )
        ]
