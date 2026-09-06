"""`powergis doctor` y `powergis check-config`.

Son los dos comandos que se ejecutan cuando algo va mal, y estaban sin una
sola prueba. Lo que se comprueba aquí no es que digan «ok», sino que **fallan
bien**: con la base de datos caída tienen que informar del problema y salir
con código distinto de cero, no reventar con una traza.

Un diagnóstico que se cae cuando el sistema está roto no sirve para nada,
porque es exactamente cuando se usa.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from powergis.cli import app

runner = CliRunner()


@pytest.fixture
def sin_base_de_datos(monkeypatch):
    """Apunta la conexión a un host que no existe.

    Es el estado real de un servidor recién levantado sin `docker compose up`,
    o con `postgres` caído: precisamente el momento en que alguien escribe
    `powergis doctor`.
    """
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://x:y@host-que-no-existe:5432/x"
    )
    monkeypatch.setenv("REDIS_URL", "redis://host-que-no-existe:6379/0")
    from powergis.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestDoctor:
    def test_con_la_base_de_datos_caida_informa_y_no_revienta(self, sin_base_de_datos):
        resultado = runner.invoke(app, ["doctor"])

        # Sale con error, que es lo correcto...
        assert resultado.exit_code != 0
        # ...pero por decisión propia, no por una excepción sin capturar.
        assert resultado.exception is None or isinstance(resultado.exception, SystemExit)

        # Y dice qué pasa, en vez de una traza de SQLAlchemy.
        assert "PostgreSQL" in resultado.output
        assert "problema" in resultado.output.lower()

    def test_menciona_el_servicio_que_hay_que_mirar(self, sin_base_de_datos):
        """La pista importa: el mensaje de psycopg habla de resolución de
        nombres, que parece un problema de red y no lo es."""
        resultado = runner.invoke(app, ["doctor"])
        assert "postgres" in resultado.output

    def test_informa_del_secreto_configurado(self, sin_base_de_datos):
        resultado = runner.invoke(app, ["doctor"])
        assert "HMAC_SECRET" in resultado.output


class TestCheckConfig:
    def test_en_desarrollo_no_se_queja(self, monkeypatch):
        monkeypatch.setenv("ENV", "development")
        from powergis.config import get_settings

        get_settings.cache_clear()
        try:
            resultado = runner.invoke(app, ["check-config"])
            assert resultado.exit_code == 0, resultado.output
            assert "correcta" in resultado.output
        finally:
            get_settings.cache_clear()

    def test_en_produccion_con_secreto_por_defecto_falla(self, monkeypatch):
        """El motor debe negarse a arrancar con los valores de ejemplo.

        Es la barrera que impide desplegar con el secreto que viene en el
        repositorio, que cualquiera que haya visto el código conoce.
        """
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("HMAC_SECRET", "cambia-esto-en-produccion")
        monkeypatch.setenv("INTERNAL_API_KEY", "cambia-esto-tambien")
        from powergis.config import get_settings

        get_settings.cache_clear()
        try:
            resultado = runner.invoke(app, ["check-config"])
            assert resultado.exit_code == 1
            assert "HMAC_SECRET" in resultado.output
            assert "INTERNAL_API_KEY" in resultado.output
        finally:
            get_settings.cache_clear()

    def test_en_produccion_con_debug_activo_falla(self, monkeypatch):
        monkeypatch.setenv("ENV", "production")
        monkeypatch.setenv("DEBUG", "true")
        monkeypatch.setenv("HMAC_SECRET", "a" * 40)
        monkeypatch.setenv("INTERNAL_API_KEY", "b" * 40)
        from powergis.config import get_settings

        get_settings.cache_clear()
        try:
            resultado = runner.invoke(app, ["check-config"])
            assert resultado.exit_code == 1
            assert "DEBUG" in resultado.output
        finally:
            get_settings.cache_clear()
