"""Configuración de Celery.

**Colas separadas.** Es la decisión más importante de este fichero: una carga
masiva del INE no puede dejar a un cliente esperando su informe.

    reports.basic     informes gratuitos       — rápido, muchos workers
    reports.advanced  informes de pago         — prioritario
    etl               ingesta de fuentes       — concurrencia 1, de madrugada
    narrative         textos de IA             — nunca bloquea la publicación
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging as celery_setup_logging

from ..config import get_settings

cfg = get_settings()

app = Celery("powergis", broker=cfg.celery_broker_url, backend=cfg.celery_result_backend)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Madrid",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,                 # si el worker muere, la tarea se reintenta
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,        # sin acaparar tareas largas
    worker_max_tasks_per_child=200,      # recicla procesos: pandas fragmenta memoria
    result_expires=60 * 60 * 24,
    broker_transport_options={"visibility_timeout": 3600},
    task_default_queue="reports.basic",
    task_routes={
        "powergis.reports.build": {"queue": "reports.basic"},
        "powergis.reports.build_advanced": {"queue": "reports.advanced"},
        "powergis.etl.*": {"queue": "etl"},
        "powergis.narrative.*": {"queue": "narrative"},
    },
    task_annotations={
        "powergis.etl.*": {"rate_limit": "30/m"},
    },
    beat_schedule={
        # El INE cambia una o dos veces al año: mensual sobra y va de madrugada.
        "ine-mensual": {
            "task": "powergis.etl.refresh_source",
            "schedule": crontab(hour=3, minute=15, day_of_month="5"),
            "args": ("ine",),
            "options": {"queue": "etl"},
        },
        "adrh-mensual": {
            "task": "powergis.etl.refresh_source",
            "schedule": crontab(hour=4, minute=0, day_of_month="6"),
            "args": ("ine_adrh",),
            "options": {"queue": "etl"},
        },
        # OSM cambia a diario; semanal es el equilibrio razonable.
        "osm-semanal": {
            "task": "powergis.etl.refresh_source",
            "schedule": crontab(hour=2, minute=30, day_of_week="sunday"),
            "args": ("osm",),
            "options": {"queue": "etl"},
        },
        # Las normales climatológicas son de 30 años: una vez al año basta.
        "aemet-anual": {
            "task": "powergis.etl.refresh_source",
            "schedule": crontab(hour=5, minute=0, day_of_month="1", month_of_year="2"),
            "args": ("aemet",),
            "options": {"queue": "etl"},
        },
        "derivados-diario": {
            "task": "powergis.etl.compute_derived",
            "schedule": crontab(hour=6, minute=0),
            "options": {"queue": "etl"},
        },
        "reintentar-fallidos": {
            "task": "powergis.reports.retry_failed",
            "schedule": crontab(minute="*/20"),
            "options": {"queue": "reports.basic"},
        },
    },
)

app.autodiscover_tasks(
    ["powergis.workers.tasks_reports", "powergis.workers.tasks_etl",
     "powergis.workers.tasks_narrative"],
    force=True,
)


@celery_setup_logging.connect
def _configure_logging(**_kwargs):
    from ..logging_setup import setup_logging

    setup_logging(cfg.log_level, cfg.log_json)
