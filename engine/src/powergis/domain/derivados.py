"""De qué datos sale cada indicador derivado.

Sirve para fechar el resultado con el periodo de SUS datos: la tasa de
dependencia calculada con los porcentajes del Atlas de 2023 es un dato de
2023, aunque la población del Padrón sea de 2025 y el cálculo se haga hoy.
Antes se fechaba con el día de la carga (el colector) o con el periodo más
reciente de cualquier dato (el cálculo diario), y el informe decía «2025» de
cosas que eran de 2023.
"""

from __future__ import annotations

ENTRADAS: dict[str, tuple[str, ...]] = {
    "dem.age.18_64_pct": ("dem.age.u18_pct", "dem.age.65p_pct",
                          "dem.age.0_15", "dem.age.16_64", "dem.age.65p"),
    "dem.dependency.total": ("dem.age.u18_pct", "dem.age.65p_pct",
                             "dem.age.0_15", "dem.age.16_64", "dem.age.65p"),
    "dem.ageing.index": ("dem.age.u18_pct", "dem.age.65p_pct",
                         "dem.age.0_15", "dem.age.65p"),
    "dem.femininity.index": ("dem.sex.women", "dem.sex.men"),
    "dem.sex.women_pct": ("dem.sex.women", "dem.pop.total"),
    "dem.pop.density": ("dem.pop.total",),
    "dem.pop.segment_pct": ("dem.pop.segment", "dem.pop.total"),
    "dem.edu.qualification_index": ("dem.edu.university_pct", "dem.edu.postgrad_pct"),
    "cmp.opportunity.index": ("dem.pop.segment", "dem.pop.total", "cmp.count"),
    "sat.demand_supply": ("dem.pop.segment", "dem.pop.total", "cmp.count"),
    "eco.nse.index": ("eco.income.household.median", "eco.gini", "eco.nse.risk_pct"),
    "eco.resilience.index": ("eco.income.household.median", "eco.gini", "eco.nse.risk_pct"),
}

