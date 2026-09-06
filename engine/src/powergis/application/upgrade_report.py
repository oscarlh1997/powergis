"""Caso de uso: promover un informe de básico a avanzado.

Ésta es la respuesta a «¿genero todo y oculto, o hago dos llamadas?»:
**ninguna de las dos**. Un solo job, dos perfiles de ejecución, acumulativo
sobre el mismo `project_uuid`.

    run #1  perfil BASIC     → [demografía]                    → snapshot v1
    [Stripe webhook]
    run #2  perfil ADVANCED  → reutiliza demografía            → snapshot v2
                             + [socioeconómico, competencia,
                                clima, tráfico, GeoLens,
                                PlaceRank, IA]

Nunca se envía contenido de pago al navegador para ocultarlo con CSS: las
secciones bloqueadas viajan con `available: false` y sin datos dentro.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from ..domain.enums import RunStatus, Tier
from ..domain.errors import ProjectNotFound, TierNotAllowed
from ..domain.models import ReportRun
from ..domain.ports import UnitOfWork
from .dto import UpgradeIn


@dataclass(slots=True)
class UpgradeResult:
    run: ReportRun
    already_advanced: bool
    reused_sections: list[str]


class UpgradeReport:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        engine_version: str,
        enqueue: Callable[[int, str], None],
    ) -> None:
        self._uow_factory = uow_factory
        self._engine_version = engine_version
        self._enqueue = enqueue

    def __call__(self, project_uuid: UUID, payload: UpgradeIn | None = None) -> UpgradeResult:
        payload = payload or UpgradeIn()

        with self._uow_factory() as uow:
            project = uow.projects.get(project_uuid)
            if project is None:
                raise ProjectNotFound("Proyecto no encontrado", uuid=str(project_uuid))

            latest = uow.snapshots.latest(project_uuid)
            if latest and latest[1] is Tier.AVANZADO and not payload.force_refresh:
                run = uow.runs.latest_for(project_uuid)
                if run and run.status is RunStatus.DONE:
                    uow.commit()
                    return UpgradeResult(run=run, already_advanced=True, reused_sections=[])

            # El tier sube en la base de datos ANTES de encolar: si el worker
            # tarda, el usuario ya consta como avanzado y `GET /reports` no
            # le devuelve un 403.
            uow.projects.set_tier(project_uuid, Tier.AVANZADO)
            project.tier = Tier.AVANZADO

            reused = _sections_in(latest[2]) if latest else []

            run = uow.runs.create(
                ReportRun(
                    run_id=None,
                    project_uuid=project_uuid,
                    tier=Tier.AVANZADO,
                    status=RunStatus.QUEUED,
                    engine_version=self._engine_version,
                    input_hash=project.input_hash(Tier.AVANZADO),
                    sections_done=[],  # se recalcula lo que falte; el builder reutiliza
                )
            )
            uow.commit()

        self._enqueue(run.run_id, "reports.advanced")  # type: ignore[arg-type]
        return UpgradeResult(run=run, already_advanced=False, reused_sections=reused)


class DowngradeReport:
    """Reembolso o disputa: se baja el tier y se invalida el snapshot avanzado.

    No se borra el histórico (hay que poder auditar qué se entregó), pero
    `GET /reports` deja de servir las secciones de pago.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork], cache=None) -> None:
        self._uow_factory = uow_factory
        self._cache = cache

    def __call__(self, project_uuid: UUID) -> bool:
        with self._uow_factory() as uow:
            project = uow.projects.get(project_uuid)
            if project is None:
                raise ProjectNotFound("Proyecto no encontrado", uuid=str(project_uuid))
            uow.projects.set_tier(project_uuid, Tier.BASICO)
            uow.commit()
        if self._cache is not None:
            try:
                self._cache.delete(f"report:{project_uuid}")
            except Exception as exc:
                logging.getLogger(__name__).debug("operación auxiliar falló: %s", exc)
        return True


def assert_tier(requested: Tier, granted: Tier) -> None:
    if requested not in granted.includes:
        raise TierNotAllowed(
            "El proyecto no tiene contratado ese nivel de informe",
            requested=str(requested),
            granted=str(granted),
        )


def _sections_in(payload: dict) -> list[str]:
    return [s["id"] for s in payload.get("sections", []) if s.get("available")]
