"""Informe por distrito (proyecto 8071, San Sebastián de los Reyes).

Un municipio con dos distritos y tres secciones censales, todo en memoria.
Cada clase fija uno de los cambios del análisis de datos faltantes.
"""

from __future__ import annotations

from datetime import date

from conftest import FakeUnitOfWork

from powergis.domain.enums import GeoLevel, Tier
from powergis.domain.models import Fact, Geo, Scope, Segments
from powergis.domain.sections.base import SectionContext, kpi_from, sin_datos_de_capa

P = date(2023, 1, 1)
MUN = 10


def geos() -> list[Geo]:
    return [
        Geo(1, GeoLevel.PAIS, "ES", "España", None),
        Geo(2, GeoLevel.CCAA, "13", "Comunidad de Madrid", 1),
        Geo(3, GeoLevel.PROVINCIA, "28", "Madrid", 2),
        Geo(MUN, GeoLevel.MUNICIPIO, "28134", "San Sebastián de los Reyes", 3, 92_000, 59.0),
        Geo(11, GeoLevel.DISTRITO, "2813401", "Distrito 01", MUN),
        Geo(12, GeoLevel.DISTRITO, "2813402", "Distrito 02", MUN),
        Geo(21, GeoLevel.SECCION, "2813401001", "Sección 01001", 11),
        Geo(22, GeoLevel.SECCION, "2813401002", "Sección 01002", 11),
        Geo(23, GeoLevel.SECCION, "2813402001", "Sección 02001", 12),
    ]


def f(geo_id: int, code: str, value: float | None, ref: str = "INE:1", **seg: str) -> Fact:
    return Fact(geo_id=geo_id, indicator=code, period=P, value=value, segment=dict(seg),
                source_ref=ref)


def ctx_de(facts: list[Fact], catalog_codes: list[str]) -> SectionContext:
    from powergis.domain import indicators as catalog

    todas = {g.geo_id: g for g in geos()}
    return SectionContext(
        scope=Scope(level=GeoLevel.MUNICIPIO, ine_code="28134",
                    children_level=GeoLevel.DISTRITO),
        parent=todas[MUN], children=[todas[11], todas[12]], segments=Segments(),
        tier=Tier.AVANZADO, catalog={c: catalog.BY_CODE[c] for c in catalog_codes},
        facts=SectionContext.index(facts),
    )


def uow(facts: list[Fact]) -> FakeUnitOfWork:
    return FakeUnitOfWork(geos(), facts)


class TestEtiquetasYAvisos:
    def test_el_kpi_fuera_del_catalogo_lleva_su_etiqueta_no_el_codigo(self):
        ctx = ctx_de([f(MUN, "eco.resilience.index", 61.0)], [])
        kpi = kpi_from(ctx, "eco.resilience.index")
        assert kpi.label == "Índice de resistencia económica"

    def test_el_kpi_del_municipio_dice_que_es_del_conjunto(self):
        ctx = ctx_de([f(MUN, "eco.poverty.risk_pct", 11.4)], ["eco.poverty.risk_pct"])
        kpi = kpi_from(ctx, "eco.poverty.risk_pct")
        assert kpi.value == 11.4
        assert "conjunto de San Sebastián de los Reyes" in kpi.note
        assert "distrito" in kpi.note

    def test_el_aviso_nombra_el_distrito(self):
        ctx = ctx_de([], [])
        assert sin_datos_de_capa(ctx, ["inm.rent.m2"], "Alquiler de vivienda")
        assert "por distrito;" in ctx.warnings[-1]
