"""Agregación de municipios a provincia, comunidad y país.

El formulario ofrece informes que comparan provincias («ccaa») y comunidades
(«nacional»), y el INE publica casi todo por municipio: sin agregar, esas
zonas sólo tenían la natalidad.
"""

from __future__ import annotations

from datetime import date

import pytest

from conftest import FakeUnitOfWork
from powergis.application.ingest import AggregateUp, ComputeDerived
from powergis.domain import agregacion
from powergis.domain.enums import GeoLevel
from powergis.domain.models import Fact, Geo

A2025 = date(2025, 1, 1)
A2023 = date(2023, 1, 1)


def pop(v: float | None, periodo: date = A2025) -> tuple[float | None, date]:
    return (v, periodo)


class TestReglas:
    def test_las_personas_se_suman(self):
        out = agregacion.agregar([
            {"dem.pop.total": pop(100)}, {"dem.pop.total": pop(250)},
        ])
        assert out["dem.pop.total"] == (350.0, A2025, agregacion.FUENTE_SUMA)

    def test_un_hueco_impide_la_suma(self):
        """Con un municipio sin dato, la suma sería menor que la real y no lo
        diría. Mejor hueco."""
        out = agregacion.agregar([
            {"dem.pop.total": pop(100), "dem.sex.men": pop(50)},
            {"dem.pop.total": pop(250), "dem.sex.men": pop(None)},
        ])
        assert out["dem.pop.total"][0] == 350.0
        assert "dem.sex.men" not in out

    def test_un_municipio_sin_ningun_dato_no_cuenta(self):
        """Fusionados o desaparecidos: siguen en el nomenclátor, nadie publica."""
        out = agregacion.agregar([{"dem.pop.total": pop(100)}, {}])
        assert out["dem.pop.total"][0] == 100.0

    def test_no_se_suman_anios_distintos(self):
        out = agregacion.agregar([
            {"dem.pop.total": pop(100, A2025)}, {"dem.pop.total": pop(250, A2023)},
        ])
        assert "dem.pop.total" not in out

    def test_porcentajes_ponderados_por_poblacion(self):
        out = agregacion.agregar([
            {"dem.pop.total": pop(100), "dem.age.u18_pct": (20.0, A2023)},
            {"dem.pop.total": pop(300), "dem.age.u18_pct": (10.0, A2023)},
        ])
        valor, periodo, fuente = out["dem.age.u18_pct"]
        assert valor == pytest.approx(12.5)
        assert periodo == A2023, "el periodo es el del dato, no el del peso"
        assert fuente == agregacion.FUENTE_MEDIA

    def test_lo_de_hogares_se_pondera_por_hogares(self):
        """Tamaño medio del hogar de la provincia = personas / hogares."""
        out = agregacion.agregar([
            {"dem.pop.total": pop(100), "dem.household.size": (2.0, A2023)},
            {"dem.pop.total": pop(400), "dem.household.size": (4.0, A2023)},
        ])
        assert out["dem.household.size"][0] == pytest.approx(500 / (50 + 100))

    def test_sin_cobertura_suficiente_no_hay_media(self):
        out = agregacion.agregar([
            {"dem.pop.total": pop(900), "dem.age.mean": (None, A2023)},
            {"dem.pop.total": pop(100), "dem.age.mean": (40.0, A2023)},
        ])
        assert "dem.age.mean" not in out

    def test_mediana_y_gini_no_se_agregan(self):
        """La mediana de una provincia no sale de las de sus municipios."""
        assert "eco.income.household.median" not in agregacion.REGLAS
        assert "eco.gini" not in agregacion.REGLAS


def _geos() -> list[Geo]:
    return [
        Geo(1, GeoLevel.PAIS, "ES", "España", None),
        Geo(2, GeoLevel.CCAA, "08", "Castilla-La Mancha", 1),
        Geo(3, GeoLevel.PROVINCIA, "02", "Albacete", 2),
        Geo(4, GeoLevel.PROVINCIA, "16", "Cuenca", 2),
        Geo(10, GeoLevel.MUNICIPIO, "02003", "Albacete", 3),
        Geo(11, GeoLevel.MUNICIPIO, "02009", "Almansa", 3),
        Geo(12, GeoLevel.MUNICIPIO, "16078", "Cuenca", 4),
        Geo(13, GeoLevel.MUNICIPIO, "16999", "Extinto", 4),
    ]


def _f(geo_id: int, code: str, value: float, period: date = A2025, fuente: str = "INE") -> Fact:
    return Fact(geo_id=geo_id, indicator=code, period=period, value=value,
                segment={}, source_ref=fuente)


class TestAggregateUp:
    def _uow(self, extra: list[Fact] | None = None) -> FakeUnitOfWork:
        hechos = [
            _f(10, "dem.pop.total", 173_000), _f(11, "dem.pop.total", 24_000),
            _f(12, "dem.pop.total", 54_000),
            _f(10, "dem.sex.women", 89_000), _f(11, "dem.sex.women", 12_000),
            _f(12, "dem.sex.women", 28_000),
            _f(10, "dem.sex.men", 84_000), _f(11, "dem.sex.men", 12_000),
            _f(12, "dem.sex.men", 26_000),
            _f(10, "dem.age.65p_pct", 17.0, A2023), _f(11, "dem.age.65p_pct", 20.0, A2023),
            _f(12, "dem.age.65p_pct", 22.0, A2023),
        ]
        return FakeUnitOfWork(_geos(), hechos + (extra or []))

    def test_escribe_provincia_comunidad_y_pais(self):
        uow = self._uow()
        AggregateUp(lambda: uow)()
        valor = {g: uow.facts.fetch([g], ["dem.pop.total"])[0].value for g in (1, 2, 3, 4)}
        assert valor == {3: 197_000, 4: 54_000, 2: 251_000, 1: 251_000}

        mayores = uow.facts.fetch([3], ["dem.age.65p_pct"])[0]
        assert mayores.value == pytest.approx((17 * 173 + 20 * 24) / 197)
        assert mayores.period == A2023

    def test_no_pisa_un_dato_propio_de_la_provincia(self):
        uow = self._uow([_f(3, "dem.pop.total", 400_000, fuente="INE:2852")])
        AggregateUp(lambda: uow)()
        assert uow.facts.fetch([3], ["dem.pop.total"])[0].value == 400_000

    def test_los_datos_de_demostracion_no_cuentan_como_propios(self):
        uow = self._uow([_f(3, "dem.pop.total", 1.0, A2025, fuente="DEMO-SINTÉTICO")])
        AggregateUp(lambda: uow)()
        assert uow.facts.fetch([3], ["dem.pop.total"])[0].value == 197_000

    def test_despues_se_derivan_los_indices_de_la_provincia(self):
        uow = self._uow()
        AggregateUp(lambda: uow)()
        ComputeDerived(lambda: uow)(GeoLevel.PROVINCIA)
        feminidad = uow.facts.fetch([3], ["dem.femininity.index"])
        assert feminidad and feminidad[0].value == pytest.approx(101_000 / 96_000 * 100)


class TestFechaDeLosDerivadosDiarios:
    def test_cada_derivado_con_el_periodo_de_sus_datos(self):
        """Dependencia con el Atlas de 2023 es de 2023, aunque el Padrón sea
        de 2025. Antes, todo se fechaba con el más reciente."""
        uow = FakeUnitOfWork(_geos(), [
            _f(10, "dem.pop.total", 173_000), _f(10, "dem.sex.women", 89_000),
            _f(10, "dem.sex.men", 84_000),
            _f(10, "dem.age.u18_pct", 18.0, A2023), _f(10, "dem.age.65p_pct", 17.0, A2023),
        ])
        ComputeDerived(lambda: uow)(GeoLevel.MUNICIPIO)
        fechas = {
            f.indicator: f.period
            for f in uow.facts.fetch([10], ["dem.dependency.total", "dem.femininity.index"])
        }
        assert fechas == {"dem.dependency.total": A2023, "dem.femininity.index": A2025}
