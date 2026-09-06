"""GeoLens — capas del mapa interactivo (fase 5).

Una capa es dato, no código:

    capa = { indicador, nivel geográfico, método de rupturas, paleta, opacidad }

Añadir una capa nueva es añadir una fila al catálogo de indicadores. Esta
función solo traduce del almacén al formato que espera MapLibre.

Los VALORES viajan aquí, en el payload del informe. Las GEOMETRÍAS viajan en
las teselas PMTiles, que solo llevan `geo_code`. El front une ambos con
`setFeatureState`: una misma tesela sirve para todas las capas y todos los
usuarios, y el caché del CDN es perfecto.
"""

from __future__ import annotations

from collections.abc import Sequence

from . import stats
from .enums import BreakMethod, Direction, GeoLevel, Section, Tier
from .models import GeoLensLayer, Indicator
from .sections.base import SectionContext

# Paletas declaradas por dirección del indicador. El front las resuelve;
# aquí solo se nombra para que la leyenda y el color sean coherentes.
PALETTES: dict[str, str] = {
    "higher_is_better": "sequential-positive",
    "lower_is_better": "sequential-negative",
    "neutral": "sequential-neutral",
}

# Capas que se muestran encendidas al abrir el mapa, en orden.
DEFAULT_LAYERS: list[str] = [
    "dem.pop.segment",
    "eco.income.household.median",
    "cmp.opportunity.index",
]


def palette_for(direction: Direction) -> str:
    if direction is Direction.HIGHER_IS_BETTER:
        return PALETTES["higher_is_better"]
    if direction is Direction.LOWER_IS_BETTER:
        return PALETTES["lower_is_better"]
    return PALETTES["neutral"]


def build_layer(
    ctx: SectionContext,
    indicator: Indicator,
    *,
    classes: int = 5,
    method: BreakMethod = BreakMethod.QUANTILES,
    default_on: bool = False,
) -> GeoLensLayer | None:
    """Construye una capa coroplética. Devuelve None si no hay datos."""
    values = {g.ine_code: ctx.value(g.geo_id, indicator.code) for g in ctx.children}
    if not any(v is not None for v in values.values()):
        return None

    breaks = stats.compute_breaks(list(values.values()), classes=classes, method=method)
    return GeoLensLayer(
        id=indicator.code,
        label=indicator.label,
        indicator=indicator.code,
        level=ctx.scope.resolve_children_level(),
        unit=indicator.unit,
        breaks=breaks,
        palette=palette_for(indicator.direction),
        values=values,
        default_on=default_on,
    )


def build(
    ctx: SectionContext,
    *,
    tier: Tier,
    include: Sequence[str] | None = None,
    classes: int = 5,
    method: BreakMethod = BreakMethod.QUANTILES,
) -> dict:
    """Payload completo de GeoLens para el informe."""
    allowed_tiers = tier.includes
    codes = include or [
        code for code, ind in ctx.catalog.items() if ind.tier in allowed_tiers
    ]

    layers: list[GeoLensLayer] = []
    for code in codes:
        ind = ctx.catalog.get(code)
        if ind is None or ind.tier not in allowed_tiers:
            continue
        layer = build_layer(
            ctx, ind, classes=classes, method=method,
            default_on=code in DEFAULT_LAYERS,
        )
        if layer is not None:
            layers.append(layer)

    # Agrupadas por sección para que el panel de switches salga ordenado.
    groups: dict[str, list[str]] = {}
    for layer in layers:
        section = ctx.catalog[layer.indicator].section
        groups.setdefault(str(section), []).append(layer.id)

    level = ctx.scope.resolve_children_level()
    return {
        "level": str(level),
        "tiles": tiles_descriptor(level),
        "center": None,          # lo rellena el adaptador con el centroide PostGIS
        "bbox": None,
        "groups": groups,
        "break_methods": [str(m) for m in BreakMethod],
        "layers": [layer.as_dict() for layer in layers],
        "attribution": "© Instituto Geográfico Nacional · © Colaboradores de OpenStreetMap (ODbL)",
    }


def tiles_descriptor(level: GeoLevel) -> dict:
    """Qué fichero PMTiles y qué capa interna usar para este nivel.

    Se generan con: geometrías IGN → mapshaper (simplificado por zoom) →
    tippecanoe → PMTiles, servidos como estáticos. Sin servidor de teselas y
    sin coste por petición.
    """
    return {
        "url": f"pmtiles://{level}.pmtiles",
        "source_layer": str(level),
        "promote_id": "geo_code",
        "minzoom": _MINZOOM.get(level, 4),
        "maxzoom": _MAXZOOM.get(level, 12),
    }


_MINZOOM: dict[GeoLevel, int] = {
    GeoLevel.CCAA: 3,
    GeoLevel.PROVINCIA: 4,
    GeoLevel.MUNICIPIO: 6,
    GeoLevel.DISTRITO: 9,
    GeoLevel.SECCION: 11,
}

_MAXZOOM: dict[GeoLevel, int] = {
    GeoLevel.CCAA: 8,
    GeoLevel.PROVINCIA: 9,
    GeoLevel.MUNICIPIO: 12,
    GeoLevel.DISTRITO: 14,
    GeoLevel.SECCION: 16,
}


def swipe_pair(layers: Sequence[GeoLensLayer], a: str, b: str) -> dict | None:
    """Comparador por swipe entre dos capas. Alto valor, coste casi nulo."""
    ids = {layer.id for layer in layers}
    if a not in ids or b not in ids:
        return None
    return {"mode": "swipe", "left": a, "right": b}


def section_of(catalog: dict[str, Indicator], code: str) -> Section | None:
    ind = catalog.get(code)
    return ind.section if ind else None
