"""El callback firmado hacia WordPress.

Es el último tramo del circuito: cuando el informe está listo, el motor avisa
a `saas/v1/projects/callback` y WordPress publica el proyecto. Si esto falla en
silencio, el cliente ve su informe «en preparación» para siempre aunque el
motor lo haya terminado.

Se comprueban las tres decisiones que tiene tomadas el reintento, porque son
justo las que no se ven mirando el código:

  · un 5xx o un fallo de red se reintentan;
  · un 4xx NO se reintenta — reintentar un cuerpo mal formado sólo gasta
    tiempo y llena el log;
  · un 429 sí, porque significa «ahora no», no «nunca».

El `time.sleep` del backoff se anula: si no, la suite tardaría seis segundos
en cada caso de fallo.
"""

from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from conftest import SECRETO_DE_PRUEBAS as SECRET
from powergis.adapters.wordpress import NullNotifier, WordPressNotifier
from powergis.api.security import HEADER_SIGNATURE, HEADER_TIMESTAMP, compute_signature
from powergis.domain.enums import Tier

UUID_PROYECTO = UUID("3f2a1b4c-5d6e-4f70-8a91-b2c3d4e5f607")
URL = "https://powergis.es/wp-json/saas/v1/projects/callback"


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr("powergis.adapters.wordpress.time.sleep", lambda _: None)


class Transporte(httpx.BaseTransport):
    """Responde lo que se le diga y guarda lo que recibió."""

    def __init__(self, *codigos: int):
        self.codigos = list(codigos)
        self.peticiones: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.peticiones.append(request)
        codigo = self.codigos.pop(0) if self.codigos else 200
        if codigo == 0:  # fallo de red
            raise httpx.ConnectError("sin ruta al host", request=request)
        return httpx.Response(codigo, text="")


def notificador(*codigos: int) -> tuple[WordPressNotifier, Transporte]:
    transporte = Transporte(*codigos)
    n = WordPressNotifier()
    n._client = httpx.Client(transport=transporte)
    return n, transporte


class TestFirma:
    def test_firma_los_bytes_que_envia(self):
        """La firma se calcula sobre el cuerpo serializado UNA vez.

        Si se reserializara para firmar, WordPress verificaría sobre otros
        bytes y rechazaría todos los callbacks con 401.
        """
        n, t = notificador(200)
        n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok")

        peticion = t.peticiones[0]
        enviado = peticion.content
        firma = peticion.headers[HEADER_SIGNATURE]
        ts = peticion.headers[HEADER_TIMESTAMP]

        assert firma == compute_signature(SECRET, ts, enviado)

    def test_el_cuerpo_lleva_lo_que_wordpress_necesita(self):
        n, t = notificador(200)
        n.report_ready(URL, UUID_PROYECTO, Tier.AVANZADO, 2, "ok")

        cuerpo = json.loads(t.peticiones[0].content)
        assert cuerpo["project_uuid"] == str(UUID_PROYECTO)
        assert cuerpo["version"] == 2
        assert cuerpo["status"] == "ok"
        assert "engine_version" in cuerpo


class TestReintentos:
    def test_a_la_primera(self):
        n, t = notificador(200)
        assert n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok") is True
        assert len(t.peticiones) == 1

    def test_un_500_se_reintenta_y_puede_acabar_bien(self):
        n, t = notificador(500, 200)
        assert n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok") is True
        assert len(t.peticiones) == 2

    def test_un_fallo_de_red_se_reintenta(self):
        n, t = notificador(0, 200)
        assert n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok") is True
        assert len(t.peticiones) == 2

    def test_un_400_no_se_reintenta(self):
        """Reintentar un cuerpo que WordPress rechaza no lo arregla."""
        n, t = notificador(400, 200)
        assert n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok") is False
        assert len(t.peticiones) == 1

    def test_un_429_si_se_reintenta(self):
        """«Demasiadas peticiones» significa ahora no, no nunca."""
        n, t = notificador(429, 200)
        assert n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok") is True
        assert len(t.peticiones) == 2

    def test_se_rinde_tras_agotar_los_intentos(self):
        n, t = notificador(500, 500, 500)
        assert n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok") is False
        assert len(t.peticiones) == 3


class TestNarrativa:
    def test_avisa_con_su_propio_estado(self):
        n, t = notificador(200)
        assert n.narrative_ready(URL, UUID_PROYECTO, 2) is True
        assert json.loads(t.peticiones[0].content)["status"] == "narrative_ready"


class TestNullNotifier:
    def test_no_manda_nada_y_dice_que_si(self):
        """El respaldo cuando no hay callback configurado: no debe hacer que
        el informe se dé por fallido."""
        n = NullNotifier()
        assert n.report_ready(URL, UUID_PROYECTO, Tier.BASICO, 1, "ok") is True
        assert n.narrative_ready(URL, UUID_PROYECTO, 1) is True
        n.close()
