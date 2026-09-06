"""Caso de uso: ejecutar un informe.

Es lo que corre el worker. Cuatro propiedades que no son negociables:

* **Resumible**: `report_run.sections_done` permite que un fallo en
  «competencia» no tire abajo las cuatro secciones ya calculadas.
* **Incremental**: en un upgrade se reutiliza el snapshot anterior; la
  demografía del informe gratuito no se recalcula al pagar.
* **Perezoso con las fuentes**: si los indicadores del ámbito ya están
  frescos, no se toca ni una API externa. Ahí está todo el ahorro.
* **Honesto**: una sección sin datos se marca, no se inventa.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from ..domain import indicators as catalog_mod
from ..domain.enums import RunStatus, Section, Tier
from ..domain.errors import PowerGisError, ProjectNotFound
from ..domain.models import Project, Report, ReportRun
from ..domain.ports import CachePort, NotifierPort, UnitOfWork
from ..domain.report import ReportBuilder
from .context import build_context, indicators_for

log = logging.getLogger(__name__)

# Cada cuánto se considera caduco el dato de una fuente. El INE no es una API
# de tiempo real: es un catálogo que cambia una o dos veces al año.
FRESHNESS_DAYS: dict[str, int] = {
    "INE": 180,
    "OSM": 30,
    "AEMET": 365,
    "Catastro": 180,
    "derivado": 180,
    "estimación modelada": 180,
}
DEFAULT_FRESHNESS_DAYS = 90


@dataclass(slots=True)
class BuildResult:
    run: ReportRun
    report: Report | None
    version: int | None
    missing_indicators: list[str]
    notified: bool = False


class BuildReport:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        engine_version: str,
        *,
        cache: CachePort | None = None,
        notifier: NotifierPort | None = None,
        request_ingest: Callable[[list[str], str, str], None] | None = None,
        max_children: int = 8500,
        cache_ttl: int = 3600,
    ) -> None:
        self._uow_factory = uow_factory
        self._builder = ReportBuilder(engine_version)
        self._engine_version = engine_version
        self._cache = cache
        self._notifier = notifier
        self._request_ingest = request_ingest
        self._max_children = max_children
        self._cache_ttl = cache_ttl

    # ------------------------------------------------------------------ #

    def __call__(self, run_id: int, callback_url: str | None = None) -> BuildResult:
        with self._uow_factory() as uow:
            run = uow.runs.get(run_id)
            if run is None:
                raise PowerGisError("Ejecución no encontrada", run_id=run_id)
            project = uow.projects.get(run.project_uuid)
            if project is None:
                raise ProjectNotFound("Proyecto no encontrado", uuid=str(run.project_uuid))

            run.status = RunStatus.RUNNING
            run.started_at = datetime.now(UTC)
            uow.runs.update(run)
            uow.commit()

        try:
            result = self._execute(run, project)
        except Exception as exc:
            with self._uow_factory() as uow:
                run.status = RunStatus.FAILED
                run.finished_at = datetime.now(UTC)
                run.error = _error_payload(exc)
                uow.runs.update(run)
                uow.commit()
            self._notify(project, run, callback_url, version=None, error=run.error)
            raise

        self._notify(project, result.run, callback_url, version=result.version)
        result.notified = True
        return result

    # ------------------------------------------------------------------ #

    def _execute(self, run: ReportRun, project: Project) -> BuildResult:
        wanted = catalog_mod.sections_for_tier(run.tier)
        pending = run.pending(wanted) or wanted

        with self._uow_factory() as uow:
            # 1. ¿Hay que refrescar algo antes de calcular?
            missing = self._plan_ingest(uow, project, run.tier, pending)

            # 2. Contexto: geografías + hechos. A partir de aquí, dominio puro.
            ctx = build_context(
                uow, project, tier=run.tier, sections=wanted,
                max_children=self._max_children,
            )

            # 3. Snapshot anterior: base del upgrade incremental. El builder
            #    solo reutiliza secciones disponibles y del mismo motor; si la
            #    versión de motor cambió, se recalcula todo.
            previous = uow.snapshots.latest(project.project_uuid)
            reusable = None
            if previous and not run.error:
                _, _, payload_prev = previous
                if payload_prev.get("engine_version") == self._engine_version:
                    reusable = payload_prev

            version = uow.snapshots.next_version(project.project_uuid)

            report = self._builder.build(
                project, ctx, version=version, tier=run.tier,
                only=wanted, previous=reusable,
            )
            if missing:
                report.warnings.append(
                    f"{len(missing)} indicadores estaban caducos y se han encolado para "
                    "recarga; el informe se actualizará automáticamente."
                )

            payload = report.as_dict()
            uow.snapshots.save(project.project_uuid, version, run.tier, payload)

            for section in wanted:
                run.mark_section(section)
            covered = [s for s in report.sections if s.available and s.coverage > 0]
            run.status = RunStatus.DONE if covered else RunStatus.PARTIAL
            run.finished_at = datetime.now(UTC)
            uow.runs.update(run)
            uow.commit()

        self._cache_put(project, version, payload)
        return BuildResult(run=run, report=report, version=version, missing_indicators=missing)

    # ------------------------------------------------------------------ #

    def _plan_ingest(
        self,
        uow: UnitOfWork,
        project: Project,
        tier: Tier,
        sections: Sequence[Section],
    ) -> list[str]:
        """Devuelve los indicadores caducos y encola su recarga.

        Nunca bloquea el informe: se construye con lo que hay y el ETL corre
        por detrás. Un usuario no espera a que el INE conteste.
        """
        wanted = indicators_for(tier, sections)
        codes = [i.code for i in wanted]
        if not codes:
            return []

        try:
            resolved = uow.geos.get(project.scope.level, project.scope.ine_code)
            geo_ids = (
                [g.geo_id for g in uow.geos.descendants(
                    resolved.geo_id, project.scope.resolve_children_level()
                )]
                if resolved else []
            )
        except Exception:
            return []

        if not geo_ids:
            return []

        freshness = uow.facts.freshness(codes, geo_ids)
        today = date.today()
        stale: list[str] = []
        for ind in wanted:
            last = freshness.get(ind.code)
            limit = FRESHNESS_DAYS.get(ind.source.split(":")[0], DEFAULT_FRESHNESS_DAYS)
            if last is None or (today - last) > timedelta(days=limit):
                stale.append(ind.code)

        if stale and self._request_ingest is not None:
            self._request_ingest(
                stale,
                str(project.scope.resolve_children_level()),
                project.scope.ine_code,
            )
        return stale

    def _cache_put(self, project: Project, version: int, payload: dict) -> None:
        if self._cache is None:
            return
        try:
            self._cache.set(f"report:{project.project_uuid}", payload, self._cache_ttl)
            self._cache.set(f"report:{project.project_uuid}:{version}", payload, self._cache_ttl)
        except Exception as exc:
            log.debug("operación auxiliar falló: %s", exc)

    def _notify(
        self,
        project: Project,
        run: ReportRun,
        callback_url: str | None,
        version: int | None,
        error: dict | None = None,
    ) -> None:
        if self._notifier is None or not callback_url:
            return
        try:
            self._notifier.report_ready(
                callback_url=callback_url,
                project_uuid=project.project_uuid,
                tier=run.tier,
                version=version or 0,
                status=str(run.status),
                error=error,
            )
        except Exception as exc:
            log.debug("operación auxiliar falló: %s", exc)


def _error_payload(exc: Exception) -> dict:
    if isinstance(exc, PowerGisError):
        return exc.as_dict()
    return {"code": "internal_error", "message": str(exc)[:500], "context": {}}
