"""Implementación SQLAlchemy de los puertos del dominio."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ...domain.enums import Dimension, Direction, GeoLevel, RunStatus, Section, Tier, Unit
from ...domain.models import (
    BusinessProfile,
    Fact,
    Geo,
    Indicator,
    Project,
    ReportRun,
    Scope,
    Segments,
)
from ...domain.target import TargetProfile
from .orm import (
    FactRow,
    GeoRow,
    IndicatorRow,
    ProjectRow,
    RunRow,
    SectorDimensionRow,
    SectorProfileRow,
    SnapshotRow,
)


def _segment_key(segment: dict[str, str] | None) -> str:
    return json.dumps(segment or {}, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- #


class SqlGeoRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @staticmethod
    def _to_domain(row: GeoRow) -> Geo:
        return Geo(
            geo_id=row.geo_id,
            level=GeoLevel(row.level),
            ine_code=row.ine_code,
            name=row.name,
            parent_id=row.parent_id,
            population=row.population,
            area_km2=float(row.area_km2) if row.area_km2 is not None else None,
        )

    def get(self, level: GeoLevel, ine_code: str) -> Geo | None:
        row = self._s.scalar(
            select(GeoRow).where(GeoRow.level == str(level), GeoRow.ine_code == ine_code)
        )
        return self._to_domain(row) if row else None

    def get_by_id(self, geo_id: int) -> Geo | None:
        row = self._s.get(GeoRow, geo_id)
        return self._to_domain(row) if row else None

    def children(self, geo_id: int, level: GeoLevel) -> list[Geo]:
        rows = self._s.scalars(
            select(GeoRow).where(GeoRow.parent_id == geo_id, GeoRow.level == str(level))
        ).all()
        return [self._to_domain(r) for r in rows]

    def by_level(self, level: GeoLevel) -> list[Geo]:
        rows = self._s.scalars(
            select(GeoRow).where(GeoRow.level == str(level)).order_by(GeoRow.ine_code)
        ).all()
        return [self._to_domain(r) for r in rows]

    def descendants(self, geo_id: int, level: GeoLevel) -> list[Geo]:
        """Descendientes a un nivel, saltando niveles intermedios.

        CTE recursiva: pedir los municipios de una CCAA no obliga a pasar por
        las provincias en código.
        """
        cte = (
            select(GeoRow.geo_id, GeoRow.parent_id)
            .where(GeoRow.geo_id == geo_id)
            .cte("tree", recursive=True)
        )
        child = select(GeoRow.geo_id, GeoRow.parent_id).join(
            cte, GeoRow.parent_id == cte.c.geo_id
        )
        tree = cte.union_all(child)

        rows = self._s.scalars(
            select(GeoRow)
            .join(tree, GeoRow.geo_id == tree.c.geo_id)
            .where(GeoRow.level == str(level))
            .order_by(GeoRow.name)
        ).all()
        return [self._to_domain(r) for r in rows]

    def search(self, query: str, level: GeoLevel | None = None, limit: int = 20) -> list[Geo]:
        stmt: Select = select(GeoRow).where(
            or_(
                GeoRow.name.ilike(f"%{query}%"),
                GeoRow.ine_code.startswith(query),
            )
        )
        if level is not None:
            stmt = stmt.where(GeoRow.level == str(level))
        stmt = stmt.order_by(
            func.length(GeoRow.name), GeoRow.population.desc().nullslast()
        ).limit(limit)
        return [self._to_domain(r) for r in self._s.scalars(stmt).all()]

    def upsert_many(self, geos: Sequence[Geo]) -> int:
        if not geos:
            return 0
        payload = [
            {
                "level": str(g.level),
                "ine_code": g.ine_code,
                "name": g.name,
                "parent_id": g.parent_id,
                "population": g.population,
                "area_km2": g.area_km2,
            }
            for g in geos
        ]
        stmt = pg_insert(GeoRow).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[GeoRow.level, GeoRow.ine_code],
            set_={
                "name": stmt.excluded.name,
                "parent_id": stmt.excluded.parent_id,
                "population": stmt.excluded.population,
                "area_km2": stmt.excluded.area_km2,
            },
        )
        self._s.execute(stmt)
        return len(payload)


# --------------------------------------------------------------------------- #


class SqlIndicatorRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @staticmethod
    def _to_domain(row: IndicatorRow) -> Indicator:
        return Indicator(
            code=row.code,
            section=Section(row.section),
            subsection=row.subsection,
            label=row.label,
            unit=Unit(row.unit),
            direction=Direction(row.direction),
            source=row.source,
            min_level=GeoLevel(row.min_level),
            tier=Tier(row.tier),
            dimension=Dimension(row.dimension) if row.dimension else None,
            formula=row.formula,
            decimals=row.decimals,
            description=row.description or "",
        )

    def get(self, code: str) -> Indicator | None:
        row = self._s.get(IndicatorRow, code)
        return self._to_domain(row) if row and row.active else None

    def by_section(self, section: Section, tier: Tier | None = None) -> list[Indicator]:
        stmt = select(IndicatorRow).where(
            IndicatorRow.section == str(section), IndicatorRow.active.is_(True)
        )
        if tier is not None:
            stmt = stmt.where(IndicatorRow.tier.in_([str(t) for t in tier.includes]))
        return [self._to_domain(r) for r in self._s.scalars(stmt).all()]

    def all(self) -> list[Indicator]:
        rows = self._s.scalars(
            select(IndicatorRow).where(IndicatorRow.active.is_(True))
        ).all()
        return [self._to_domain(r) for r in rows]

    def upsert_many(self, indicators: Sequence[Indicator]) -> int:
        if not indicators:
            return 0
        payload = [
            {
                "code": i.code,
                "section": str(i.section),
                "subsection": i.subsection,
                "label": i.label,
                "unit": str(i.unit),
                "direction": int(i.direction),
                "source": i.source,
                "min_level": str(i.min_level),
                "tier": str(i.tier),
                "dimension": str(i.dimension) if i.dimension else None,
                "formula": i.formula,
                "decimals": i.decimals,
                "description": i.description,
                "active": True,
            }
            for i in indicators
        ]
        stmt = pg_insert(IndicatorRow).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[IndicatorRow.code],
            set_={c: getattr(stmt.excluded, c) for c in (
                "section", "subsection", "label", "unit", "direction", "source",
                "min_level", "tier", "dimension", "formula", "decimals",
                "description", "active",
            )},
        )
        self._s.execute(stmt)
        return len(payload)


# --------------------------------------------------------------------------- #


class SqlFactRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def fetch(
        self,
        geo_ids: Sequence[int],
        indicators: Sequence[str],
        segments: Sequence[dict[str, str]] | None = None,
        period: date | None = None,
    ) -> list[Fact]:
        """Último periodo disponible por (geo, indicador, segmento).

        `DISTINCT ON` de PostgreSQL: una sola pasada, sin subconsulta de
        máximos ni ventana. Es la consulta más caliente del sistema.
        """
        if not geo_ids or not indicators:
            return []

        keys = [_segment_key(s) for s in (segments or [{}])]
        conditions = [
            FactRow.geo_id.in_(list(geo_ids)),
            FactRow.indicator.in_(list(indicators)),
            FactRow.segment_key.in_(keys),
        ]
        if period is not None:
            conditions.append(FactRow.period == period)

        stmt = (
            select(FactRow)
            .where(and_(*conditions))
            .distinct(FactRow.geo_id, FactRow.indicator, FactRow.segment_key)
            .order_by(
                FactRow.geo_id, FactRow.indicator, FactRow.segment_key, FactRow.period.desc()
            )
        )
        rows = self._s.scalars(stmt).all()
        return [
            Fact(
                geo_id=r.geo_id,
                indicator=r.indicator,
                period=r.period,
                value=r.value,
                segment=r.segment or {},
                source_ref=r.source_ref,
                ingested_at=r.ingested_at,
            )
            for r in rows
        ]

    def freshness(self, indicators: Sequence[str], geo_ids: Sequence[int]) -> dict[str, date | None]:
        if not indicators or not geo_ids:
            return {}
        rows = self._s.execute(
            select(FactRow.indicator, func.max(FactRow.period))
            .where(FactRow.indicator.in_(list(indicators)), FactRow.geo_id.in_(list(geo_ids)))
            .group_by(FactRow.indicator)
        ).all()
        out: dict[str, date | None] = dict.fromkeys(indicators)
        out.update(dict(rows))
        return out

    def upsert_many(self, facts: Sequence[Fact]) -> int:
        if not facts:
            return 0
        payload = [
            {
                "geo_id": f.geo_id,
                "indicator": f.indicator,
                "period": f.period,
                "segment_key": _segment_key(f.segment),
                "segment": f.segment or {},
                "value": f.value,
                "source_ref": f.source_ref,
                "ingested_at": f.ingested_at or datetime.utcnow(),
            }
            for f in facts
        ]
        written = 0
        # Lotes de 1.000: mantiene el statement por debajo del límite de
        # parámetros de psycopg y hace el progreso visible en el log.
        for i in range(0, len(payload), 1000):
            chunk = payload[i:i + 1000]
            stmt = pg_insert(FactRow).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    FactRow.geo_id, FactRow.indicator, FactRow.period, FactRow.segment_key
                ],
                set_={
                    "value": stmt.excluded.value,
                    "source_ref": stmt.excluded.source_ref,
                    "ingested_at": stmt.excluded.ingested_at,
                    "segment": stmt.excluded.segment,
                },
            )
            self._s.execute(stmt)
            written += len(chunk)
        return written

    def coverage(self, geo_ids: Sequence[int], indicators: Sequence[str]) -> float:
        cells = len(geo_ids) * len(indicators)
        if cells == 0:
            return 0.0
        filled = self._s.scalar(
            select(func.count())
            .select_from(FactRow)
            .where(
                FactRow.geo_id.in_(list(geo_ids)),
                FactRow.indicator.in_(list(indicators)),
                FactRow.value.isnot(None),
                FactRow.segment_key == "{}",
            )
        ) or 0
        return min(filled / cells, 1.0)


# --------------------------------------------------------------------------- #


class SqlProjectRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @staticmethod
    def _to_domain(row: ProjectRow) -> Project:
        scope = row.scope or {}
        return Project(
            project_uuid=row.project_uuid,
            wp_user_id=row.wp_user_id,
            wp_post_id=row.wp_post_id,
            scope=Scope(
                level=GeoLevel(scope.get("level", "ccaa")),
                ine_code=scope.get("ine_code", ""),
                children_level=(
                    GeoLevel(scope["children_level"]) if scope.get("children_level") else None
                ),
            ),
            segments=Segments.from_mapping(row.segments or {}),
            business=BusinessProfile(**{
                k: v for k, v in (row.business or {}).items()
                if k in BusinessProfile.__dataclass_fields__
            }),
            tier=Tier(row.tier),
            created_at=row.created_at,
            target=TargetProfile.from_mapping(row.target or {}),
        )

    def get(self, project_uuid: UUID) -> Project | None:
        row = self._s.get(ProjectRow, project_uuid)
        return self._to_domain(row) if row else None

    def save(self, project: Project) -> Project:
        row = ProjectRow(
            project_uuid=project.project_uuid,
            wp_user_id=project.wp_user_id,
            wp_post_id=project.wp_post_id,
            scope={
                "level": str(project.scope.level),
                "ine_code": project.scope.ine_code,
                "children_level": str(project.scope.resolve_children_level()),
            },
            segments=project.segments.as_dict(),
            business=project.business.as_dict(),
            target=project.target.as_dict() if project.target else {},
            sector=project.business.sector,
            tier=str(project.tier),
        )
        self._s.merge(row)
        self._s.flush()
        return project

    def set_tier(self, project_uuid: UUID, tier: Tier) -> None:
        row = self._s.get(ProjectRow, project_uuid)
        if row is not None:
            row.tier = str(tier)
            self._s.flush()


# --------------------------------------------------------------------------- #


class SqlRunRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    @staticmethod
    def _to_domain(row: RunRow) -> ReportRun:
        return ReportRun(
            run_id=row.run_id,
            project_uuid=row.project_uuid,
            tier=Tier(row.tier),
            status=RunStatus(row.status),
            engine_version=row.engine_ver,
            input_hash=row.input_hash,
            sections_done=list(row.sections_done or []),
            error=row.error,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    def create(self, run: ReportRun) -> ReportRun:
        row = RunRow(
            project_uuid=run.project_uuid,
            tier=str(run.tier),
            status=str(run.status),
            engine_ver=run.engine_version,
            input_hash=run.input_hash,
            sections_done=list(run.sections_done),
        )
        self._s.add(row)
        self._s.flush()
        run.run_id = row.run_id
        return run

    def get(self, run_id: int) -> ReportRun | None:
        row = self._s.get(RunRow, run_id)
        return self._to_domain(row) if row else None

    def find_by_hash(self, project_uuid: UUID, input_hash: str) -> ReportRun | None:
        row = self._s.scalar(
            select(RunRow)
            .where(RunRow.project_uuid == project_uuid, RunRow.input_hash == input_hash)
            .order_by(RunRow.run_id.desc())
            .limit(1)
        )
        return self._to_domain(row) if row else None

    def update(self, run: ReportRun) -> ReportRun:
        row = self._s.get(RunRow, run.run_id)
        if row is None:
            return run
        row.status = str(run.status)
        row.sections_done = list(run.sections_done)
        row.error = run.error
        row.started_at = run.started_at
        row.finished_at = run.finished_at
        self._s.flush()
        return run

    def latest_for(self, project_uuid: UUID) -> ReportRun | None:
        row = self._s.scalar(
            select(RunRow)
            .where(RunRow.project_uuid == project_uuid)
            .order_by(RunRow.run_id.desc())
            .limit(1)
        )
        return self._to_domain(row) if row else None


# --------------------------------------------------------------------------- #


class SqlSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(self, project_uuid: UUID, version: int, tier: Tier, payload: dict[str, Any]) -> None:
        stmt = pg_insert(SnapshotRow).values(
            project_uuid=project_uuid,
            version=version,
            tier=str(tier),
            payload=payload,
            engine_ver=payload.get("engine_version"),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SnapshotRow.project_uuid, SnapshotRow.version],
            set_={"payload": stmt.excluded.payload, "tier": stmt.excluded.tier},
        )
        self._s.execute(stmt)

    def latest(self, project_uuid: UUID) -> tuple[int, Tier, dict[str, Any]] | None:
        row = self._s.scalar(
            select(SnapshotRow)
            .where(SnapshotRow.project_uuid == project_uuid)
            .order_by(SnapshotRow.version.desc())
            .limit(1)
        )
        return (row.version, Tier(row.tier), row.payload) if row else None

    def get(self, project_uuid: UUID, version: int) -> dict[str, Any] | None:
        row = self._s.get(SnapshotRow, (project_uuid, version))
        return row.payload if row else None

    def next_version(self, project_uuid: UUID) -> int:
        current = self._s.scalar(
            select(func.max(SnapshotRow.version)).where(
                SnapshotRow.project_uuid == project_uuid
            )
        )
        return (current or 0) + 1


# --------------------------------------------------------------------------- #


class SqlSectorProfileRepository:
    """Pesos del PlaceRank. Son datos: cambiarlos no requiere despliegue."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def load(self, sector: str | None):
        from ...domain.placerank import BUILTIN_PROFILES, SectorProfile

        key = (sector or "generico").lower()
        rows = self._s.scalars(
            select(SectorProfileRow).where(SectorProfileRow.sector == key)
        ).all()
        dims = self._s.scalars(
            select(SectorDimensionRow).where(SectorDimensionRow.sector == key)
        ).all()

        if not rows and not dims:
            return BUILTIN_PROFILES.get(key, SectorProfile.default(key))

        profile = SectorProfile(sector=key)
        if dims:
            profile.dimension_weights = {Dimension(d.dimension): d.weight for d in dims}
        if rows:
            profile.indicator_weights = {r.indicator: r.weight for r in rows}
        return profile

    def save(self, profile) -> None:
        for dimension, weight in profile.dimension_weights.items():
            stmt = pg_insert(SectorDimensionRow).values(
                sector=profile.sector, dimension=str(dimension), weight=weight
            )
            self._s.execute(stmt.on_conflict_do_update(
                index_elements=[SectorDimensionRow.sector, SectorDimensionRow.dimension],
                set_={"weight": stmt.excluded.weight},
            ))
        for code, weight in profile.indicator_weights.items():
            stmt = pg_insert(SectorProfileRow).values(
                sector=profile.sector, indicator=code, weight=weight
            )
            self._s.execute(stmt.on_conflict_do_update(
                index_elements=[SectorProfileRow.sector, SectorProfileRow.indicator],
                set_={"weight": stmt.excluded.weight},
            ))


def install_extensions(session: Session) -> None:
    """PostGIS y pg_trgm. Idempotente; se llama en la migración inicial."""
    for ext in ("postgis", "pg_trgm"):
        session.execute(text(f"CREATE EXTENSION IF NOT EXISTS {ext}"))
