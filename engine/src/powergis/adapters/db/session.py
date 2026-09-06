"""Sesión y Unit of Work."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ...config import Settings, get_settings
from ...domain.ports import (
    FactRepository,
    GeoRepository,
    IndicatorRepository,
    ProjectRepository,
    RunRepository,
    SnapshotRepository,
)
from .repositories import (
    SqlFactRepository,
    SqlGeoRepository,
    SqlIndicatorRepository,
    SqlProjectRepository,
    SqlRunRepository,
    SqlSectorProfileRepository,
    SqlSnapshotRepository,
)

_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine(settings: Settings | None = None):
    global _engine
    if _engine is None:
        cfg = settings or get_settings()
        _engine = create_engine(
            cfg.database_url,
            pool_size=cfg.db_pool_size,
            max_overflow=cfg.db_max_overflow,
            pool_pre_ping=True,          # la conexión muerta tras un reinicio no rompe un job
            pool_recycle=1800,
            echo=cfg.db_echo,
            future=True,
        )
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(settings), expire_on_commit=False, class_=Session
        )
    return _session_factory


class SqlUnitOfWork:
    """Agrupa los repositorios en una transacción.

    Se usa como context manager; `commit()` es explícito y la salida sin
    commit hace rollback. Nada se persiste «por accidente».
    """

    # Los repositorios se declaran aquí aunque se construyan en `__enter__`.
    #
    # No es decoración: sin estas anotaciones, para el analizador de tipos esta
    # clase no tiene esos atributos y por tanto NO cumple el protocolo
    # `UnitOfWork` del dominio. La consecuencia era que `uow_factory` —que
    # devuelve un `SqlUnitOfWork`— se rechazaba en todos los casos de uso que
    # piden un `Callable[[], UnitOfWork]`: diecinueve errores, todos el mismo.
    #
    # Declararlos aquí dice la verdad sobre la clase y hace que el adaptador
    # vuelva a encajar en el puerto, que es de lo que trata la arquitectura.
    #
    # Y se anotan con el tipo del PUERTO, no con el del adaptador: los
    # atributos de un Protocol son invariantes: se pueden leer y escribir,
    # así que declarar aquí `SqlGeoRepository` donde el puerto pide
    # `GeoRepository` no cumple el protocolo aunque uno herede del otro.
    #
    # Y es además lo correcto: quien recibe un UnitOfWork trabaja contra los
    # puertos del dominio. Que por dentro sean implementaciones de SQLAlchemy
    # es cosa de este adaptador y de nadie más.
    geos: GeoRepository
    indicators: IndicatorRepository
    facts: FactRepository
    projects: ProjectRepository
    runs: RunRepository
    snapshots: SnapshotRepository
    sector_profiles: SqlSectorProfileRepository

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._factory = session_factory or get_session_factory()
        self._session: Session | None = None

    @property
    def session(self) -> Session:
        """La sesión abierta.

        Es una propiedad y no un atributo porque fuera del `with` no existe
        ninguna sesión. Antes esto era `Session | None`, y cada uso —
        `uow.session.scalar(...)`, `uow.session.add(...)`— arrastraba un aviso
        del analizador que se ignoraba. En ejecución, usarlo fuera del contexto
        daba `AttributeError: 'NoneType' object has no attribute 'scalar'`, que
        no dice nada de lo que pasó realmente.
        """
        if self._session is None:
            raise RuntimeError(
                "No hay sesión abierta: usa el UnitOfWork dentro de un `with`."
            )
        return self._session

    def __enter__(self) -> SqlUnitOfWork:
        self._session = self._factory()
        self.geos = SqlGeoRepository(self._session)
        self.indicators = SqlIndicatorRepository(self._session)
        self.facts = SqlFactRepository(self._session)
        self.projects = SqlProjectRepository(self._session)
        self.runs = SqlRunRepository(self._session)
        self.snapshots = SqlSnapshotRepository(self._session)
        self.sector_profiles = SqlSectorProfileRepository(self._session)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        sesion = self._session
        if sesion is None:
            return
        try:
            if exc_type is not None:
                sesion.rollback()
        finally:
            sesion.close()
            self._session = None

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()


def uow_factory() -> SqlUnitOfWork:
    return SqlUnitOfWork()


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping(settings: Settings | None = None) -> bool:
    """¿Conecta la base de datos? Nada más. Para liveness."""
    from sqlalchemy import text

    try:
        with get_engine(settings).connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def schema_ready(settings: Settings | None = None) -> str | None:
    """¿Están las tablas? Devuelve el problema, o None si todo está en su sitio.

    `ping()` sólo prueba que el servidor acepta la conexión. Un PostgreSQL
    recién creado, sin migrar, responde `SELECT 1` perfectamente y luego
    devuelve 500 en cada consulta:

        relation "dim_geo" does not exist

    Con readiness mirando sólo el ping, el motor se declaraba listo y el
    proxy le enviaba tráfico. Comprobado en un entorno real: `/ready` decía
    «ok» mientras toda la geografía y todos los informes fallaban.
    """
    from sqlalchemy import inspect, text

    try:
        engine = get_engine(settings)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            tablas = set(inspect(conn).get_table_names())
    except Exception as exc:  # el ping ya reporta la conexión caída
        return f"no se pudo inspeccionar el esquema: {exc}"

    # Las mínimas para servir un informe. Si falta cualquiera, no hay nada
    # que servir y más vale decirlo antes de recibir tráfico.
    faltan = {"dim_geo", "dim_indicator", "fact_indicator", "project"} - tablas
    if faltan:
        return (
            "faltan tablas: " + ", ".join(sorted(faltan))
            + " — ejecuta las migraciones (alembic upgrade head)"
        )
    return None
