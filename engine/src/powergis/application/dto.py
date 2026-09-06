"""Contratos de entrada y salida de la API (Pydantic v2).

Aquí y solo aquí se valida lo que llega de fuera. El dominio recibe objetos ya
sanos; si algo no cumple, nunca llega al motor.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..domain.enums import BreakMethod, GeoLevel, Section, Tier
from ..domain.models import BusinessProfile, Scope, Segments
from ..domain.target import TargetProfile

_AGE_RE = re.compile(r"^\d{1,3}(-\d{1,3}|\+)?$")
_INE_RE = re.compile(r"^\d{2,10}$")


class ScopeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: GeoLevel
    ine_code: str = Field(min_length=1, max_length=10)
    children_level: GeoLevel | None = None

    @field_validator("ine_code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip()
        if v.lower() == "es":
            return "ES"
        if not _INE_RE.match(v):
            raise ValueError("ine_code debe ser numérico (código INE) o 'ES' para nacional")
        return v

    @model_validator(mode="after")
    def _coherent(self) -> ScopeIn:
        if self.children_level and not self.level.contains(self.children_level):
            raise ValueError(
                f"children_level ({self.children_level}) debe estar por debajo de level ({self.level})"
            )
        if self.children_level is None and self.level.child is None:
            raise ValueError(f"El nivel {self.level} no admite desagregación")
        return self

    def to_domain(self) -> Scope:
        return Scope(level=self.level, ine_code=self.ine_code, children_level=self.children_level)


class SegmentsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age: list[str] = Field(default_factory=list, max_length=12)
    sex: list[Literal["F", "M"]] = Field(default_factory=list, max_length=2)
    nationality: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("age")
    @classmethod
    def _ages(cls, v: list[str]) -> list[str]:
        for item in v:
            if not _AGE_RE.match(item.strip()):
                raise ValueError(f"Rango de edad inválido: {item!r}. Formato: '18-35' o '65+'")
        return [i.strip() for i in v]

    def to_domain(self) -> Segments:
        return Segments.from_mapping(self.model_dump())


class BusinessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sector: str | None = Field(default=None, max_length=64)
    avg_ticket: float | None = Field(default=None, ge=0, le=1_000_000)
    surface_m2: float | None = Field(default=None, ge=0, le=1_000_000)
    horizon_months: int | None = Field(default=None, ge=1, le=240)
    company_name: str | None = Field(default=None, max_length=200)
    candidate_address: str | None = Field(default=None, max_length=300)

    def to_domain(self) -> BusinessProfile:
        return BusinessProfile(**self.model_dump())


class TargetIn(BaseModel):
    """Perfil de cliente objetivo.

    Los nombres son los del formulario de powergis.es
    (`/crear-proyecto-geolocalizado/`). Todo es opcional: «indiferente» se
    manda como cadena vacía o simplemente no se manda.
    """

    model_config = ConfigDict(extra="forbid")

    age_range: list[str] = Field(default_factory=list, max_length=12)
    gender: str | None = Field(default=None, max_length=32)
    family_status: str | None = Field(default=None, max_length=48)
    education_level: str | None = Field(default=None, max_length=48)
    nationality: str | None = Field(default=None, max_length=64)
    nse: list[str] = Field(default_factory=list, max_length=8)
    annual_income: str | None = Field(default=None, max_length=32)
    monthly_available_income: str | None = Field(default=None, max_length=32)
    average_ticket: str | None = Field(default=None, max_length=32)
    climate: list[str] = Field(default_factory=list, max_length=8)
    pedestrian_traffic: str | None = Field(default=None, max_length=32)
    vehicular_traffic: str | None = Field(default=None, max_length=32)
    traffic_generators_high: list[str] = Field(default_factory=list, max_length=30)
    traffic_generators_medium: list[str] = Field(default_factory=list, max_length=30)
    direct_competition: bool | None = None

    def to_domain(self) -> TargetProfile:
        return TargetProfile.from_mapping(self.model_dump())


class CreateReportIn(BaseModel):
    """Cuerpo de POST /v1/reports."""

    model_config = ConfigDict(extra="forbid")

    project_uuid: UUID
    wp_user_id: int = Field(ge=1)
    wp_post_id: int | None = Field(default=None, ge=1)
    tier: Tier = Tier.BASICO
    scope: ScopeIn
    segments: SegmentsIn = Field(default_factory=SegmentsIn)
    business: BusinessIn = Field(default_factory=BusinessIn)
    target: TargetIn = Field(default_factory=TargetIn)
    callback_url: str | None = Field(default=None, max_length=500)
    force: bool = False

    @field_validator("callback_url")
    @classmethod
    def _https(cls, v: str | None) -> str | None:
        """En producción, solo https.

        En desarrollo se admite http porque WordPress y el motor se hablan por
        la red interna de Docker (`http://wordpress/wp-json/...`), donde no hay
        —ni tiene sentido que haya— certificado.
        """
        if not v:
            return v
        from ..config import get_settings

        if v.startswith("https://"):
            return v
        if v.startswith("http://") and not get_settings().is_production:
            return v
        raise ValueError("callback_url debe ser https")


class UpgradeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_reference: str | None = Field(default=None, max_length=200)
    callback_url: str | None = None
    force_refresh: bool = False


class RebalanceIn(BaseModel):
    """Ajuste de pesos del PlaceRank en vivo desde la UI."""

    model_config = ConfigDict(extra="forbid")

    economico: float = Field(default=0.35, ge=0, le=1)
    demografico: float = Field(default=0.30, ge=0, le=1)
    ambiental: float = Field(default=0.20, ge=0, le=1)
    match: float = Field(default=0.15, ge=0, le=1)

    @model_validator(mode="after")
    def _not_all_zero(self) -> RebalanceIn:
        if self.economico + self.demografico + self.ambiental + self.match <= 0:
            raise ValueError("Al menos un peso debe ser mayor que cero")
        return self


class GeoLensQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicators: list[str] = Field(default_factory=list, max_length=40)
    classes: int = Field(default=5, ge=3, le=9)
    method: BreakMethod = BreakMethod.QUANTILES


class IngestIn(BaseModel):
    """Disparo manual de ETL (solo con clave interna)."""

    model_config = ConfigDict(extra="forbid")

    collector: str
    indicators: list[str] = Field(default_factory=list, max_length=200)
    level: GeoLevel = GeoLevel.MUNICIPIO
    parent_code: str | None = None
    period: str | None = Field(default=None, pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")
    force: bool = False


# --------------------------------------------------------------------------- #
# Salidas
# --------------------------------------------------------------------------- #


class RunOut(BaseModel):
    run_id: int | None
    project_uuid: UUID
    tier: Tier
    status: str
    version: int | None = None
    sections_done: list[str] = Field(default_factory=list)
    reused: bool = False
    poll_after_seconds: int = 2


class GeoOut(BaseModel):
    geo_id: int
    level: GeoLevel
    ine_code: str
    name: str
    parent_id: int | None = None
    population: int | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    engine_version: str
    database: bool
    redis: bool
    checks: dict[str, Any] = Field(default_factory=dict)


class ErrorOut(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class SectionsOut(BaseModel):
    """Catálogo público: qué secciones e indicadores existen por tier."""

    tier: Tier
    sections: list[dict[str, Any]]


def sections_catalog(tier: Tier) -> SectionsOut:
    from ..domain import indicators as catalog
    from ..domain.sections import REGISTRY

    out: list[dict[str, Any]] = []
    for section in Section:
        builder = REGISTRY.get(section)
        if builder is None:
            continue
        inds = catalog.by_section(section)
        out.append({
            "id": str(section),
            "title": builder.title,
            "tier": str(builder.tier),
            "available": builder.tier in tier.includes,
            "indicators": [
                {"code": i.code, "label": i.label, "unit": str(i.unit),
                 "subsection": i.subsection, "tier": str(i.tier),
                 "direction": int(i.direction), "source": i.source}
                for i in inds
            ],
        })
    return SectionsOut(tier=tier, sections=out)
