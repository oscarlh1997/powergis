"""Capas del formulario en el proyecto y fuera los restos del NSE.

Dos cambios que llegan con el formulario de octubre de 2026:

* `project.layers`: los interruptores de las capas complementarias
  (resultados electorales, traslados, turismo, vivienda…). Los proyectos que
  ya existían quedan con `{}`, que significa «todas encendidas»: salen igual
  que antes.

* El NSE salió del formulario y del motor el 18/10/2026. El indicador de
  riesgo de exclusión conservaba el prefijo `eco.nse.`; pasa a
  `eco.poverty.risk_pct` con sus datos, y los indicadores de clase social que
  quedaron en `dim_indicator` (y sus hechos) se borran.

Revision ID: 0003_capas_y_sin_nse
Revises: 0002_target_profile
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_capas_y_sin_nse"
down_revision = "0002_target_profile"
branch_labels = None
depends_on = None

ANTIGUO = "eco.nse.risk_pct"
NUEVO = "eco.poverty.risk_pct"
CLASES_SOCIALES = (
    "eco.nse.index", "eco.nse.upper_middle_pct", "eco.class.high_pct",
    "eco.class.mid_pct", "eco.class.lower_mid_pct", "eco.class.low_pct",
)


def upgrade() -> None:
    op.add_column(
        "project",
        sa.Column("layers", postgresql.JSONB, nullable=False, server_default="{}"),
    )

    # Renombrar con sus datos. `fact_indicator.indicator` apunta a
    # `dim_indicator.code` sin ON UPDATE CASCADE: primero el código nuevo,
    # luego se mueven los hechos y al final se borra el viejo.
    op.execute(sa.text(f"""
        INSERT INTO dim_indicator (code, section, subsection, label, unit, direction, source,
                                   min_level, tier, dimension, formula, decimals, description,
                                   active)
        SELECT '{NUEVO}', section, 'desigualdad', label, unit, direction, source, min_level,
               tier, dimension, formula, decimals, description, active
          FROM dim_indicator WHERE code = '{ANTIGUO}'
        ON CONFLICT (code) DO NOTHING
    """))
    op.execute(sa.text(f"""
        UPDATE fact_indicator f SET indicator = '{NUEVO}'
         WHERE f.indicator = '{ANTIGUO}'
           AND NOT EXISTS (
               SELECT 1 FROM fact_indicator n
                WHERE n.geo_id = f.geo_id AND n.indicator = '{NUEVO}'
                  AND n.period = f.period AND n.segment_key = f.segment_key)
    """))
    # Lo que no se pudo mover (ya había dato con el código nuevo) se va con
    # el indicador viejo: ON DELETE CASCADE.
    op.execute(sa.text(f"DELETE FROM dim_indicator WHERE code = '{ANTIGUO}'"))
    op.execute(sa.text(
        "UPDATE dim_indicator SET subsection = 'desigualdad' "
        "WHERE code IN ('eco.gini', 'eco.resilience.index') AND subsection = 'nse'"
    ))
    codigos = ", ".join(f"'{c}'" for c in CLASES_SOCIALES)
    op.execute(sa.text(f"DELETE FROM dim_indicator WHERE code IN ({codigos})"))


def downgrade() -> None:
    # Los indicadores de clase social no se recuperan: no tenían fuente.
    op.execute(sa.text(f"""
        INSERT INTO dim_indicator (code, section, subsection, label, unit, direction, source,
                                   min_level, tier, dimension, formula, decimals, description,
                                   active)
        SELECT '{ANTIGUO}', section, 'nse', label, unit, direction, source, min_level,
               tier, dimension, formula, decimals, description, active
          FROM dim_indicator WHERE code = '{NUEVO}'
        ON CONFLICT (code) DO NOTHING
    """))
    op.execute(sa.text(
        f"UPDATE fact_indicator SET indicator = '{ANTIGUO}' WHERE indicator = '{NUEVO}'"
    ))
    op.execute(sa.text(f"DELETE FROM dim_indicator WHERE code = '{NUEVO}'"))
    op.drop_column("project", "layers")
