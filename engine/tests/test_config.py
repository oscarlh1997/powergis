"""La configuración, cargada como la carga un contenedor: desde el entorno.

POR QUÉ EXISTE ESTE FICHERO
---------------------------
`ALLOWED_ORIGINS=http://localhost:8080` tumbaba la API y el worker enteros.
pydantic-settings intenta `json.loads()` de todo campo tipo lista antes de
llamar a ningún validador, así que el validador que partía por comas —que
estaba escrito y era correcto— nunca llegaba a ejecutarse. El fallo saltaba al
IMPORTAR `config`, de modo que `celery` salía con código 2 y el contenedor
entraba en bucle de reinicios.

No lo cazó ninguna prueba porque todas construían `Settings()` con los valores
por defecto o pasando argumentos, nunca desde variables de entorno, que es la
única vía que usan los contenedores. De ahí `monkeypatch.setenv` aquí.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from powergis.config import Settings


@pytest.fixture
def desde_entorno(monkeypatch):
    """Construye Settings leyendo del entorno, como en un contenedor."""

    def _cargar(**variables: str) -> Settings:
        for clave, valor in variables.items():
            monkeypatch.setenv(clave.upper(), valor)
        # Sin esto tomaría el .env del repositorio y la prueba dependería de él.
        return Settings(_env_file=None)

    return _cargar


class TestOrigenesPermitidos:
    def test_una_sola_url(self, desde_entorno):
        cfg = desde_entorno(allowed_origins="http://localhost:8080")

        assert cfg.allowed_origins == ["http://localhost:8080"]

    def test_lista_separada_por_comas(self, desde_entorno):
        """Es lo que documenta .env.example y lo que rompía el arranque."""
        cfg = desde_entorno(allowed_origins="https://powergis.es,https://www.powergis.es")

        assert cfg.allowed_origins == ["https://powergis.es", "https://www.powergis.es"]

    def test_array_json(self, desde_entorno):
        """La forma que exigía la versión anterior: sigue valiendo."""
        cfg = desde_entorno(allowed_origins='["https://a.es","https://b.es"]')

        assert cfg.allowed_origins == ["https://a.es", "https://b.es"]

    def test_espacios_alrededor(self, desde_entorno):
        cfg = desde_entorno(allowed_origins="  https://x.es , https://y.es  ")

        assert cfg.allowed_origins == ["https://x.es", "https://y.es"]

    def test_vacio_no_revienta(self, desde_entorno):
        assert desde_entorno(allowed_origins="").allowed_origins == []


class TestArranqueDesdeElEntorno:
    """El entorno completo de `docker-compose.dev.yml`, tal cual.

    Si esto falla, el contenedor no arranca: da igual que el resto de la suite
    esté en verde.
    """

    ENTORNO_DEV: ClassVar[dict[str, str]] = {
        "ENV": "development",
        "DEBUG": "true",
        "LOG_JSON": "false",
        "LOG_LEVEL": "INFO",
        "DATABASE_URL": "postgresql+psycopg://powergis:powergis@postgres:5432/powergis",
        "REDIS_URL": "redis://redis:6379/0",
        "CELERY_BROKER_URL": "redis://redis:6379/1",
        "CELERY_RESULT_BACKEND": "redis://redis:6379/2",
        "HMAC_SECRET": "dev-secreto-compartido-cambialo-en-produccion-0123456789",
        "INTERNAL_API_KEY": "dev-clave-interna-0123456789",
        "ALLOWED_ORIGINS": "http://localhost:8080",
        "WORDPRESS_BASE_URL": "http://wordpress",
        "LLM_ENABLED": "false",
        "USE_LOCAL_OSM": "false",
        "AEMET_API_KEY": "",
    }

    def test_el_entorno_de_desarrollo_carga(self, monkeypatch):
        for clave, valor in self.ENTORNO_DEV.items():
            monkeypatch.setenv(clave, valor)

        cfg = Settings(_env_file=None)

        assert cfg.env == "development"
        assert cfg.allowed_origins == ["http://localhost:8080"]
        assert cfg.hmac_secret.startswith("dev-secreto")

    def test_el_entorno_de_produccion_carga(self, monkeypatch):
        entorno = {
            **self.ENTORNO_DEV,
            "ENV": "production",
            "DEBUG": "false",
            "ALLOWED_ORIGINS": "https://powergis.es,https://www.powergis.es",
            "WORDPRESS_BASE_URL": "https://powergis.es",
        }
        for clave, valor in entorno.items():
            monkeypatch.setenv(clave, valor)

        cfg = Settings(_env_file=None)

        assert cfg.is_production
        assert len(cfg.allowed_origins) == 2

    def test_importar_los_workers_no_revienta_con_ese_entorno(self, monkeypatch):
        """El fallo real ocurría al importar, no al usar la configuración."""
        for clave, valor in self.ENTORNO_DEV.items():
            monkeypatch.setenv(clave, valor)

        from powergis.workers.celery_app import app

        assert app.main == "powergis"
