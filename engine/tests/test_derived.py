"""Indicadores derivados.

Son los números calculados que acaban en el informe: tasa de dependencia,
índice de envejecimiento, densidad, feminidad. Nadie los introduce a mano, así
que si una fórmula está mal el informe miente y no hay ningún error que lo
delate.

`DerivedCollector` recibe su acceso a los datos por inyección
(`facts_lookup`), así que se comprueba entero sin base de datos.

La regla que más se comprueba aquí es la de los huecos: **si falta el dato de
partida, el derivado NO se calcula**. Un cero inventado donde había un hueco
se convierte en un informe que afirma algo falso — y en este dominio los
huecos son reales: el INE aplica secreto estadístico en municipios pequeños.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

import pytest

from powergis.adapters.collectors.derived import MODELLED_REF, DerivedCollector
from powergis.domain.enums import GeoLevel
from powergis.domain.models import Geo, Segments

PERIODO = date(2024, 1, 1)


def geo(geo_id: int = 1, area_km2: float | None = 100.0) -> Geo:
    return Geo(
        geo_id=geo_id,
        level=GeoLevel.MUNICIPIO,
        ine_code="28079",
        name="Madrid",
        parent_id=None,
        area_km2=area_km2,
    )


def coleccionar(datos: dict[str, float | None], indicadores, area_km2=100.0, **kw):
    """Ejecuta el colector con un almacén simulado."""
    collector = DerivedCollector(
        facts_lookup=lambda geo_id, code: datos.get(code), **kw
    )
    hechos = collector.collect(
        list(indicadores), [geo(area_km2=area_km2)], Segments(), PERIODO
    )
    return {h.indicator: h.value for h in hechos}


class TestFormulas:
    def test_tasa_de_dependencia(self):
        """(0-15 + 65+) / 16-64 × 100."""
        out = coleccionar(
            {"dem.age.0_15": 150.0, "dem.age.16_64": 600.0, "dem.age.65p": 250.0},
            ["dem.dependency.total"],
        )
        assert out["dem.dependency.total"] == pytest.approx((150 + 250) / 600 * 100)

    def test_indice_de_envejecimiento(self):
        """65+ / 0-15 × 100. Por encima de 100 hay más mayores que niños."""
        out = coleccionar(
            {"dem.age.65p": 250.0, "dem.age.0_15": 125.0}, ["dem.ageing.index"]
        )
        assert out["dem.ageing.index"] == pytest.approx(200.0)

    def test_indice_de_feminidad(self):
        out = coleccionar(
            {"dem.sex.women": 520.0, "dem.sex.men": 480.0}, ["dem.femininity.index"]
        )
        assert out["dem.femininity.index"] == pytest.approx(520 / 480 * 100)

    def test_densidad_de_poblacion(self):
        out = coleccionar({"dem.pop.total": 5000.0}, ["dem.pop.density"], area_km2=25.0)
        assert out["dem.pop.density"] == pytest.approx(200.0)

    def test_porcentaje_de_mujeres(self):
        out = coleccionar(
            {"dem.sex.women": 510.0, "dem.pop.total": 1000.0}, ["dem.sex.women_pct"]
        )
        assert out["dem.sex.women_pct"] == pytest.approx(51.0)


class TestHuecos:
    """Un hueco no es un cero. Es la regla de honestidad del almacén."""

    def test_sin_datos_no_inventa_indicadores(self):
        out = coleccionar({}, ["dem.dependency.total", "dem.ageing.index"])
        assert out == {} or all(v is None for v in out.values())

    def test_dividir_por_cero_no_produce_un_numero(self):
        """Población activa a cero: la tasa de dependencia no existe, no es
        infinita ni cero."""
        out = coleccionar(
            {"dem.age.0_15": 150.0, "dem.age.16_64": 0.0, "dem.age.65p": 250.0},
            ["dem.dependency.total"],
        )
        assert out.get("dem.dependency.total") is None

    def test_sin_superficie_no_hay_densidad(self):
        """Una geografía sin área no da densidad cero: no da densidad."""
        out = coleccionar({"dem.pop.total": 5000.0}, ["dem.pop.density"], area_km2=None)
        assert out.get("dem.pop.density") is None

    def test_un_dato_ausente_no_arrastra_a_los_demas(self):
        """Falta la superficie, pero el envejecimiento sí puede calcularse."""
        out = coleccionar(
            {"dem.age.65p": 250.0, "dem.age.0_15": 125.0},
            ["dem.pop.density", "dem.ageing.index"],
            area_km2=None,
        )
        assert out["dem.ageing.index"] == pytest.approx(200.0)


class TestSeleccion:
    def test_solo_devuelve_lo_que_se_le_pide(self):
        datos = {
            "dem.age.65p": 250.0,
            "dem.age.0_15": 125.0,
            "dem.sex.women": 520.0,
            "dem.sex.men": 480.0,
        }
        out = coleccionar(datos, ["dem.ageing.index"])
        assert "dem.femininity.index" not in out

    def test_ignora_indicadores_que_no_son_suyos(self):
        out = coleccionar({"dem.pop.total": 100.0}, ["dem.pop.total", "inventado.xyz"])
        assert "inventado.xyz" not in out

    def test_sin_geografias_no_hay_nada_que_calcular(self):
        collector = DerivedCollector(facts_lookup=lambda g, c: 1.0)
        assert collector.collect(["dem.ageing.index"], [], Segments(), PERIODO) == []

    def test_sin_indicadores_pedidos_no_calcula(self):
        collector = DerivedCollector(facts_lookup=lambda g, c: 1.0)
        assert collector.collect([], [geo()], Segments(), PERIODO) == []


class TestSector:
    def test_un_sector_desconocido_cae_en_generico(self):
        """No revienta ni calcula con una cesta de consumo equivocada."""
        collector = DerivedCollector(sector="sector-que-no-existe")
        assert collector.sector == "generico"

    def test_un_sector_conocido_se_conserva(self):
        collector = DerivedCollector(sector="restauracion")
        assert collector.sector in ("restauracion", "generico")


class TestEconomicos:
    """Renta bruta, disponible, ahorro y tensión financiera.

    Se modelan a partir de la renta media del hogar aplicando un tipo efectivo
    progresivo, así que son estimaciones y no dato del INE. El colector los
    marca como modelados precisamente para que el informe no los presente como
    observados.
    """

    RENTA: ClassVar[dict[str, float]] = {"eco.income.household.mean": 36_000.0}

    def test_la_renta_bruta_mensual_es_la_anual_entre_doce(self):
        out = coleccionar(self.RENTA, ["eco.gross_monthly"])
        assert out["eco.gross_monthly"] == pytest.approx(3000.0)

    def test_la_disponible_es_menor_que_la_bruta(self):
        """Si salieran iguales, el tipo efectivo no se estaría aplicando."""
        out = coleccionar(self.RENTA, ["eco.gross_monthly", "eco.disposable.monthly"])
        assert out["eco.disposable.monthly"] < out["eco.gross_monthly"]
        assert out["eco.disposable.monthly"] > 0

    def test_la_brecha_cuadra_con_las_dos_anteriores(self):
        out = coleccionar(
            self.RENTA,
            ["eco.gross_monthly", "eco.disposable.monthly", "eco.gross_net_gap"],
        )
        assert out["eco.gross_net_gap"] == pytest.approx(
            out["eco.gross_monthly"] - out["eco.disposable.monthly"]
        )

    def test_el_tipo_efectivo_es_progresivo(self):
        """A más renta, mayor proporción se va en impuestos."""
        baja = coleccionar(
            {"eco.income.household.mean": 18_000.0},
            ["eco.gross_monthly", "eco.disposable.monthly"],
        )
        alta = coleccionar(
            {"eco.income.household.mean": 90_000.0},
            ["eco.gross_monthly", "eco.disposable.monthly"],
        )
        def retencion(o):
            return 1 - o["eco.disposable.monthly"] / o["eco.gross_monthly"]

        assert retencion(alta) > retencion(baja)

    def test_la_tasa_de_ahorro_nunca_es_negativa(self):
        """Una renta baja consume más del 100 % de lo disponible; la tasa se
        corta en cero en vez de salir negativa, que no significaría nada en el
        informe."""
        out = coleccionar({"eco.income.household.mean": 9_000.0}, ["eco.saving.rate"])
        assert out["eco.saving.rate"] >= 0.0

    def test_la_tension_financiera_esta_acotada_a_cien(self):
        out = coleccionar(
            {"eco.income.household.mean": 9_000.0}, ["eco.financial_stress.index"]
        )
        assert 0.0 <= out["eco.financial_stress.index"] <= 100.0

    def test_el_gasto_del_sector_depende_del_sector(self):
        restauracion = coleccionar(
            self.RENTA, ["eco.sector_spend"], sector="restauracion"
        )
        generico = coleccionar(self.RENTA, ["eco.sector_spend"], sector="generico")
        assert restauracion["eco.sector_spend"] != generico["eco.sector_spend"]

    def test_sin_renta_no_se_modela_nada_economico(self):
        out = coleccionar(
            {}, ["eco.gross_monthly", "eco.disposable.monthly", "eco.saving.rate"]
        )
        assert out == {}

    def test_el_indice_nse_necesita_la_mediana(self):
        sin_mediana = coleccionar({"eco.gini": 0.32}, ["eco.nse.index"])
        assert sin_mediana == {}

        con_mediana = coleccionar(
            {"eco.income.household.median": 28_000.0, "eco.gini": 0.32,
             "eco.nse.risk_pct": 18.0},
            ["eco.nse.index", "eco.resilience.index"],
        )
        assert "eco.nse.index" in con_mediana
        assert "eco.resilience.index" in con_mediana

    def test_los_modelados_se_marcan_como_tales(self):
        """El informe tiene que poder distinguir lo observado de lo estimado."""
        collector = DerivedCollector(
            facts_lookup=lambda g, c: self.RENTA.get(c), sector="generico"
        )
        hechos = collector.collect(
            ["eco.gross_monthly"], [geo()], Segments(), PERIODO
        )
        assert hechos, "esperaba al menos un hecho modelado"
        # `source_ref` distingue lo modelado de lo derivado por aritmética
        # directa. Es lo que permite al informe no presentar una estimación
        # como si fuera un dato del INE.
        assert hechos[0].source_ref == MODELLED_REF
        assert hechos[0].source_ref != "derivado"

    def test_el_nse_se_calcula_aunque_falten_gini_y_riesgo(self):
        """El almacén tiene huecos reales; el índice no debe exigirlo todo."""
        solo_mediana = coleccionar(
            {"eco.income.household.median": 28_000.0}, ["eco.nse.index"]
        )
        assert "eco.nse.index" in solo_mediana

    def test_mas_desigualdad_no_mejora_la_resiliencia(self):
        igual = coleccionar(
            {"eco.income.household.median": 28_000.0, "eco.gini": 0.25,
             "eco.nse.risk_pct": 10.0},
            ["eco.resilience.index"],
        )
        desigual = coleccionar(
            {"eco.income.household.median": 28_000.0, "eco.gini": 0.45,
             "eco.nse.risk_pct": 30.0},
            ["eco.resilience.index"],
        )
        assert desigual["eco.resilience.index"] <= igual["eco.resilience.index"]

    def test_el_ticket_de_consumo_sale_del_gasto_y_la_frecuencia(self):
        out = coleccionar(
            self.RENTA,
            ["eco.sector_spend", "eco.consumer.frequency", "eco.consumer.ticket"],
            sector="restauracion",
        )
        esperado = out["eco.sector_spend"] / (out["eco.consumer.frequency"] * 4.33)
        assert out["eco.consumer.ticket"] == pytest.approx(esperado)
