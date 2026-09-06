"""Tareas de ingesta. Cola `etl`, concurrencia 1, de madrugada."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from celery import shared_task

from ..adapters.collectors.registry import build_registry
from ..adapters.db.orm import IngestLogRow
from ..adapters.db.session import uow_factory
from ..application.ingest import ComputeDerived, IngestData
from ..domain.enums import GeoLevel
from ..domain.errors import CollectorUnavailable

log = logging.getLogger(__name__)


def _facts_lookup_factory(uow, geo_ids: list[int]):
    """Cache en memoria de los hechos ya cargados, para los derivados."""
    from ..domain import indicators as catalog_mod

    codes = [i.code for i in catalog_mod.CATALOG]
    facts = uow.facts.fetch(geo_ids, codes, [{}])
    index = {(f.geo_id, f.indicator): f.value for f in facts}
    return lambda geo_id, code: index.get((geo_id, code))


@shared_task(
    name="powergis.etl.ingest_collector",
    bind=True,
    max_retries=5,
    autoretry_for=(CollectorUnavailable,),
    retry_backoff=30,
    retry_backoff_max=900,
    retry_jitter=True,
)
def ingest_collector_task(
    self,
    collector: str,
    indicators: list[str] | None = None,
    level: str = "municipio",
    parent_code: str | None = None,
    period: str | None = None,
) -> dict:
    started = datetime.now(UTC)
    with uow_factory() as uow:
        registry = build_registry(session=uow.session)
        service = IngestData(uow_factory, registry)
        report = service.by_collector(
            collector, indicators or [], GeoLevel(level), parent_code,
            date.fromisoformat(period) if period and len(period) == 10 else None,
        )
        uow.session.add(IngestLogRow(
            collector=collector, level=level, parent_code=parent_code,
            indicators=report.requested, written=report.written,
            errors={"errors": report.errors} if report.errors else None,
            started_at=started, finished_at=datetime.now(UTC),
        ))
        uow.commit()

    log.info("ETL %s: %s hechos escritos", collector, report.written)
    return report.as_dict()


@shared_task(name="powergis.etl.ingest_indicators", bind=True, max_retries=3)
def ingest_indicators_task(
    self,
    indicators: list[str],
    level: str = "municipio",
    parent_code: str | None = None,
) -> dict:
    """Enruta cada indicador a su colector. Lo dispara el planificador del informe."""
    with uow_factory() as uow:
        registry = build_registry(session=uow.session)
        service = IngestData(uow_factory, registry)
        plan = service.plan(indicators)
        orphans = service.unroutable(indicators)

    for collector, codes in plan.items():
        ingest_collector_task.apply_async(
            args=[collector, codes, level, parent_code], queue="etl"
        )
    if orphans:
        # Silenciar esto sería mentir sobre la cobertura del informe.
        log.warning("Indicadores sin colector asignado: %s", orphans)
    return {"plan": {k: len(v) for k, v in plan.items()}, "orphans": orphans}


@shared_task(name="powergis.etl.refresh_source")
def refresh_source_task(collector: str, level: str = "municipio") -> dict:
    """Refresco programado completo de una fuente (Celery beat)."""
    with uow_factory() as uow:
        registry = build_registry(session=uow.session)
        codes = registry[collector].provides() if collector in registry else []
    if not codes:
        return {"collector": collector, "skipped": True}
    ingest_collector_task.apply_async(args=[collector, codes, level, None], queue="etl")
    return {"collector": collector, "indicators": len(codes)}


@shared_task(name="powergis.etl.compute_derived")
def compute_derived_task(level: str = "municipio", parent_code: str | None = None) -> dict:
    """Recalcula los indicadores derivados sobre lo ya cargado."""
    written = ComputeDerived(uow_factory)(GeoLevel(level), parent_code)
    log.info("Derivados: %s hechos escritos", written)
    return {"written": written, "level": level}


@shared_task(name="powergis.etl.load_geographies")
def load_geographies_task(path: str | None = None) -> dict:
    """Carga dim_geo desde el fichero de geografías del IGN/INE."""
    from ..cli import load_geographies

    return load_geographies(path)
