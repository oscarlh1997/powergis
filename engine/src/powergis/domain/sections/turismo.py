"""Nivel turístico (capa del formulario «Incluir nivel turístico»).

Tres bloques (decisión de Aldo del 20/10/2026):

* **Índice de intensidad turística** (España = 100): pernoctaciones hoteleras
  por 1.000 habitantes de la zona frente a las de España. Es un índice propio
  y se etiqueta como estimado.
* **Turismo nacional e internacional**: viajeros de la Encuesta de Ocupación
  Hotelera por lugar de residencia y, donde hay dato, la medición experimental
  del INE con teléfonos móviles (llega a municipio y cuenta también a quien no
  duerme en un hotel).
* La ocupación hotelera de siempre.

La EOH publica nacional, comunidad, provincia y los «puntos turísticos» que el
INE elige. Un municipio que no es punto turístico no tiene dato y se queda en
blanco: no es un cero.
"""

from __future__ import annotations

from ..enums import Section, Tier
from ..models import Fact, Subsection
from .base import (
    SectionBuilder,
    SectionContext,
    build_chart,
    build_table,
    kpi_from,
    register,
    sin_datos_de_capa,
)

_HOTEL = [
    "tur.hotel.travellers", "tur.hotel.overnight", "tur.hotel.stay_mean",
    "tur.overnight_per_1000hab",
]
_INDICE = ["tur.index", "tur.overnight_per_1000hab", "tur.hotel.stay_mean"]
_ORIGEN = ["tur.hotel.travellers.resident", "tur.hotel.travellers.foreign",
           "tur.hotel.foreign_pct", "tur.mobile.domestic", "tur.mobile.international"]
_TODOS = list(dict.fromkeys(_HOTEL + _INDICE + _ORIGEN))

#: `source_ref` del índice: «estimación» hace que salga con la etiqueta «Estimado».
REF_INDICE = "PowerGIS · índice calculado (estimación) sobre INE, EOH"


def indice_turistico(ctx: SectionContext) -> None:
    """Añade `tur.index` a los hechos del contexto (zonas y ámbito).

    Se calcula al construir el informe, no en la carga: depende del valor de
    España, que es la base 100.
    """
    if "tur.index" not in ctx.catalog:
        return
    base = ctx.national_value("tur.overnight_per_1000hab")
    if base is None and ctx.national is not None and ctx.parent.geo_id == ctx.national.geo_id:
        base = ctx.parent_value("tur.overnight_per_1000hab")
    if not base:
        return
    periodos = [f.period for k, f in ctx.facts.items() if k[1] == "tur.overnight_per_1000hab"]
    for geo in [*ctx.children, ctx.parent]:
        hecho = ctx.fact(geo.geo_id, "tur.overnight_per_1000hab")
        valor = hecho.value if hecho else (
            ctx.parent_value("tur.overnight_per_1000hab") if geo is ctx.parent else None)
        if valor is None:
            continue
        ref = REF_INDICE
        if hecho is not None and hecho.source_ref and "dato de la" in hecho.source_ref:
            ref += " · " + hecho.source_ref.split(" · ")[-1]
        nuevo = Fact(geo_id=geo.geo_id, indicator="tur.index",
                     period=hecho.period if hecho else max(periodos),
                     value=round(valor / base * 100.0, 1), source_ref=ref)
        ctx.facts[(geo.geo_id, "tur.index", ctx.segment_key(None))] = nuevo


@register
class Turismo(SectionBuilder):
    section = Section.TURISMO
    title = "Nivel turístico"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        if not ctx.layer_on("nivel_turistico"):
            return []
        if sin_datos_de_capa(ctx, _TODOS, "Nivel turístico"):
            return []
        indice_turistico(ctx)
        return [self._indice(ctx), self._origen(ctx), self._hotelero(ctx)]

    @staticmethod
    def _con_datos(ctx: SectionContext, codes: list[str]) -> list[str]:
        return [c for c in codes if c in ctx.catalog
                and (ctx.has_any([c]) or ctx.parent_value(c) is not None)]

    def _indice(self, ctx: SectionContext) -> Subsection | None:
        codes = self._con_datos(ctx, _INDICE)
        if "tur.index" not in codes:
            return None
        return Subsection(
            id="turismo.indice",
            title="Índice de intensidad turística",
            layer="nivel_turistico",
            kpis=[kpi_from(ctx, c) for c in codes],
            charts=[build_chart(ctx, "tur.indice", "Intensidad turística (España = 100)",
                                ["tur.index"], chart_type="bar")],
            tables=[build_table(
                ctx, "tur.tabla_indice", "Intensidad turística por zona", codes,
                highlight_by="tur.index",
                footnote="Índice de PowerGIS: pernoctaciones hoteleras por 1.000 habitantes "
                         "de cada zona frente a las de España (= 100). Fuente de base: INE, "
                         "Encuesta de Ocupación Hotelera.",
            )],
        )

    def _origen(self, ctx: SectionContext) -> Subsection | None:
        codes = self._con_datos(ctx, _ORIGEN)
        if not codes:
            return None
        charts = []
        if {"tur.hotel.travellers.resident", "tur.hotel.travellers.foreign"} & set(codes):
            charts.append(build_chart(
                ctx, "tur.origen", "Viajeros en hoteles: nacionales e internacionales",
                ["tur.hotel.travellers.resident", "tur.hotel.travellers.foreign"],
                chart_type="bar", stack=True,
            ))
        if {"tur.mobile.domestic", "tur.mobile.international"} & set(codes):
            charts.append(build_chart(
                ctx, "tur.moviles", "Turistas (teléfonos móviles): nacionales e internacionales",
                ["tur.mobile.domestic", "tur.mobile.international"],
                chart_type="bar", stack=True,
            ))
        return Subsection(
            id="turismo.origen",
            title="Turismo nacional e internacional",
            layer="nivel_turistico",
            kpis=[kpi_from(ctx, c) for c in codes],
            charts=charts,
            tables=[build_table(
                ctx, "tur.tabla_origen", "Origen de los turistas por zona", codes,
                highlight_by="tur.hotel.foreign_pct" if "tur.hotel.foreign_pct" in codes
                else None,
                footnote="Fuente: INE, Encuesta de Ocupación Hotelera (viajeros por lugar de "
                         "residencia) y Medición del turismo a partir de teléfonos móviles "
                         "(estadística experimental). En blanco donde el INE no publica.",
            )],
        )

    def _hotelero(self, ctx: SectionContext) -> Subsection | None:
        codes = self._con_datos(ctx, _HOTEL)
        if not codes:
            return None
        return Subsection(
            id="turismo.hotelero",
            title="Ocupación hotelera",
            layer="nivel_turistico",
            kpis=[kpi_from(ctx, c) for c in _HOTEL],
            charts=[build_chart(ctx, "tur.intensidad", "Pernoctaciones por 1.000 habitantes",
                                ["tur.overnight_per_1000hab"], chart_type="bar")],
            tables=[build_table(
                ctx, "tur.tabla", "Turismo por zona", _HOTEL,
                highlight_by="tur.overnight_per_1000hab",
                footnote="Fuente: INE, Encuesta de Ocupación Hotelera. Por municipio sólo "
                         "hay dato en los puntos turísticos del INE; el resto queda en "
                         "blanco, no a cero.",
            )],
        )
