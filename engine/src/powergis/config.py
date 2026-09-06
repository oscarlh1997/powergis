"""Configuración por entorno.

Ningún secreto vive en código ni en la base de datos de WordPress: todo llega
por variables de entorno del VPS. `.env.example` documenta cada una.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Valores por defecto DELIBERADAMENTE inválidos en producción:
# `check_production_ready()` impide arrancar si siguen puestos.
_DEFAULT_SECRET = "cambia-esto-en-produccion"  # noqa: S105
_DEFAULT_INTERNAL_KEY = "cambia-esto-tambien"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # -- entorno ------------------------------------------------------------
    env: str = "development"
    debug: bool = False
    engine_version: str = "1.0.0"
    log_level: str = "INFO"
    log_json: bool = True

    # -- base de datos ------------------------------------------------------
    database_url: str = "postgresql+psycopg://powergis:powergis@postgres:5432/powergis"
    # Por PROCESO. (pool + overflow) × nº de procesos ≤ max_connections.
    # En KVM2: (3+4) × 6 = 42 ≤ 50. Ver .env.example antes de subirlos.
    db_pool_size: int = 3
    db_max_overflow: int = 4
    db_echo: bool = False

    # -- redis / celery -----------------------------------------------------
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # -- seguridad ----------------------------------------------------------
    hmac_secret: str = Field(default=_DEFAULT_SECRET, min_length=16)
    hmac_window_seconds: int = 300
    internal_api_key: str = _DEFAULT_INTERNAL_KEY
    # `NoDecode` es obligatorio, no una preferencia de estilo.
    #
    # Ante un campo de tipo lista, pydantic-settings intenta `json.loads()` del
    # valor de la variable de entorno. Con
    #
    #     ALLOWED_ORIGINS=https://powergis.es,https://www.powergis.es
    #
    # —que es lo que documenta `.env.example` y lo que pone cualquiera— eso
    # revienta con JSONDecodeError ANTES de llegar a ningún validador, y el
    # error se produce al importar `config`, así que se lleva por delante a la
    # API y al worker enteros: `celery` sale con código 2 y el contenedor entra
    # en bucle de reinicios. `NoDecode` desactiva ese intento de JSON y deja
    # que el validador de abajo haga el trabajo.
    allowed_origins: Annotated[list[str], NoDecode] = ["https://powergis.es"]
    wordpress_base_url: str = "https://powergis.es"
    wordpress_callback_path: str = "/wp-json/saas/v1/projects/callback"

    # -- límites ------------------------------------------------------------
    rate_limit_free_per_day: int = 5
    rate_limit_free_per_hour: int = 3
    report_cache_ttl: int = 3600
    max_children: int = 8500  # todos los municipios de España caben

    # -- fuentes de datos ---------------------------------------------------
    ine_base_url: str = "https://servicios.ine.es/wstempus/js/ES"
    ine_timeout: int = 60
    ine_max_retries: int = 4
    ine_rps: float = 2.0

    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout: int = 180
    use_local_osm: bool = True  # en producción: extracto Geofabrik en PostGIS

    aemet_api_key: str = ""
    aemet_base_url: str = "https://opendata.aemet.es/opendata/api"
    aemet_timeout: int = 60

    catastro_wfs_url: str = "https://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"

    # -- LLM ----------------------------------------------------------------
    llm_enabled: bool = True
    llm_base_url: str = "https://api.nexos.ai/v1"   # AI Router de Hostinger
    llm_api_key: str = ""
    llm_model_fast: str = "gpt-4o-mini"
    llm_model_deep: str = "gpt-4o"
    llm_timeout: int = 45
    llm_max_retries: int = 2
    llm_cache_ttl: int = 60 * 60 * 24 * 30

    # -- stripe (solo verificación; el cobro lo inicia WordPress) -----------
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # -- almacenamiento -----------------------------------------------------
    tiles_dir: str = "/data/tiles"
    exports_dir: str = "/data/exports"
    osm_extract_path: str = "/data/osm/spain-latest.osm.pbf"

    # -- observabilidad -----------------------------------------------------
    sentry_dsn: str = ""

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Acepta las dos formas que la gente escribe de verdad.

        Con `NoDecode` ya no hay parseo JSON automático, así que aquí se
        admiten tanto la lista separada por comas —lo que documenta
        `.env.example`— como un array JSON, que es lo que exigía la versión
        anterior y puede seguir escrito en algún `.env` viejo. Que una de las
        dos tumbara el arranque del worker ya ha pasado una vez.
        """
        if not isinstance(value, str):
            return value

        texto = value.strip()
        if texto.startswith("["):
            import json

            try:
                return json.loads(texto)
            except json.JSONDecodeError:
                pass  # no era JSON válido: se trata como lista con comas

        return [v.strip() for v in texto.split(",") if v.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"prod", "production"}

    @property
    def callback_url(self) -> str:
        return f"{self.wordpress_base_url.rstrip('/')}{self.wordpress_callback_path}"

    def check_production_ready(self) -> list[str]:
        """Errores que impiden arrancar en producción. Se comprueban al inicio."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        if self.hmac_secret == _DEFAULT_SECRET or len(self.hmac_secret) < 32:
            problems.append("HMAC_SECRET débil o por defecto (mínimo 32 caracteres)")
        if self.internal_api_key == _DEFAULT_INTERNAL_KEY:
            problems.append("INTERNAL_API_KEY por defecto")
        if self.debug:
            problems.append("DEBUG activo en producción")
        if not self.allowed_origins:
            problems.append("ALLOWED_ORIGINS vacío")
        if self.llm_enabled and not self.llm_api_key:
            problems.append("LLM activo sin LLM_API_KEY")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
