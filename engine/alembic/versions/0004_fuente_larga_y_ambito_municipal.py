"""Fuente larga en los hechos y el ámbito municipal que no se recargaba.

Dos incidencias de la hoja «Incidencias» de la especificación de visualización:

* `fact_indicator.source_ref` era VARCHAR(200) y la plantilla del equipo de
  datos trae fuentes más largas: la carga fallaba con StringDataRightTruncation.
  Pasa a TEXT.
* `project.scope.children_level` se guardaba RESUELTO: un municipio quedaba
  con «distrito» y al recargarlo ya no se comparaba con los municipios de su
  provincia («El ámbito no tiene zonas al nivel de desagregación pedido»). El
  repositorio ya sólo lo guarda si se pidió; aquí se limpia lo guardado.

Revision ID: 0004_fuente_larga_y_ambito_municipal
Revises: 0003_capas_y_sin_nse
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_fuente_larga_y_ambito_municipal"
down_revision = "0003_capas_y_sin_nse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("fact_indicator", "source_ref", type_=sa.Text(),
                    existing_type=sa.String(200), existing_nullable=True)
    op.execute(sa.text("""
        UPDATE project
           SET scope = scope - 'children_level'
         WHERE scope ->> 'level' = 'municipio'
           AND scope ->> 'children_level' = 'distrito'
    """))


def downgrade() -> None:
    # Las fuentes de más de 200 caracteres se recortan: no hay otra forma de
    # volver al tipo anterior.
    op.execute(sa.text(
        "UPDATE fact_indicator SET source_ref = left(source_ref, 200) "
        "WHERE length(source_ref) > 200"
    ))
    op.alter_column("fact_indicator", "source_ref", type_=sa.String(200),
                    existing_type=sa.Text(), existing_nullable=True)
