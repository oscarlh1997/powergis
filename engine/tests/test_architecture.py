"""Reglas de arquitectura verificadas, no solo documentadas.

Un README que dice «arquitectura hexagonal» envejece mal. Estos tests fallan
en CI el día que alguien importe SQLAlchemy dentro del dominio.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "powergis"
DOMAIN = SRC / "domain"


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # import relativo: se resuelve contra el paquete
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                relative = base.relative_to(SRC.parent).as_posix().replace("/", ".")
                found.add(f"{relative}.{node.module}" if node.module else relative)
            elif node.module:
                found.add(node.module)
    return found


DOMAIN_FILES = sorted(DOMAIN.rglob("*.py"))


class TestFronteraHexagonal:
    @pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.name)
    def test_el_dominio_no_importa_adaptadores(self, path):
        prohibidos = ("powergis.adapters", "powergis.api", "powergis.workers",
                      "powergis.application")
        for module in _imports(path):
            assert not module.startswith(prohibidos), (
                f"{path.name} importa {module}: rompe la frontera del dominio"
            )

    @pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.name)
    def test_el_dominio_no_importa_librerias_de_infraestructura(self, path):
        prohibidos = {
            "sqlalchemy", "fastapi", "celery", "redis", "httpx", "requests",
            "psycopg", "pydantic", "geoalchemy2", "starlette",
        }
        for module in _imports(path):
            raiz = module.split(".")[0]
            assert raiz not in prohibidos, (
                f"{path.name} importa {module}: el dominio debe ser puro stdlib"
            )

    def test_el_dominio_existe_y_es_sustancial(self):
        assert len(DOMAIN_FILES) >= 8


class TestCatalogo:
    def test_todos_los_indicadores_tienen_codigo_bien_formado(self):
        from powergis.domain import indicators as catalog

        for indicator in catalog.CATALOG:
            assert "." in indicator.code
            assert indicator.code == indicator.code.lower()
            assert indicator.label

    def test_no_hay_codigos_duplicados(self):
        from powergis.domain import indicators as catalog

        codes = [i.code for i in catalog.CATALOG]
        assert len(codes) == len(set(codes))

    def test_los_indicadores_de_scoring_tienen_dimension_y_direccion(self):
        from powergis.domain import indicators as catalog
        from powergis.domain.enums import Direction

        for indicator in catalog.scoring_indicators():
            assert indicator.dimension is not None
            assert indicator.direction is not Direction.NEUTRAL

    def test_solo_demografia_tiene_indicadores_basicos(self):
        from powergis.domain import indicators as catalog
        from powergis.domain.enums import Section, Tier

        basicos = catalog.by_tier(Tier.BASICO)
        assert basicos
        assert {i.section for i in basicos} == {Section.DEMOGRAFIA}

    def test_cada_seccion_tiene_indicadores(self):
        from powergis.domain import indicators as catalog
        from powergis.domain.enums import Section

        for section in Section:
            assert catalog.by_section(section), f"{section} no tiene indicadores"

    def test_la_granularidad_no_permite_desagregar_hacia_abajo(self):
        from powergis.domain.enums import GeoLevel
        from powergis.domain.indicators import BY_CODE

        municipal = BY_CODE["dem.pop.total"]
        assert municipal.available_at(GeoLevel.PROVINCIA)   # se agrega hacia arriba
        assert not municipal.available_at(GeoLevel.SECCION)  # no se inventa hacia abajo


class TestCoberturaDeColectores:
    def test_los_indicadores_del_catalogo_tienen_colector_o_estan_listados(self):
        """Un indicador sin colector es una columna vacía en el informe.

        No se exige cobertura total (hay derivados y fases futuras), pero sí
        que la lista de huérfanos sea explícita y no una sorpresa.
        """
        from powergis.adapters.collectors.aemet import AemetCollector
        from powergis.adapters.collectors.catastro import CatastroCollector
        from powergis.adapters.collectors.derived import DerivedCollector
        from powergis.adapters.collectors.ine import IneCollector
        from powergis.adapters.collectors.ine_adrh import AdrhCollector
        from powergis.domain import indicators as catalog

        routed: set[str] = set()
        for collector in (IneCollector, AdrhCollector, AemetCollector,
                          CatastroCollector, DerivedCollector):
            routed.update(collector.PROVIDES)
        # OSM se instancia con sesión; su lista se toma de la clase.
        from powergis.adapters.collectors.osm import OsmCollector

        routed.update(OsmCollector.PROVIDES)

        orphans = sorted(i.code for i in catalog.CATALOG if i.code not in routed)
        cobertura = 1 - len(orphans) / len(catalog.CATALOG)
        assert cobertura > 0.75, f"cobertura {cobertura:.0%}; huérfanos: {orphans}"
