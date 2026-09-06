"""El comando `powergis firmar`.

Existe porque firmar a mano es donde más se falla, y porque su contrato tiene
dos reglas que no se adivinan mirando el código:

  · en un POST se firman los BYTES EXACTOS del cuerpo, no el JSON
    reserializado;
  · en un GET se firma `GET\\nruta?query`, y **sin `?` cuando no hay query**.

Las dos se comprueban aquí contra la misma función que usa el motor para
verificar, no contra una copia del algoritmo: si alguien cambia una, esto
falla.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from typer.testing import CliRunner

from conftest import SECRETO_DE_PRUEBAS as SECRET
from powergis.api.security import canonical_get, compute_signature
from powergis.cli import app

runner = CliRunner()

CUERPO = {
    "project_uuid": "3f2a1b4c-5d6e-4f70-8a91-b2c3d4e5f607",
    "wp_user_id": 7,
    "tier": "basico",
    "scope": {"level": "pais", "ine_code": "ES", "children_level": "ccaa"},
}


@pytest.fixture
def fichero(tmp_path):
    """Un cuerpo JSON en disco, con saltos Unix."""
    ruta = tmp_path / "cuerpo.json"
    ruta.write_bytes(json.dumps(CUERPO, separators=(",", ":")).encode())
    return ruta


def _cabeceras(salida: str) -> dict[str, str]:
    """Extrae las dos cabeceras de la salida del comando."""
    out = {}
    for linea in salida.splitlines():
        for nombre in ("X-PG-Timestamp", "X-PG-Signature"):
            if linea.strip().startswith(nombre):
                out[nombre] = linea.split(":", 1)[1].strip()
    return out


class TestFirmarPost:
    def test_la_firma_vale_para_el_motor(self, fichero):
        r = runner.invoke(app, ["firmar", "--cuerpo", str(fichero)])
        assert r.exit_code == 0, r.output

        cab = _cabeceras(r.output)
        esperada = compute_signature(SECRET, cab["X-PG-Timestamp"], fichero.read_bytes())
        assert cab["X-PG-Signature"] == esperada

    def test_se_firman_los_bytes_del_fichero_no_el_json_reformateado(self, tmp_path):
        """El mismo objeto con otro formato produce OTRA firma.

        Es la razón de que Swagger dé 401 cuando reindenta el cuerpo: la firma
        es correcta y aun así no casa, porque los bytes cambiaron.
        """
        compacto = tmp_path / "compacto.json"
        indentado = tmp_path / "indentado.json"
        compacto.write_bytes(json.dumps(CUERPO, separators=(",", ":")).encode())
        indentado.write_bytes(json.dumps(CUERPO, indent=2).encode())

        ts = "1700000000"
        f1 = compute_signature(SECRET, ts, compacto.read_bytes())
        f2 = compute_signature(SECRET, ts, indentado.read_bytes())
        assert f1 != f2

    def test_avisa_de_los_saltos_de_windows(self, tmp_path):
        ruta = tmp_path / "crlf.json"
        ruta.write_bytes(b'{"a":1}\r\n')
        r = runner.invoke(app, ["firmar", "--cuerpo", str(ruta)])
        assert r.exit_code == 0
        assert "CRLF" in r.output

    def test_json_invalido_aborta(self, tmp_path):
        ruta = tmp_path / "roto.json"
        ruta.write_text("{esto no es json")
        r = runner.invoke(app, ["firmar", "--cuerpo", str(ruta)])
        assert r.exit_code == 1
        assert "JSON" in r.output

    def test_fichero_inexistente_aborta(self, tmp_path):
        r = runner.invoke(app, ["firmar", "--cuerpo", str(tmp_path / "no-existe.json")])
        assert r.exit_code == 1

    def test_sin_argumentos_aborta(self):
        r = runner.invoke(app, ["firmar"])
        assert r.exit_code == 1


class TestFirmarGet:
    def test_sin_query_no_se_añade_interrogacion(self):
        """La regla que rompía todas las firmas de lectura.

        `canonical_get` no pone `?` cuando no hay query. Un `?` de más produce
        una firma distinta y el motor devuelve 401.
        """
        ruta = "/v1/reports/3f2a1b4c-5d6e-4f70-8a91-b2c3d4e5f607"
        r = runner.invoke(app, ["firmar", "--get", ruta])
        assert r.exit_code == 0, r.output

        cab = _cabeceras(r.output)
        ts = cab["X-PG-Timestamp"]
        assert cab["X-PG-Signature"] == compute_signature(SECRET, ts, canonical_get(ruta))
        # Y explícitamente: la variante con `?` NO coincide.
        assert cab["X-PG-Signature"] != compute_signature(SECRET, ts, f"GET\n{ruta}?")

    def test_con_query(self):
        ruta = "/v1/reports/abc"
        r = runner.invoke(app, ["firmar", "--get", ruta, "--query", "wp_user_id=7"])
        assert r.exit_code == 0, r.output

        cab = _cabeceras(r.output)
        assert cab["X-PG-Signature"] == compute_signature(
            SECRET, cab["X-PG-Timestamp"], canonical_get(ruta, "wp_user_id=7")
        )

    def test_admite_la_request_url_entera_de_swagger(self):
        """Pegar la URL completa tiene que dar la misma firma que ruta+query.

        Es el camino recomendado precisamente porque el ORDEN de los
        parámetros forma parte de la firma y copiarlos a mano es donde se
        falla.
        """
        entera = "http://localhost:8000/v1/reports/abc?wp_user_id=7&version=2"
        r = runner.invoke(app, ["firmar", "--get", entera])
        assert r.exit_code == 0, r.output

        cab = _cabeceras(r.output)
        assert cab["X-PG-Signature"] == compute_signature(
            SECRET,
            cab["X-PG-Timestamp"],
            canonical_get("/v1/reports/abc", "wp_user_id=7&version=2"),
        )
        # El dominio NO entra en lo firmado.
        assert "localhost:8000" not in r.output.split("Se ha firmado")[-1]

    def test_el_orden_de_los_parametros_cambia_la_firma(self):
        ts = "1700000000"
        uno = compute_signature(SECRET, ts, canonical_get("/v1/reports/abc", "a=1&b=2"))
        otro = compute_signature(SECRET, ts, canonical_get("/v1/reports/abc", "b=2&a=1"))
        assert uno != otro

    def test_ruta_relativa_sin_barra_aborta(self):
        r = runner.invoke(app, ["firmar", "--get", "v1/reports/abc"])
        assert r.exit_code == 1


class TestContratoDeFirma:
    """El algoritmo, contrastado contra una implementación independiente."""

    def test_es_hmac_sha256_de_timestamp_salto_cuerpo(self):
        cuerpo = b'{"a":1}'
        ts = "1700000000"
        a_mano = hmac.new(
            SECRET.encode(), f"{ts}\n".encode() + cuerpo, hashlib.sha256
        ).hexdigest()
        assert compute_signature(SECRET, ts, cuerpo) == a_mano

    def test_canonical_get_no_pone_interrogacion_vacia(self):
        assert canonical_get("/x") == "GET\n/x"
        assert canonical_get("/x", "") == "GET\n/x"
        assert canonical_get("/x", "a=1") == "GET\n/x?a=1"
