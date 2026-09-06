"""Perfil de cliente objetivo en el proyecto.

El formulario de powergis.es no pregunta solo *dónde*, sino *a quién*:
formación, NSE, renta, estructura familiar, clima y tráfico. Ese perfil es
justamente la dimensión «Match% perfil» del PlaceRank, así que hay que
guardarlo con el proyecto.

Revision ID: 0002_target_profile
Revises: 0001_initial
Create Date: 2026-08-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_target_profile"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column(
            "target",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )
    # Los proyectos que ya existían no tenían perfil: quedan con `{}`, y el
    # PlaceRank cae al cálculo por indicadores genéricos como hasta ahora.
    op.create_index(
        "ix_project_target",
        "project",
        ["target"],
        postgresql_using="gin",
        postgresql_ops={"target": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_project_target", table_name="project")
    op.drop_column("project", "target")
