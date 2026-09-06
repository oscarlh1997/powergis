"""Generación de textos. Cola aparte: nunca bloquea la publicación."""

from __future__ import annotations

import logging

from celery import shared_task

from ..adapters.cache import get_cache
from ..adapters.db.session import uow_factory
from ..adapters.llm.narrative import NarrativeService
from ..adapters.wordpress import WordPressNotifier
from ..config import get_settings
from ..domain import indicators as catalog_mod
from ..domain.enums import Dimension, ScoreCategory
from ..domain.models import PlaceRankRow
from ..domain.placerank import explain

log = logging.getLogger(__name__)

MAX_ZONES = 10  # se describen las zonas relevantes, no las 8.000


@shared_task(name="powergis.narrative.generate", bind=True, max_retries=2, default_retry_delay=60)
def generate_narrative_task(self, project_uuid: str, version: int) -> dict:
    """Escribe los textos y los inyecta en el snapshot ya publicado.

    Si algo falla, el informe sigue siendo válido: las plantillas
    deterministas ya rellenaron el hueco.
    """
    from uuid import UUID

    cfg = get_settings()
    service = NarrativeService(cache=get_cache())
    uid = UUID(project_uuid)

    with uow_factory() as uow:
        payload = uow.snapshots.get(uid, version)
        if payload is None:
            return {"project_uuid": project_uuid, "status": "snapshot_missing"}

        placerank = payload.get("placerank") or {}
        rows = placerank.get("rows", [])[:MAX_ZONES]
        catalog = catalog_mod.BY_CODE

        written = 0
        for raw in rows:
            row = PlaceRankRow(
                geo_code=raw["geo_code"], geo_name=raw["geo_name"], score=raw["score"],
                category=ScoreCategory(raw["category"]),
                dimensions={Dimension(k): v for k, v in raw.get("dimensions", {}).items()},
                contributions=raw.get("contributions", {}), rank=raw.get("rank", 0),
            )
            facts = explain(row, catalog)
            try:
                result = service.zone_full(facts)
            except Exception as exc:
                log.warning("Narrativa de %s falló: %s", row.geo_name, exc)
                continue
            raw["narrative"] = result.get("resumen")
            raw["fortalezas"] = result.get("fortalezas", [])
            raw["riesgos"] = result.get("riesgos", [])
            written += 1

        summary = payload.get("executive_summary") or {}
        summary_facts = {
            "ambito": payload.get("scope", {}).get("name"),
            "zonas_comparadas": payload.get("scope", {}).get("children_count"),
            "sector": payload.get("business", {}).get("sector"),
            "headline": summary.get("headline", []),
            "mejores_zonas": summary.get("mejores_zonas", []),
            "peores_zonas": summary.get("peores_zonas", []),
            "cobertura": summary.get("cobertura", {}),
            "cobertura_baja": any(v < 0.5 for v in (summary.get("cobertura") or {}).values()),
        }
        try:
            summary["narrative"] = service.executive_summary(summary_facts)
        except Exception as exc:
            log.warning("Resumen ejecutivo falló: %s", exc)

        payload["executive_summary"] = summary
        payload["placerank"] = placerank
        uow.snapshots.save(uid, version, payload_tier(payload), payload)
        uow.commit()

    get_cache().delete_prefix(f"report:{project_uuid}")
    WordPressNotifier().narrative_ready(cfg.callback_url, uid, version)
    return {"project_uuid": project_uuid, "version": version, "zones": written}


def payload_tier(payload: dict):
    from ..domain.enums import Tier

    return Tier(payload.get("tier", "avanzado"))
