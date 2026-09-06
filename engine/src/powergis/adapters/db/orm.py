"""Modelo relacional (SQLAlchemy 2.0 + PostGIS).

Esquema en estrella: `dim_geo` y `dim_indicator` describen; `fact_indicator`
mide. Todo lo demás (proyecto, ejecución, snapshot) es operativa.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Dimensiones
# --------------------------------------------------------------------------- #


class GeoRow(Base):
    __tablename__ = "dim_geo"

    geo_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    ine_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dim_geo.geo_id", ondelete="SET NULL")
    )
    population: Mapped[int | None] = mapped_column(BigInteger)
    area_km2: Mapped[float | None] = mapped_column(Numeric(14, 4))
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
    centroid = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    children: Mapped[list[GeoRow]] = relationship(remote_side=[parent_id], viewonly=True)

    __table_args__ = (
        UniqueConstraint("level", "ine_code", name="uq_geo_level_code"),
        Index("ix_geo_parent", "parent_id"),
        Index("ix_geo_level", "level"),
        Index("ix_geo_name_trgm", "name", postgresql_using="gin",
              postgresql_ops={"name": "gin_trgm_ops"}),
        Index("ix_geo_geom", "geom", postgresql_using="gist"),
    )


class IndicatorRow(Base):
    __tablename__ = "dim_indicator"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    subsection: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    min_level: Mapped[str] = mapped_column(String(16), nullable=False, default="municipio")
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="avanzado")
    dimension: Mapped[str | None] = mapped_column(String(16))
    formula: Mapped[str | None] = mapped_column(Text)
    decimals: Mapped[int] = mapped_column(SmallInteger, default=2)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("direction IN (-1, 0, 1)", name="ck_indicator_direction"),
        Index("ix_indicator_section", "section", "tier"),
    )


# --------------------------------------------------------------------------- #
# Hechos
# --------------------------------------------------------------------------- #


class FactRow(Base):
    """Una fila por (geografía × indicador × periodo × segmento).

    `value` NULL significa «no publicado» (secreto estadístico). Es
    deliberadamente distinto de 0 y la UI lo muestra como tal.
    """

    __tablename__ = "fact_indicator"

    geo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dim_geo.geo_id", ondelete="CASCADE"), primary_key=True
    )
    indicator: Mapped[str] = mapped_column(
        String(64), ForeignKey("dim_indicator.code", ondelete="CASCADE"), primary_key=True
    )
    period: Mapped[date] = mapped_column(Date, primary_key=True)
    segment_key: Mapped[str] = mapped_column(String(200), primary_key=True, default="{}")
    segment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    value: Mapped[float | None] = mapped_column(Float)
    source_ref: Mapped[str | None] = mapped_column(String(200))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_fact_lookup", "indicator", "period", "geo_id"),
        Index("ix_fact_geo", "geo_id", "indicator"),
        Index("ix_fact_segment", "segment", postgresql_using="gin",
              postgresql_ops={"segment": "jsonb_path_ops"}),
    )


# --------------------------------------------------------------------------- #
# Operativa
# --------------------------------------------------------------------------- #


class ProjectRow(Base):
    __tablename__ = "project"

    project_uuid: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    wp_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    wp_post_id: Mapped[int | None] = mapped_column(BigInteger)
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    segments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    business: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Perfil de cliente objetivo: alimenta el Match% del PlaceRank.
    target: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    sector: Mapped[str | None] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="basico")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_project_user", "wp_user_id"),
        Index("ix_project_post", "wp_post_id"),
        CheckConstraint("tier IN ('basico','avanzado')", name="ck_project_tier"),
    )


class RunRow(Base):
    __tablename__ = "report_run"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_uuid: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.project_uuid", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    engine_ver: Mapped[str] = mapped_column(String(32), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sections_done: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    error: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Idempotencia: una sola ejecución viva por (proyecto, hash de entradas).
        Index("ix_run_hash", "project_uuid", "input_hash"),
        Index("ix_run_status", "status"),
    )


class SnapshotRow(Base):
    __tablename__ = "report_snapshot"

    project_uuid: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.project_uuid", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    engine_ver: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (Index("ix_snapshot_latest", "project_uuid", "version"),)


class SectorProfileRow(Base):
    """Pesos del PlaceRank por sector. Cambiar el modelo no requiere despliegue."""

    __tablename__ = "sector_profile"

    sector: Mapped[str] = mapped_column(String(64), primary_key=True)
    indicator: Mapped[str] = mapped_column(String(64), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SectorDimensionRow(Base):
    __tablename__ = "sector_dimension"

    sector: Mapped[str] = mapped_column(String(64), primary_key=True)
    dimension: Mapped[str] = mapped_column(String(16), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)


class NarrativeCacheRow(Base):
    """Textos de IA cacheados por hash de los HECHOS, no por proyecto.

    Dos usuarios que pidan Madrid con el mismo perfil comparten el texto.
    """

    __tablename__ = "narrative_cache"

    facts_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WebhookEventRow(Base):
    """Idempotencia de Stripe: un `event.id` no se procesa dos veces."""

    __tablename__ = "webhook_event"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    payload: Mapped[dict | None] = mapped_column(JSONB)


class IngestLogRow(Base):
    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collector: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_code: Mapped[str | None] = mapped_column(String(16))
    indicators: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    written: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_ingest_collector", "collector", "started_at"),)


class RateLimitRow(Base):
    """Contador de informes gratuitos: la superficie de abuso del tier básico."""

    __tablename__ = "rate_limit"

    subject: Mapped[str] = mapped_column(String(128), primary_key=True)
    window: Mapped[str] = mapped_column(String(32), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
