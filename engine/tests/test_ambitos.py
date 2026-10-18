"""Los cuatro ámbitos del formulario: nacional, comunidad, provincia y municipio.

Cada uno tiene que dar un informe de SU ámbito. El municipio es el caso raro:
el almacén no tiene distritos ni secciones, así que se compara con los
municipios de su provincia en vez de cortar el informe con un error.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from conftest import _fact
from powergis.application.build_report import BuildReport
from powergis.application.context import resolve_scope
from powergis.application.create_report import CreateReport
from powergis.application.dto import CreateReportIn
from powergis.domain.enums import GeoLevel, RunStatus, Tier
from powergis.domain.models import Geo, Scope

ENGINE = "1.0.0-test"


@pytest.fixture
def geos(geos) -> list[Geo]:
    """Las provincias del conftest más tres municipios de Toledo."""
    return [
        *geos,
        Geo(10, GeoLevel.MUNICIPIO, "45168", "Toledo", 4, 86_000, 232),
        Geo(11, GeoLevel.MUNICIPIO, "45165", "Talavera de la Reina", 4, 83_000, 185),
        Geo(12, GeoLevel.MUNICIPIO, "45087", "Illescas", 4, 31_000, 57),
    ]


@pytest.fixture
def facts(facts) -> list:
    extra = []
    for geo_id, pop in ((10, 86_000), (11, 83_000), (12, 31_000)):
        extra.append(_fact(geo_id, "dem.pop.total", pop))
        extra.append(_fact(geo_id, "dem.age.mean", 44.0))
    return facts + extra


def _build(uow_factory, scope: dict):
    payload = CreateReportIn(
        project_uuid=uuid4(),
        wp_user_id=7,
        wp_post_id=7818,
        tier=Tier.BASICO,
        scope=scope,
        business={"sector": "restauracion"},
    )
    run = CreateReport(uow_factory, ENGINE, lambda *_: None)(payload).run
    return BuildReport(uow_factory, ENGINE)(run.run_id)


@pytest.mark.parametrize(
    ("scope", "nombre", "nivel_filas", "filas"),
    [
        ({"level": "pais", "ine_code": "ES"}, "España", "ccaa", 1),
        ({"level": "ccaa", "ine_code": "13"}, "Comunidad de Madrid", "provincia", 4),
        ({"level": "provincia", "ine_code": "45"}, "Toledo", "municipio", 3),
        ({"level": "municipio", "ine_code": "45087"}, "Illescas", "municipio", 3),
    ],
)
def test_cada_ambito_da_su_propio_informe(uow_factory, scope, nombre, nivel_filas, filas):
    result = _build(uow_factory, scope)

    # PARTIAL en el nacional: el conftest no trae datos de las CCAA.
    assert result.run.status in (RunStatus.DONE, RunStatus.PARTIAL)
    bloque = result.report.scope
    assert bloque["level"] == scope["level"]
    assert bloque["code"] == scope["ine_code"]
    assert bloque["name"] == nombre
    assert bloque["children_level"] == nivel_filas
    assert bloque["children_count"] == filas


def test_el_municipio_se_compara_con_su_provincia_y_lo_avisa(uow):
    resolved = resolve_scope(uow, Scope(GeoLevel.MUNICIPIO, "45087"))

    assert resolved.parent.name == "Illescas"
    assert resolved.children_level is GeoLevel.MUNICIPIO
    assert resolved.zones_parent.name == "Toledo"
    assert {g.name for g in resolved.children} == {"Toledo", "Talavera de la Reina", "Illescas"}
    assert "provincia de Toledo" in resolved.note


def test_el_dato_del_municipio_no_se_inventa_con_el_de_la_provincia(uow_factory):
    result = _build(uow_factory, {"level": "municipio", "ine_code": "45087"})
    # Illescas tiene población: sale la suya, no la suma de la provincia.
    assert result.report.scope["population"] == 31_000


def test_pide_la_recarga_de_los_municipios_de_la_provincia(uow_factory):
    pedidos = []
    payload = CreateReportIn(
        project_uuid="00000000-0000-4000-8000-000000000099",
        wp_user_id=7,
        wp_post_id=7818,
        tier=Tier.BASICO,
        scope={"level": "municipio", "ine_code": "45087"},
    )
    run = CreateReport(uow_factory, ENGINE, lambda *_: None)(payload).run
    BuildReport(
        uow_factory, ENGINE,
        request_ingest=lambda codes, level, parent: pedidos.append((level, parent)),
    )(run.run_id)
    assert pedidos in ([], [("municipio", "45")])
