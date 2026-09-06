"""Perfil socioeconómico (fase 4a).

Se alimenta del Atlas de Distribución de Renta de los Hogares del INE, que es
estadística experimental con ~2 años de desfase y con secreto estadístico en
municipios pequeños. Por eso cada subsección comprueba disponibilidad antes de
construirse y deja constancia en `ctx.warnings` cuando no hay dato.
"""

from __future__ import annotations

from ..enums import Section, Tier
from ..models import Subsection
from .base import (
    SectionBuilder,
    SectionContext,
    build_chart,
    build_table,
    kpi_from,
    register,
)

_SECRETO = (
    "Sin dato publicado por secreto estadístico. El INE no difunde el ADRH en "
    "unidades con poblaciones pequeñas; no se sustituye por cero."
)


@register
class Socioeconomico(SectionBuilder):
    section = Section.SOCIOECONOMICO
    title = "Perfil Socioeconómico"
    tier = Tier.AVANZADO

    def subsections(self, ctx: SectionContext) -> list[Subsection | None]:
        return [
            self._nse(ctx),
            self._renta(ctx),
            self._disponible(ctx),
            self._consumo(ctx),
        ]

    def _nse(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "eco.nse.index", "eco.nse.risk_pct", "eco.nse.upper_middle_pct",
            "eco.gini", "eco.resilience.index",
        ]
        table_codes = [
            "eco.class.high_pct", "eco.nse.upper_middle_pct", "eco.class.mid_pct",
            "eco.class.lower_mid_pct", "eco.class.low_pct", "eco.nse.index",
        ]
        if not ctx.has_any(codes + table_codes):
            ctx.warnings.append(f"Nivel socioeconómico: {_SECRETO}")
            return None

        return Subsection(
            id="socioeconomico.nse",
            title="Nivel socioeconómico (NSE)",
            kpis=[kpi_from(ctx, c) for c in codes],
            charts=[
                build_chart(
                    ctx, "eco.clases", "Distribución por clase social",
                    ["eco.class.high_pct", "eco.nse.upper_middle_pct", "eco.class.mid_pct",
                     "eco.class.lower_mid_pct", "eco.class.low_pct"],
                    chart_type="bar", stack=True,
                )
            ],
            tables=[
                build_table(
                    ctx, "eco.tabla_nse", "Estructura social por zona", table_codes,
                    highlight_by="eco.nse.index",
                    footnote=(
                        "Fuente: INE, Atlas de Distribución de Renta de los Hogares "
                        "(estadística experimental)."
                    ),
                )
            ],
        )

    def _renta(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "eco.income.household.mean", "eco.income.household.median",
            "eco.income.percapita", "eco.income.under15k_pct",
            "eco.income.over30k_pct", "eco.income.over60k_pct", "eco.income.yoy",
        ]
        if not ctx.has_any(codes):
            ctx.warnings.append(f"Renta por hogar: {_SECRETO}")
            return None

        return Subsection(
            id="socioeconomico.renta",
            title="Renta bruta anual por hogar",
            kpis=[
                kpi_from(ctx, "eco.income.household.mean"),
                kpi_from(ctx, "eco.income.household.median"),
                kpi_from(ctx, "eco.income.under15k_pct"),
                kpi_from(ctx, "eco.income.over60k_pct"),
            ],
            charts=[
                build_chart(ctx, "eco.renta", "Renta media por hogar",
                            ["eco.income.household.mean"], chart_type="bar"),
                build_chart(ctx, "eco.renta_distribucion", "Distribución de renta",
                            ["eco.income.under15k_pct", "eco.income.over30k_pct",
                             "eco.income.over60k_pct"], chart_type="bar"),
            ],
            tables=[
                build_table(ctx, "eco.tabla_renta", "Renta por zona", codes,
                            highlight_by="eco.income.household.median",
                            footnote="Renta bruta declarada. La mediana es más representativa "
                                     "que la media cuando hay concentración de renta alta.")
            ],
        )

    def _disponible(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "eco.gross_monthly", "eco.disposable.monthly", "eco.gross_net_gap",
            "eco.financial_stress.index", "eco.saving.rate", "eco.sector_spend",
        ]
        if not ctx.has_any(codes):
            return None

        return Subsection(
            id="socioeconomico.disponible",
            title="Renta mensual disponible",
            kpis=[
                kpi_from(ctx, "eco.disposable.monthly"),
                kpi_from(ctx, "eco.gross_net_gap"),
                kpi_from(ctx, "eco.financial_stress.index"),
                kpi_from(ctx, "eco.saving.rate"),
            ],
            charts=[
                build_chart(ctx, "eco.disponible", "Bruto frente a disponible",
                            ["eco.gross_monthly", "eco.disposable.monthly"], chart_type="bar")
            ],
            tables=[
                build_table(ctx, "eco.tabla_disponible", "Capacidad de gasto por zona", codes,
                            highlight_by="eco.sector_spend",
                            footnote="Gasto en el sector estimado con coeficientes COICOP de la "
                                     "Encuesta de Presupuestos Familiares. Es una estimación modelada.")
            ],
        )

    def _consumo(self, ctx: SectionContext) -> Subsection | None:
        codes = [
            "eco.consumer.ticket", "eco.consumer.frequency", "eco.consumer.online_pct",
            "eco.consumer.local_pref", "eco.consumer.loyalty",
        ]
        if not ctx.has_any(codes):
            return None

        return Subsection(
            id="socioeconomico.consumo",
            title="Comportamiento del consumidor",
            kpis=[kpi_from(ctx, c) for c in codes[:3]],
            charts=[
                build_chart(ctx, "eco.consumo", "Ticket medio estimado",
                            ["eco.consumer.ticket"], chart_type="bar")
            ],
            tables=[
                build_table(ctx, "eco.tabla_consumo", "Perfil de consumo por zona", codes,
                            highlight_by="eco.consumer.ticket",
                            footnote="Indicadores modelados a partir de renta disponible, "
                                     "estructura de edad y penetración TIC (INE).")
            ],
        )
