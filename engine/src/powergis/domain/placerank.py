"""PlaceRank — ranking ponderado de zonas (fase 6).

Tres reglas que separan un ranking serio de uno decorativo, y las tres están
implementadas aquí, no documentadas en un README:

1. **Los pesos son datos, no código.** `SectorProfile` se carga de la tabla
   `sector_profile`; cambiar el modelo de una farmacia no requiere despliegue,
   y el usuario puede mover los pesos en la UI y ver el ranking recalcularse.
2. **Se normaliza DENTRO del ámbito consultado.** Si comparas provincias de
   Galicia, el 100 es la mejor de Galicia. Normalizar contra toda España deja
   todos los informes regionales en gris.
3. **Se guarda la contribución de cada indicador.** Sin eso no puedes explicar
   el resultado ni la IA puede escribir por qué una zona es buena.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from . import stats
from .enums import (
    DEFAULT_DIMENSION_WEIGHTS,
    Dimension,
    Direction,
    ScoreCategory,
)
from .models import Geo, Indicator, PlaceRankResult, PlaceRankRow
from .sections.base import SectionContext
from .target import TargetProfile, match_scores


@dataclass(slots=True)
class SectorProfile:
    """Perfil de ponderación de un sector de negocio.

    `indicator_weights` es un peso relativo DENTRO de su dimensión. Si un
    indicador no aparece, entra con peso 1 siempre que tenga dimensión.
    """

    sector: str
    dimension_weights: dict[Dimension, float] = field(
        default_factory=lambda: dict(DEFAULT_DIMENSION_WEIGHTS)
    )
    indicator_weights: dict[str, float] = field(default_factory=dict)
    excluded: frozenset[str] = frozenset()

    def normalized_dimensions(self) -> dict[Dimension, float]:
        total = sum(self.dimension_weights.values())
        if total <= 0:
            return dict(DEFAULT_DIMENSION_WEIGHTS)
        return {d: w / total for d, w in self.dimension_weights.items()}

    def weight_of(self, code: str) -> float:
        return float(self.indicator_weights.get(code, 1.0))

    @classmethod
    def default(cls, sector: str | None = None) -> SectorProfile:
        return cls(sector=sector or "generico")


# Perfiles de arranque. En producción viven en la tabla `sector_profile`;
# esto es la semilla que se carga con `powergis seed`.
BUILTIN_PROFILES: dict[str, SectorProfile] = {
    "generico": SectorProfile("generico"),
    "restauracion": SectorProfile(
        "restauracion",
        dimension_weights={
            Dimension.ECONOMICO: 0.35,
            Dimension.DEMOGRAFICO: 0.25,
            Dimension.AMBIENTAL: 0.10,
            Dimension.MATCH: 0.30,
        },
        indicator_weights={
            "eco.sector_spend": 2.0,
            "eco.disposable.monthly": 1.5,
            "dem.pop.segment": 2.0,
            "tra.pedestrian.index": 2.0,
            "anc.attraction.index": 1.5,
            "cmp.density_km2": 1.5,
            "sat.isc": 1.5,
        },
    ),
    "retail": SectorProfile(
        "retail",
        dimension_weights={
            Dimension.ECONOMICO: 0.40,
            Dimension.DEMOGRAFICO: 0.25,
            Dimension.AMBIENTAL: 0.10,
            Dimension.MATCH: 0.25,
        },
        indicator_weights={
            "eco.income.household.median": 2.0,
            "eco.consumer.ticket": 1.5,
            "tra.pedestrian.index": 1.5,
            "cmp.opportunity.index": 1.5,
            "sat.occupancy": 1.2,
        },
    ),
    "salud": SectorProfile(
        "salud",
        dimension_weights={
            Dimension.ECONOMICO: 0.25,
            Dimension.DEMOGRAFICO: 0.45,
            Dimension.AMBIENTAL: 0.10,
            Dimension.MATCH: 0.20,
        },
        indicator_weights={
            "dem.age.65p": 2.0,
            "dem.ageing.index": 1.8,
            "dem.pop.total": 1.5,
            "cmp.per_1000hab": 1.5,
        },
    ),
    "servicios": SectorProfile(
        "servicios",
        dimension_weights={
            Dimension.ECONOMICO: 0.35,
            Dimension.DEMOGRAFICO: 0.30,
            Dimension.AMBIENTAL: 0.15,
            Dimension.MATCH: 0.20,
        },
    ),
}


def get_profile(sector: str | None) -> SectorProfile:
    if not sector:
        return BUILTIN_PROFILES["generico"]
    return BUILTIN_PROFILES.get(sector.lower(), SectorProfile.default(sector))


# --------------------------------------------------------------------------- #
# Motor de scoring
# --------------------------------------------------------------------------- #


def _usable_indicators(
    ctx: SectionContext,
    profile: SectorProfile,
    min_coverage: float = 0.5,
) -> list[Indicator]:
    """Indicadores que aportan al score: tienen dimensión, dirección y datos.

    Un indicador con menos de `min_coverage` de zonas informadas se descarta:
    puntuar con dos valores de veinte zonas es ruido, no señal.
    """
    out: list[Indicator] = []
    n = max(len(ctx.children), 1)
    for ind in ctx.catalog.values():
        if ind.dimension is None or ind.direction is Direction.NEUTRAL:
            continue
        if ind.code in profile.excluded:
            continue
        values = ctx.values(ind.code)
        filled = sum(1 for v in values if v is not None)
        if filled / n < min_coverage:
            continue
        out.append(ind)
    return out


def compute(
    ctx: SectionContext,
    profile: SectorProfile | None = None,
    *,
    target: TargetProfile | None = None,
    min_coverage: float = 0.5,
    normalizer=stats.normalize_percentile,
) -> PlaceRankResult:
    """Calcula el PlaceRank de todas las zonas hijas del ámbito.

    `target` es el perfil de cliente que el usuario declaró en el formulario.
    Cuando viene, la dimensión MATCH deja de ser una aproximación con
    indicadores genéricos y pasa a ser lo que la tabla del informe promete:
    qué parte del perfil pedido cumple cada zona.
    """
    profile = profile or get_profile(ctx.business.get("sector"))
    match_by_geo = match_scores(ctx, target) if target and not target.is_empty() else {}
    dim_weights = profile.normalized_dimensions()
    indicators = _usable_indicators(ctx, profile, min_coverage)

    if not ctx.children or not indicators:
        return PlaceRankResult(weights=dim_weights, rows=[])

    # 1-3. Normalizar cada indicador dentro del ámbito, aplicando su dirección.
    normalized: dict[str, list[float | None]] = {}
    for ind in indicators:
        normalized[ind.code] = normalizer(ctx.values(ind.code), ind.direction)

    # 4. Agregar por dimensión (media ponderada de los indicadores de esa dimensión).
    rows: list[PlaceRankRow] = []
    for idx, geo in enumerate(ctx.children):
        dim_scores: dict[Dimension, float] = {}
        contributions: dict[str, float] = {}

        for dimension in Dimension:
            if dimension is Dimension.MATCH and match_by_geo:
                declared = match_by_geo.get(geo.geo_id)
                if declared is not None:
                    dim_scores[dimension] = declared
                    contributions["perfil.match"] = (
                        declared / 100.0 * dim_weights.get(dimension, 0.0)
                    )
                    continue

            members = [i for i in indicators if i.dimension is dimension]
            values = [normalized[i.code][idx] for i in members]
            weights = [profile.weight_of(i.code) for i in members]
            score = stats.weighted_mean(values, [
                w if v is not None else None for v, w in zip(values, weights, strict=False)
            ])
            if score is None:
                # Dimensión sin dato: se puntúa 50 (neutro) y se avisa.
                score = 50.0
            dim_scores[dimension] = score

            wsum = sum(
                w for v, w in zip(values, weights, strict=False) if v is not None
            ) or 1.0
            for ind, v, w in zip(members, values, weights, strict=False):
                if v is None:
                    continue
                contributions[ind.code] = (
                    (v * w / wsum) * dim_weights.get(dimension, 0.0)
                )

        # 5. Score final = Σ dimensión × peso.
        score = sum(dim_scores[d] * dim_weights.get(d, 0.0) for d in Dimension)
        score = min(max(score, 0.0), 100.0)

        rows.append(
            PlaceRankRow(
                geo_code=geo.ine_code,
                geo_name=geo.name,
                score=score,
                category=ScoreCategory.from_score(score),
                dimensions=dim_scores,
                contributions=contributions,
            )
        )

    rows.sort(key=lambda r: r.score, reverse=True)
    for position, row in enumerate(rows, start=1):
        row.rank = position

    return PlaceRankResult(weights=dim_weights, rows=rows)


def explain(row: PlaceRankRow, catalog: dict[str, Indicator], top_n: int = 5) -> dict:
    """Hechos compactos de una zona, listos para la IA.

    La IA no ve el dataset: ve esto. Menos tokens, menos alucinación y
    verificación de cifras trivial.
    """
    ordered = sorted(row.contributions.items(), key=lambda kv: abs(kv[1]), reverse=True)
    drivers = []
    for code, contribution in ordered[:top_n]:
        ind = catalog.get(code)
        drivers.append({
            "code": code,
            "label": ind.label if ind else code,
            "unit": str(ind.unit) if ind else "",
            "contribution": round(contribution, 4),
            "direction": int(ind.direction) if ind else 0,
        })
    return {
        "zona": row.geo_name,
        "codigo": row.geo_code,
        "posicion": row.rank,
        "score": round(row.score, 2),
        "categoria": str(row.category),
        "dimensiones": {str(k): round(v, 1) for k, v in row.dimensions.items()},
        "factores": drivers,
    }


def rebalance(result: PlaceRankResult, weights: dict[Dimension, float]) -> PlaceRankResult:
    """Recalcula el ranking con pesos nuevos sin volver a tocar la base de datos.

    Es lo que permite el ajuste de pesos en vivo desde la UI: el front manda
    los pesos, el backend reusa las dimensiones ya calculadas.
    """
    total = sum(weights.values()) or 1.0
    norm = {d: w / total for d, w in weights.items()}
    rows: list[PlaceRankRow] = []
    for row in result.rows:
        score = sum(row.dimensions.get(d, 50.0) * norm.get(d, 0.0) for d in Dimension)
        score = min(max(score, 0.0), 100.0)
        rows.append(
            PlaceRankRow(
                geo_code=row.geo_code,
                geo_name=row.geo_name,
                score=score,
                category=ScoreCategory.from_score(score),
                dimensions=row.dimensions,
                contributions=row.contributions,
                narrative=row.narrative,
            )
        )
    rows.sort(key=lambda r: r.score, reverse=True)
    for position, row in enumerate(rows, start=1):
        row.rank = position
    return PlaceRankResult(weights=norm, rows=rows, method=result.method)


def podium(result: PlaceRankResult, n: int = 3) -> tuple[list[PlaceRankRow], list[PlaceRankRow]]:
    """Las n mejores y las n peores zonas."""
    if not result.rows:
        return [], []
    n = min(n, len(result.rows) // 2 or 1)
    return result.rows[:n], list(reversed(result.rows[-n:]))


def geos_by_code(geos: Sequence[Geo]) -> dict[str, Geo]:
    return {g.ine_code: g for g in geos}
