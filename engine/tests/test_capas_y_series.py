"""Formulario de octubre de 2026: capas con interruptor, series nuevas y sin NSE.

El formulario `[crear_proyecto_v6]` que entregó el equipo de datos el
18/10/2026 trae ocho interruptores (`datos_territoriales`: incluir/excluir),
el «peso de población extranjera» en lugar de la nacionalidad y ya no pregunta
el nivel socioeconómico. Aquí se comprueba el circuito entero del lado del
motor:

  · lo que manda el formulario se acepta (y lo que ya no existe, no);
  · una capa apagada desaparece del informe —sección, tabla, GeoLens,
    glosario, índice de venta del básico—, y encendida sale;
  · las series nuevas se cargan de la plantilla, con herencia de provincia
    donde la fuente no llega a municipio y con su histórico anual;
  · todo ello en los cuatro ámbitos del formulario (nacional, comunidad,
    provincia y municipio).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from conftest import PERIOD, FakeUnitOfWork
from powergis.adapters.collectors.plantilla import (
    COLUMNAS_HISTORICO,
    HOJA_HISTORICO,
    PlantillaCollector,
    validar,
)
from powergis.application.context import build_context
from powergis.application.dto import CreateReportIn, LayersIn, TargetIn
from powergis.domain import capas
from powergis.domain import indicators as catalogo
from powergis.domain.enums import GeoLevel, Section, Tier
from powergis.domain.models import (
    BusinessProfile,
    Fact,
    Geo,
    Project,
    Scope,
    Segments,
)
from powergis.domain.report import ReportBuilder
from powergis.domain.sections.inmobiliario import SERIES_HISTORICAS
from powergis.domain.target import TargetProfile

TODAS_APAGADAS = dict.fromkeys(capas.CLAVES, "excluir")
CODIGOS_NUEVOS = [c for c in capas.INDICADOR_CAPA if not c.startswith("sat.")]


# --------------------------------------------------------------------------- #
# Fixtures: España → Madrid (CCAA) → 4 provincias → 2 municipios → 2 secciones
# --------------------------------------------------------------------------- #


def _f(geo_id: int, code: str, value: float, segment: dict | None = None) -> Fact:
    return Fact(geo_id=geo_id, indicator=code, period=PERIOD, value=value,
                segment=segment or {}, source_ref="TEST")


@pytest.fixture
def geos_completos(geos) -> list[Geo]:
    return [
        *geos,
        Geo(10, GeoLevel.MUNICIPIO, "28079", "Madrid", 3, 3_300_000, 604),
        Geo(11, GeoLevel.MUNICIPIO, "28065", "Getafe", 3, 185_000, 78),
        Geo(20, GeoLevel.SECCION, "2807901001", "Sección 1001", 10, 1_500, 0.2),
        Geo(21, GeoLevel.SECCION, "2807901002", "Sección 1002", 10, 1_700, 0.3),
    ]


def _series(geo_id: int, k: float) -> list[Fact]:
    """Un valor de cada serie nueva, distinto por zona (k)."""
    out = [
        _f(geo_id, "dem.pop.total", 100_000 * k),
        _f(geo_id, "pol.turnout_pct", 60 + k),
        _f(geo_id, "pol.winner_share_pct", 30 + k),
        _f(geo_id, "pol.effective_parties", 3 + k / 10),
        _f(geo_id, "mov.interprov.in_rate", 10 + k),
        _f(geo_id, "mov.interprov.out_rate", 12 - k),
        _f(geo_id, "mov.interprov.net_rate", -2 + 2 * k),
        _f(geo_id, "tur.hotel.travellers", 50_000 * k),
        _f(geo_id, "tur.hotel.overnight", 120_000 * k),
        _f(geo_id, "tur.hotel.stay_mean", 2.4),
        _f(geo_id, "tur.overnight_per_1000hab", 900 * k),
        _f(geo_id, "inm.sales.dwellings", 4_000 * k),
        _f(geo_id, "inm.sales.per_1000hab", 9 + k),
        _f(geo_id, "inm.dwellings.main_pct", 80 - k),
        _f(geo_id, "inm.dwellings.empty_pct", 10 + k),
        _f(geo_id, "inm.price.m2", 1_500 * k),
        _f(geo_id, "inm.price.yoy_change", -1.5 + k),
        _f(geo_id, "inm.rent.m2", 9.5 + k),
        _f(geo_id, "sat.occupancy", 70 + k),
        _f(geo_id, "sat.available_units", 30 * k),
    ]
    for anio, factor in (("2022", 0.9), ("2023", 0.95), ("2024", 1.0)):
        out.append(_f(geo_id, "inm.price.m2", 1_500 * k * factor, {"year": anio}))
        out.append(_f(geo_id, "inm.rent.m2", (9.5 + k) * factor, {"year": anio}))
    return out


@pytest.fixture
def uow_capas(geos_completos, facts) -> FakeUnitOfWork:
    extra: list[Fact] = []
    for geo_id, k in ((1, 4.0), (2, 3.0), (3, 3.5), (4, 1.0), (5, 1.5), (6, 2.0),
                      (10, 3.8), (11, 1.2), (20, 1.0), (21, 2.0)):
        extra += [f for f in _series(geo_id, k)
                  if not (f.indicator == "dem.pop.total" and geo_id in (3, 4, 5, 6))]
    return FakeUnitOfWork(geos_completos, [*facts, *extra])


def proyecto(scope: Scope, layers: dict | None = None, tier: Tier = Tier.AVANZADO) -> Project:
    return Project(
        project_uuid=uuid4(), wp_user_id=7, wp_post_id=7818, scope=scope,
        segments=Segments(age=("18-35",), sex=("F", "M")),
        business=BusinessProfile(sector="restauracion", avg_ticket=18.5),
        tier=tier, layers=dict(layers or {}),
    )


CCAA = Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA)


def informe(uow, project: Project, tier: Tier = Tier.AVANZADO):
    ctx = build_context(uow, project, tier=tier)
    return ReportBuilder("1.0.0-test").build(project, ctx, version=1, tier=tier)


def seccion(report, section: Section):
    return next((s for s in report.sections if s.id == section), None)


def subsecciones(report, section: Section) -> list[str]:
    s = seccion(report, section)
    return [sub.id for sub in (s.subsections if s else [])]


# --------------------------------------------------------------------------- #
# Interruptores: dominio y DTO
# --------------------------------------------------------------------------- #


class TestInterruptores:
    def test_ocho_capas_con_los_nombres_del_formulario(self):
        assert capas.CLAVES == (
            "votaciones_politicas", "traslados_entre_provincias", "nivel_turistico",
            "compra_venta_inmuebles", "viviendas_vacias_principales",
            "precio_vivienda_historico", "catastro_locales_cartografia",
            "alquiler_vivienda_proxy",
        )

    def test_lo_que_no_viene_queda_encendido(self):
        assert capas.normalizar(None) == dict.fromkeys(capas.CLAVES, True)
        assert capas.normalizar({"nivel_turistico": ""})["nivel_turistico"] is True

    @pytest.mark.parametrize("valor, esperado", [
        ("incluir", True), ("excluir", False), ("Excluir ", False), (True, True),
        (False, False), (1, True), (0, False), ("no", False), ("sí", True),
    ])
    def test_incluir_excluir_y_booleanos(self, valor, esperado):
        assert capas.normalizar({"votaciones_politicas": valor})["votaciones_politicas"] is esperado

    def test_ocultas(self):
        assert capas.ocultas({"nivel_turistico": "excluir"}) == {"nivel_turistico"}

    def test_cada_capa_tiene_indicadores_del_catalogo(self):
        for clave in capas.CLAVES:
            codigos = [c for c, k in capas.INDICADOR_CAPA.items() if k == clave]
            assert codigos, clave
            assert all(c in catalogo.BY_CODE for c in codigos), clave

    def test_las_series_nuevas_son_del_avanzado(self):
        for code in CODIGOS_NUEVOS:
            assert catalogo.BY_CODE[code].tier is Tier.AVANZADO, code

    def test_dto_acepta_lo_que_manda_el_formulario(self):
        layers = LayersIn.model_validate({
            "votaciones_politicas": "incluir", "traslados_entre_provincias": "excluir",
            "nivel_turistico": "incluir", "compra_venta_inmuebles": "excluir",
            "viviendas_vacias_principales": "excluir", "precio_vivienda_historico": "excluir",
            "catastro_locales_cartografia": "excluir", "alquiler_vivienda_proxy": "excluir",
        })
        dominio = layers.to_domain()
        assert dominio["votaciones_politicas"] is True
        assert dominio["traslados_entre_provincias"] is False
        assert capas.ocultas(dominio) == {
            "traslados_entre_provincias", "compra_venta_inmuebles",
            "viviendas_vacias_principales", "precio_vivienda_historico",
            "catastro_locales_cartografia", "alquiler_vivienda_proxy",
        }

    def test_dto_rechaza_capas_inventadas_y_valores_raros(self):
        with pytest.raises(ValidationError):
            LayersIn.model_validate({"capa_inventada": "incluir"})
        with pytest.raises(ValidationError):
            LayersIn.model_validate({"nivel_turistico": "quizá"})

    def test_sin_capas_en_el_cuerpo_todo_encendido(self):
        cuerpo = CreateReportIn.model_validate({
            "project_uuid": str(uuid4()), "wp_user_id": 1,
            "scope": {"level": "pais", "ine_code": "ES"},
        })
        assert all(cuerpo.layers.to_domain().values())

    def test_el_hash_solo_cambia_si_se_apaga_algo(self):
        base = proyecto(CCAA)
        encendidas = proyecto(CCAA, dict.fromkeys(capas.CLAVES, True))
        apagada = proyecto(CCAA, {"nivel_turistico": False})
        assert base.input_hash(Tier.AVANZADO) == encendidas.input_hash(Tier.AVANZADO)
        assert base.input_hash(Tier.AVANZADO) != apagada.input_hash(Tier.AVANZADO)


# --------------------------------------------------------------------------- #
# NSE fuera; peso de población extranjera dentro
# --------------------------------------------------------------------------- #


class TestSinNSE:
    def test_el_catalogo_no_tiene_nada_de_nse(self):
        for code in catalogo.BY_CODE:
            assert "nse" not in code.split(".") and not code.startswith("eco.class."), code
        assert "eco.poverty.risk_pct" in catalogo.BY_CODE

    def test_ninguna_subseccion_se_llama_nse(self):
        assert all(i.subsection != "nse" for i in catalogo.CATALOG)

    def test_el_motor_rechaza_un_perfil_con_nse(self):
        with pytest.raises(ValidationError):
            TargetIn.model_validate({"nse": "medio"})

    def test_un_perfil_guardado_con_nse_se_lee_sin_el(self):
        perfil = TargetProfile.from_mapping({"nse": "alto", "gender": "F"})
        assert "nse" not in perfil.as_dict()

    def test_el_informe_no_menciona_nse(self, uow_capas):
        blob = json.dumps(informe(uow_capas, proyecto(CCAA)).as_dict(), ensure_ascii=False)
        assert "eco.nse" not in blob and "eco.class" not in blob


class TestPesoPoblacionExtranjera:
    @pytest.mark.parametrize("peso, kind", [("alta", "higher"), ("media", "middle"),
                                            ("baja", "lower")])
    def test_se_traduce_a_un_criterio(self, peso, kind):
        criterios = TargetProfile(foreign_share=peso).criteria()
        extranjeros = [c for c in criterios if c.indicator == "dem.nat.foreign_pct"]
        assert [c.kind for c in extranjeros] == [kind]

    def test_indiferente_no_puntua(self):
        criterios = TargetProfile(foreign_share="indiferente").criteria()
        assert all(c.indicator != "dem.nat.foreign_pct" for c in criterios)

    def test_media_premia_el_centro(self):
        (criterio,) = [c for c in TargetProfile(foreign_share="media").criteria()
                       if c.indicator == "dem.nat.foreign_pct"]
        poblacion = [5.0, 10.0, 15.0, 20.0, 25.0]
        assert criterio.score(15.0, poblacion) > criterio.score(5.0, poblacion)
        assert criterio.score(15.0, poblacion) > criterio.score(25.0, poblacion)

    def test_manda_sobre_la_nacionalidad_antigua(self):
        criterios = TargetProfile(foreign_share="baja", nationality="Marruecos").criteria()
        assert [c.kind for c in criterios if c.indicator == "dem.nat.foreign_pct"] == ["lower"]

    def test_el_dto_lo_acepta_y_lo_conserva(self):
        perfil = TargetIn.model_validate({"foreign_share": "alta"}).to_domain()
        assert perfil.as_dict()["foreign_share"] == "alta"

    def test_un_perfil_sin_el_no_cambia_de_forma(self):
        assert "foreign_share" not in TargetProfile(gender="F").as_dict()


# --------------------------------------------------------------------------- #
# El informe obedece a los interruptores
# --------------------------------------------------------------------------- #


class TestInformeConCapas:
    def test_todo_encendido_salen_las_tres_secciones_nuevas(self, uow_capas):
        report = informe(uow_capas, proyecto(CCAA))
        assert subsecciones(report, Section.CONTEXTO) == ["contexto.electoral",
                                                         "contexto.traslados"]
        assert subsecciones(report, Section.TURISMO) == ["turismo.hotelero"]
        assert subsecciones(report, Section.INMOBILIARIO) == [
            "inmobiliario.compraventa", "inmobiliario.viviendas", "inmobiliario.precio",
            "inmobiliario.alquiler",
        ]
        assert "competencia.saturacion" in subsecciones(report, Section.COMPETENCIA)

    def test_el_payload_lleva_las_capas_y_cada_subseccion_la_suya(self, uow_capas):
        payload = informe(uow_capas, proyecto(CCAA, {"nivel_turistico": "excluir"})).as_dict()
        assert payload["layers"] == {**dict.fromkeys(capas.CLAVES, True),
                                     "nivel_turistico": False}
        etiquetas = {
            sub["id"]: sub.get("layer")
            for s in payload["sections"] for sub in s.get("subsections", [])
        }
        assert etiquetas["contexto.electoral"] == "votaciones_politicas"
        assert etiquetas["inmobiliario.precio"] == "precio_vivienda_historico"
        # Las secciones de siempre no dependen de ninguna capa.
        demografia = [k for k in etiquetas if k.startswith("demografia.")]
        assert demografia and all(etiquetas[k] is None for k in demografia)

    def test_apagar_una_capa_quita_solo_su_subseccion(self, uow_capas):
        report = informe(uow_capas, proyecto(CCAA, {"votaciones_politicas": "excluir"}))
        assert subsecciones(report, Section.CONTEXTO) == ["contexto.traslados"]

    def test_apagadas_todas_las_de_una_seccion_la_seccion_no_sale(self, uow_capas):
        layers = {"votaciones_politicas": False, "traslados_entre_provincias": False}
        report = informe(uow_capas, proyecto(CCAA, layers))
        assert seccion(report, Section.CONTEXTO) is None
        assert seccion(report, Section.TURISMO) is not None

    def test_todo_apagado(self, uow_capas):
        report = informe(uow_capas, proyecto(CCAA, TODAS_APAGADAS))
        ids = [s.id for s in report.sections]
        assert Section.CONTEXTO not in ids
        assert Section.TURISMO not in ids
        assert Section.INMOBILIARIO not in ids
        # Competencia sigue, pero sin los locales del Catastro.
        assert Section.COMPETENCIA in ids
        blob = json.dumps(report.as_dict(), ensure_ascii=False)
        for code in capas.INDICADOR_CAPA:
            assert f'"{code}"' not in blob, code

    def test_una_capa_apagada_no_se_pide_al_almacen(self, uow_capas):
        ctx = build_context(uow_capas, proyecto(CCAA, {"nivel_turistico": "excluir"}),
                            tier=Tier.AVANZADO)
        assert "tur.hotel.overnight" not in ctx.catalog
        assert "pol.turnout_pct" in ctx.catalog
        assert ctx.hidden_layers == {"nivel_turistico"}

    def test_catastro_apagado_lo_quita_de_competencia(self, uow_capas):
        report = informe(uow_capas, proyecto(CCAA, {"catastro_locales_cartografia": "excluir"}))
        blob = json.dumps(report.as_dict(), ensure_ascii=False)
        assert '"sat.occupancy"' not in blob and '"sat.available_units"' not in blob
        assert seccion(report, Section.COMPETENCIA) is not None

    def test_geolens_y_glosario_respetan_las_capas(self, uow_capas):
        apagado = informe(uow_capas, proyecto(CCAA, {"compra_venta_inmuebles": False})).as_dict()
        encendido = informe(uow_capas, proyecto(CCAA)).as_dict()
        def indicadores_geolens(p):
            return {c["indicator"] for c in p["geolens"].get("layers", [])}
        def glosario(p):
            return json.dumps(p["glossary"], ensure_ascii=False)
        assert "inm.sales.per_1000hab" not in indicadores_geolens(apagado)
        assert "inm.sales.per_1000hab" not in glosario(apagado)
        assert "inm.price.m2" in json.dumps(apagado, ensure_ascii=False)
        assert "inm.sales.per_1000hab" in json.dumps(encendido, ensure_ascii=False)

    def test_el_historico_de_precio_es_una_linea_por_anio(self, uow_capas):
        report = informe(uow_capas, proyecto(CCAA))
        sub = next(s for s in seccion(report, Section.INMOBILIARIO).subsections
                   if s.id == "inmobiliario.precio")
        historico = next(c for c in sub.charts if c.id == "inm.price.m2.historico")
        assert historico.type == "line"
        assert historico.x == ["2022", "2023", "2024"]
        assert len(historico.series) >= 2
        assert set(SERIES_HISTORICAS) == set(COLUMNAS_HISTORICO)

    def test_sin_datos_la_capa_avisa_y_no_inventa(self, uow, project):
        project.tier = Tier.AVANZADO
        report = informe(uow, project)
        assert subsecciones(report, Section.TURISMO) == []
        assert any("Nivel turístico: todavía no hay datos cargados" in w
                   for w in report.warnings)


class TestInformeBasicoConCapas:
    def test_las_secciones_nuevas_viajan_bloqueadas(self, uow_capas):
        report = informe(uow_capas, proyecto(CCAA, tier=Tier.BASICO), tier=Tier.BASICO)
        for section in (Section.CONTEXTO, Section.TURISMO, Section.INMOBILIARIO):
            s = seccion(report, section)
            assert s is not None and not s.available and s.locked_reason == "tier"
            assert s.preview

    def test_una_seccion_apagada_ni_siquiera_se_anuncia(self, uow_capas):
        layers = {"nivel_turistico": "excluir", "votaciones_politicas": "excluir"}
        report = informe(uow_capas, proyecto(CCAA, layers, tier=Tier.BASICO), tier=Tier.BASICO)
        assert seccion(report, Section.TURISMO) is None
        contexto = seccion(report, Section.CONTEXTO)
        assert contexto is not None
        etiquetas = " ".join(contexto.preview).lower()
        assert "particip" not in etiquetas and "electoral" not in etiquetas
        assert contexto.preview

    def test_el_basico_no_filtra_datos_de_las_capas(self, uow_capas):
        payload = informe(uow_capas, proyecto(CCAA, tier=Tier.BASICO), tier=Tier.BASICO).as_dict()
        blob = json.dumps(payload, ensure_ascii=False)
        for code in CODIGOS_NUEVOS:
            assert f'"{code}"' not in blob, code


# --------------------------------------------------------------------------- #
# Los cuatro ámbitos del formulario
# --------------------------------------------------------------------------- #


AMBITOS = {
    "nacional": Scope(GeoLevel.PAIS, "ES", GeoLevel.CCAA),
    "comunidad": Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA),
    "provincia": Scope(GeoLevel.PROVINCIA, "28", GeoLevel.MUNICIPIO),
    "municipio": Scope(GeoLevel.MUNICIPIO, "28079", GeoLevel.SECCION),
}


@pytest.mark.parametrize("ambito", list(AMBITOS))
@pytest.mark.parametrize("encendidas", [True, False], ids=["capas-on", "capas-off"])
@pytest.mark.parametrize("tier", [Tier.BASICO, Tier.AVANZADO])
def test_cada_ambito_respeta_los_interruptores(uow_capas, ambito, encendidas, tier):
    layers = {} if encendidas else TODAS_APAGADAS
    report = informe(uow_capas, proyecto(AMBITOS[ambito], layers, tier=tier), tier=tier)
    payload = report.as_dict()
    json.dumps(payload, ensure_ascii=False)
    ids = [s.id for s in report.sections]
    assert Section.DEMOGRAFIA in ids
    assert payload["layers"] == dict.fromkeys(capas.CLAVES, encendidas)
    nuevas = {Section.CONTEXTO, Section.TURISMO, Section.INMOBILIARIO}
    if encendidas:
        assert nuevas <= set(ids)
    else:
        assert not nuevas & set(ids)
    if tier is Tier.AVANZADO and encendidas:
        if ambito == "municipio":
            # Por sección censal sólo llega el Censo 2021 (viviendas); el
            # turismo y el precio no se publican a ese nivel y se dice así.
            assert subsecciones(report, Section.TURISMO) == []
            assert subsecciones(report, Section.INMOBILIARIO) == ["inmobiliario.viviendas"]
            assert any("Nivel turístico: la fuente no se publica por sección censal" in w
                       for w in report.warnings)
        else:
            assert subsecciones(report, Section.TURISMO) == ["turismo.hotelero"]
            assert "inmobiliario.precio" in subsecciones(report, Section.INMOBILIARIO)


# --------------------------------------------------------------------------- #
# API: el cuerpo que construye el plugin
# --------------------------------------------------------------------------- #


class TestApi:
    @pytest.fixture
    def client(self, uow, monkeypatch):
        from fastapi.testclient import TestClient

        import powergis.api.deps as deps
        import powergis.api.routers.reports as reports_router
        from powergis.api.main import create_app
        from powergis.application.create_report import CreateReport

        encolados: list = []
        monkeypatch.setattr(deps, "enqueue_report", lambda rid, q: encolados.append((rid, q)))
        monkeypatch.setattr(reports_router, "uow_factory", lambda: uow)
        monkeypatch.setattr(deps, "uow_factory", lambda: uow)
        app = create_app()
        app.dependency_overrides[deps.get_create_report] = lambda: CreateReport(
            lambda: uow, "1.0.0-test", lambda rid, q: encolados.append((rid, q))
        )
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def _cuerpo(self, **extra) -> dict:
        return {
            "project_uuid": str(uuid4()), "wp_user_id": 7, "wp_post_id": 7818,
            "tier": "avanzado",
            "scope": {"level": "ccaa", "ine_code": "13", "children_level": "provincia"},
            "segments": {"age": ["18-35"]},
            "business": {"sector": "restauracion"},
            **extra,
        }

    def test_crea_con_capas_y_peso_extranjero(self, client, uow):
        from test_api import signed_post

        cuerpo = self._cuerpo(
            target={"foreign_share": "media", "education_level": "universitario"},
            layers={"nivel_turistico": "excluir", "votaciones_politicas": "incluir"},
        )
        r = signed_post(client, "/v1/reports", cuerpo)
        assert r.status_code == 202, r.text
        guardado = next(iter(uow.projects._items.values()))
        assert capas.ocultas(guardado.layers) == {"nivel_turistico"}
        assert guardado.target.foreign_share == "media"

    def test_rechaza_nse(self, client):
        from test_api import signed_post

        r = signed_post(client, "/v1/reports", self._cuerpo(target={"nse": "alto"}))
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Plantilla del equipo de datos: series nuevas
# --------------------------------------------------------------------------- #


MADRID = Geo(10, GeoLevel.MUNICIPIO, "28079", "Madrid", 3)
TOLEDO_CIUDAD = Geo(12, GeoLevel.MUNICIPIO, "45168", "Toledo", 4)
PROV_MADRID = Geo(3, GeoLevel.PROVINCIA, "28", "Madrid", 2)
CCAA_MADRID = Geo(2, GeoLevel.CCAA, "13", "Comunidad de Madrid", 1)


def csv_plantilla(tmp_path: Path, filas: list[str], con_anio: bool = False) -> Path:
    ruta = tmp_path / "plantilla.csv"
    cab = "nivel;codigo_ine;territorio;indicador;valor;periodo;fuente"
    if con_anio:
        cab += ";anio"
    ruta.write_text(cab + "\n" + "\n".join(filas), encoding="utf-8")
    return ruta


class TestPlantillaSeriesNuevas:
    def test_todas_las_series_nuevas_se_pueden_cargar(self):
        for code in [*CODIGOS_NUEVOS, "cli.humidity.annual", "cli.sun.hours.annual"]:
            assert code in PlantillaCollector.PROVIDES, code

    def test_carga_y_hereda_de_la_provincia(self, tmp_path: Path):
        ruta = csv_plantilla(tmp_path, [
            "provincia;28;Madrid;inm.price.m2;2950;2025;MIVAU",
            "provincia;28;Madrid;inm.sales.dwellings;90000;2024;INE ETDP",
            "provincia;28;Madrid;cli.humidity.annual;57;2019;CTE",
            "provincia;28;Madrid;cli.sun.hours.annual;2769;2024;AEMET",
            "municipio;28079;Madrid;inm.rent.m2;19,8;2024;SERPAVI",
        ])
        col = PlantillaCollector(ruta=ruta, semillas=())
        hechos = {(h.geo_id, h.indicator): h for h in col.collect(
            ["inm.price.m2", "inm.sales.dwellings", "cli.humidity.annual",
             "cli.sun.hours.annual", "inm.rent.m2"],
            [PROV_MADRID, MADRID, TOLEDO_CIUDAD], Segments())}
        assert col.fallos == []
        assert hechos[(3, "inm.price.m2")].value == 2950
        # El municipio hereda el valor tasado y el clima de su provincia...
        assert hechos[(10, "inm.price.m2")].value == 2950
        assert "dato de la provincia" in hechos[(10, "inm.price.m2")].source_ref
        assert hechos[(10, "cli.humidity.annual")].value == 57
        assert hechos[(10, "cli.sun.hours.annual")].value == 2769
        # ...pero un total (compraventas) no se hereda nunca.
        assert (10, "inm.sales.dwellings") not in hechos
        # El dato propio no se pisa con el heredado.
        assert hechos[(10, "inm.rent.m2")].value == pytest.approx(19.8)
        # Otra provincia sin datos: nada.
        assert not [k for k in hechos if k[0] == 12]

    def test_la_api_manda_sobre_el_heredado(self, tmp_path: Path):
        ruta = csv_plantilla(tmp_path, ["provincia;28;Madrid;cli.temp.annual;15;2024;AEMET"])
        oficial = Fact(geo_id=10, indicator="cli.temp.annual", period=date(2024, 1, 1),
                       value=15.9, source_ref="AEMET")
        col = PlantillaCollector(ruta=ruta, semillas=(), oficiales={"cli.temp.annual"},
                                 facts_loader=lambda ids, codes: [oficial])
        hechos = col.collect(["cli.temp.annual"], [PROV_MADRID, MADRID], Segments())
        assert [(h.geo_id, h.value) for h in hechos] == [(3, 15)]

    def test_negativos_solo_donde_tiene_sentido(self, tmp_path: Path):
        ruta = csv_plantilla(tmp_path, [
            "provincia;28;Madrid;mov.interprov.net_rate;-3,4;2024;INE EMCR",
            "provincia;28;Madrid;inm.price.yoy_change;-1,2;2025;MIVAU",
            "provincia;28;Madrid;tur.hotel.overnight;-5;2024;INE EOH",
        ])
        col = PlantillaCollector(ruta=ruta, semillas=())
        hechos = {h.indicator: h.value for h in col.collect(
            list(col.PROVIDES), [PROV_MADRID], Segments())}
        assert hechos["mov.interprov.net_rate"] == pytest.approx(-3.4)
        assert hechos["inm.price.yoy_change"] == pytest.approx(-1.2)
        assert "tur.hotel.overnight" not in hechos
        assert len(col.fallos) == 1 and "negativo" in col.fallos[0]

    def test_porcentajes_fuera_de_rango(self, tmp_path: Path):
        ruta = csv_plantilla(tmp_path, ["ccaa;13;Madrid;pol.turnout_pct;140;2023;Interior"])
        col = PlantillaCollector(ruta=ruta, semillas=())
        assert col.collect(["pol.turnout_pct"], [CCAA_MADRID], Segments()) == []
        assert "0–100" in col.fallos[0]

    def test_historico_en_csv_con_anio(self, tmp_path: Path):
        ruta = csv_plantilla(tmp_path, [
            "provincia;28;Madrid;inm.price.m2;2500;;MIVAU;2021",
            "provincia;28;Madrid;inm.price.m2;2700;;MIVAU;2023",
            "provincia;28;Madrid;inm.price.m2;2950;2025;MIVAU;",
        ], con_anio=True)
        col = PlantillaCollector(ruta=ruta, semillas=())
        hechos = col.collect(["inm.price.m2"], [PROV_MADRID], Segments())
        assert col.fallos == []
        por = {h.segment.get("year", ""): h.value for h in hechos}
        assert por == {"2021": 2500, "2023": 2700, "": 2950}

    def test_el_nse_ya_no_se_carga(self, tmp_path: Path):
        ruta = csv_plantilla(tmp_path, ["seccion;2807901001;x;eco.nse.upper_middle_pct;20;2021;x"])
        col = PlantillaCollector(ruta=ruta, semillas=())
        assert col.collect(list(col.PROVIDES), [Geo(20, GeoLevel.SECCION, "2807901001", "x")],
                           Segments()) == []
        assert "indicador desconocido" in col.fallos[0]


def _herramienta():
    import importlib.util

    ruta = Path(__file__).resolve().parents[1] / "tools" / "build_plantilla.py"
    spec = importlib.util.spec_from_file_location("build_plantilla_capas", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _fijar_meta(libro, codigos: dict[str, tuple[str, str]]) -> None:
    ind = libro["Indicadores"]
    cab = [c.value for c in ind[1]]
    for fila in ind.iter_rows(min_row=2):
        if fila[0].value in codigos:
            periodo, fuente = codigos[fila[0].value]
            fila[cab.index("Periodo de referencia")].value = periodo
            fila[cab.index("Fuente / bibliografía")].value = fuente


class TestPlantillaXlsx:
    def test_hoja_de_series_historicas_y_validacion(self, tmp_path: Path):
        openpyxl = pytest.importorskip("openpyxl")
        ruta = _herramienta().construir(tmp_path / "plantilla.xlsx")
        libro = openpyxl.load_workbook(ruta)
        assert HOJA_HISTORICO in libro.sheetnames
        prov = libro["Provincias"]
        codigos = [c.value for c in prov[2]]
        assert "inm.price.m2" in codigos and "cli.sun.hours.annual" in codigos
        assert all("nse" not in str(c) for hoja in libro.worksheets for c in hoja[2]
                   if c.value)
        prov.cell(row=3, column=1, value="28")
        prov.cell(row=3, column=2, value="Madrid")
        prov.cell(row=3, column=codigos.index("inm.price.m2") + 1, value=2950)
        prov.cell(row=3, column=codigos.index("tur.hotel.overnight") + 1, value="muchas")
        hist = libro[HOJA_HISTORICO]
        hist.append(["provincia", "28", "Madrid", "inm.price.m2", 2020, 2400])
        hist.append(["provincia", "28", "Madrid", "inm.price.m2", 2021, 2500])
        hist.append(["provincia", "28", "Madrid", "tur.hotel.overnight", 2021, 5])
        _fijar_meta(libro, {"inm.price.m2": ("2025", "MIVAU"),
                            "tur.hotel.overnight": ("2024", "INE EOH")})
        libro.save(ruta)

        col = PlantillaCollector(ruta=ruta, semillas=())
        hechos = col.collect(["inm.price.m2"], [PROV_MADRID, MADRID], Segments())
        por = {(h.geo_id, h.segment.get("year", "")): h.value for h in hechos}
        assert por[(3, "")] == 2950
        assert por[(3, "2020")] == 2400 and por[(3, "2021")] == 2500
        assert por[(10, "")] == 2950          # heredado
        assert (10, "2020") not in por       # el histórico no se hereda

        v = validar(ruta)
        assert not v.ok
        assert v.cargados["Provincias"]["inm.price.m2"] == 1
        assert v.cargados[HOJA_HISTORICO]["inm.price.m2"] == 2
        assert any("no es un número" in m for m in v.rechazos["Provincias"])
        assert any("no tiene serie histórica" in m for m in v.rechazos[HOJA_HISTORICO])
        assert "inm.price.m2" not in v.vacias["Provincias"]
        assert "inm.rent.m2" in v.vacias["Provincias"]

    def test_migrar_conserva_lo_relleno(self, tmp_path: Path):
        openpyxl = pytest.importorskip("openpyxl")
        herramienta = _herramienta()
        vieja = herramienta.construir(tmp_path / "vieja.xlsx")
        libro = openpyxl.load_workbook(vieja)
        prov = libro["Provincias"]
        codigos = [c.value for c in prov[2]]
        prov.cell(row=3, column=1, value="28")
        prov.cell(row=3, column=codigos.index("cli.temp.annual") + 1, value=15.1)
        prov.cell(row=3, column=codigos.index("cli.precip.annual") + 1, value="=400+21")
        libro.create_sheet("Notas del equipo").append(["Una nota que no hay que perder"])
        _fijar_meta(libro, {"cli.temp.annual": ("2024", "AEMET")})
        libro.save(vieja)

        nueva = herramienta.construir(tmp_path / "nueva.xlsx")
        herramienta.migrar(vieja, nueva)
        libro2 = openpyxl.load_workbook(nueva)
        prov2 = libro2["Provincias"]
        cods2 = [c.value for c in prov2[2]]
        fila = next(r for r in prov2.iter_rows(min_row=3) if r[0].value == "28")
        assert fila[cods2.index("cli.temp.annual")].value == 15.1
        assert fila[cods2.index("cli.precip.annual")].value == "=400+21"
        assert libro2["Notas del equipo"]["A1"].value == "Una nota que no hay que perder"
        ind = {r[0].value: r for r in libro2["Indicadores"].iter_rows(min_row=2)}
        assert ind["cli.temp.annual"][7].value == "AEMET"
