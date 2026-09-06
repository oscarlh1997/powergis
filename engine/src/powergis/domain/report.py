"""Composición del informe.

Orquesta secciones + GeoLens + PlaceRank + resumen ejecutivo. Es puro dominio:
recibe el contexto con los hechos ya cargados y devuelve un `Report`. La
persistencia, el LLM y las llamadas a APIs quedan fuera.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from . import geolens as geolens_mod
from . import indicators as catalog_mod
from . import placerank as placerank_mod
from . import stats
from .enums import Dimension, Section, Tier
from .models import (
    Indicator,
    PlaceRankResult,
    Project,
    Report,
    SectionResult,
)
from .sections import REGISTRY, SectionContext


class ReportBuilder:
    """Construye el payload que consume el front."""

    def __init__(self, engine_version: str) -> None:
        self.engine_version = engine_version

    # ------------------------------------------------------------------ #

    def build(
        self,
        project: Project,
        ctx: SectionContext,
        *,
        version: int,
        tier: Tier | None = None,
        only: Sequence[Section] | None = None,
        previous: dict | None = None,
    ) -> Report:
        """Compone el informe.

        `previous` es el snapshot anterior: en un upgrade básico→avanzado se
        reutilizan las secciones ya calculadas en vez de rehacerlas.
        """
        tier = tier or project.tier
        wanted = list(only) if only else catalog_mod.sections_for_tier(tier)
        reusable = _reusable_sections(previous, wanted) if previous else {}

        sections: list[SectionResult] = []
        for section in catalog_mod.sections_for_tier(Tier.AVANZADO):
            builder = REGISTRY.get(section)
            if builder is None:
                continue

            if section not in wanted:
                # Sección bloqueada: viaja SIN datos dentro, pero SÍ con el
                # índice de lo que contiene. Sin esto el usuario del informe
                # básico ve una caja gris y no tiene motivo para pagar; con
                # esto ve exactamente qué compra. Son etiquetas del catálogo,
                # no valores calculados.
                sections.append(
                    SectionResult(
                        id=section,
                        title=builder.title,
                        available=False,
                        locked_reason="tier",
                        preview=builder.preview_labels(),
                    )
                )
                continue

            if section in reusable:
                sections.append(reusable[section])
                continue

            ctx.tier = tier
            sections.append(builder.build(ctx))

        placerank = self._placerank(ctx, tier)
        report = Report(
            project_uuid=project.project_uuid,
            tier=tier,
            version=version,
            engine_version=self.engine_version,
            generated_at=datetime.now(UTC),
            scope=self._scope_block(ctx),
            segments=project.segments.as_dict(),
            business=project.business.as_dict(),
            sections=sections,
            geolens=geolens_mod.build(ctx, tier=tier),
            placerank=placerank.as_dict() if placerank else None,
            glossary=self._glossary(ctx, wanted),
            sources=self._sources(sections),
            warnings=sorted(set(ctx.warnings)),
        )
        report.executive_summary = self._executive_summary(report, ctx, placerank)
        return report

    # ------------------------------------------------------------------ #

    def _placerank(self, ctx: SectionContext, tier: Tier) -> PlaceRankResult | None:
        if tier is not Tier.AVANZADO:
            return None
        profile = placerank_mod.get_profile(ctx.business.get("sector"))
        result = placerank_mod.compute(ctx, profile, target=ctx.target)
        return result if result.rows else None

    def _scope_block(self, ctx: SectionContext) -> dict:
        return {
            "level": str(ctx.scope.level),
            "code": ctx.scope.ine_code,
            "name": ctx.parent.name,
            "children_level": str(ctx.scope.resolve_children_level()),
            "children_count": len(ctx.children),
            "population": ctx.parent_value("dem.pop.total"),
            "area_km2": ctx.parent.area_km2,
        }

    def _glossary(self, ctx: SectionContext, wanted: Sequence[Section]) -> list[dict[str, str]]:
        wanted_set = set(wanted)
        out: list[dict[str, str]] = []
        for ind in ctx.catalog.values():
            if ind.section not in wanted_set:
                continue
            definition = ind.description or ind.formula or ""
            if not definition:
                continue
            out.append({
                "term": ind.label,
                "code": ind.code,
                "definition": definition,
                "unit": str(ind.unit),
                "source": ind.source,
            })
        return sorted(out, key=lambda d: d["term"])

    def _sources(self, sections: Sequence[SectionResult]) -> list[dict[str, str]]:
        seen: dict[str, dict[str, str]] = {}
        for section in sections:
            if not section.available:
                continue
            for src in section.sources:
                seen.setdefault(src, {"name": src, "attribution": _ATTRIBUTION.get(
                    src.split(":")[0], ""
                )})
        return sorted(seen.values(), key=lambda d: d["name"])

    # ------------------------------------------------------------------ #

    def _executive_summary(
        self,
        report: Report,
        ctx: SectionContext,
        placerank: PlaceRankResult | None,
    ) -> dict:
        """Resumen ejecutivo determinista.

        Los textos de IA se añaden después, en cola aparte: si el LLM falla, el
        informe ya está publicado con este resumen.
        """
        pop = ctx.parent_value("dem.pop.total")
        segment = ctx.parent_value("dem.pop.segment")
        share = stats.relative_share(segment, pop)

        headline = [
            {"label": "Población analizada", "value": pop, "unit": "personas"},
            {"label": "Público objetivo", "value": segment, "unit": "personas"},
            {"label": "Peso del público objetivo", "value": share, "unit": "%"},
            {"label": "Zonas comparadas", "value": len(ctx.children), "unit": "ud"},
        ]

        best: list[dict] = []
        worst: list[dict] = []
        if placerank:
            top, bottom = placerank_mod.podium(placerank, 3)
            best = [placerank_mod.explain(r, ctx.catalog) for r in top]
            worst = [placerank_mod.explain(r, ctx.catalog) for r in bottom]
        else:
            pairs = [(g.ine_code, ctx.value(g.geo_id, "dem.pop.segment")) for g in ctx.children]
            highlights = stats.top_bottom(pairs, n=3)
            names = {g.ine_code: g.name for g in ctx.children}
            best = [{"zona": names.get(c, c), "codigo": c} for c in highlights["top"]]
            worst = [{"zona": names.get(c, c), "codigo": c} for c in highlights["bottom"]]

        return {
            "headline": headline,
            "mejores_zonas": best,
            "peores_zonas": worst,
            "cobertura": {
                str(s.id): round(s.coverage, 3) for s in report.sections if s.available
            },
            "dimension_weights": (
                {str(k): v for k, v in placerank.weights.items()} if placerank else None
            ),
            "narrative": None,  # lo rellena la cola de IA
        }


_ATTRIBUTION: dict[str, str] = {
    "INE": "Fuente: Instituto Nacional de Estadística",
    "OSM": "© Colaboradores de OpenStreetMap (ODbL)",
    "AEMET": "© Agencia Estatal de Meteorología (AEMET)",
    "Catastro": "Fuente: Dirección General del Catastro",
    "derivado": "Elaboración propia a partir de fuentes oficiales",
    "estimación modelada": "Estimación propia: no es un dato observado",
}


def _reusable_sections(
    previous: dict | None,
    wanted: Sequence[Section],
) -> dict[Section, SectionResult]:
    """Secciones del snapshot anterior que se pueden reutilizar tal cual.

    Es el corazón del upgrade incremental: la demografía del informe básico no
    se recalcula al pagar, se reutiliza.
    """
    if not previous:
        return {}
    out: dict[Section, SectionResult] = {}
    for raw in previous.get("sections", []):
        if not raw.get("available"):
            continue
        try:
            section = Section(raw["id"])
        except ValueError:
            continue
        if section not in wanted:
            continue
        out[section] = _section_from_dict(raw, section)
    return out


def _section_from_dict(raw: dict, section: Section) -> SectionResult:
    from . import enums as _e
    from .models import Chart, Column, Kpi, Subsection, Table

    subs: list[Subsection] = []
    for s in raw.get("subsections", []):
        subs.append(
            Subsection(
                id=s["id"],
                title=s["title"],
                kpis=[
                    Kpi(
                        code=k["code"], label=k["label"], value=k["value"],
                        unit=_e.Unit(k["unit"]), direction=_e.Direction(k.get("direction", 0)),
                        delta_vs_parent=k.get("delta_vs_parent"),
                        percentile=k.get("percentile"), decimals=k.get("decimals", 2),
                        note=k.get("note"),
                    )
                    for k in s.get("kpis", [])
                ],
                charts=[
                    Chart(
                        id=c["id"], title=c["title"], type=c["type"], x=c["x"],
                        series=c["series"],
                        unit=_e.Unit(c["unit"]) if c.get("unit") else None,
                        stack=c.get("stack", False),
                    )
                    for c in s.get("charts", [])
                ],
                tables=[
                    Table(
                        id=t["id"], title=t["title"],
                        columns=[
                            Column(
                                key=col["key"], label=col["label"], type=col["type"],
                                decimals=col.get("decimals", 2),
                                direction=_e.Direction(col.get("direction", 0)),
                            )
                            for col in t["columns"]
                        ],
                        rows=t["rows"], highlights=t.get("highlights", {}),
                        footnote=t.get("footnote"),
                    )
                    for t in s.get("tables", [])
                ],
                narrative=s.get("narrative"),
            )
        )
    return SectionResult(
        id=section,
        title=raw["title"],
        available=True,
        subsections=subs,
        sources=raw.get("sources", []),
        coverage=raw.get("coverage", 1.0),
    )


def indicators_for(tier: Tier, sections: Sequence[Section]) -> list[Indicator]:
    """Indicadores a cargar para un informe: los del tier en esas secciones."""
    wanted = set(sections)
    return [i for i in catalog_mod.by_tier(tier) if i.section in wanted]


def dimension_weights_from(payload: dict | None) -> dict[Dimension, float] | None:
    """Convierte pesos que llegan del front a `Dimension` validados."""
    if not payload:
        return None
    out: dict[Dimension, float] = {}
    for key, value in payload.items():
        try:
            out[Dimension(key)] = max(float(value), 0.0)
        except (ValueError, TypeError):
            continue
    return out or None


def build_uuid_key(project_uuid: UUID, version: int) -> str:
    return f"report:{project_uuid}:{version}"
