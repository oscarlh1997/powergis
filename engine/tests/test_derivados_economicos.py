"""Derivados económicos: que se escriban, con qué fecha y con qué sector.

Tres fallos silenciosos que nunca dieron un error:

1. El registro creaba el colector de derivados SIN acceso al almacén, así que
   `ingest derived` acababa «bien» con cero hechos. Renta disponible, NSE,
   gasto en el sector y ticket no existían en ningún informe.
2. Los derivados se fechaban con el día de la carga: la renta de 2023 salía
   como dato de hoy, y cada ejecución añadía una fila nueva.
3. Gasto y ticket se calculaban con el sector «genérico» para todos, y el
   criterio de ticket del Match comparaba euros por compra con euros al mes.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from powergis.adapters.collectors.derived import DerivedCollector
from powergis.domain import consumo
from powergis.domain.enums import GeoLevel, Tier
from powergis.domain.models import BusinessProfile, Fact, Geo, Project, Scope, Segments

RENTA_2023 = date(2023, 1, 1)
PADRON_2025 = date(2025, 1, 1)


def _geo(geo_id: int = 10) -> Geo:
    return Geo(geo_id, GeoLevel.MUNICIPIO, "02003", "Albacete", None, 170_000, 1_125.0)


def _hecho(code: str, value: float, period: date, geo_id: int = 10) -> Fact:
    return Fact(geo_id=geo_id, indicator=code, period=period, value=value,
                segment={}, source_ref="INE")


ALMACEN = [
    _hecho("eco.income.household.mean", 36_000.0, RENTA_2023),
    _hecho("eco.income.household.net", 30_000.0, RENTA_2023),
    _hecho("eco.income.household.median", 18_000.0, RENTA_2023),
    _hecho("dem.pop.total", 170_000.0, PADRON_2025),
    _hecho("dem.sex.women", 87_000.0, PADRON_2025),
    _hecho("dem.sex.men", 83_000.0, PADRON_2025),
]


def _cargador(hechos: list[Fact]):
    llamadas: list[tuple[list[int], list[str]]] = []

    def cargar(geo_ids: list[int], codigos: list[str]) -> list[Fact]:
        llamadas.append((geo_ids, codigos))
        return [h for h in hechos if h.geo_id in geo_ids and h.indicator in codigos]

    return cargar, llamadas


class TestElColectorVeElAlmacen:
    def test_el_registro_le_da_acceso_al_almacen(self):
        """Con sesión, el colector de derivados tiene que poder leer."""
        from powergis.adapters.collectors.registry import build_registry

        registry = build_registry(session=object())  # type: ignore[arg-type]
        assert registry["derived"]._loader is not None

    def test_con_el_almacen_escribe_los_economicos(self):
        cargar, llamadas = _cargador(ALMACEN)
        c = DerivedCollector(facts_loader=cargar)
        hechos = c.collect(
            ["eco.disposable.monthly", "eco.gross_monthly", "eco.nse.index"],
            [_geo()], Segments(),
        )
        por_codigo = {h.indicator: h for h in hechos}
        assert por_codigo["eco.disposable.monthly"].value == pytest.approx(2_500.0)
        assert por_codigo["eco.gross_monthly"].value == pytest.approx(3_000.0)
        assert "eco.nse.index" in por_codigo
        assert len(llamadas) == 1, "una lectura por lote, no una por municipio"

    def test_sin_acceso_no_inventa_nada(self):
        c = DerivedCollector()
        assert c.collect(["eco.disposable.monthly"], [_geo()], Segments()) == []


class TestFechaDeLosDerivados:
    def test_la_renta_de_2023_sigue_siendo_de_2023(self):
        cargar, _ = _cargador(ALMACEN)
        hechos = DerivedCollector(facts_loader=cargar).collect(
            ["eco.disposable.monthly", "eco.sector_spend"], [_geo()], Segments()
        )
        assert hechos
        assert {h.period for h in hechos} == {RENTA_2023}

    def test_cada_derivado_con_la_fecha_de_sus_datos(self):
        cargar, _ = _cargador(ALMACEN)
        hechos = DerivedCollector(facts_loader=cargar).collect(
            ["dem.femininity.index", "eco.disposable.monthly"], [_geo()], Segments()
        )
        fechas = {h.indicator: h.period for h in hechos}
        assert fechas["dem.femininity.index"] == PADRON_2025
        assert fechas["eco.disposable.monthly"] == RENTA_2023

    def test_un_periodo_explicito_manda(self):
        cargar, _ = _cargador(ALMACEN)
        fijo = date(2020, 1, 1)
        hechos = DerivedCollector(facts_loader=cargar).collect(
            ["eco.disposable.monthly"], [_geo()], Segments(), fijo
        )
        assert hechos[0].period == fijo


class TestSectorDelProyecto:
    def test_el_informe_recalcula_con_su_sector(self):
        almacen = [
            _hecho("eco.disposable.monthly", 2_500.0, RENTA_2023),
            # Lo que dejó la carga, con el sector genérico:
            _hecho("eco.sector_spend", 125.0, RENTA_2023),
            _hecho("eco.consumer.ticket", 28.9, RENTA_2023),
        ]
        out = {f.indicator: f for f in consumo.con_el_sector_del_proyecto(almacen, "restauracion")}

        assert out["eco.sector_spend"].value == pytest.approx(2_500.0 * 0.093)
        assert out["eco.consumer.frequency"].value == pytest.approx(1.6)
        assert out["eco.consumer.ticket"].value == pytest.approx(2_500.0 * 0.093 / (1.6 * 4.33))
        assert out["eco.sector_spend"].period == RENTA_2023
        assert out["eco.sector_spend"].source_ref == consumo.MODELADO

    def test_sin_renta_disponible_no_queda_el_generico(self):
        """Un gasto calculado con otro sector es peor que un hueco."""
        almacen = [_hecho("eco.sector_spend", 125.0, RENTA_2023)]
        assert consumo.con_el_sector_del_proyecto(almacen, "restauracion") == []

    def test_sector_desconocido_es_generico(self):
        assert consumo.sector_normalizado("Restauracion ") == "restauracion"
        assert consumo.sector_normalizado("peluqueria-canina") == "generico"
        assert consumo.sector_normalizado(None) == "generico"

    def test_el_contexto_del_informe_usa_el_sector_del_proyecto(self, geos, facts):
        from conftest import FakeUnitOfWork
        from powergis.application.context import build_context

        extra = [
            Fact(geo_id=g, indicator="eco.disposable.monthly", period=RENTA_2023,
                 value=v, segment={}, source_ref="derivado")
            for g, v in ((3, 3_200.0), (4, 2_300.0), (5, 2_500.0))
        ]
        uow = FakeUnitOfWork(geos, facts + extra)
        proyecto = Project(
            project_uuid=uuid4(), wp_user_id=1, wp_post_id=1,
            scope=Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA),
            segments=Segments(),
            business=BusinessProfile(sector="restauracion"),
            tier=Tier.AVANZADO,
        )
        ctx = build_context(uow, proyecto, tier=Tier.AVANZADO)
        if "eco.sector_spend" not in ctx.catalog:
            pytest.skip("el gasto en el sector no está en este nivel")
        assert ctx.value(3, "eco.sector_spend") == pytest.approx(3_200.0 * 0.093)


class TestCriterioDeTicket:
    def test_compara_ticket_con_ticket(self):
        from powergis.domain.target import TargetProfile

        perfil = TargetProfile.from_mapping({"average_ticket": "bajo"})
        criterio = next(c for c in perfil.criteria() if c.label == "Ticket medio en tu sector")
        assert criterio.indicator == "eco.consumer.ticket"

    def test_un_restaurante_barato_puntua_en_una_zona_normal(self):
        """Antes daba 0: 10–50 € por compra contra ~230 € al mes."""
        from powergis.domain.target import TargetProfile

        perfil = TargetProfile.from_mapping({"average_ticket": "bajo"})
        criterio = next(c for c in perfil.criteria() if c.indicator == "eco.consumer.ticket")
        ticket = consumo.consumo_del_sector(2_500.0, "restauracion")["eco.consumer.ticket"]
        assert criterio.score(ticket, [ticket]) == 100.0


class TestOportunidadSinCompetencia:
    def test_sin_recuento_de_competidores_no_hay_indice(self):
        cargar, _ = _cargador(ALMACEN)
        hechos = DerivedCollector(facts_loader=cargar).collect(
            ["cmp.opportunity.index"], [_geo()], Segments()
        )
        assert hechos == []

    def test_cero_competidores_si_es_un_dato(self):
        cargar, _ = _cargador([*ALMACEN, _hecho("cmp.count", 0.0, PADRON_2025)])
        hechos = DerivedCollector(facts_loader=cargar).collect(
            ["cmp.opportunity.index"], [_geo()], Segments()
        )
        assert [h.value for h in hechos] == [170_000.0]
