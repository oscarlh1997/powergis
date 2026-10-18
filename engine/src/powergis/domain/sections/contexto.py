"""Contexto electoral y movilidad entre provincias (capas del formulario).

Dos capas que el cliente enciende en «Variables de contexto del público
objetivo»: resultados electorales agregados y traslados de residencia entre
provincias. Son contexto del territorio, no criterio de puntuación: ninguna
entra en el PlaceRank ni en el Match.

Los resultados electorales se enseñan agregados por territorio y sin
interpretar: participación, concentración del voto y fragmentación. Nada que
permita inferir la ideología de una persona, que es lo que promete el
formulario.
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

_ELECTORAL = ["pol.turnout_pct", "pol.winner_share_pct", "pol.effective_parties"]
_TRASLADOS = ["mov.interprov.in_rate", "mov.interprov.out_rate", "mov.interprov.net_rate"]


@register
class Contexto(SectionBuilder):
    section = Section.CONTEXTO
    title = "Contexto electoral y movilidad"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        return [self._electoral(ctx), self._traslados(ctx)]

    def _electoral(self, ctx: SectionContext) -> Subsection | None:
        if not ctx.layer_on("votaciones_politicas"):
            return None
        if sin_datos_de_capa(ctx, _ELECTORAL, "Resultados electorales"):
            return None
        return Subsection(
            id="contexto.electoral",
            title="Resultados electorales agregados",
            layer="votaciones_politicas",
            kpis=[kpi_from(ctx, c) for c in _ELECTORAL],
            charts=[build_chart(ctx, "pol.participacion", "Participación por zona",
                                ["pol.turnout_pct"], chart_type="bar")],
            tables=[build_table(
                ctx, "pol.tabla", "Resultados electorales por zona", _ELECTORAL,
                footnote="Fuente: Ministerio del Interior, Infoelectoral. Resultados "
                         "agregados por territorio de la convocatoria indicada; no se "
                         "infiere la ideología de ninguna persona.",
            )],
        )

    def _traslados(self, ctx: SectionContext) -> Subsection | None:
        if not ctx.layer_on("traslados_entre_provincias"):
            return None
        if sin_datos_de_capa(ctx, _TRASLADOS, "Traslados entre provincias"):
            return None
        return Subsection(
            id="contexto.traslados",
            title="Traslados de residencia entre provincias",
            layer="traslados_entre_provincias",
            kpis=[kpi_from(ctx, c) for c in _TRASLADOS],
            charts=[build_chart(ctx, "mov.flujos", "Llegadas y salidas por 1.000 habitantes",
                                ["mov.interprov.in_rate", "mov.interprov.out_rate"],
                                chart_type="bar")],
            tables=[build_table(
                ctx, "mov.tabla", "Movilidad residencial por zona", _TRASLADOS,
                highlight_by="mov.interprov.net_rate",
                footnote="Fuente: INE, Estadística de Migraciones y Cambios de Residencia. "
                         "Tasas por 1.000 habitantes; sólo cambios entre provincias.",
            )],
        )
