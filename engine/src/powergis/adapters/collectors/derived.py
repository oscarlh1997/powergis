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
from collections.abc import Sequence
from datetime import date

from ...domain import stats
from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector

log = logging.getLogger(__name__)

MODELLED_REF = "estimación modelada · elaboración propia"

# Coeficientes COICOP: fracción de la renta disponible que un hogar destina al
# sector. Semilla a partir de la Encuesta de Presupuestos Familiares del INE;
# se refinan con datos reales de conversión cuando los haya.
SECTOR_COICOP: dict[str, float] = {
    "restauracion": 0.093,
    "cafeteria": 0.041,
    "alimentacion": 0.142,
    "retail": 0.052,
    "salud": 0.035,
    "belleza": 0.021,
    "fitness": 0.018,
    "servicios": 0.048,
    "generico": 0.050,
}

# Frecuencia media de compra semanal por sector (visitas/hogar/semana).
SECTOR_FREQUENCY: dict[str, float] = {
    "restauracion": 1.6, "cafeteria": 3.2, "alimentacion": 3.8, "retail": 0.6,
    "salud": 0.3, "belleza": 0.4, "fitness": 2.1, "servicios": 0.5, "generico": 1.0,
}


class DerivedCollector(BaseCollector):
    name = "derived"
    PROVIDES = (
        "dem.dependency.total", "dem.ageing.index", "dem.femininity.index",
        "dem.sex.women_pct", "dem.pop.density", "dem.pop.segment_pct",
        "dem.edu.qualification_index", "dem.nat.diversity_index",
        "eco.nse.index", "eco.resilience.index", "eco.gross_monthly",
        "eco.disposable.monthly", "eco.gross_net_gap", "eco.saving.rate",
        "eco.financial_stress.index", "eco.sector_spend",
        "eco.consumer.ticket", "eco.consumer.frequency",
        "cmp.hhi", "cmp.opportunity.index",
        "sat.isc", "sat.demand_supply", "sat.opportunity.index",
    )

    def __init__(self, facts_lookup=None, sector: str = "generico") -> None:
        """`facts_lookup(geo_id, code) -> float | None` da acceso a lo ya cargado."""
        self._lookup = facts_lookup or (lambda geo_id, code: None)
        self.sector = sector if sector in SECTOR_COICOP else "generico"

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

        when = period or date.today()
        out: list[Fact] = []
        for geo in geos:
            out.extend(self._for_geo(geo, wanted, when))
        return out

    # ------------------------------------------------------------------ #

    def _for_geo(self, geo: Geo, wanted: set[str], when: date) -> list[Fact]:
        def v(code: str) -> float | None:
            return self._lookup(geo.geo_id, code)

        exact: dict[str, float | None] = {
            "dem.dependency.total": stats.dependency_ratio(
                v("dem.age.0_15"), v("dem.age.16_64"), v("dem.age.65p")
            ),
            "dem.ageing.index": stats.ageing_index(v("dem.age.65p"), v("dem.age.0_15")),
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
        }

        modelled: dict[str, float | None] = {}
        annual = v("eco.income.household.mean")
        if annual is not None:
            gross_monthly = annual / 12.0
            # Tipo efectivo IRPF + cotizaciones, progresivo por tramos.
            effective_rate = _effective_tax_rate(annual)
            disposable = gross_monthly * (1 - effective_rate)
            modelled["eco.gross_monthly"] = gross_monthly
            modelled["eco.disposable.monthly"] = disposable
            modelled["eco.gross_net_gap"] = gross_monthly - disposable
            modelled["eco.sector_spend"] = disposable * SECTOR_COICOP[self.sector]
            modelled["eco.saving.rate"] = max(0.0, (1 - _consumption_ratio(annual)) * 100.0)
            modelled["eco.financial_stress.index"] = min(
                _consumption_ratio(annual) * 100.0, 100.0
            )
            frequency = SECTOR_FREQUENCY[self.sector]
            modelled["eco.consumer.frequency"] = frequency
            spend = modelled["eco.sector_spend"]
            modelled["eco.consumer.ticket"] = (
                spend / (frequency * 4.33) if spend and frequency else None
            )

        gini = v("eco.gini")
        risk = v("eco.nse.risk_pct")
        median = v("eco.income.household.median")
        if median is not None:
            modelled["eco.nse.index"] = _nse_index(median, gini, risk)
            modelled["eco.resilience.index"] = _resilience(median, gini, risk)

        out: list[Fact] = []
        for code, value in exact.items():
            if code in wanted and value is not None:
                out.append(self.fact(geo, code, value, when, None, "derivado"))
        for code, value in modelled.items():
            if code in wanted and value is not None:
                out.append(self.fact(geo, code, value, when, None, MODELLED_REF))
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
    """Demanda potencial por competidor, amortiguada para evitar el infinito."""
    if demand is None:
        return None
    return demand / (1.0 + (competitors or 0.0))


def _nse_index(median_income: float, gini: float | None, risk_pct: float | None) -> float:
    """Índice NSE 0-100. Renta mediana como base, ajustada por desigualdad."""
    base = min(median_income / 45_000.0, 1.0) * 100.0
    if gini is not None:
        base *= 1.0 - min(max(gini, 0.0), 0.6) * 0.5
    if risk_pct is not None:
        base *= 1.0 - min(risk_pct / 100.0, 0.8) * 0.4
    return round(min(max(base, 0.0), 100.0), 2)


def _resilience(median_income: float, gini: float | None, risk_pct: float | None) -> float:
    """Capacidad de la zona de sostener consumo en una recesión."""
    income_score = min(median_income / 40_000.0, 1.5)
    equality = 1.0 - min(max(gini or 0.30, 0.0), 0.6)
    stability = 1.0 - min((risk_pct or 20.0) / 100.0, 0.8)
    return round(min(income_score * equality * stability * 100.0, 100.0), 2)


def competitive_hhi(shares: Sequence[float]) -> float | None:
    return stats.herfindahl(shares)
