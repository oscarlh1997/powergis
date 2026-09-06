"""Las fixtures de `scripts/fixtures.json` contra el contrato real.

Los datos de prueba envejecen peor que el código: alguien cambia un enum y las
fixtures siguen pareciendo correctas hasta que alguien las ejecuta. Aquí se
comprueba, en la suite, que:

  1. cada operación que expone el motor tiene al menos un caso;
  2. ningún caso apunta a una ruta que ya no existe;
  3. cada cuerpo lo acepta el modelo de verdad.

Encontró un `method: "quantile"` cuando el enum es `quantiles`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from powergis.api.main import create_app
from powergis.api.routers.internal import IngestIn
from powergis.application.dto import (
    CreateReportIn,
    GeoLensQuery,
    RebalanceIn,
    UpgradeIn,
)

FIXTURES = Path(__file__).resolve().parents[2] / "scripts" / "fixtures.json"
UUID_DEMO = "3f2a1b4c-5d6e-4f70-8a91-b2c3d4e5f607"

# Los mismos marcadores que resuelve `powergis endpoints` en cada tanda.
SUSTITUCIONES = {
    "{uuid}": UUID_DEMO,
    "{uuid2}": "5c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f",
    "{uuid3}": "7e8f9a0b-1c2d-4e3f-9a8b-7c6d5e4f3a2b",
    "{owner}": "7",
}


def _resolver(texto: str) -> str:
    for clave, valor in SUSTITUCIONES.items():
        texto = texto.replace(clave, valor)
    return texto

MODELOS = {
    "/v1/reports": CreateReportIn,
    "/upgrade": UpgradeIn,
    "/placerank/rebalance": RebalanceIn,
    "/geolens": GeoLensQuery,
    "/internal/ingest": IngestIn,
}


def _casos() -> list[dict]:
    if not FIXTURES.exists():
        pytest.skip(f"No hay fixtures en {FIXTURES}")
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return [
        {**caso, "_grupo": grupo}
        for grupo, lista in data.items()
        if not grupo.startswith("_")
        for caso in lista
    ]


def _plantilla(ruta: str) -> str:
    """La ruta concreta de un caso, a la plantilla que declara OpenAPI."""
    r = ruta.replace("{uuid}", "{project_uuid}")
    niveles = "pais|ccaa|provincia|municipio|distrito|seccion"
    r = re.sub(rf"/v1/geo/({niveles})/[^/]+/children", "/v1/geo/{level}/{ine_code}/children", r)
    r = re.sub(rf"/v1/geo/({niveles})/[^/]+$", "/v1/geo/{level}/{ine_code}", r)
    r = re.sub(r"/v1/reports/catalog/(basico|avanzado)", "/v1/reports/catalog/{tier}", r)
    r = re.sub(r"/export/(xlsx|pdf|pptx)", "/export/{kind}", r)
    r = re.sub(r"/internal/ine/discover/\w+", "/internal/ine/discover/{table_id}", r)
    return r


def _operaciones_reales() -> set[tuple[str, str]]:
    spec = create_app().openapi()
    return {
        (metodo.upper(), ruta)
        for ruta, ops in spec["paths"].items()
        for metodo in ops
        if metodo.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE")
    }


def _modelo_de(ruta: str):
    for fragmento, modelo in MODELOS.items():
        if ruta == fragmento or ruta.endswith(fragmento):
            return modelo
    return None


class TestCobertura:
    def test_toda_operacion_tiene_caso_de_prueba(self):
        cubiertas = {(c["metodo"], _plantilla(c["ruta"])) for c in _casos()}
        faltan = sorted(_operaciones_reales() - cubiertas)

        assert not faltan, (
            "Operaciones sin datos de prueba en fixtures.json:\n  "
            + "\n  ".join(f"{m} {r}" for m, r in faltan)
        )

    def test_ningun_caso_apunta_a_una_ruta_inexistente(self):
        reales = _operaciones_reales()
        huerfanos = sorted(
            (c["metodo"], c["ruta"])
            for c in _casos()
            if (c["metodo"], _plantilla(c["ruta"])) not in reales
        )

        assert not huerfanos, (
            "Casos que llaman a rutas que el motor ya no expone:\n  "
            + "\n  ".join(f"{m} {r}" for m, r in huerfanos)
        )


class TestCuerpos:
    @pytest.mark.parametrize(
        "caso",
        [c for c in _casos() if c.get("cuerpo") and _modelo_de(c["ruta"])],
        ids=lambda c: c["nombre"],
    )
    def test_el_cuerpo_lo_acepta_el_modelo_real(self, caso):
        modelo = _modelo_de(caso["ruta"])
        datos = json.loads(_resolver(json.dumps(caso["cuerpo"])))

        modelo.model_validate(datos)

    def test_los_casos_de_seguridad_esperan_un_rechazo(self):
        """El grupo `seguridad` comprueba lo que NO debe funcionar. Si alguno
        esperase un 200, la prueba pasaría con el sistema abierto."""
        for caso in _casos():
            if caso["_grupo"] != "seguridad":
                continue
            esperado = caso["espera"]
            codigos = esperado if isinstance(esperado, list) else [esperado]
            assert all(c in (401, 403, 422) for c in codigos), (
                f"«{caso['nombre']}» espera {esperado}: un caso de seguridad "
                "sólo puede dar por buena una negativa"
            )
