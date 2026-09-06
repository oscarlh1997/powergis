"""Firma HMAC bidireccional. Es la puerta del sistema."""

from __future__ import annotations

import time

import pytest

from powergis.api import security
from powergis.domain.errors import ReplayError, SignatureError

SECRET = "secreto-de-pruebas-suficientemente-largo-1234"


class TestFirma:
    def test_firma_valida_pasa(self):
        body = b'{"project_uuid":"x"}'
        headers = security.sign(body, SECRET)
        security.verify(body, headers.timestamp, headers.signature, secret=SECRET)

    def test_cuerpo_alterado_falla(self):
        body = b'{"tier":"basico"}'
        headers = security.sign(body, SECRET)
        with pytest.raises(SignatureError):
            security.verify(b'{"tier":"avanzado"}', headers.timestamp,
                            headers.signature, secret=SECRET)

    def test_secreto_distinto_falla(self):
        body = b"{}"
        headers = security.sign(body, SECRET)
        with pytest.raises(SignatureError):
            security.verify(body, headers.timestamp, headers.signature, secret="otro-secreto")

    def test_faltan_cabeceras(self):
        with pytest.raises(SignatureError):
            security.verify(b"{}", None, None, secret=SECRET)

    def test_timestamp_no_numerico(self):
        with pytest.raises(SignatureError):
            security.verify(b"{}", "ayer", "deadbeef", secret=SECRET)


class TestAntiReenvio:
    def test_peticion_antigua_se_rechaza(self):
        body = b"{}"
        old = str(int(time.time()) - 4000)
        signature = security.compute_signature(SECRET, old, body)
        with pytest.raises(ReplayError):
            security.verify(body, old, signature, secret=SECRET, window_seconds=300)

    def test_dentro_de_la_ventana_pasa(self):
        body = b"{}"
        recent = str(int(time.time()) - 60)
        signature = security.compute_signature(SECRET, recent, body)
        security.verify(body, recent, signature, secret=SECRET, window_seconds=300)

    def test_timestamp_futuro_tambien_se_rechaza(self):
        """Un reloj adelantado no debe ser una vía de reenvío."""
        body = b"{}"
        future = str(int(time.time()) + 4000)
        signature = security.compute_signature(SECRET, future, body)
        with pytest.raises(ReplayError):
            security.verify(body, future, signature, secret=SECRET, window_seconds=300)


class TestCompatibilidadConPhp:
    """El plugin de WordPress firma exactamente igual.

    payload = timestamp + "\\n" + cuerpo_crudo ; hex(HMAC-SHA256).
    Si este test cambia, hay que cambiar `class-signer.php` a la vez.
    """

    def test_vector_conocido(self):
        expected = security.compute_signature("clave", "1700000000", b'{"a":1}')
        # Equivalente PHP: hash_hmac('sha256', "1700000000\n" . '{"a":1}', 'clave')
        import hashlib
        import hmac

        manual = hmac.new(b"clave", b'1700000000\n{"a":1}', hashlib.sha256).hexdigest()
        assert expected == manual
        assert len(expected) == 64

    def test_firma_es_estable(self):
        a = security.compute_signature("k", "1", b"body")
        b = security.compute_signature("k", "1", b"body")
        assert a == b


class TestClaveInterna:
    def test_clave_correcta(self):
        security.verify_internal_key("clave-interna-de-pruebas")

    def test_clave_incorrecta(self):
        with pytest.raises(SignatureError):
            security.verify_internal_key("nope")

    def test_sin_clave(self):
        with pytest.raises(SignatureError):
            security.verify_internal_key(None)
