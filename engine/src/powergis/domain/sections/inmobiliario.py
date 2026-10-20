"""Mercado inmobiliario y parque residencial (capas del formulario).

El formulario las activa todas juntas con «Incluir mercado inmobiliario y
parque residencial», pero el motor las trata una por una —compraventa,
viviendas vacías y principales, precio con su histórico y alquiler— para que
el día que el formulario las separe no haya que tocar nada aquí.

Cada fuente publica a un nivel distinto y se dice en la tabla: la compraventa
(ETDP) y el valor tasado (MIVAU) son provinciales y los municipios llevan el
dato de su provincia; el Censo 2021 llega a sección censal; el alquiler de
referencia (SERPAVI), a municipio.
"""

from __future__ import annotations

from ..enums import Section, Tier, Unit
from ..models import Chart, Subsection
from .base import (
    SectionBuilder,
    SectionContext,
    build_chart,
    build_table,
    kpi_from,
    register,
    sin_datos_de_capa,
)

#: Indicadores con serie anual (segmento `{"year": "2019"}`), que es lo que
#: pide «Precio de vivienda e histórico». La carga la hoja «Series historicas»
#: de la plantilla.
SERIES_HISTORICAS: tuple[str, ...] = ("inm.price.m2", "inm.rent.m2")
ANIOS_HISTORICO: tuple[str, ...] = tuple(str(a) for a in range(2005, 2031))

_COMPRAVENTA = ["inm.sales.dwellings", "inm.sales.per_1000hab"]
_VIVIENDAS = ["inm.dwellings.main_pct", "inm.dwellings.empty_pct"]
_PRECIO = ["inm.price.m2", "inm.price.yoy_change", "inm.ipv.index", "inm.ipv.yoy",
           "inm.affordability.years"]
_ALQUILER = ["inm.rent.m2", "inm.rent.ipva_yoy", "inm.rent.effort_pct"]
#: Catastro: inmuebles urbanos y locales comerciales (los locales también
#: salen en Competencia, en la saturación comercial).
_CATASTRO = ["inm.cadastre.urban_units", "inm.cadastre.value_mean",
             "sat.available_units", "sat.occupancy", "sat.rent_m2"]

_HEREDADO = ("Por provincia: el INE/MIVAU no lo publica por municipio, así que cada "
             "municipio lleva el dato de su provincia.")


@register
class Inmobiliario(SectionBuilder):
    section = Section.INMOBILIARIO
    title = "Mercado inmobiliario y parque residencial"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        return [
            self._compraventa(ctx),
            self._viviendas(ctx),
            self._precio(ctx),
            self._alquiler(ctx),
            self._catastro(ctx),
        ]

    # ------------------------------------------------------------------ #

    def _sin_datos(self, ctx: SectionContext, codes: list[str], que: str) -> bool:
        return sin_datos_de_capa(ctx, codes, que)

    def _compraventa(self, ctx: SectionContext) -> Subsection | None:
        if not ctx.layer_on("compra_venta_inmuebles") or self._sin_datos(
            ctx, _COMPRAVENTA, "Compraventa de viviendas"
        ):
            return None
        return Subsection(
            id="inmobiliario.compraventa",
            title="Compraventa de viviendas",
            layer="compra_venta_inmuebles",
            kpis=[kpi_from(ctx, c) for c in _COMPRAVENTA],
            charts=[build_chart(ctx, "inm.compraventa", "Compraventas por 1.000 habitantes",
                                ["inm.sales.per_1000hab"], chart_type="bar")],
            tables=[build_table(
                ctx, "inm.tabla_compraventa", "Compraventa por zona", _COMPRAVENTA,
                highlight_by="inm.sales.per_1000hab",
                footnote="Fuente: INE, Estadística de Transmisiones de Derechos de la "
                         "Propiedad (ETDP). " + _HEREDADO,
            )],
        )

    def _viviendas(self, ctx: SectionContext) -> Subsection | None:
        if not ctx.layer_on("viviendas_vacias_principales") or self._sin_datos(
            ctx, _VIVIENDAS, "Viviendas vacías y principales"
        ):
            return None
        return Subsection(
            id="inmobiliario.viviendas",
            title="Viviendas principales y vacías",
            layer="viviendas_vacias_principales",
            kpis=[kpi_from(ctx, c) for c in _VIVIENDAS],
            charts=[build_chart(ctx, "inm.parque", "Uso del parque de viviendas",
                                _VIVIENDAS, chart_type="bar")],
            tables=[build_table(
                ctx, "inm.tabla_viviendas", "Parque residencial por zona", _VIVIENDAS,
                footnote="Fuente: INE, Censo de Población y Viviendas 2021. «Vacía» es la "
                         "categoría del Censo; las de uso esporádico no se cuentan como "
                         "segunda residencia.",
            )],
        )

    def _precio(self, ctx: SectionContext) -> Subsection | None:
        if not ctx.layer_on("precio_vivienda_historico") or self._sin_datos(
            ctx, _PRECIO, "Precio de la vivienda"
        ):
            return None
        charts = [build_chart(ctx, "inm.precio", "Valor tasado por zona (€/m²)",
                              ["inm.price.m2"], chart_type="bar")]
        historico = _historico(ctx, "inm.price.m2", "Evolución del valor tasado (€/m²)")
        if historico is not None:
            charts.insert(0, historico)
        return Subsection(
            id="inmobiliario.precio",
            title="Precio de la vivienda e histórico",
            layer="precio_vivienda_historico",
            kpis=[kpi_from(ctx, c) for c in _PRECIO if c in ctx.catalog],
            charts=charts,
            tables=[build_table(
                ctx, "inm.tabla_precio", "Precio de la vivienda por zona", _PRECIO,
                footnote="Fuente: Ministerio de Vivienda y Agenda Urbana, valor tasado medio "
                         "de la vivienda libre (valor de tasación, no precio de operaciones "
                         "ni de anuncios); INE, Índice de Precios de Vivienda (por comunidad "
                         "autónoma). " + _HEREDADO + " «Años de renta para comprar 90 m²» "
                         "es una estimación de PowerGIS.",
            )],
        )

    def _alquiler(self, ctx: SectionContext) -> Subsection | None:
        if not ctx.layer_on("alquiler_vivienda_proxy") or self._sin_datos(
            ctx, _ALQUILER, "Alquiler de vivienda"
        ):
            return None
        # Sólo el €/m²: la variación (%) y el esfuerzo (%) no comparten eje.
        charts = [build_chart(ctx, "inm.alquiler", "Alquiler de referencia (€/m² al mes)",
                              ["inm.rent.m2"], chart_type="bar")]
        historico = _historico(ctx, "inm.rent.m2", "Evolución del alquiler de referencia")
        if historico is not None:
            charts.insert(0, historico)
        return Subsection(
            id="inmobiliario.alquiler",
            title="Alquiler de vivienda (aproximación)",
            layer="alquiler_vivienda_proxy",
            kpis=[kpi_from(ctx, c) for c in _ALQUILER if c in ctx.catalog],
            charts=charts,
            tables=[build_table(
                ctx, "inm.tabla_alquiler", "Alquiler por zona", _ALQUILER,
                footnote="Fuente: Ministerio de Vivienda y Agenda Urbana, Sistema Estatal de "
                         "Referencia del Precio del Alquiler (SERPAVI), índice de referencia y "
                         "no la renta de un contrato concreto; INE, Índice de Precios de "
                         "Vivienda en Alquiler (experimental). El esfuerzo del alquiler es una "
                         "estimación de PowerGIS.",
            )],
        )

    def _catastro(self, ctx: SectionContext) -> Subsection | None:
        if not ctx.layer_on("catastro_locales_cartografia"):
            return None
        codes = [c for c in _CATASTRO if c in ctx.catalog]
        if not codes or self._sin_datos(ctx, codes, "Catastro: inmuebles y locales"):
            return None
        return Subsection(
            id="inmobiliario.catastro",
            title="Catastro: inmuebles y locales",
            layer="catastro_locales_cartografia",
            kpis=[kpi_from(ctx, c) for c in codes],
            charts=[build_chart(ctx, "inm.catastro", "Valor catastral medio por zona",
                                ["inm.cadastre.value_mean"], chart_type="bar")],
            tables=[build_table(
                ctx, "inm.tabla_catastro", "Catastro por zona", codes,
                footnote="Fuente: Dirección General del Catastro. El valor catastral es "
                         "administrativo, no de mercado. El precio de alquiler de locales "
                         "es una estimación de PowerGIS.",
            )],
        )


def _historico(ctx: SectionContext, code: str, title: str) -> Chart | None:
    """Serie anual del ámbito y de las 3 zonas más pobladas, si hay al menos dos años."""
    if code not in ctx.catalog:
        return None
    anios = [a for a in ANIOS_HISTORICO
             if ctx.parent_value(code, {"year": a}) is not None
             or any(v is not None for v in ctx.values(code, {"year": a}))]
    if len(anios) < 2:
        return None
    zonas = sorted(
        (g for g in ctx.children if g.geo_id != ctx.parent.geo_id),
        key=lambda g: ctx.value(g.geo_id, "dem.pop.total") or 0,
        reverse=True,
    )[:3]
    series = [{
        "name": ctx.parent.name,
        "code": code,
        "data": [ctx.parent_value(code, {"year": a}) for a in anios],
    }]
    for g in zonas:
        datos = [ctx.value(g.geo_id, code, {"year": a}) for a in anios]
        if any(v is not None for v in datos):
            series.append({"name": g.name, "code": code, "data": datos})
    return Chart(id=f"{code}.historico", title=title, type="line", x=list(anios),
                 series=series, unit=Unit.EUROS)
