"""Infoelectoral: mesas → sección → distrito → municipio.

Fixture: `fixtures/infoelectoral/09022307.DAT` y `10022307.DAT`, cinco mesas
de San Sebastián de los Reyes (28134) escritas con las posiciones
PROVISIONALES del colector, más una del CERA que se ignora. Las cuentas se
pueden seguir a mano:

    sección 2813401001: mesas A y B → censo 1000, votantes 700
    sección 2813401002: censo 800, votantes 500
    distrito 2813401:   censo 1800, votantes 1200
    sección 2813402001: censo 500, votantes 300 (y es todo el distrito 02)
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from powergis.adapters.collectors.infoelectoral import (
    InfoelectoralCollector,
    agregar,
    leer_zip,
    por_seccion,
)
from powergis.domain.enums import GeoLevel
from powergis.domain.models import Geo, Segments

DIR = Path(__file__).parent / "fixtures" / "infoelectoral"


def zip_de_mesas(tmp_path: Path) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for fichero in DIR.iterdir():
            z.write(fichero, fichero.name)
    ruta = tmp_path / "02202307_MESA.zip"
    ruta.write_bytes(buf.getvalue())
    return ruta


def totales(tmp_path):
    _, l09, l10 = leer_zip(zip_de_mesas(tmp_path).read_bytes())
    return agregar(por_seccion(l09, l10))


def test_las_mesas_se_suman_por_seccion_distrito_y_municipio(tmp_path):
    t = totales(tmp_path)
    assert t["2813401001"].censo == 1000
    assert t["2813401001"].indicadores()["pol.turnout_pct"] == pytest.approx(70.0)
    assert t["2813401"].censo == 1800
    assert t["2813401"].indicadores()["pol.turnout_pct"] == pytest.approx(1200 / 1800 * 100)
    assert t["28134"].censo == 2300


def test_el_cera_no_es_una_seccion(tmp_path):
    t = totales(tmp_path)
    assert not any(c.startswith("28999") for c in t)


def test_concentracion_y_fragmentacion(tmp_path):
    ind = totales(tmp_path)["2813402001"].indicadores()
    # 200 de 299 válidos (295 a candidaturas + 4 en blanco).
    assert ind["pol.winner_share_pct"] == pytest.approx(200 / 299 * 100)
    p = (95 / 295, 200 / 295)
    assert ind["pol.effective_parties"] == pytest.approx(1 / sum(x * x for x in p))


def test_el_colector_escribe_las_zonas_que_conoce(tmp_path):
    geos = [Geo(11, GeoLevel.DISTRITO, "2813401", "Distrito 01", 10),
            Geo(21, GeoLevel.SECCION, "2813401001", "Sección 01001", 11),
            Geo(99, GeoLevel.SECCION, "2899901001", "Otra", 11)]
    col = InfoelectoralCollector(str(zip_de_mesas(tmp_path)))
    hechos = col.collect(list(col.PROVIDES), geos, Segments())
    assert col.fallos == []
    assert {h.geo_id for h in hechos} == {11, 21}
    assert all(h.period.isoformat() == "2023-07-01" for h in hechos)
    assert all("provisional" in h.source_ref and "tipo 02" in h.source_ref for h in hechos)


def test_sin_zip_no_carga_ni_bloquea(monkeypatch):
    monkeypatch.delenv("POWERGIS_INFOELECTORAL", raising=False)
    col = InfoelectoralCollector()
    assert col.collect(["pol.turnout_pct"], [Geo(1, GeoLevel.SECCION, "1", "x", None)],
                       Segments()) == []
    assert col.fallos == []


def test_verificar_cuadra_la_fixture(tmp_path):
    out = InfoelectoralCollector(str(zip_de_mesas(tmp_path))).verificar(
        [Geo(21, GeoLevel.SECCION, "2813401001", "Sección 01001", 11)])
    assert out["cabecera"] == {"tipo": "02", "anio": "2023", "mes": "07"}
    assert out["secciones"] == 3 and out["secciones_con_descuadre"] == 0
    assert out["secciones_en_dim_geo"] == 1


def test_el_registro_lo_enruta_antes_que_la_plantilla():
    from powergis.adapters.collectors.registry import build_registry, indicator_owner

    assert indicator_owner("pol.turnout_pct", build_registry()) == "infoelectoral"
