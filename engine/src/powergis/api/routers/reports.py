"""Endpoints de informes. El contrato con WordPress vive aquí."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from ...adapters.cache import get_cache
from ...adapters.db.session import uow_factory
from ...adapters.exports import get_exporter
from ...application.dto import (
    CreateReportIn,
    GeoLensQuery,
    RebalanceIn,
    RunOut,
    UpgradeIn,
    sections_catalog,
)
from ...application.upgrade_report import assert_tier
from ...config import get_settings
from ...domain.enums import Dimension, ScoreCategory, Tier
from ...domain.errors import ProjectNotFound, ReportNotReady
from ...domain.models import PlaceRankResult, PlaceRankRow
from ...domain.placerank import rebalance
from ..deps import (
    CreateReportDep,
    DowngradeReportDep,
    SignedBody,
    SignedGet,
    UpgradeReportDep,
    assert_owner,
    enforce_free_quota,
    idempotency_key,
    parse_signed_json,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/reports", tags=["informes"])


def _cuerpo_documentado(modelo: str) -> dict[str, Any]:
    """Declara el esquema del cuerpo para Swagger.

    Estos endpoints leen el cuerpo CRUDO (`SignedBody`), porque la firma se
    calcula sobre los bytes exactos que llegaron: si FastAPI deserializara y
    volviera a serializar, la firma dejaría de cuadrar. El precio es que
    FastAPI no sabe qué forma tiene el cuerpo y Swagger no dibuja el editor,
    así que desde /docs no se puede ni escribir la petición.

    `openapi_extra` recupera la documentación sin tocar cómo se lee el cuerpo.
    """
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": f"#/components/schemas/{modelo}"}
                }
            },
        }
    }



@router.post("", response_model=RunOut, status_code=202,
             openapi_extra=_cuerpo_documentado("CreateReportIn"))
def create_report(
    body: SignedBody,
    create: CreateReportDep,
    _idem: Annotated[str | None, Depends(idempotency_key)] = None,
) -> RunOut:
    """Crea (o reutiliza) una ejecución de informe.

    202 siempre: el informe se construye en cola. WordPress no espera aquí.
    """
    payload = CreateReportIn.model_validate(parse_signed_json(body))
    enforce_free_quota(payload.wp_user_id, str(payload.tier))

    result = create(payload)
    return RunOut(
        run_id=result.run.run_id,
        project_uuid=result.project.project_uuid,
        tier=result.run.tier,
        status=str(result.run.status),
        version=result.version,
        sections_done=result.run.sections_done,
        reused=not result.created,
        poll_after_seconds=2 if result.created else 0,
    )


@router.get("/{project_uuid}")
def get_report(
    _signed: SignedGet,
    project_uuid: UUID,
    wp_user_id: Annotated[int | None, Query()] = None,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    """Devuelve el payload del informe según el tier CONTRATADO.

    El tier se decide en el servidor con el estado del proyecto, nunca con lo
    que pida el cliente: es lo que impide que un `?tier=avanzado` desbloquee
    secciones de pago.
    """
    cache = get_cache()
    cache_key = f"report:{project_uuid}" + (f":{version}" if version else "")

    with uow_factory() as uow:
        project = uow.projects.get(project_uuid)
        if project is None:
            raise ProjectNotFound("Proyecto no encontrado", uuid=str(project_uuid))
        assert_owner(project.wp_user_id, wp_user_id)

        cached = cache.get(cache_key)
        payload = cached
        if payload is None:
            stored = (
                uow.snapshots.get(project_uuid, version)
                if version
                else (uow.snapshots.latest(project_uuid) or (None, None, None))[2]
            )
            if stored is None:
                run = uow.runs.latest_for(project_uuid)
                raise ReportNotReady(
                    "El informe todavía se está generando",
                    status=str(run.status) if run else "unknown",
                )
            payload = stored
            cache.set(cache_key, payload, get_settings().report_cache_ttl)

        granted = project.tier

    return _enforce_tier(payload, granted)


@router.post("/{project_uuid}/upgrade", response_model=RunOut, status_code=202,
             openapi_extra=_cuerpo_documentado("UpgradeIn"))
def upgrade_report(
    project_uuid: UUID,
    body: SignedBody,
    upgrade: UpgradeReportDep,
) -> RunOut:
    """Promueve el informe a avanzado. Lo dispara el webhook de Stripe.

    Nunca se llama desde `success_url`: esa URL la puede visitar cualquiera sin
    haber pagado.
    """
    payload = UpgradeIn.model_validate(parse_signed_json(body))
    result = upgrade(project_uuid, payload)
    get_cache().delete_prefix(f"report:{project_uuid}")
    return RunOut(
        run_id=result.run.run_id,
        project_uuid=project_uuid,
        tier=Tier.AVANZADO,
        status=str(result.run.status),
        sections_done=result.reused_sections,
        reused=result.already_advanced,
    )


@router.post("/{project_uuid}/downgrade", status_code=200)
def downgrade_report(
    project_uuid: UUID,
    body: SignedBody,
    downgrade: DowngradeReportDep,
) -> dict[str, Any]:
    """Reembolso o disputa: se retira el acceso a las secciones de pago."""
    parse_signed_json(body)
    downgrade(project_uuid)
    return {"project_uuid": str(project_uuid), "tier": str(Tier.BASICO)}


@router.post("/{project_uuid}/placerank/rebalance",
             openapi_extra=_cuerpo_documentado("RebalanceIn"))
def rebalance_placerank(
    project_uuid: UUID,
    body: SignedBody,
    wp_user_id: Annotated[int | None, Query()] = None,
) -> dict[str, Any]:
    """Recalcula el ranking con pesos nuevos SIN tocar la base de datos.

    Es lo que permite mover los pesos en la UI y ver el ranking actualizarse
    al instante: las dimensiones ya están calculadas en el snapshot.

    VA FIRMADO, y no es opcional. Devuelve el PlaceRank entero —zonas, puntos,
    dimensiones y contribuciones—, que es producto de pago. Sin firma bastaba
    conocer un UUID para leerlo: `assert_owner` se salta la comprobación
    cuando `wp_user_id` viene vacío, precisamente porque da por hecho que la
    firma ya ha autenticado la llamada. Aquí no había firma, así que la
    segunda barrera estaba defendiendo una puerta abierta.
    """
    weights = RebalanceIn.model_validate(parse_signed_json(body))
    with uow_factory() as uow:
        project = uow.projects.get(project_uuid)
        if project is None:
            raise ProjectNotFound("Proyecto no encontrado", uuid=str(project_uuid))
        assert_owner(project.wp_user_id, wp_user_id)
        assert_tier(Tier.AVANZADO, project.tier)
        latest = uow.snapshots.latest(project_uuid)

    if latest is None or not (latest[2] or {}).get("placerank"):
        raise ReportNotReady("El PlaceRank aún no está calculado")

    stored = latest[2]["placerank"]
    result = PlaceRankResult(
        weights={Dimension(k): v for k, v in stored.get("weights", {}).items()},
        rows=[
            PlaceRankRow(
                geo_code=r["geo_code"],
                geo_name=r["geo_name"],
                score=r["score"],
                category=ScoreCategory(r["category"]),
                dimensions={Dimension(k): v for k, v in r.get("dimensions", {}).items()},
                contributions=r.get("contributions", {}),
                narrative=r.get("narrative"),
                rank=r.get("rank", 0),
            )
            for r in stored.get("rows", [])
        ],
        method=stored.get("method", ""),
    )
    updated = rebalance(result, {
        Dimension.ECONOMICO: weights.economico,
        Dimension.DEMOGRAFICO: weights.demografico,
        Dimension.AMBIENTAL: weights.ambiental,
        Dimension.MATCH: weights.match,
    })
    return updated.as_dict()


@router.post("/{project_uuid}/geolens",
             openapi_extra=_cuerpo_documentado("GeoLensQuery"))
def geolens(
    project_uuid: UUID,
    body: SignedBody,
    wp_user_id: Annotated[int | None, Query()] = None,
) -> dict[str, Any]:
    """Capas del mapa. Los valores viajan aquí; las geometrías, en las teselas."""
    query = GeoLensQuery.model_validate(parse_signed_json(body))
    with uow_factory() as uow:
        project = uow.projects.get(project_uuid)
        if project is None:
            raise ProjectNotFound("Proyecto no encontrado", uuid=str(project_uuid))
        assert_owner(project.wp_user_id, wp_user_id)
        latest = uow.snapshots.latest(project_uuid)

    if latest is None:
        raise ReportNotReady("El informe todavía se está generando")

    payload = latest[2].get("geolens", {})
    if query.indicators:
        wanted = set(query.indicators)
        payload = {
            **payload,
            "layers": [layer for layer in payload.get("layers", []) if layer["id"] in wanted],
        }
    return payload


@router.get("/{project_uuid}/export/{kind}")
def export_report(
    _signed: SignedGet,
    project_uuid: UUID,
    kind: str,
    wp_user_id: Annotated[int | None, Query()] = None,
) -> Response:
    """Exporta el informe a xlsx | pdf | pptx."""
    from ...domain.report import ReportBuilder  # noqa: F401  (documenta el origen)

    with uow_factory() as uow:
        project = uow.projects.get(project_uuid)
        if project is None:
            raise ProjectNotFound("Proyecto no encontrado", uuid=str(project_uuid))
        assert_owner(project.wp_user_id, wp_user_id)
        latest = uow.snapshots.latest(project_uuid)
        granted = project.tier

    if latest is None:
        raise ReportNotReady("El informe todavía se está generando")

    payload = _enforce_tier(latest[2], granted)
    exporter = get_exporter(kind)
    report = _rehydrate(payload)
    content = exporter.render(report)
    filename = f"powergis-{payload['scope'].get('code', '')}-v{payload['version']}.{exporter.extension}"
    return Response(
        content=content,
        media_type=exporter.media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/catalog/{tier}")
def catalog(tier: Tier) -> dict[str, Any]:
    """Qué secciones e indicadores incluye cada nivel. Alimenta la web comercial."""
    return sections_catalog(tier).model_dump()


# --------------------------------------------------------------------------- #


def _enforce_tier(payload: dict[str, Any], granted: Tier) -> dict[str, Any]:
    """Recorta el payload al tier realmente contratado.

    Defensa en profundidad: aunque un snapshot avanzado quedara en caché tras
    un reembolso, aquí se vuelve a filtrar. Las secciones bloqueadas se
    devuelven SIN datos dentro, nunca ocultas con CSS.
    """
    allowed = {str(t) for t in granted.includes}
    from ...domain import indicators as catalog_mod

    visible = {str(s) for s in catalog_mod.sections_for_tier(granted)}
    sections = []
    for section in payload.get("sections", []):
        if section.get("id") in visible and section.get("available"):
            sections.append(section)
        else:
            sections.append({
                "id": section.get("id"),
                "title": section.get("title"),
                "available": False,
                "locked_reason": "tier",
            })

    out = dict(payload)
    out["sections"] = sections
    out["tier"] = str(granted)
    if granted is not Tier.AVANZADO:
        out["placerank"] = None
        out["geolens"] = _filter_layers(payload.get("geolens", {}), allowed)
        summary = dict(out.get("executive_summary") or {})
        summary.pop("dimension_weights", None)
        out["executive_summary"] = summary or None
    return out


def _filter_layers(geolens: dict[str, Any], allowed_tiers: set[str]) -> dict[str, Any]:
    from ...domain import indicators as catalog_mod

    layers = [
        layer for layer in geolens.get("layers", [])
        if str(getattr(catalog_mod.BY_CODE.get(layer.get("indicator", "")), "tier", "avanzado"))
        in allowed_tiers
    ]
    return {**geolens, "layers": layers}


def _rehydrate(payload: dict[str, Any]):
    """Reconstruye un `Report` desde el snapshot para los exportadores."""
    from datetime import datetime

    from ...domain import enums as _e
    from ...domain.models import Report
    from ...domain.report import _section_from_dict

    sections = []
    for raw in payload.get("sections", []):
        try:
            section = _e.Section(raw["id"])
        except (ValueError, KeyError):
            continue
        if raw.get("available"):
            sections.append(_section_from_dict(raw, section))
        else:
            from ...domain.models import SectionResult

            sections.append(SectionResult(
                id=section, title=raw.get("title", ""), available=False,
                locked_reason=raw.get("locked_reason", "tier"),
            ))

    return Report(
        project_uuid=UUID(payload["project_uuid"]),
        tier=_e.Tier(payload["tier"]),
        version=payload["version"],
        engine_version=payload["engine_version"],
        generated_at=datetime.fromisoformat(payload["generated_at"]),
        scope=payload.get("scope", {}),
        segments=payload.get("segments", {}),
        business=payload.get("business", {}),
        sections=sections,
        geolens=payload.get("geolens", {}),
        placerank=payload.get("placerank"),
        executive_summary=payload.get("executive_summary"),
        glossary=payload.get("glossary", []),
        sources=payload.get("sources", []),
        warnings=payload.get("warnings", []),
    )
