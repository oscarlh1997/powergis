"""El Atlas de renta y las tablas del INE por distrito y sección censal.

Fixture: `fixtures/adrh_renta_28134.json`, filas como las devuelve
DATOS_TABLA con `det=2` (municipio, distrito, sección y una provincia).
Los nombres y metadatos imitan los del Atlas; no se han podido contrastar con
la API real (el proxy de la sesión no llega al INE), por eso los specs nuevos
van `provisional` y el VPS los comprueba con `powergis ine-verify`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from powergis.adapters.collectors.ine import TABLES, IneCollector, TableSpec
from powergis.adapters.collectors.ine_adrh import SPECS, AdrhCollector
from powergis.domain.enums import GeoLevel
from powergis.domain.models import Geo, Segments

FIXTURE = Path(__file__).parent / "fixtures" / "adrh_renta_28134.json"

GEOS = [
    Geo(10, GeoLevel.MUNICIPIO, "28134", "San Sebastián de los Reyes", 3),
    Geo(11, GeoLevel.DISTRITO, "2813401", "Distrito 01", 10),
    Geo(21, GeoLevel.SECCION, "2813401001", "Sección 01001", 11),
    Geo(23, GeoLevel.SECCION, "2813402001", "Sección 02001", 11),
]


def filas() -> list[dict]:
    return [IneCollector._esencial(r) | {"Tabla": "30896"} for r in json.loads(FIXTURE.read_text())]


def mapear(spec: TableSpec, rows=None, geos=GEOS):
    col = AdrhCollector(client=object())
    by_code = {g.ine_code: g for g in geos}
    return col._map(spec, rows if rows is not None else filas(), by_code,
                    IneCollector._indice_por_nombre(geos), Segments(), None)


def spec(indicador: str) -> TableSpec:
    return next(s for s in SPECS if s.indicator == indicador)


class TestNivelDetectado:
    def test_siete_cifras_es_distrito_y_diez_seccion(self):
        """Era un bug: 7 cifras se tomaba por sección."""
        assert IneCollector._detect_level(["2813401 Distrito 01. Renta."] * 3) == "distrito"
        assert IneCollector._detect_level(["2813401001 Sección. Renta."] * 3) == "seccion"


class TestAtlasPorDistritoYSeccion:
    def test_la_renta_llega_a_municipio_distrito_y_seccion(self):
        hechos = mapear(spec("eco.income.household.mean"))
        ultimo = {(h.geo_id, h.period.year): h.value for h in hechos}
        assert ultimo[(10, 2023)] == 67269
        assert ultimo[(11, 2023)] == round(67269 * 1.1)
        assert ultimo[(21, 2023)] == round(67269 * 1.2)

    def test_la_provincia_no_cae_en_ninguna_zona(self):
        assert all(h.value != 50000 for h in mapear(spec("eco.income.household.mean")))

    def test_el_secreto_de_la_seccion_es_hueco(self):
        hechos = {h.geo_id: h.value for h in mapear(spec("eco.income.household.mean"))}
        assert 23 in hechos and hechos[23] is None

    def test_pide_dos_anos_para_la_variacion_interanual(self):
        assert spec("eco.income.household.mean").nult == 2
        anos = {h.period.year for h in mapear(spec("eco.income.household.mean")) if h.geo_id == 11}
        assert anos == {2022, 2023}

    def test_un_spec_solo_municipal_sigue_apartando_distritos(self):
        municipal = TableSpec("30896", "eco.income.household.mean", "municipio",
                              match=("renta bruta media por hogar",))
        assert {h.geo_id for h in mapear(municipal)} == {10}

    def test_sin_metadatos_se_resuelve_por_el_nombre_del_atlas(self):
        rows = [{"Nombre": "San Sebastián de los Reyes distrito 01. Renta bruta media por hogar. "
                           "Dato base.", "Municipio": None, "Data": [{"Valor": 70000, "Anyo": 2023}],
                 "Tabla": "30896"}]
        hechos = mapear(spec("eco.income.household.mean"), rows)
        assert [(h.geo_id, h.value) for h in hechos] == [(11, 70000.0)]

    def test_umbrales_y_pobreza_ya_no_estan_pendientes(self):
        for code in ("eco.poverty.risk_pct", "eco.income.under15k_pct",
                     "eco.income.over30k_pct", "eco.income.over60k_pct"):
            s = spec(code)
            assert s.pendiente is None and s.provisional and s.operacion == 353
            assert "distrito" in s.niveles and "seccion" in s.niveles


class TestCargaDeSecciones:
    class Cliente:
        def __init__(self) -> None:
            self.pedidas: list[str] = []

        def get_json(self, path, params=None):
            self.pedidas.append(path)
            return json.loads(FIXTURE.read_text())

    def test_cargando_distritos_no_reescribe_municipios(self):
        class Uno(IneCollector):
            SPECS = (TableSpec("30896", "eco.income.household.mean", "municipio",
                               match=("renta bruta media por hogar",),
                               tambien=("distrito", "seccion")),)

        hechos = Uno(client=self.Cliente()).collect(
            ["eco.income.household.mean"], GEOS[:2], Segments())
        assert {h.geo_id for h in hechos} == {11}

    def test_sin_id_no_se_descarga_ni_bloquea(self):
        cliente = self.Cliente()
        col = IneCollector(client=cliente)
        hechos = col.collect(["inm.dwellings.main_pct"], GEOS, Segments())
        assert hechos == [] and col.fallos == [] and cliente.pedidas == []

    def test_verify_lo_dice(self):
        col = IneCollector(client=self.Cliente())
        sin_id = [s for s in TABLES if s.level == "seccion"]
        out = col.verify(sin_id)
        assert out["broken"] == 0 and out["provisional"] == len(sin_id)
        assert all("INE_SECCION_TABLE_" in r["detail"] for r in out["results"])

    def test_lo_provisional_por_seccion_lleva_la_marca(self):
        provisional = TableSpec("1", "dem.sex.men", "seccion", match=("hombres",),
                                provisional="por verificar")
        rows = [{"Nombre": "2813401001. Hombres. Total edades.", "Municipio": None,
                 "Data": [{"Valor": 800, "Anyo": 2024}], "Tabla": "1"}]
        hechos = mapear(provisional, rows)
        assert hechos and "provisional" in hechos[0].source_ref


def test_la_carga_por_seccion_pasa_tambien_los_municipios_al_ine():
    from powergis.application.ingest import IngestData
    from test_distrito import uow

    vistos: list = []

    class Espia:
        CONTEXTO_MUNICIPAL = True
        TODAS_LAS_GEOS = True
        fallos: ClassVar[list] = []

        def provides(self):
            return ["eco.gini"]

        def collect(self, codes, geos_, segments, period):
            vistos.extend(geos_)
            return []

    u = uow([])
    IngestData(lambda: u, {"ine_adrh": Espia()}).by_collector(
        "ine_adrh", [], GeoLevel.SECCION)
    assert {g.level for g in vistos} == {GeoLevel.SECCION, GeoLevel.MUNICIPIO}
    assert len([g for g in vistos if g.level is GeoLevel.SECCION]) == 3
