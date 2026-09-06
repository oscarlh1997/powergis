"""Tareas de generación de informes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from celery import shared_task

from ..adapters.cache import get_cache
from ..adapters.db.session import uow_factory
from ..adapters.wordpress import WordPressNotifier
from ..application.build_report import BuildReport
from ..config import get_settings
from ..domain.enums import RunStatus, Tier
from ..domain.errors import CollectorUnavailable, PowerGisError

log = logging.getLogger(__name__)


def _build_report_service() -> BuildReport:
    cfg = get_settings()

    def request_ingest(indicators: list[str], level: str, parent_code: str) -> None:
        from .tasks_etl import ingest_indicators_task

        ingest_indicators_task.apply_async(
            args=[indicators, level, parent_code], queue="etl"
        )

    return BuildReport(
        uow_factory,
        cfg.engine_version,
        cache=get_cache(),
        notifier=WordPressNotifier(),
        request_ingest=request_ingest,
        max_children=cfg.max_children,
        cache_ttl=cfg.report_cache_ttl,
    )


@shared_task(
    name="powergis.reports.build",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(CollectorUnavailable,),
    retry_backoff=True,
    retry_jitter=True,
)
def build_report_task(self, run_id: int, callback_url: str | None = None) -> dict:
    """Construye un informe.

    Un lock por proyecto evita que dos workers calculen lo mismo si WordPress
    reintenta el POST mientras el primero sigue en marcha.
    """
    cache = get_cache()
    cfg = get_settings()

    with uow_factory() as uow:
        run = uow.runs.get(run_id)
        if run is None:
            log.warning("Ejecución %s no encontrada", run_id)
            return {"run_id": run_id, "status": "missing"}
        project_uuid = str(run.project_uuid)

    lock_key = f"build:{project_uuid}"
    if not cache.lock(lock_key, ttl_seconds=900):
        log.info("Informe %s ya se está construyendo; se omite el duplicado", project_uuid)
        return {"run_id": run_id, "status": "locked"}

    try:
        service = _build_report_service()
        result = service(run_id, callback_url or cfg.callback_url)

        # La narrativa va aparte: el informe se publica sin esperar al LLM.
        if result.report and result.run.tier is Tier.AVANZADO:
            from .tasks_narrative import generate_narrative_task

            generate_narrative_task.apply_async(
                args=[project_uuid, result.version], queue="narrative"
            )

        return {
            "run_id": run_id,
            "status": str(result.run.status),
            "version": result.version,
            "missing_indicators": len(result.missing_indicators),
        }
    except PowerGisError as exc:
        log.error("Informe %s falló: %s", project_uuid, exc.message, extra=exc.context)
        raise
    finally:
        cache.unlock(lock_key)


@shared_task(name="powergis.reports.build_advanced", bind=True, max_retries=3)
def build_advanced_task(self, run_id: int, callback_url: str | None = None) -> dict:
    """Alias en la cola prioritaria. Los que pagan no hacen cola detrás."""
    return build_report_task(run_id, callback_url)


@shared_task(name="powergis.reports.retry_failed")
def retry_failed_task(max_age_minutes: int = 120, limit: int = 20) -> dict:
    """Reencola ejecuciones colgadas.

    Cubre el caso feo: worker muerto a mitad de trabajo, con la ejecución en
    RUNNING para siempre. Sin esto, el usuario ve «generando» eternamente.
    """
    from sqlalchemy import select

    from ..adapters.db.orm import RunRow

    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    requeued: list[int] = []

    with uow_factory() as uow:
        rows = uow.session.scalars(
            select(RunRow)
            .where(
                RunRow.status.in_([str(RunStatus.QUEUED), str(RunStatus.RUNNING)]),
                RunRow.created_at < cutoff,
            )
            .limit(limit)
        ).all()
        for row in rows:
            queue = "reports.advanced" if row.tier == str(Tier.AVANZADO) else "reports.basic"
            build_report_task.apply_async(args=[row.run_id], queue=queue)
            requeued.append(row.run_id)
        uow.commit()

    if requeued:
        log.info("Reencoladas %s ejecuciones colgadas: %s", len(requeued), requeued)
    return {"requeued": requeued}


@shared_task(name="powergis.reports.invalidate_cache")
def invalidate_cache_task(project_uuid: str) -> dict:
    deleted = get_cache().delete_prefix(f"report:{project_uuid}")
    return {"project_uuid": project_uuid, "deleted": deleted}
