"""Construcción del `SectionContext` a partir de los repositorios.

Es la frontera: aquí se pasa de «puertos» a «dominio puro». A partir de este
punto el motor de informes ya no toca la base de datos.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from ..domain import indicators as catalog_mod
from ..domain.enums import GeoLevel, Section, Tier
from ..domain.errors import GeoNotFound, ValidationError
from ..domain.models import Geo, Indicator, Project, Scope, Segments
from ..domain.ports import UnitOfWork
from ..domain.sections.base import SectionContext


@dataclass(slots=True)
class ResolvedScope:
    parent: Geo
    children: list[Geo]
    children_level: GeoLevel


def resolve_scope(uow: UnitOfWork, scope: Scope, max_children: int = 8500) -> ResolvedScope:
    """Traduce el ámbito del usuario a geografías concretas."""
    parent = uow.geos.get(scope.level, scope.ine_code)
    if parent is None:
        raise GeoNotFound(
            "No existe esa unidad territorial",
            level=str(scope.level),
            ine_code=scope.ine_code,
        )

    children_level = scope.resolve_children_level()
    children = uow.geos.descendants(parent.geo_id, children_level)
    if not children:
        raise ValidationError(
            "El ámbito no tiene zonas al nivel de desagregación pedido",
            level=str(scope.level),
            children_level=str(children_level),
        )
    if len(children) > max_children:
        raise ValidationError(
            "Demasiadas zonas para un solo informe; sube el nivel de desagregación",
            count=len(children),
            limit=max_children,
        )
    children.sort(key=lambda g: g.name)
    return ResolvedScope(parent=parent, children=children, children_level=children_level)


def segment_combinations(segments: Segments) -> list[dict[str, str]]:
    """Producto cartesiano de los segmentos pedidos, más el agregado `{}`.

    Se pide siempre el agregado para poder calcular porcentajes y totales sin
    depender de que estén todos los cruces.
    """
    axes: list[list[tuple[str, str]]] = []
    if segments.age:
        axes.append([("age", a) for a in segments.age])
    if segments.sex:
        axes.append([("sex", s) for s in segments.sex])
    if segments.nationality:
        axes.append([("nationality", n) for n in segments.nationality])

    combos: list[dict[str, str]] = [{}]
    if not axes:
        return combos

    # Cada eje por separado (para totales por edad, por sexo...).
    for axis in axes:
        combos.extend(dict([pair]) for pair in axis)

    # Y el cruce completo, que es lo que alimenta las tablas de segmentación.
    if len(axes) > 1:
        for tup in itertools.product(*axes):
            combos.append(dict(tup))

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for combo in combos:
        key = SectionContext.segment_key(combo)
        if key not in seen:
            seen.add(key)
            unique.append(combo)
    return unique


def indicators_for(tier: Tier, sections: Sequence[Section] | None = None) -> list[Indicator]:
    wanted = set(sections or catalog_mod.sections_for_tier(tier))
    return [i for i in catalog_mod.by_tier(tier) if i.section in wanted]


def build_context(
    uow: UnitOfWork,
    project: Project,
    *,
    tier: Tier | None = None,
    sections: Sequence[Section] | None = None,
    max_children: int = 8500,
) -> SectionContext:
    """Carga geografías + hechos y devuelve el contexto listo para el dominio."""
    tier = tier or project.tier
    resolved = resolve_scope(uow, project.scope, max_children)

    wanted = list(sections or catalog_mod.sections_for_tier(tier))
    indicators = indicators_for(tier, wanted)
    codes = [i.code for i in indicators]

    # Filtrar por granularidad publicada: pedir renta por sección censal cuando
    # solo se publica por municipio devolvería una tabla vacía y sin explicación.
    level = resolved.children_level
    usable = [i for i in indicators if i.available_at(level)]
    dropped = [i.code for i in indicators if i not in usable]

    geo_ids = [g.geo_id for g in resolved.children] + [resolved.parent.geo_id]
    combos = segment_combinations(project.segments)
    facts = uow.facts.fetch(geo_ids, [i.code for i in usable], combos)

    ctx = SectionContext(
        scope=project.scope,
        parent=resolved.parent,
        children=resolved.children,
        segments=project.segments,
        tier=tier,
        catalog={i.code: i for i in usable},
        facts=SectionContext.index(facts),
        business=project.business.as_dict(),
        target=project.target,
    )

    if dropped:
        ctx.warnings.append(
            f"{len(dropped)} indicadores no se publican a nivel {level}; se omiten "
            f"en lugar de estimarlos."
        )
    missing = [c for c in codes if c not in ctx.catalog]
    if missing:
        ctx.warnings.append(
            "Indicadores sin cobertura suficiente en este ámbito: "
            + ", ".join(sorted(missing)[:8])
            + ("…" if len(missing) > 8 else "")
        )
    return ctx
