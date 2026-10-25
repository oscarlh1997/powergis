"""Decisiones de Aldo del 20/10/2026 y fase de visualización (v3).

Marcas por valor y cortes P25/P75, horas de sol anuales, población de la ECP,
riesgo de pobreza estimado, turismo y vivienda ampliados, e incidencias del
motor de la especificación de visualización.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from conftest import PERIOD, FakeUnitOfWork
from powergis.adapters.collectors.aemet import _horas_de_sol
from powergis.adapters.collectors.derived import DerivedCollector, poverty_risk_estimate
from powergis.adapters.collectors.plantilla import PlantillaCollector
from powergis.application.context import build_context
from powergis.domain import estado
from powergis.domain.enums import GeoLevel, Section, Tier
from powergis.domain.models import BusinessProfile, Fact, Geo, Project, Scope, Segments
from powergis.domain.report import ReportBuilder
from powergis.domain.sections.base import build_chart, build_table, kpi_from


def _f(geo_id, code, value, ref="INE", period=PERIOD, segment=None):
    return Fact(geo_id=geo_id, indicator=code, period=period, value=value,
                segment=segment or {}, source_ref=ref)


# --------------------------------------------------------------------------- #
# Marcas y referencia
# --------------------------------------------------------------------------- #


class TestMarcas:
    HOY = date(2026, 10, 20)

    def test_dato_oficial_al_dia_no_lleva_marcas(self):
        assert estado.de_hecho(_f(1, "dem.pop.total", 10, period=date(2025, 1, 1)),
                               "dem.pop.total", hoy=self.HOY) == []

    def test_heredado_provisional_antiguo_y_estimado(self):
        hecho = _f(1, "dem.nat.foreign_pct", 9.0, period=date(2019, 1, 1),
                   ref="Equipo de datos · X · dato de la provincia")
        assert estado.de_hecho(hecho, "dem.nat.foreign_pct", hoy=self.HOY) == [
            estado.HEREDADO, estado.PROVISIONAL, estado.ANTIGUO]
        modelado = _f(1, "eco.disposable.monthly", 2000,
                      ref="estimación modelada · elaboración propia")
        assert estado.ESTIMADO in estado.de_hecho(modelado, "eco.disposable.monthly", hoy=self.HOY)

    def test_riesgo_de_pobreza_estimado_solo_si_es_modelo(self):
        modelo = _f(1, "eco.poverty.risk_pct", 20.0, ref="estimación modelada · elaboración propia")
        assert estado.ESTIMADO in estado.de_hecho(modelo, "eco.poverty.risk_pct", hoy=self.HOY)
        # El del Atlas (umbrales relativos) es un dato publicado.
        assert estado.ESTIMADO not in estado.de_hecho(
            _f(1, "eco.poverty.risk_pct", 11.4, ref="INE:37700"), "eco.poverty.risk_pct",
            hoy=self.HOY)

    def test_las_normales_de_aemet_no_son_dato_antiguo(self):
        normal = _f(1, "cli.temp.annual", 15.0, period=date(2020, 1, 1),
                    ref="AEMET:3195 · © AEMET")
        assert estado.de_hecho(normal, "cli.temp.annual", hoy=self.HOY) == []

    def test_el_nulo_no_lleva_marcas(self):
        assert estado.de_hecho(_f(1, "dem.nat.foreign_pct", None), "dem.nat.foreign_pct") == []

    def test_la_lista_en_actualizacion_sigue_a_los_colectores_del_ine(self):
        from powergis.adapters.collectors import ine_adrh
        from powergis.adapters.collectors.ine import TABLES

        # Las tablas por distrito o sección no marcan el código entero: sus
        # hechos llevan «provisional» en la fuente (`IneCollector._ref`).
        marcados = {s.indicator for s in (*TABLES, *ine_adrh.SPECS)
                    if (s.pendiente or s.provisional) and s.level not in ("distrito", "seccion")}
        # El riesgo de pobreza se estima: sale «Estimado», no «En actualización».
        assert marcados - {"eco.poverty.risk_pct"} == set(estado.EN_ACTUALIZACION)


class TestReferencia:
    def test_cinco_zonas_usan_p25_y_p75(self):
        ref = estado.referencia([1, 2, 3, 4, 5, None], 100.0)
        assert ref["base"] == "zonas" and ref["n"] == 5
        assert ref["p25"] == pytest.approx(2.0) and ref["p75"] == pytest.approx(4.0)

    def test_menos_de_cinco_zonas_compara_con_el_total_nacional(self):
        ref = estado.referencia([1, 2, 3, None], 10.0)
        assert ref == {"base": "nacional", "n": 3, "valor": 10.0, "p25": 9.5, "p75": 10.5}

    def test_los_heredados_no_cuentan_como_zonas(self):
        ref = estado.referencia([5, 5, 5, 5, 5, 5], 4.0, heredados=6)
        assert ref["base"] == "nacional"

    def test_sin_nacional_ni_zonas_no_hay_color(self):
        assert estado.referencia([1, 2], None) is None

    @pytest.mark.parametrize(("valor", "direccion", "esperado"), [
        (5, 1, "favorable"), (1, 1, "desfavorable"), (3, 1, "media"),
        (5, -1, "desfavorable"), (1, -1, "favorable"), (5, 0, None), (None, 1, None),
    ])
    def test_clase(self, valor, direccion, esperado):
        assert estado.clase(valor, {"p25": 2, "p75": 4}, direccion) == esperado


# --------------------------------------------------------------------------- #
# KPIs, tablas y gráficos
# --------------------------------------------------------------------------- #


@pytest.fixture
def ctx(uow, project):
    return build_context(uow, project, tier=Tier.AVANZADO)


class TestPiezas:
    def test_kpi_lleva_referencia_rating_y_periodo(self, ctx):
        kpi = kpi_from(ctx, "eco.income.household.mean").as_dict()
        # 3 provincias con renta (< 5) → referencia nacional; España no la tiene.
        assert kpi["reference"] is None and kpi["rating"] is None
        assert kpi["period"] == PERIOD.isoformat()
        assert kpi["flags"] == []

    def test_un_total_no_tiene_percentil_ni_color(self, ctx):
        kpi = kpi_from(ctx, "dem.pop.total")
        assert kpi.percentile is None and kpi.reference is None

    def test_referencia_nacional_con_pocas_zonas(self, uow, project):
        uow.facts.upsert_many([_f(1, "dem.edu.university_pct", 30.0)])
        ctx = build_context(uow, project, tier=Tier.AVANZADO)
        kpi = kpi_from(ctx, "dem.edu.university_pct")
        assert kpi.reference["base"] == "nacional"
        assert kpi.rating in {"favorable", "media", "desfavorable"}
        assert estado.PROVISIONAL in kpi.flags

    def test_la_tabla_marca_cada_valor(self, ctx):
        ctx.facts[(4, "eco.gini", ctx.segment_key(None))] = _f(
            4, "eco.gini", 0.29, ref="Equipo de datos · X · dato de la provincia")
        tabla = build_table(ctx, "t", "T", ["eco.gini", "dem.edu.university_pct"]).as_dict()
        fila = next(r for r in tabla["rows"] if r["geo_id"] == 4)
        assert fila["_flags"]["eco.gini"] == [estado.HEREDADO]
        assert fila["_flags"]["dem.edu.university_pct"] == [estado.PROVISIONAL]

    def test_el_grafico_va_ordenado_por_valor(self, ctx):
        chart = build_chart(ctx, "c", "C", ["eco.income.household.mean"])
        assert chart.x == ["Madrid", "Guadalajara", "Toledo", "Ávila"]
        assert chart.series[0]["data"][-1] is None

    def test_un_grafico_vacio_no_se_emite(self, ctx):
        from powergis.domain.models import Subsection

        vacio = build_chart(ctx, "c", "C", ["tur.hotel.travellers"])
        assert Subsection("s", "S", charts=[vacio]).as_dict()["charts"] == []


# --------------------------------------------------------------------------- #
# Plantilla: horas de sol, el más reciente manda, población ECP
# --------------------------------------------------------------------------- #

PROV_MADRID = Geo(3, GeoLevel.PROVINCIA, "28", "Madrid", 2, 6_871_000, 8_028)
ESPANA = Geo(1, GeoLevel.PAIS, "ES", "España", None, 49_801_559, 505_939)


def _csv(tmp_path: Path, filas: list[str]) -> Path:
    ruta = tmp_path / "plantilla.csv"
    ruta.write_text("nivel;codigo_ine;territorio;indicador;valor;periodo;fuente\n"
                    + "\n".join(filas), encoding="utf-8")
    return ruta


class TestPlantilla:
    def test_horas_de_sol_mensuales_pasan_a_anuales_y_se_dice(self, tmp_path):
        col = PlantillaCollector(_csv(tmp_path, [
            "provincia;28;Madrid;cli.sun.hours.annual;221;2025;AEMET vía datosespana"]),
            semillas=())
        (hecho,) = col.collect(["cli.sun.hours.annual"], [PROV_MADRID], Segments())
        assert hecho.value == 2652
        assert "media mensual × 12" in hecho.source_ref
        assert estado.ESTIMADO in estado.de_hecho(hecho, "cli.sun.hours.annual")

    def test_horas_de_sol_ya_anuales_no_se_tocan(self, tmp_path):
        col = PlantillaCollector(_csv(tmp_path, [
            "provincia;28;Madrid;cli.sun.hours.annual;2769;2024;AEMET"]), semillas=())
        (hecho,) = col.collect(["cli.sun.hours.annual"], [PROV_MADRID], Segments())
        assert hecho.value == 2769

    def _con_oficial(self, tmp_path, code, valor_oficial, anio_oficial, anio_plantilla):
        oficial = _f(3, code, valor_oficial, ref="AEMET:3195", period=date(anio_oficial, 1, 1))
        col = PlantillaCollector(
            _csv(tmp_path, [f"provincia;28;Madrid;{code};2700;{anio_plantilla};AEMET"]),
            facts_loader=lambda ids, codes: [oficial], oficiales={code}, semillas=())
        return col.collect([code], [PROV_MADRID], Segments())

    def test_horas_de_sol_manda_la_mas_reciente(self, tmp_path):
        assert [h.value for h in self._con_oficial(
            tmp_path, "cli.sun.hours.annual", 2800, 2020, 2025)] == [2700]

    def test_horas_de_sol_del_mismo_anio_manda_aemet(self, tmp_path):
        assert self._con_oficial(tmp_path, "cli.sun.hours.annual", 2800, 2025, 2025) == []

    def test_la_temperatura_sigue_prefiriendo_las_normales(self, tmp_path):
        assert self._con_oficial(tmp_path, "cli.temp.annual", 15.0, 2020, 2025) == []

    def test_poblacion_de_la_ecp_a_1_de_julio_de_2026(self):
        col = PlantillaCollector(ruta="/no/existe.xlsx")
        hechos = {h.indicator: h for h in col.collect(
            ["dem.pop.total", "dem.sex.men", "dem.sex.women"], [ESPANA], Segments())}
        assert hechos["dem.pop.total"].value == 49_801_559
        assert hechos["dem.sex.men"].value == 24_462_607
        assert hechos["dem.sex.women"].value == 25_338_952
        assert hechos["dem.sex.men"].value + hechos["dem.sex.women"].value == 49_801_559
        assert hechos["dem.pop.total"].period == date(2026, 7, 1)
        assert hechos["dem.pop.total"].source_ref.startswith("INE, Estadística Continua")

    def test_la_ecp_gana_al_padron_de_enero(self):
        padron = _f(1, "dem.pop.total", 49_128_297, ref="INE:29005", period=date(2025, 1, 1))
        col = PlantillaCollector(ruta="/no/existe.xlsx", oficiales={"dem.pop.total"},
                                 facts_loader=lambda ids, codes: [padron])
        (hecho,) = col.collect(["dem.pop.total"], [ESPANA], Segments())
        assert hecho.value == 49_801_559

    def test_la_semilla_de_geografias_lleva_la_ecp(self):
        import json

        from powergis.adapters.collectors.plantilla import SEED_DIR

        datos = json.loads((SEED_DIR / "geographies.json").read_text(encoding="utf-8"))
        assert next(d for d in datos if d["ine_code"] == "ES")["population"] == 49_801_559


# --------------------------------------------------------------------------- #
# AEMET y derivados
# --------------------------------------------------------------------------- #


class TestHorasDeSolAemet:
    def test_media_diaria_por_mes(self):
        normals = {f"{m:02d}": {"inso": "7.5"} for m in range(1, 13)}
        assert _horas_de_sol(normals) == round(7.5 * 365.25)

    def test_total_mensual(self):
        normals = {f"{m:02d}": {"inso": 230} for m in range(1, 13)}
        assert _horas_de_sol(normals) == 2760

    def test_sin_algun_mes_no_hay_anual(self):
        assert _horas_de_sol({"01": {"inso": 7}}) is None


class TestRiesgoDePobreza:
    def test_calibrado_con_la_tasa_nacional(self):
        # Mediana de España (ADRH 2023) → la tasa de la ECV 2024 (19,7 %).
        assert poverty_risk_estimate(19_250) == pytest.approx(19.7, abs=0.1)

    def test_mas_renta_menos_riesgo(self):
        assert poverty_risk_estimate(30_000, 0.30) < poverty_risk_estimate(12_000, 0.30)

    def _derivado(self, valores):
        geo = PROV_MADRID
        col = DerivedCollector(facts_lookup=lambda g, c: valores.get(c))
        return {h.indicator: h for h in col.collect(
            ["eco.poverty.risk_pct", "inm.affordability.years", "inm.rent.effort_pct"],
            [geo], Segments())}

    def test_se_estima_si_no_hay_dato_publicado(self):
        hechos = self._derivado({"eco.income.household.median": 19_250,
                                 "eco.income.household.mean": 45_000,
                                 "inm.price.m2": 2_500, "inm.rent.m2": 15.0})
        assert hechos["eco.poverty.risk_pct"].source_ref.startswith("estimación")
        assert hechos["inm.affordability.years"].value == pytest.approx(5.0)
        assert hechos["inm.rent.effort_pct"].value == pytest.approx(32.0)

    def test_no_se_pisa_el_dato_publicado(self):
        hechos = self._derivado({"eco.income.household.median": 19_250,
                                 "eco.poverty.risk_pct": 18.0})
        assert "eco.poverty.risk_pct" not in hechos


# --------------------------------------------------------------------------- #
# Turismo y vivienda en el informe
# --------------------------------------------------------------------------- #


def _proyecto(scope: Scope) -> Project:
    return Project(project_uuid=uuid4(), wp_user_id=1, wp_post_id=1, scope=scope,
                   segments=Segments(age=("18-35",)),
                   business=BusinessProfile(sector="restauracion"), tier=Tier.AVANZADO)


@pytest.fixture
def uow_tur(geos, facts) -> FakeUnitOfWork:
    extra = [_f(1, "tur.overnight_per_1000hab", 2_000.0)]
    for geo_id, k in ((3, 2.0), (4, 0.5), (5, 1.0), (6, 1.5)):
        extra += [
            _f(geo_id, "tur.overnight_per_1000hab", 2_000.0 * k),
            _f(geo_id, "tur.hotel.travellers.resident", 1_000.0 * k),
            _f(geo_id, "tur.hotel.travellers.foreign", 500.0 * k),
            _f(geo_id, "tur.hotel.foreign_pct", 33.3),
            _f(geo_id, "inm.cadastre.value_mean", 60_000.0 * k, ref="Catastro"),
            _f(geo_id, "inm.cadastre.urban_units", 100_000.0 * k, ref="Catastro"),
            _f(geo_id, "inm.ipv.yoy", 8.0 + k, ref="INE · dato de la comunidad"),
        ]
    return FakeUnitOfWork(geos, [*facts, *extra])


class TestTurismoYVivienda:
    def _informe(self, uow):
        project = _proyecto(Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA))
        ctx = build_context(uow, project, tier=Tier.AVANZADO)
        return ReportBuilder("t").build(project, ctx, version=1, tier=Tier.AVANZADO).as_dict()

    def _sub(self, payload, section, sub):
        sec = next(s for s in payload["sections"] if s["id"] == section)
        return next(s for s in sec["subsections"] if s["id"] == sub)

    def test_indice_turistico_base_espana(self, uow_tur):
        sub = self._sub(self._informe(uow_tur), "turismo", "turismo.indice")
        tabla = sub["tables"][0]
        madrid = next(r for r in tabla["rows"] if r["geo_code"] == "28")
        assert madrid["tur.index"] == 200.0
        assert madrid["_flags"]["tur.index"] == [estado.ESTIMADO]

    def test_turismo_nacional_e_internacional(self, uow_tur):
        sub = self._sub(self._informe(uow_tur), "turismo", "turismo.origen")
        assert [c["id"] for c in sub["charts"]] == ["tur.origen"]
        assert {k["code"] for k in sub["kpis"]} >= {"tur.hotel.travellers.resident",
                                                   "tur.hotel.travellers.foreign"}

    def test_catastro_e_ipv_en_vivienda(self, uow_tur):
        payload = self._informe(uow_tur)
        catastro = self._sub(payload, "inmobiliario", "inmobiliario.catastro")
        assert catastro["layer"] == "catastro_locales_cartografia"
        precio = self._sub(payload, "inmobiliario", "inmobiliario.precio")
        fila = precio["tables"][0]["rows"][0]
        assert fila["_flags"]["inm.ipv.yoy"] == [estado.HEREDADO]

    def test_el_catastro_apagado_quita_la_subseccion(self, uow_tur):
        project = _proyecto(Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA))
        project.layers = {"catastro_locales_cartografia": "excluir"}
        ctx = build_context(uow_tur, project, tier=Tier.AVANZADO)
        payload = ReportBuilder("t").build(project, ctx, version=1, tier=Tier.AVANZADO).as_dict()
        sec = next(s for s in payload["sections"] if s["id"] == "inmobiliario")
        assert "inmobiliario.catastro" not in [s["id"] for s in sec["subsections"]]

    def test_geolens_abre_en_una_tasa(self, uow_tur):
        payload = self._informe(uow_tur)
        on = [layer["id"] for layer in payload["geolens"]["layers"] if layer["default_on"]]
        assert "dem.pop.segment" not in on

    def test_seccion_turismo_en_el_orden(self):
        from powergis.domain import indicators

        assert Section.TURISMO in indicators.sections_for_tier(Tier.AVANZADO)
        assert Section.INMOBILIARIO in indicators.sections_for_tier(Tier.AVANZADO)


# --------------------------------------------------------------------------- #
# Incidencias del motor
# --------------------------------------------------------------------------- #


class TestIncidencias:
    def test_el_municipio_no_guarda_distrito(self):
        from powergis.adapters.db.repositories import SqlProjectRepository

        guardado = {}

        class Sesion:
            def merge(self, row):
                guardado["scope"] = row.scope

            def flush(self):
                return None

        project = _proyecto(Scope(GeoLevel.MUNICIPIO, "42173"))
        SqlProjectRepository(Sesion()).save(project)
        assert guardado["scope"]["children_level"] is None

    def test_osm_sin_pois_no_escribe_ceros(self):
        from powergis.adapters.collectors.osm import OsmCollector

        class Vacia:
            def has_data(self):
                return False

            def count_by_tags(self, geo, tags):
                return 0

        col = OsmCollector(source=Vacia())
        assert col.collect(["cmp.count", "anc.supermarkets"], [PROV_MADRID], Segments()) == []

    def test_source_ref_sin_limite_de_200(self):
        from sqlalchemy import Text

        from powergis.adapters.db.orm import FactRow

        assert isinstance(FactRow.__table__.c.source_ref.type, Text)


def test_los_graficos_mensuales_del_clima_traen_sus_datos(geos, facts):
    """Incidencia: las normales mensuales (segmento «month») no se pedían."""
    extra = [Fact(geo_id=g, indicator=code, period=PERIOD, value=10.0 + i,
                  segment={"month": f"{i + 1:02d}"}, source_ref="AEMET:normales")
             for g in (2, 3, 4, 5, 6) for code in ("cli.temp.month", "cli.precip.month")
             for i in range(12)]
    uow = FakeUnitOfWork(geos, [*facts, *extra])
    ctx = build_context(uow, _proyecto(Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA)),
                        tier=Tier.AVANZADO)
    report = ReportBuilder("t").build(_proyecto(Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA)),
                                      ctx, version=1, tier=Tier.AVANZADO)
    clima = next(s for s in report.as_dict()["sections"] if s["id"] == "clima")
    ids = [c["id"] for sub in clima["subsections"] for c in sub["charts"]]
    assert ids == ["cli.temp.month.chart", "cli.precip.month.chart"]


def test_el_peso_del_publico_objetivo_lleva_valoracion(geos, facts, project):
    from powergis.domain.sections.demografia import Demografia

    # 4 provincias: menos de 5 zonas, se compara con España (20 %).
    uow = FakeUnitOfWork(geos, [*facts, _f(1, "dem.pop.segment_pct", 20.0)])
    ctx = build_context(uow, project, tier=Tier.AVANZADO)
    kpis = [k for sub in Demografia().subsections(ctx) if sub for k in sub.kpis]
    peso = next(k for k in kpis if k.code == "dem.pop.segment_pct")
    assert peso.reference["base"] == "nacional"
    assert peso.rating == "favorable"   # 24 % > 20 % + 5 %


def test_el_pdf_lleva_valoracion_y_etiquetas(advanced_project, uow):
    from powergis.adapters.exports import get_exporter

    uow.facts.upsert_many([_f(3, "eco.poverty.risk_pct", 18.0, ref="estimación PowerGIS"),
                           _f(1, "eco.income.household.mean", 30_000.0)])
    ctx = build_context(uow, advanced_project, tier=Tier.AVANZADO)
    report = ReportBuilder("t").build(advanced_project, ctx, version=1, tier=Tier.AVANZADO)
    html = get_exporter("pdf").to_html(report)
    assert "(est.)" in html and "Estimado" in html
    assert any(r in html for r in ("Favorable", "En la media", "Desfavorable"))
