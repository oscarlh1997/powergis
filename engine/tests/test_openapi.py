"""El documento OpenAPI tiene que ser resoluble, no sólo generarse.

Los endpoints firmados leen el cuerpo CRUDO —la firma cubre los bytes
exactos—, así que FastAPI no ve el modelo y no lo registra. Sus rutas lo
declaran a mano con `openapi_extra`, y ahí es fácil dejar un `$ref` colgando:
el documento se genera sin quejarse y Swagger revienta al abrirlo con

    Could not resolve reference: Invalid object key "CreateReportIn"

Comprobar que el `$ref` está escrito no vale: hay que resolverlo.
"""

from __future__ import annotations

import pytest

from powergis.api.main import create_app

FIRMADOS = [
    ("/v1/reports", "post", "CreateReportIn"),
    ("/v1/reports/{project_uuid}/upgrade", "post", "UpgradeIn"),
    ("/v1/reports/{project_uuid}/placerank/rebalance", "post", "RebalanceIn"),
    ("/v1/reports/{project_uuid}/geolens", "post", "GeoLensQuery"),
]


@pytest.fixture(scope="module")
def spec():
    return create_app().openapi()


def _referencias(nodo, ruta="raíz"):
    if isinstance(nodo, dict):
        for clave, valor in nodo.items():
            if clave == "$ref" and isinstance(valor, str):
                yield valor, ruta
            else:
                yield from _referencias(valor, f"{ruta}.{clave}")
    elif isinstance(nodo, list):
        for i, valor in enumerate(nodo):
            yield from _referencias(valor, f"{ruta}[{i}]")


def _resuelve(spec: dict, ref: str) -> bool:
    if not ref.startswith("#/"):
        return False
    nodo = spec
    for parte in ref[2:].split("/"):
        parte = parte.replace("~1", "/").replace("~0", "~")
        if not isinstance(nodo, dict) or parte not in nodo:
            return False
        nodo = nodo[parte]
    return True


class TestReferencias:
    def test_todas_las_referencias_resuelven(self, spec):
        rotas = [(r, d) for r, d in _referencias(spec) if not _resuelve(spec, r)]

        assert not rotas, "Swagger no podrá cargar el documento:\n  " + "\n  ".join(
            f"{r}  ←  {d}" for r, d in rotas
        )

    def test_hay_referencias_que_comprobar(self, spec):
        """Si un refactor dejara el documento sin `$ref`, la prueba de arriba
        pasaría por vacío y no estaría comprobando nada."""
        assert len(list(_referencias(spec))) > 20


class TestCuerposFirmados:
    @pytest.mark.parametrize(("ruta", "metodo", "modelo"), FIRMADOS)
    def test_el_cuerpo_esta_documentado(self, spec, ruta, metodo, modelo):
        """Sin esto Swagger no dibuja el editor y no se puede ni escribir la
        petición desde /docs."""
        operacion = spec["paths"][ruta][metodo]

        assert "requestBody" in operacion, f"{metodo.upper()} {ruta} sin cuerpo declarado"
        esquema = operacion["requestBody"]["content"]["application/json"]["schema"]
        assert esquema["$ref"].endswith(f"/{modelo}")

    @pytest.mark.parametrize(("ruta", "metodo", "modelo"), FIRMADOS)
    def test_el_modelo_esta_registrado(self, spec, ruta, metodo, modelo):
        assert modelo in spec["components"]["schemas"], (
            f"{modelo} se referencia pero no está en components.schemas"
        )

    @pytest.mark.parametrize(("ruta", "metodo", "modelo"), FIRMADOS)
    def test_siguen_pidiendo_la_firma(self, spec, ruta, metodo, modelo):
        """Documentar el cuerpo no debe haber quitado las cabeceras de firma."""
        cabeceras = {
            p["name"]
            for p in spec["paths"][ruta][metodo].get("parameters", [])
            if p.get("in") == "header"
        }

        assert {"X-PG-Timestamp", "X-PG-Signature"} <= cabeceras
