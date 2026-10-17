"""Censo anual en porcentaje, compra online por comunidad y plantilla del equipo de datos.

Tres reglas que, si se rompen, no dan error y sí un informe falso:

* El cociente del Censo se hace con numerador y denominador de la MISMA
  tabla, y si el denominador no está claro no se calcula.
* La compra online sólo existe por comunidad: provincias y municipios llevan
  la de su comunidad, y la fuente lo dice.
* La plantilla no pisa un dato oficial: sólo rellena huecos.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from powergis.adapters.collectors.ine import IneCollector, TableSpec
from powergis.adapters.collectors.plantilla import PlantillaCollector
from powergis.domain.enums import GeoLevel
from powergis.domain.models import Fact, Geo, Segments
from powergis.domain.territorio import PROVINCIA_A_CCAA, ccaa_de


class FakeClient:
    def __init__(self, tables: dict[str, object]) -> None:
        self.tables = tables

    def get_json(self, path: str, params: dict | None = None) -> object:
        return self.tables[path.rsplit("/", 1)[-1]]


def serie(nombre: str, valor: float | None, dims: list[str] | None = None) -> dict:
    fila: dict = {"Nombre": nombre, "Data": [{"Valor": valor, "Anyo": 2024}]}
    if dims is not None:
        fila["MetaData"] = [{"Variable": {"Nombre": "Municipios", "Id": 19},
                             "Codigo": "28079", "Nombre": "Madrid"}]
        fila["MetaData"] += [{"Variable": {"Nombre": f"v{i}"}, "Nombre": d}
                             for i, d in enumerate(dims)]
    return fila


MADRID = Geo(geo_id=1, level=GeoLevel.MUNICIPIO, ine_code="28079", name="Madrid")
GETAFE = Geo(geo_id=2, level=GeoLevel.MUNICIPIO, ine_code="28065", name="Getafe")


def cargar(tabla: list[dict], spec: TableSpec, geos=(MADRID,)) -> tuple[list[Fact], IneCollector]:
    ine = IneCollector(client=FakeClient({spec.table_id: tabla}))
    ine.SPECS = (spec,)
    ine.PROVIDES = (spec.indicator,)
    return ine.collect([spec.indicator], list(geos), Segments()), ine


class TestTerritorio:
    def test_las_52_provincias_tienen_comunidad(self):
        assert len(PROVINCIA_A_CCAA) == 52
        assert set(PROVINCIA_A_CCAA.values()) == {f"{n:02d}" for n in range(1, 20)}

    def test_coincide_con_la_semilla_de_geografias(self):
        import json

        ruta = Path(__file__).resolve().parents[1] / "src/powergis/seed/geographies.json"
        semilla = {g["ine_code"]: g["parent_code"] for g in json.loads(ruta.read_text())
                   if g["level"] == "provincia"}
        assert semilla == PROVINCIA_A_CCAA

    @pytest.mark.parametrize(("nivel", "codigo", "esperado"), [
        ("municipio", "28079", "13"),
        ("municipio", "1059", "16"),       # Vitoria sin el cero: Excel se lo come
        ("provincia", "08", "09"),
        ("seccion", "4109101001", "01"),
        ("ccaa", "5", "05"),
        ("pais", "ES", None),
    ])
    def test_ccaa_de(self, nivel, codigo, esperado):
        assert ccaa_de(nivel, codigo) == esperado


class TestCocienteDelCenso:
    SPEC = TableSpec("68535", "dem.nat.foreign_pct", "municipio", match=("extranjer",),
                     cociente=True)

    def test_porcentaje_con_metadatos(self):
        tabla = [
            serie("Madrid. Total. Total.", 3_400_000, ["Total", "Total"]),
            serie("Madrid. Total. Extranjera.", 680_000, ["Total", "Extranjera"]),
            serie("Madrid. Hombres. Extranjera.", 330_000, ["Hombres", "Extranjera"]),
            serie("Madrid. Total. Española.", 2_720_000, ["Total", "Española"]),
        ]
        hechos, _ = cargar(tabla, self.SPEC)
        assert len(hechos) == 1
        assert hechos[0].value == pytest.approx(20.0)
        assert hechos[0].source_ref == "INE:68535"

    def test_porcentaje_solo_con_el_nombre(self):
        tabla = [
            serie("Madrid. Ambos sexos. Total.", 1000),
            serie("Madrid. Ambos sexos. Extranjera.", 150),
            serie("Madrid. Mujeres. Extranjera.", 80),
        ]
        hechos, _ = cargar(tabla, self.SPEC)
        assert [h.value for h in hechos] == [pytest.approx(15.0)]

    def test_denominador_ambiguo_no_calcula(self):
        """Dos «totales» distintos: no se sabe cuál es, así que hueco."""
        tabla = [
            serie("Madrid. Total. Total.", 1000, ["Total", "Total"]),
            serie("Madrid. Total. Total.", 900, ["Total", "Total"]),
            serie("Madrid. Total. Extranjera.", 150, ["Total", "Extranjera"]),
        ]
        hechos, _ = cargar(tabla, self.SPEC)
        assert hechos == []

    def test_secreto_estadistico_es_hueco(self):
        tabla = [
            serie("Madrid. Total. Total.", 1000, ["Total", "Total"]),
            serie("Madrid. Total. Extranjera.", None, ["Total", "Extranjera"]),
        ]
        hechos, _ = cargar(tabla, self.SPEC)
        assert [h.value for h in hechos] == [None]

    def test_suma_varias_categorias_del_numerador(self):
        spec = TableSpec("66620", "dem.edu.secondary_pct", "municipio",
                         match=("secundaria",), exclude=("primaria",), cociente=True)
        tabla = [
            serie("Madrid", 1000, ["Total", "Total", "Total"]),
            serie("Madrid", 200, ["Total", "Total", "Primera etapa de educación secundaria"]),
            serie("Madrid", 300, ["Total", "Total", "Segunda etapa de educación secundaria"]),
            serie("Madrid", 250, ["Total", "Total", "Educación primaria e inferior"]),
        ]
        hechos, _ = cargar(tabla, spec)
        assert [h.value for h in hechos] == [pytest.approx(50.0)]

    def test_por_tramo_de_edad(self):
        spec = TableSpec("66620", "dem.edu.university_pct", "municipio",
                         match=("superior",), exclude=("no superior",),
                         segment_from="age", cociente=True)
        tabla = [
            serie("Madrid", 1000, ["Total", "De 25 a 34 años", "Total"]),
            serie("Madrid", 450, ["Total", "De 25 a 34 años", "Educación superior"]),
            serie("Madrid", 100, ["Total", "De 25 a 34 años",
                             "Segunda etapa de secundaria y postsecundaria no superior"]),
            serie("Madrid", 2000, ["Total", "Total", "Total"]),
            serie("Madrid", 600, ["Total", "Total", "Educación superior"]),
        ]
        hechos, _ = cargar(tabla, spec)
        assert [(h.segment, h.value) for h in hechos] == [({"age": "25-34"}, pytest.approx(45.0))]

    def test_provisional_que_no_casa_no_bloquea(self):
        spec = TableSpec("68535", "dem.nat.foreign_pct", "municipio", match=("foraneo",),
                         cociente=True, provisional="sin verificar")
        tabla = [serie("Madrid. Total. Total.", 1000, ["Total", "Total"])]
        hechos, ine = cargar(tabla, spec)
        assert hechos == []
        assert ine.fallos == [], "un mapeo provisional no puede tumbar la carga"

    def test_verificado_que_no_casa_si_bloquea(self):
        spec = TableSpec("68535", "dem.nat.foreign_pct", "municipio", match=("foraneo",),
                         cociente=True)
        tabla = [serie("Madrid. Total. Total.", 1000, ["Total", "Total"])]
        _, ine = cargar(tabla, spec)
        assert ine.fallos

    def test_verify_marca_provisional_sin_romper(self):
        spec = TableSpec("68535", "dem.nat.foreign_pct", "municipio", match=("foraneo",),
                         cociente=True, provisional="sin verificar")
        ine = IneCollector(client=FakeClient({"68535": [serie("28079 Madrid. Total.", 1.0)]}))
        report = ine.verify([spec])
        assert report["results"][0]["status"] == "PROVISIONAL"
        assert report["broken"] == 0


def geo(geo_id: int, level: GeoLevel, code: str, name: str = "x") -> Geo:
    return Geo(geo_id=geo_id, level=level, ine_code=code, name=name)


class TestCompraOnline:
    def test_semilla_por_comunidad_y_herencia(self, tmp_path: Path):
        col = PlantillaCollector(ruta=tmp_path / "no-existe.xlsx")
        geos = [
            geo(1, GeoLevel.CCAA, "13"),
            geo(2, GeoLevel.PROVINCIA, "28"),
            geo(3, GeoLevel.MUNICIPIO, "28079"),
            geo(4, GeoLevel.MUNICIPIO, "38038"),   # Santa Cruz de Tenerife → Canarias
        ]
        hechos = {h.geo_id: h for h in col.collect(["eco.consumer.online_pct"], geos, Segments())}
        assert hechos[1].value == pytest.approx(65.0)
        assert hechos[2].value == pytest.approx(65.0)
        assert hechos[3].value == pytest.approx(65.0)
        assert hechos[4].value == pytest.approx(47.6)
        assert hechos[1].period == date(2025, 1, 1)
        assert "comunidad autónoma" in (hechos[3].source_ref or "")
        assert "comunidad autónoma" not in (hechos[1].source_ref or "")

    def test_nacional(self, tmp_path: Path):
        col = PlantillaCollector(ruta=tmp_path / "no-existe.xlsx")
        hechos = col.collect(["eco.consumer.online_pct"], [geo(1, GeoLevel.PAIS, "ES")], Segments())
        assert [h.value for h in hechos] == [pytest.approx(59.6)]


def plantilla_csv(tmp_path: Path, filas: list[str]) -> Path:
    ruta = tmp_path / "plantilla.csv"
    ruta.write_text(
        "nivel;codigo_ine;territorio;indicador;valor;periodo;fuente\n" + "\n".join(filas),
        encoding="utf-8",
    )
    return ruta


class TestPlantilla:
    def test_carga_y_marca_la_fuente(self, tmp_path: Path):
        ruta = plantilla_csv(tmp_path, [
            "municipio;28079;Madrid;tra.vehicle.imd;45000;2025;Ayuntamiento de Madrid",
            "municipio;28079;Madrid;dem.children.mean;1,4;2021;ECEPOV",
        ])
        col = PlantillaCollector(ruta=ruta, semillas=())
        hechos = {h.indicator: h for h in col.collect(
            ["tra.vehicle.imd", "dem.children.mean"], [MADRID], Segments())}
        assert hechos["tra.vehicle.imd"].value == 45000
        assert hechos["dem.children.mean"].value == pytest.approx(1.4)
        assert hechos["tra.vehicle.imd"].source_ref == "Equipo de datos · Ayuntamiento de Madrid"
        assert col.fallos == []

    def test_no_pisa_un_dato_oficial(self, tmp_path: Path):
        ruta = plantilla_csv(tmp_path, [
            "municipio;28079;Madrid;dem.nat.foreign_pct;30;2025;estimación propia",
            "municipio;28065;Getafe;dem.nat.foreign_pct;12;2025;estimación propia",
        ])
        oficial = Fact(geo_id=1, indicator="dem.nat.foreign_pct", period=date(2025, 1, 1),
                       value=20.0, source_ref="INE:68535")
        col = PlantillaCollector(
            ruta=ruta, semillas=(), oficiales={"dem.nat.foreign_pct"},
            facts_loader=lambda ids, codes: [oficial],
        )
        hechos = col.collect(["dem.nat.foreign_pct"], [MADRID, GETAFE], Segments())
        assert [(h.geo_id, h.value) for h in hechos] == [(2, 12.0)]

    def test_errores_se_dicen(self, tmp_path: Path):
        ruta = plantilla_csv(tmp_path, [
            "municipio;28079;Madrid;dem.civil.single_pct;140;2024;x",
            "municipio;28079;Madrid;dem.inventado;3;2024;x",
            "municipio;28079;Madrid;tra.vehicle.imd;mucho;2024;x",
            "municipio;28079;Madrid;tra.pedestrian.aforo;300;;x",
        ])
        col = PlantillaCollector(ruta=ruta, semillas=())
        assert col.collect(list(col.PROVIDES), [MADRID], Segments()) == []
        assert len(col.fallos) == 4

    def test_xlsx_generada_por_la_herramienta(self, tmp_path: Path):
        """La plantilla que se entrega es la que el colector sabe leer."""
        import importlib.util

        openpyxl = pytest.importorskip("openpyxl")
        ruta_tool = Path(__file__).resolve().parents[1] / "tools" / "build_plantilla.py"
        spec = importlib.util.spec_from_file_location("build_plantilla", ruta_tool)
        assert spec and spec.loader
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        construir = modulo.construir

        ruta = tmp_path / "plantilla.xlsx"
        construir(ruta)
        libro = openpyxl.load_workbook(ruta)
        muni = libro["Municipios"]
        codigos = [c.value for c in muni[2]]
        muni.cell(row=3, column=1, value="28079")
        muni.cell(row=3, column=2, value="Madrid")
        muni.cell(row=3, column=codigos.index("tra.vehicle.imd") + 1, value=45000)
        ind = libro["Indicadores"]
        for fila in ind.iter_rows(min_row=2):
            if fila[0].value in ("tra.vehicle.imd", "dem.edu.university_pct"):
                cab = [c.value for c in ind[1]]
                fila[cab.index("Periodo de referencia")].value = "2025"
                fila[cab.index("Fuente / bibliografía")].value = "Ayuntamiento de Madrid"
        edad = libro["Educacion por edad"]
        edad.append(["municipio", "28079", "Madrid", "25-34", None, None, 52.5])
        libro.save(ruta)

        col = PlantillaCollector(ruta=ruta, semillas=())
        hechos = col.collect(list(col.PROVIDES), [MADRID], Segments())
        assert col.fallos == []
        por = {(h.indicator, h.segment.get("age", "")): h.value for h in hechos}
        assert por[("tra.vehicle.imd", "")] == 45000
        assert por[("dem.edu.university_pct", "25-34")] == pytest.approx(52.5)
        # La compra online precargada en «Comunidades» se hereda en Madrid.
        assert ("eco.consumer.online_pct", "") in por
