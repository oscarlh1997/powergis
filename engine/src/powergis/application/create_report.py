"""Caso de uso: crear una ejecución de informe.

Idempotente por diseño. El doble submit del formulario, el reintento de
WordPress y el reenvío de un webhook devuelven la MISMA ejecución en lugar de
duplicar trabajo.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from ..domain.enums import RunStatus, Tier
from ..domain.models import Project, ReportRun
from ..domain.ports import UnitOfWork
from .dto import CreateReportIn


@dataclass(slots=True)
class CreateResult:
    run: ReportRun
    project: Project
    created: bool          # False si se reutilizó una ejecución existente
    version: int | None    # versión ya disponible, si la hay


class CreateReport:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        engine_version: str,
        enqueue: Callable[[int, str], None],
    ) -> None:
        self._uow_factory = uow_factory
        self._engine_version = engine_version
        self._enqueue = enqueue

    def __call__(self, payload: CreateReportIn) -> CreateResult:
        project = Project(
            project_uuid=payload.project_uuid,
            wp_user_id=payload.wp_user_id,
            wp_post_id=payload.wp_post_id,
            scope=payload.scope.to_domain(),
            segments=payload.segments.to_domain(),
            business=payload.business.to_domain(),
            target=payload.target.to_domain(),
            tier=payload.tier,
            created_at=datetime.now(UTC),
        )
        input_hash = project.input_hash(payload.tier)

        with self._uow_factory() as uow:
            stored = uow.projects.get(project.project_uuid)
            if stored is None:
                stored = uow.projects.save(project)
            else:
                # El proyecto ya existe: se respeta el tier más alto alcanzado.
                if payload.tier is Tier.AVANZADO and stored.tier is Tier.BASICO:
                    uow.projects.set_tier(stored.project_uuid, Tier.AVANZADO)
                    stored.tier = Tier.AVANZADO

            if not payload.force:
                existing = uow.runs.find_by_hash(stored.project_uuid, input_hash)
                if existing is not None and existing.status is not RunStatus.FAILED:
                    snapshot = uow.snapshots.latest(stored.project_uuid)
                    uow.commit()
                    return CreateResult(
                        run=existing,
                        project=stored,
                        created=False,
                        version=snapshot[0] if snapshot else None,
                    )

            run = uow.runs.create(
                ReportRun(
                    run_id=None,
                    project_uuid=stored.project_uuid,
                    tier=payload.tier,
                    status=RunStatus.QUEUED,
                    engine_version=self._engine_version,
                    input_hash=input_hash,
                )
            )
            uow.commit()

        queue = "reports.advanced" if payload.tier is Tier.AVANZADO else "reports.basic"
        self._enqueue(run.run_id, queue)  # type: ignore[arg-type]
        return CreateResult(run=run, project=stored, created=True, version=None)


def idempotency_key(project_uuid: UUID, input_hash: str) -> str:
    return f"idem:{project_uuid}:{input_hash}"
