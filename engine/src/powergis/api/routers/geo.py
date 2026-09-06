"""Búsqueda de geografías: alimenta el autocompletado del formulario."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...adapters.db.session import uow_factory
from ...application.dto import GeoOut
from ...domain.enums import GeoLevel
from ...domain.errors import GeoNotFound

router = APIRouter(prefix="/v1/geo", tags=["geografía"])


@router.get("/search", response_model=list[GeoOut])
def search(
    q: Annotated[str, Query(min_length=2, max_length=80)],
    level: Annotated[GeoLevel | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[GeoOut]:
    with uow_factory() as uow:
        results = uow.geos.search(q, level, limit)
    return [
        GeoOut(
            geo_id=g.geo_id, level=g.level, ine_code=g.ine_code,
            name=g.name, parent_id=g.parent_id, population=g.population,
        )
        for g in results
    ]


@router.get("/{level}/{ine_code}", response_model=GeoOut)
def get_geo(level: GeoLevel, ine_code: str) -> GeoOut:
    with uow_factory() as uow:
        geo = uow.geos.get(level, ine_code)
    if geo is None:
        raise GeoNotFound("No existe esa unidad territorial", level=str(level), ine_code=ine_code)
    return GeoOut(
        geo_id=geo.geo_id, level=geo.level, ine_code=geo.ine_code,
        name=geo.name, parent_id=geo.parent_id, population=geo.population,
    )


@router.get("/{level}/{ine_code}/children", response_model=list[GeoOut])
def children(
    level: GeoLevel,
    ine_code: str,
    child_level: Annotated[GeoLevel | None, Query()] = None,
) -> list[GeoOut]:
    """Zonas en que se desagrega un ámbito. Es la previsualización de la tabla."""
    with uow_factory() as uow:
        parent = uow.geos.get(level, ine_code)
        if parent is None:
            raise GeoNotFound("No existe esa unidad territorial", level=str(level))
        target = child_level or level.child
        if target is None:
            return []
        rows = uow.geos.descendants(parent.geo_id, target)
    return [
        GeoOut(
            geo_id=g.geo_id, level=g.level, ine_code=g.ine_code,
            name=g.name, parent_id=g.parent_id, population=g.population,
        )
        for g in rows
    ]
