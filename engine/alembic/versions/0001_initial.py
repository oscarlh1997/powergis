"""Esquema inicial: estrella de indicadores + operativa.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ---------------------------------------------------------------- dim_geo
    op.create_table(
        "dim_geo",
        sa.Column("geo_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("ine_code", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("parent_id", sa.BigInteger,
                  sa.ForeignKey("dim_geo.geo_id", ondelete="SET NULL")),
        sa.Column("population", sa.BigInteger),
        sa.Column("area_km2", sa.Numeric(14, 4)),
        sa.Column("geom", Geometry("MULTIPOLYGON", srid=4326)),
        sa.Column("centroid", Geometry("POINT", srid=4326)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("level", "ine_code", name="uq_geo_level_code"),
    )
    op.create_index("ix_geo_parent", "dim_geo", ["parent_id"])
    op.create_index("ix_geo_level", "dim_geo", ["level"])
    op.execute("CREATE INDEX ix_geo_name_trgm ON dim_geo USING gin (name gin_trgm_ops)")

    # --------------------------------------------------------- dim_indicator
    op.create_table(
        "dim_indicator",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("section", sa.String(32), nullable=False),
        sa.Column("subsection", sa.String(64), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("direction", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        sa.Column("min_level", sa.String(16), nullable=False, server_default="municipio"),
        sa.Column("tier", sa.String(16), nullable=False, server_default="avanzado"),
        sa.Column("dimension", sa.String(16)),
        sa.Column("formula", sa.Text),
        sa.Column("decimals", sa.SmallInteger, server_default="2"),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("active", sa.Boolean, server_default=sa.true()),
        sa.CheckConstraint("direction IN (-1, 0, 1)", name="ck_indicator_direction"),
    )
    op.create_index("ix_indicator_section", "dim_indicator", ["section", "tier"])

    # --------------------------------------------------------- fact_indicator
    # value NULL = «no publicado» (secreto estadístico). Nunca 0.
    op.create_table(
        "fact_indicator",
        sa.Column("geo_id", sa.BigInteger,
                  sa.ForeignKey("dim_geo.geo_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("indicator", sa.String(64),
                  sa.ForeignKey("dim_indicator.code", ondelete="CASCADE"), primary_key=True),
        sa.Column("period", sa.Date, primary_key=True),
        sa.Column("segment_key", sa.String(200), primary_key=True, server_default="{}"),
        sa.Column("segment", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("value", sa.Float),
        sa.Column("source_ref", sa.String(200)),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fact_lookup", "fact_indicator", ["indicator", "period", "geo_id"])
    op.create_index("ix_fact_geo", "fact_indicator", ["geo_id", "indicator"])
    op.execute(
        "CREATE INDEX ix_fact_segment ON fact_indicator USING gin (segment jsonb_path_ops)"
    )

    # ---------------------------------------------------------------- project
    op.create_table(
        "project",
        sa.Column("project_uuid", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("wp_user_id", sa.BigInteger, nullable=False),
        sa.Column("wp_post_id", sa.BigInteger),
        sa.Column("scope", postgresql.JSONB, nullable=False),
        sa.Column("segments", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("business", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("sector", sa.String(64)),
        sa.Column("tier", sa.String(16), nullable=False, server_default="basico"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("tier IN ('basico','avanzado')", name="ck_project_tier"),
    )
    op.create_index("ix_project_user", "project", ["wp_user_id"])
    op.create_index("ix_project_post", "project", ["wp_post_id"])

    # ------------------------------------------------------------- report_run
    op.create_table(
        "report_run",
        sa.Column("run_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("project_uuid", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("project.project_uuid", ondelete="CASCADE"), nullable=False),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("engine_ver", sa.String(32), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("sections_done", postgresql.ARRAY(sa.String(32)), server_default="{}"),
        sa.Column("error", postgresql.JSONB),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_run_hash", "report_run", ["project_uuid", "input_hash"])
    op.create_index("ix_run_status", "report_run", ["status"])

    # -------------------------------------------------------- report_snapshot
    op.create_table(
        "report_snapshot",
        sa.Column("project_uuid", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("project.project_uuid", ondelete="CASCADE"), primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("engine_ver", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_snapshot_latest", "report_snapshot", ["project_uuid", "version"])

    # ----------------------------------------------------- pesos del PlaceRank
    op.create_table(
        "sector_profile",
        sa.Column("sector", sa.String(64), primary_key=True),
        sa.Column("indicator", sa.String(64), primary_key=True),
        sa.Column("weight", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "sector_dimension",
        sa.Column("sector", sa.String(64), primary_key=True),
        sa.Column("dimension", sa.String(16), primary_key=True),
        sa.Column("weight", sa.Float, nullable=False),
    )

    # ------------------------------------------------------------- auxiliares
    op.create_table(
        "narrative_cache",
        sa.Column("facts_hash", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "webhook_event",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("event_id", sa.String(128), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("payload", postgresql.JSONB),
    )
    op.create_table(
        "ingest_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("collector", sa.String(32), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("parent_code", sa.String(16)),
        sa.Column("indicators", postgresql.ARRAY(sa.String(64)), server_default="{}"),
        sa.Column("written", sa.Integer, server_default="0"),
        sa.Column("errors", sa.JSON),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ingest_collector", "ingest_log", ["collector", "started_at"])

    op.create_table(
        "rate_limit",
        sa.Column("subject", sa.String(128), primary_key=True),
        sa.Column("window", sa.String(32), primary_key=True),
        sa.Column("count", sa.Integer, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Tablas de POIs de OSM (las rellena osm2pgsql/osmium; aquí solo el contrato).
    op.create_table(
        "osm_poi",
        sa.Column("osm_id", sa.BigInteger, primary_key=True),
        sa.Column("category", sa.String(64)),
        sa.Column("tags", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("geom", Geometry("POINT", srid=4326)),
    )
    op.execute("CREATE INDEX ix_osm_poi_geom ON osm_poi USING gist (geom)")
    op.execute("CREATE INDEX ix_osm_poi_tags ON osm_poi USING gin (tags jsonb_path_ops)")

    op.create_table(
        "osm_road",
        sa.Column("osm_id", sa.BigInteger, primary_key=True),
        sa.Column("highway", sa.String(32)),
        sa.Column("name", sa.String(200)),
        sa.Column("geom", Geometry("LINESTRING", srid=4326)),
    )
    op.execute("CREATE INDEX ix_osm_road_geom ON osm_road USING gist (geom)")
    op.create_index("ix_osm_road_class", "osm_road", ["highway"])


def downgrade() -> None:
    for table in (
        "osm_road", "osm_poi", "rate_limit", "ingest_log", "webhook_event",
        "narrative_cache", "sector_dimension", "sector_profile",
        "report_snapshot", "report_run", "project", "fact_indicator",
        "dim_indicator", "dim_geo",
    ):
        op.drop_table(table)
