"""Endpoints de operación. Protegidos por clave interna, nunca públicos."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...adapters.collectors.registry import build_registry, coverage_report
from ...adapters.db.session import uow_factory
from ...application.dto import IngestIn
from ...domain import indicators as catalog_mod
from ..deps import require_internal_key

router = APIRouter(prefix="/internal", tags=["operación"],
                   dependencies=[Depends(require_internal_key)])


@router.post("/bootstrap")
def bootstrap(demo: bool = False) -> dict[str, Any]:
    """Carga geografías, perfiles de sector y catálogo. Idempotente.

    Existe porque hasta ahora la única forma de sembrar el almacén era
    `powergis seed` por shell dentro del contenedor. Si esa vía falla —y en
    Windows, entre `docker compose exec`, comillas y rutas, falla más de lo
    que parece— el sistema se queda con las tablas creadas y vacías, que es
    justo el estado en el que todo devuelve 404 sin decir por qué.

    Un sistema que hay que operar no debería depender de tener shell.

    `demo=true` añade además hechos SINTÉTICOS: sirven para ver el motor
    andando, nunca para enseñar un informe a un cliente.
    """
    from ...cli import load_demo_facts, load_geographies, load_sector_profiles

    resultado: dict[str, Any] = {}

    geos = load_geographies()
    resultado["geografias"] = geos["geos"]
    resultado["origen"] = geos["source"]

    resultado["perfiles_sector"] = load_sector_profiles()

    with uow_factory() as uow:
        resultado["indicadores"] = uow.indicators.upsert_many(catalog_mod.CATALOG)
        uow.commit()

    if demo:
        resultado["hechos_demo"] = load_demo_facts()
        resultado["aviso"] = (
            "Los hechos de demostración son SINTÉTICOS. No publiques un informe con ellos."
        )

    return resultado


@router.post("/ingest")
def trigger_ingest(payload: IngestIn) -> dict[str, Any]:
    """Encola una ingesta manual. Va a la cola `etl`, aislada de los informes."""
    from ...workers.tasks_etl import ingest_collector_task

    task = ingest_collector_task.apply_async(
        args=[payload.collector, payload.indicators, str(payload.level),
              payload.parent_code, payload.period],
        queue="etl",
    )
    return {"task_id": task.id, "queue": "etl", "collector": payload.collector}


@router.post("/catalog/sync")
def sync_catalog() -> dict[str, int]:
    """Vuelca el catálogo de indicadores del código a `dim_indicator`."""
    with uow_factory() as uow:
        written = uow.indicators.upsert_many(catalog_mod.CATALOG)
        uow.commit()
    return {"indicators": written}


@router.get("/coverage")
def coverage() -> dict[str, Any]:
    """Indicadores del catálogo sin colector. Se vigila en CI."""
    with uow_factory() as uow:
        registry = build_registry(session=uow.session)
        report = coverage_report(registry)
    return {
        "total": len(catalog_mod.CATALOG),
        "routed": len(report["routed"]),
        "orphans": report["orphans"],
    }


@router.get("/ine/discover/{table_id}")
def ine_discover(table_id: str) -> dict[str, Any]:
    """Variables y valores de una tabla del INE, para mapearla sin adivinar."""
    from ...adapters.collectors.ine import IneCollector

    collector = IneCollector()
    return {
        "metadata": collector.discover(table_id),
        "sample_series": collector.sample(table_id),
    }
