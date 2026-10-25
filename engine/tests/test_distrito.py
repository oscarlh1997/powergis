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


def proyecto(children_level: GeoLevel = GeoLevel.DISTRITO):
    from uuid import uuid4

    from powergis.domain.models import BusinessProfile, Project

    return Project(
        project_uuid=uuid4(), wp_user_id=1, wp_post_id=8071,
        scope=Scope(GeoLevel.MUNICIPIO, "28134", children_level),
        segments=Segments(), business=BusinessProfile(sector="generico"),
        tier=Tier.AVANZADO,
    )


def contexto(facts: list[Fact], children_level: GeoLevel = GeoLevel.DISTRITO):
    from powergis.application.context import build_context

    return build_context(uow(facts), proyecto(children_level), tier=Tier.AVANZADO)


class TestHerenciaDelMunicipio:
    def test_el_distrito_lleva_el_precio_de_su_municipio_con_etiqueta(self):
        ctx = contexto([f(MUN, "inm.price.m2", 3100.0, "MIVAU:1")])
        assert ctx.value(11, "inm.price.m2") == 3100.0
        assert ctx.flags(11, "inm.price.m2") == ["heredado_municipio"]
        # El ámbito es el propio municipio: su dato no lleva la marca.
        assert ctx.flags(MUN, "inm.price.m2") == []

    def test_lo_que_el_municipio_hereda_de_la_provincia_sigue_siendo_provincial(self):
        ctx = contexto([f(MUN, "inm.price.m2", 2900.0, "Equipo de datos · dato de la provincia")])
        assert ctx.flags(12, "inm.price.m2") == ["heredado"]

    def test_un_dato_propio_del_distrito_no_se_pisa(self):
        ctx = contexto([f(MUN, "cli.temp.annual", 14.0), f(11, "cli.temp.annual", 13.5)])
        assert ctx.value(11, "cli.temp.annual") == 13.5
        assert ctx.flags(11, "cli.temp.annual") == []
        assert ctx.value(12, "cli.temp.annual") == 14.0

    def test_las_secciones_suben_hasta_el_municipio(self):
        ctx = contexto([f(MUN, "mov.interprov.net_rate", 2.5)], GeoLevel.SECCION)
        assert {ctx.value(g.geo_id, "mov.interprov.net_rate") for g in ctx.children} == {2.5}

    def test_un_total_no_se_hereda(self):
        ctx = contexto([f(MUN, "tur.hotel.travellers", 50_000.0)])
        assert ctx.value(11, "tur.hotel.travellers") is None

    def test_los_meses_del_clima_tambien(self):
        ctx = contexto([f(MUN, "cli.temp.month", 5.0, "AEMET:3195", month="01")])
        assert ctx.value(11, "cli.temp.month", {"month": "01"}) == 5.0

    def test_el_heredado_no_colorea(self):
        ctx = contexto([f(MUN, "inm.price.m2", 3100.0)])
        ctx.national = None
        assert ctx.reference("inm.price.m2") is None


class TestDatoDelAmbito:
    def test_la_poblacion_del_municipio_llega_al_resumen_aunque_no_haya_por_distrito(self):
        from powergis.domain.report import ReportBuilder

        facts = [f(MUN, "dem.pop.total", 92_000.0), f(MUN, "dem.pop.segment", 20_000.0)]
        ctx = contexto(facts)
        assert ctx.parent_value("dem.pop.total") == 92_000.0
        report = ReportBuilder("test").build(proyecto(), ctx, version=1, tier=Tier.AVANZADO)
        head = {h["label"]: h["value"] for h in report.executive_summary["headline"]}
        assert head["Población analizada"] == 92_000.0
        assert head["Público objetivo"] == 20_000.0


class TestGranularidad:
    def test_un_informe_por_distrito_ya_no_descarta_casi_todo(self):
        from powergis.domain import indicators as catalog

        usables = [i for i in catalog.CATALOG
                   if i.available_at(GeoLevel.DISTRITO) or catalog.heredable(i)]
        assert len(usables) >= 90, "antes eran 12 de 129"

    def test_renta_disponible_ticket_y_resistencia_bajan_a_seccion(self):
        from powergis.domain.indicators import BY_CODE

        for code in ("eco.disposable.monthly", "eco.consumer.ticket", "eco.resilience.index",
                     "dem.pop.total", "dem.dependency.total", "pol.turnout_pct", "cmp.count",
                     "tra.transit.stops", "dem.edu.university_pct", "dem.nat.foreign_pct"):
            assert BY_CODE[code].available_at(GeoLevel.SECCION), code


class TestRecargaUtil:
    def test_no_se_encola_lo_que_nunca_tendra_dato_por_distrito(self):
        from powergis.application.build_report import BuildReport
        from powergis.domain import indicators as catalog

        encolado: list = []
        u = uow([])
        servicio = BuildReport(lambda: u, "test",
                               request_ingest=lambda c, lvl, p: encolado.append((c, lvl, p)))
        caducos = servicio._plan_ingest(u, proyecto(), Tier.AVANZADO,
                                        catalog.sections_for_tier(Tier.AVANZADO))
        assert caducos and encolado
        assert "tur.hotel.travellers" not in caducos       # sólo municipal
        assert "dem.pop.total" in caducos                  # sí se publica por distrito
        assert all(catalog.BY_CODE[c].available_at(GeoLevel.DISTRITO) for c in caducos)
        assert encolado[0][1:] == ("distrito", "28134")
