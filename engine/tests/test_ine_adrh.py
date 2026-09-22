"""El colector del Atlas de renta, heredando del colector de tablas del INE.

Tenía los mismos fallos que ya se habían arreglado en `IneCollector` y dos
mapeos cruzados. Lo que se fija aquí es que la herencia es real, que cada
indicador sale de la serie que dice su etiqueta, y que lo propio del Atlas —el
secreto estadístico— sigue en pie.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from powergis.adapters.collectors.ine import IneCollector, TableSpec
from powergis.adapters.collectors.ine_adrh import SPECS, AdrhCollector
from powergis.domain.enums import GeoLevel
from powergis.domain.models import Geo, Segments


def geo(geo_id: int, code: str, name: str) -> Geo:
    return Geo(geo_id=geo_id, level=GeoLevel.MUNICIPIO, ine_code=code, name=name, parent_id=None)


def spec_de(indicador: str) -> TableSpec:
    return next(s for s in SPECS if s.indicator == indicador)


class TestHerencia:
    def test_es_un_colector_de_tablas_del_ine(self):
        assert issubclass(AdrhCollector, IneCollector)

    def test_declara_sus_tablas_y_no_las_de_ine(self):
        assert set(AdrhCollector.PROVIDES) == {s.indicator for s in SPECS}
        assert "dem.pop.total" not in AdrhCollector.PROVIDES
        assert "eco.gini" not in IneCollector.PROVIDES

    def test_su_interruptor_no_pisa_el_de_ine(self):
        assert spec_de("eco.gini").env_key == "ADRH_TABLE_ECO_GINI"

    def test_la_renta_usa_las_54_tablas(self):
        """Con una sola tabla se cubriría una provincia: el error de La Rioja."""
        for ind in ("eco.income.household.mean", "eco.income.household.net",
                    "eco.income.percapita", "eco.income.household.median"):
            assert spec_de(ind).operacion == 353
            assert spec_de(ind).varias_tablas is True


class TestCadaIndicadorEnSuSerie:
    """Las seis series de «Indicadores de renta media y mediana», tal cual."""

    FILAS: ClassVar[list[dict]] = [
        {"Nombre": f"Abengibre. {n}. Dato base.", "Data": [{"Valor": v, "Anyo": 2023}]}
        for n, v in (
            ("Renta neta media por persona", 11000.0),
            ("Renta neta media por hogar", 26000.0),
            ("Media de la renta por unidad de consumo", 16000.0),
            ("Mediana de la renta por unidad de consumo", 14500.0),
            ("Renta bruta media por persona", 13200.0),
            ("Renta bruta media por hogar", 31500.0),
        )
    ]

    def valores(self):
        g = geo(1, "02001", "Abengibre")
        col = AdrhCollector(client=object())
        out: dict[str, list[float | None]] = {}
        for spec in SPECS:
            for h in col._map(spec, self.FILAS, {g.ine_code: g},
                              IneCollector._indice_por_nombre([g]), Segments(), None):
                out.setdefault(h.indicator, []).append(h.value)
        return out

    def test_la_bruta_es_la_bruta(self):
        """El catálogo dice «Renta BRUTA media por hogar». Recibía la neta, y el
        modelo de renta disponible le restaba impuestos otra vez."""
        assert self.valores()["eco.income.household.mean"] == [31500.0]

    def test_la_neta_va_aparte(self):
        assert self.valores()["eco.income.household.net"] == [26000.0]

    def test_la_mediana_es_por_unidad_de_consumo(self):
        """Antes se pedía a una tabla demográfica y no salía nada."""
        assert self.valores()["eco.income.household.median"] == [14500.0]

    def test_per_capita_es_la_neta_por_persona(self):
        assert self.valores()["eco.income.percapita"] == [11000.0]

    def test_ningun_indicador_sale_dos_veces(self):
        assert all(len(v) == 1 for v in self.valores().values())


class TestSecretoEstadistico:
    FILAS: ClassVar[list[dict]] = [
        {"Nombre": "Abengibre. Renta bruta media por hogar.", "Data": [{"Valor": "..", "Anyo": 2023}]},
        {"Nombre": "Albacete. Renta bruta media por hogar.", "Data": [{"Valor": 31000.0, "Anyo": 2023}]},
    ]

    def test_no_publicado_es_hueco_nunca_cero(self):
        geos = [geo(1, "02001", "Abengibre"), geo(2, "02003", "Albacete")]
        hechos = AdrhCollector(client=object())._map(
            spec_de("eco.income.household.mean"), self.FILAS,
            {g.ine_code: g for g in geos}, IneCollector._indice_por_nombre(geos),
            Segments(), None,
        )
        valores = {h.geo_id: h.value for h in hechos}
        assert valores == {1: None, 2: 31000.0}


class TestRentaDisponibleObservada:
    """La disponible se observa si hay renta neta; sólo se modela si no."""

    def coleccionar(self, datos, codigos):
        from datetime import date

        from powergis.adapters.collectors.derived import DerivedCollector
        c = DerivedCollector(facts_lookup=lambda g, code: datos.get(code), sector="generico")
        return {h.indicator: h for h in c.collect(codigos, [geo(1, "02001", "Abengibre")],
                                                    Segments(), date(2023, 1, 1))}

    def test_con_neta_la_disponible_es_la_neta_entre_doce(self):
        out = self.coleccionar(
            {"eco.income.household.mean": 36000.0, "eco.income.household.net": 30000.0},
            ["eco.disposable.monthly", "eco.gross_net_gap"],
        )
        assert out["eco.disposable.monthly"].value == pytest.approx(2500.0)
        assert out["eco.gross_net_gap"].value == pytest.approx(500.0)
        assert out["eco.disposable.monthly"].source_ref == "derivado", "observado, no modelado"

    def test_sin_neta_se_modela_y_se_dice(self):
        from powergis.adapters.collectors.derived import MODELLED_REF
        out = self.coleccionar({"eco.income.household.mean": 36000.0}, ["eco.disposable.monthly"])
        assert out["eco.disposable.monthly"].source_ref == MODELLED_REF
        assert out["eco.disposable.monthly"].value < 3000.0

    def test_la_bruta_mensual_es_aritmetica_no_modelo(self):
        out = self.coleccionar({"eco.income.household.mean": 36000.0}, ["eco.gross_monthly"])
        assert out["eco.gross_monthly"].value == pytest.approx(3000.0)
        assert out["eco.gross_monthly"].source_ref == "derivado"



class TestGini:
    def test_el_gini_del_atlas_pasa_a_tanto_por_uno(self):
        from datetime import date

        from powergis.adapters.collectors.ine_adrh import _gini_en_tanto_por_uno
        from powergis.domain.models import Fact

        def f(v):
            return Fact(geo_id=1, indicator="eco.gini", period=date(2023, 1, 1), value=v)

        assert _gini_en_tanto_por_uno(f(31.5)).value == pytest.approx(0.315)
        assert _gini_en_tanto_por_uno(f(0.315)).value == pytest.approx(0.315)
        assert _gini_en_tanto_por_uno(f(None)).value is None
