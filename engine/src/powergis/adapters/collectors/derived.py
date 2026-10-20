"""Colector de indicadores derivados y modelados.

Dos familias, y la diferencia importa mucho de cara al cliente:

* **Derivados** — aritmética exacta sobre datos oficiales (tasa de
  dependencia, índice de feminidad, densidad). Son tan fiables como su origen.
* **Modelados** — estimaciones (gasto en el sector, ticket medio, precio de
  alquiler). Se marcan como tales en `source_ref` y el informe lo dice en la
  nota al pie. Un informe de pago no puede presentar una estimación como una
  observación.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import date

from ...domain import stats
from ...domain.consumo import (
    MODELADO,
    SECTOR_COICOP,
    SECTOR_FREQUENCY,
    consumo_del_sector,
    sector_normalizado,
)
from ...domain.derivados import ENTRADAS
from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector

log = logging.getLogger(__name__)

MODELLED_REF = MODELADO

__all__ = ["MODELLED_REF", "SECTOR_COICOP", "SECTOR_FREQUENCY", "DerivedCollector"]

#: `(geo_ids, códigos) -> hechos`. Lo que el colector necesita del almacén.
CargadorDeHechos = Callable[[list[int], list[str]], list[Fact]]

_RENTA = ("eco.income.household.mean", "eco.income.household.net")


class DerivedCollector(BaseCollector):
    name = "derived"
    PROVIDES = (
        "dem.dependency.total", "dem.ageing.index", "dem.femininity.index",
        "dem.age.18_64_pct",
        "dem.sex.women_pct", "dem.pop.density", "dem.pop.segment_pct",
        "dem.edu.qualification_index",
        "eco.resilience.index", "eco.gross_monthly",
        "eco.disposable.monthly", "eco.gross_net_gap", "eco.saving.rate",
        "eco.financial_stress.index", "eco.sector_spend",
        "eco.consumer.ticket", "eco.consumer.frequency",
        "cmp.hhi", "cmp.opportunity.index",
        "sat.isc", "sat.demand_supply", "sat.opportunity.index",
        "eco.poverty.risk_pct", "tur.hotel.foreign_pct",
        "inm.affordability.years", "inm.rent.effort_pct",
    )

    def __init__(
        self,
        facts_lookup=None,
        sector: str = "generico",
        facts_loader: CargadorDeHechos | None = None,
    ) -> None:
        """Dos formas de darle acceso a lo ya cargado:

        * `facts_loader(geo_ids, códigos) -> hechos`: la de producción. Lee
          del almacén por lotes y conserva el periodo de cada dato.
        * `facts_lookup(geo_id, código) -> valor`: la de los tests.

        Sin ninguna de las dos el colector no ve nada y no escribe nada. Eso
        es lo que pasaba: el registro lo creaba sin acceso al almacén, así que
        `ingest derived` terminaba «bien» con cero hechos y la renta
        disponible, la resistencia económica y el gasto en el sector no existían en ningún
        informe.
        """
        self._lookup = facts_lookup
        self._loader = facts_loader
        self.sector = sector_normalizado(sector)

    def collect(
        self,
        indicators: Sequence[str],
        geos: Sequence[Geo],
        segments: Segments,
        period: date | None = None,
    ) -> list[Fact]:
        wanted = set(indicators) & set(self.PROVIDES)
        if not wanted or not geos:
            return []

        indice = self._precargar(geos)
        out: list[Fact] = []
        for geo in geos:
            out.extend(self._for_geo(geo, wanted, period, indice))
        return out

    def _precargar(self, geos: Sequence[Geo]) -> dict[tuple[int, str], Fact] | None:
        if self._loader is None:
            return None
        codigos = sorted({c for entradas in ENTRADAS.values() for c in entradas} | set(_RENTA))
        hechos = self._loader([g.geo_id for g in geos], codigos)
        return {(h.geo_id, h.indicator): h for h in hechos if not h.segment}

    # ------------------------------------------------------------------ #

    def _for_geo(
        self,
        geo: Geo,
        wanted: set[str],
        period: date | None,
        indice: dict[tuple[int, str], Fact] | None,
    ) -> list[Fact]:
        def v(code: str) -> float | None:
            if indice is not None:
                hecho = indice.get((geo.geo_id, code))
                return hecho.value if hecho else None
            return self._lookup(geo.geo_id, code) if self._lookup else None

        def oficial(code: str) -> float | None:
            """El valor sólo si NO lo calculó este mismo colector antes."""
            if indice is not None:
                hecho = indice.get((geo.geo_id, code))
                if hecho is None or hecho.source_ref == MODELLED_REF:
                    return None
                return hecho.value
            return v(code)

        def fecha(codes: Sequence[str]) -> date:
            """El periodo más reciente de los datos de los que sale."""
            if period is not None:
                return period
            if indice is not None:
                fechas = [
                    h.period for c in codes
                    if (h := indice.get((geo.geo_id, c))) is not None and h.value is not None
                ]
                if fechas:
                    return max(fechas)
            return date.today()

        dependencia, envejecimiento, activo = stats.razones_de_edad(v)

        exact: dict[str, float | None] = {
            "dem.age.18_64_pct": activo,
            "dem.dependency.total": dependencia,
            "dem.ageing.index": envejecimiento,
            "dem.femininity.index": stats.femininity_index(
                v("dem.sex.women"), v("dem.sex.men")
            ),
            "dem.sex.women_pct": stats.relative_share(v("dem.sex.women"), v("dem.pop.total")),
            "dem.pop.density": stats.density(v("dem.pop.total"), geo.area_km2),
            "dem.pop.segment_pct": stats.relative_share(
                v("dem.pop.segment"), v("dem.pop.total")
            ),
            "dem.edu.qualification_index": _qualification(
                v("dem.edu.university_pct"), v("dem.edu.postgrad_pct")
            ),
            "cmp.opportunity.index": _opportunity(
                v("dem.pop.segment") or v("dem.pop.total"), v("cmp.count")
            ),
            "sat.demand_supply": stats.safe_div(
                v("dem.pop.segment") or v("dem.pop.total"), v("cmp.count")
            ),
            "tur.hotel.foreign_pct": _foreign_share(
                v("tur.hotel.travellers.foreign"), v("tur.hotel.travellers.resident"),
                v("tur.hotel.travellers"),
            ),
        }

        modelled: dict[str, float | None] = {}
        annual = v("eco.income.household.mean")
        net_annual = v("eco.income.household.net")
        if annual is not None:
            gross_monthly = annual / 12.0
            exact["eco.gross_monthly"] = gross_monthly

            # La renta disponible se OBSERVA cuando se puede y sólo se modela
            # cuando no. El Atlas publica la renta neta media por hogar —bruta
            # menos IRPF y cotizaciones, medida—, así que no hace falta
            # estimarla con un tipo efectivo supuesto.
            #
            # Y había un error detrás: `eco.income.household.mean` recibía la
            # renta NETA, y este bloque la trataba como bruta y le restaba
            # impuestos otra vez. La disponible salía entre un 15 y un 25 %
            # por debajo de la real, y con ella el gasto en el sector, el
            # ticket y la tasa de ahorro.
            if net_annual is not None:
                disposable = net_annual / 12.0
                exact["eco.disposable.monthly"] = disposable
                exact["eco.gross_net_gap"] = gross_monthly - disposable
            else:
                # Tipo efectivo IRPF + cotizaciones, progresivo por tramos.
                disposable = gross_monthly * (1 - _effective_tax_rate(annual))
                modelled["eco.disposable.monthly"] = disposable
                modelled["eco.gross_net_gap"] = gross_monthly - disposable
            modelled["eco.saving.rate"] = max(0.0, (1 - _consumption_ratio(annual)) * 100.0)
            modelled["eco.financial_stress.index"] = min(
                _consumption_ratio(annual) * 100.0, 100.0
            )
            # Valor de referencia con el sector del colector. El informe lo
            # recalcula con el sector del proyecto: ver `domain.consumo`.
            modelled.update(consumo_del_sector(disposable, self.sector))

        gini = v("eco.gini")
        median = v("eco.income.household.median")
        risk = oficial("eco.poverty.risk_pct")
        if risk is None and median is not None:
            # Sin dato publicado, se estima (decisión de Aldo del 20/10/2026:
            # se enseña con la etiqueta «Estimado»).
            risk = poverty_risk_estimate(median, gini)
            modelled["eco.poverty.risk_pct"] = risk
        precio, alquiler = v("inm.price.m2"), v("inm.rent.m2")
        if precio is not None:
            modelled["inm.affordability.years"] = stats.safe_div(precio * VIVIENDA_M2, annual)
        if alquiler is not None:
            modelled["inm.rent.effort_pct"] = stats.safe_div(
                alquiler * ALQUILER_M2 * 12, annual, 100.0)
        if median is not None:
            modelled["eco.resilience.index"] = _resilience(median, gini, risk)

        out: list[Fact] = []
        for code, value in exact.items():
            if code in wanted and value is not None:
                cuando = fecha(ENTRADAS.get(code, _RENTA))
                out.append(self.fact(geo, code, value, cuando, None, "derivado"))
        for code, value in modelled.items():
            if code in wanted and value is not None:
                cuando = fecha(ENTRADAS.get(code, _RENTA))
                out.append(self.fact(geo, code, value, cuando, None, MODELLED_REF))
        return out


# --------------------------------------------------------------------------- #
# Modelos auxiliares. Cada uno con su supuesto explícito.
# --------------------------------------------------------------------------- #


def _effective_tax_rate(annual_income: float) -> float:
    """Tipo efectivo aproximado (IRPF + cotizaciones) sobre renta bruta del hogar."""
    brackets = [(12_450, 0.14), (20_200, 0.20), (35_200, 0.26),
                (60_000, 0.31), (300_000, 0.36), (float("inf"), 0.42)]
    for limit, rate in brackets:
        if annual_income <= limit:
            return rate
    return 0.42


def _consumption_ratio(annual_income: float) -> float:
    """Propensión al consumo: decrece con la renta (ley de Engel)."""
    if annual_income <= 15_000:
        return 0.98
    if annual_income <= 30_000:
        return 0.90
    if annual_income <= 60_000:
        return 0.80
    return 0.70


def _qualification(university_pct: float | None, postgrad_pct: float | None) -> float | None:
    if university_pct is None and postgrad_pct is None:
        return None
    return (university_pct or 0.0) + 1.5 * (postgrad_pct or 0.0)


def _opportunity(demand: float | None, competitors: float | None) -> float | None:
    """Demanda potencial por competidor, amortiguada para evitar el infinito.

    Sin el recuento de competidores NO hay índice. Antes un hueco contaba
    como cero competidores y el «índice de oportunidad» salía igual a la
    población: un número grande y creíble que no medía nada.
    """
    if demand is None or competitors is None:
        return None
    return demand / (1.0 + competitors)


TECHO_MEDIANA_RESILIENCIA = 25_000.0


def _resilience(median_income: float, gini: float | None, risk_pct: float | None) -> float:
    """Capacidad de la zona de sostener consumo en una recesión."""
    income_score = min(median_income / TECHO_MEDIANA_RESILIENCIA, 1.5)
    equality = 1.0 - min(max(gini or 0.30, 0.0), 0.6)
    stability = 1.0 - min((risk_pct or 20.0) / 100.0, 0.8)
    return round(min(income_score * equality * stability * 100.0, 100.0), 2)


#: Superficies de referencia de los indicadores de accesibilidad a la vivienda.
VIVIENDA_M2 = 90
ALQUILER_M2 = 80

#: Umbral de riesgo de pobreza: 60 % de la mediana nacional de la renta por
#: unidad de consumo. INE, ADRH 2023: mediana España 19.250 € → 11.550 €.
UMBRAL_POBREZA = 0.6 * 19_250.0
#: Dispersión del logaritmo de la renta sin Gini de la zona: la que reproduce
#: la tasa nacional de riesgo de pobreza (INE, ECV 2024: 19,7 %) con la
#: mediana nacional. Φ(ln 0,6 / σ) = 0,197 → σ ≈ 0,60.
SIGMA_NACIONAL = 0.5995


def poverty_risk_estimate(median_uc: float, gini: float | None = None) -> float | None:
    """% de población bajo el umbral de riesgo de pobreza, modelo log-normal.

    Con renta log-normal, Gini = 2Φ(σ/√2) − 1, así que σ = √2·Φ⁻¹((G+1)/2).
    La tasa es Φ((ln umbral − ln mediana) / σ). Es una ESTIMACIÓN: el informe
    la etiqueta como tal.
    """
    from math import log, sqrt
    from statistics import NormalDist

    if median_uc is None or median_uc <= 0:
        return None
    normal = NormalDist()
    sigma = SIGMA_NACIONAL
    if gini is not None and 0.05 < gini < 0.8:
        sigma = sqrt(2) * normal.inv_cdf((gini + 1) / 2)
    return round(normal.cdf((log(UMBRAL_POBREZA) - log(median_uc)) / sigma) * 100.0, 1)


def _foreign_share(foreign: float | None, resident: float | None,
                   total: float | None) -> float | None:
    """% de viajeros internacionales con el total publicado o la suma."""
    if foreign is None:
        return None
    base = total if total else (foreign + resident if resident is not None else None)
    return stats.safe_div(foreign, base, 100.0)


def competitive_hhi(shares: Sequence[float]) -> float | None:
    return stats.herfindahl(shares)

