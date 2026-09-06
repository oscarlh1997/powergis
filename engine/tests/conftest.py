"""Fixtures compartidos.

La clave de que estos tests corran en milisegundos y sin Docker es la
arquitectura hexagonal: los repositorios son `Protocol`, así que aquí hay
implementaciones en memoria y el dominio no nota la diferencia.
"""

from __future__ import annotations

import os
from datetime import date
from uuid import UUID, uuid4

import pytest

# El banco de pruebas fija su entorno, NO lo hereda.
#
# Antes esto era `setdefault`, que sólo asigna si la variable no existe. Basta
# con que el entorno traiga otro HMAC_SECRET —y el flujo de integración
# continua lo exporta— para que el motor verifique con el secreto del entorno
# mientras las pruebas firman con el suyo. Resultado: 401 invalid_signature en
# todo lo firmado, y una suite que pasa en tu portátil y falla en CI.
#
# SECRETO_DE_PRUEBAS es la única fuente: las pruebas que firman lo importan de
# aquí en vez de repetir el literal, para que no puedan volver a separarse.
os.environ["HMAC_SECRET"] = "secreto-de-pruebas-suficientemente-largo-1234"
os.environ["INTERNAL_API_KEY"] = "clave-interna-de-pruebas"
os.environ["LLM_ENABLED"] = "false"
os.environ["ENV"] = "test"

from powergis.domain.enums import GeoLevel, RunStatus, Section, Tier
from powergis.domain.models import (
    BusinessProfile,
    Fact,
    Geo,
    Project,
    ReportRun,
    Scope,
    Segments,
)
from powergis.domain.sections.base import SectionContext

# El secreto con el que firman las pruebas. Se LEE del entorno que se acaba de
# fijar arriba, en vez de repetir el literal: así es imposible que la firma y
# la verificación usen valores distintos.
SECRETO_DE_PRUEBAS = os.environ["HMAC_SECRET"]

PERIOD = date(2024, 1, 1)


# --------------------------------------------------------------------------- #
# Repositorios en memoria
# --------------------------------------------------------------------------- #


class FakeGeoRepo:
    def __init__(self, geos: list[Geo]) -> None:
        self._geos = {g.geo_id: g for g in geos}

    def get(self, level, ine_code):
        for g in self._geos.values():
            if g.level == level and g.ine_code == ine_code:
                return g
        return None

    def get_by_id(self, geo_id):
        return self._geos.get(geo_id)

    def children(self, geo_id, level):
        return [g for g in self._geos.values() if g.parent_id == geo_id and g.level == level]

    def descendants(self, geo_id, level):
        out, frontier = [], [geo_id]
        while frontier:
            current = frontier.pop()
            for g in self._geos.values():
                if g.parent_id == current:
                    frontier.append(g.geo_id)
                    if g.level == level:
                        out.append(g)
        return sorted(out, key=lambda g: g.name)

    def search(self, query, level=None, limit=20):
        q = query.lower()
        return [
            g for g in self._geos.values()
            if q in g.name.lower() and (level is None or g.level == level)
        ][:limit]

    def upsert_many(self, geos):
        for g in geos:
            self._geos[g.geo_id] = g
        return len(geos)


class FakeFactRepo:
    def __init__(self, facts: list[Fact] | None = None) -> None:
        self._facts: dict[tuple, Fact] = {}
        for fact in facts or []:
            self.upsert_many([fact])

    @staticmethod
    def _key(fact: Fact):
        return (fact.geo_id, fact.indicator, fact.period, SectionContext.segment_key(fact.segment))

    def fetch(self, geo_ids, indicators, segments=None, period=None):
        keys = {SectionContext.segment_key(s) for s in (segments or [{}])}
        geo_set, ind_set = set(geo_ids), set(indicators)
        out: dict[tuple, Fact] = {}
        for fact in self._facts.values():
            if fact.geo_id not in geo_set or fact.indicator not in ind_set:
                continue
            skey = SectionContext.segment_key(fact.segment)
            if skey not in keys:
                continue
            if period is not None and fact.period != period:
                continue
            slot = (fact.geo_id, fact.indicator, skey)
            current = out.get(slot)
            if current is None or fact.period > current.period:
                out[slot] = fact
        return list(out.values())

    def freshness(self, indicators, geo_ids):
        out = dict.fromkeys(indicators)
        for fact in self._facts.values():
            if fact.indicator in out and fact.geo_id in set(geo_ids):
                current = out[fact.indicator]
                if current is None or fact.period > current:
                    out[fact.indicator] = fact.period
        return out

    def upsert_many(self, facts):
        for fact in facts:
            self._facts[self._key(fact)] = fact
        return len(facts)

    def coverage(self, geo_ids, indicators):
        cells = len(geo_ids) * len(indicators)
        if not cells:
            return 0.0
        filled = sum(
            1 for f in self._facts.values()
            if f.geo_id in set(geo_ids) and f.indicator in set(indicators) and f.value is not None
        )
        return min(filled / cells, 1.0)


class FakeIndicatorRepo:
    def __init__(self) -> None:
        from powergis.domain import indicators as catalog

        self._items = dict(catalog.BY_CODE)

    def get(self, code):
        return self._items.get(code)

    def by_section(self, section, tier=None):
        out = [i for i in self._items.values() if i.section is section]
        if tier:
            out = [i for i in out if i.tier in tier.includes]
        return out

    def all(self):
        return list(self._items.values())

    def upsert_many(self, indicators):
        for i in indicators:
            self._items[i.code] = i
        return len(indicators)


class FakeProjectRepo:
    def __init__(self) -> None:
        self._items: dict[UUID, Project] = {}

    def get(self, project_uuid):
        return self._items.get(project_uuid)

    def save(self, project):
        self._items[project.project_uuid] = project
        return project

    def set_tier(self, project_uuid, tier):
        if project_uuid in self._items:
            self._items[project_uuid].tier = tier


class FakeRunRepo:
    def __init__(self) -> None:
        self._items: dict[int, ReportRun] = {}
        self._next = 1

    def create(self, run):
        run.run_id = self._next
        self._next += 1
        self._items[run.run_id] = run
        return run

    def get(self, run_id):
        return self._items.get(run_id)

    def find_by_hash(self, project_uuid, input_hash):
        matches = [
            r for r in self._items.values()
            if r.project_uuid == project_uuid and r.input_hash == input_hash
        ]
        return matches[-1] if matches else None

    def update(self, run):
        self._items[run.run_id] = run
        return run

    def latest_for(self, project_uuid):
        matches = [r for r in self._items.values() if r.project_uuid == project_uuid]
        return matches[-1] if matches else None


class FakeSnapshotRepo:
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, int], tuple[Tier, dict]] = {}

    def save(self, project_uuid, version, tier, payload):
        self._items[(project_uuid, version)] = (tier, payload)

    def latest(self, project_uuid):
        versions = [v for (uid, v) in self._items if uid == project_uuid]
        if not versions:
            return None
        top = max(versions)
        tier, payload = self._items[(project_uuid, top)]
        return top, tier, payload

    def get(self, project_uuid, version):
        found = self._items.get((project_uuid, version))
        return found[1] if found else None

    def next_version(self, project_uuid):
        versions = [v for (uid, v) in self._items if uid == project_uuid]
        return (max(versions) if versions else 0) + 1


class FakeUnitOfWork:
    def __init__(self, geos, facts) -> None:
        self.geos = FakeGeoRepo(geos)
        self.facts = FakeFactRepo(facts)
        self.indicators = FakeIndicatorRepo()
        self.projects = FakeProjectRepo()
        self.runs = FakeRunRepo()
        self.snapshots = FakeSnapshotRepo()
        self.committed = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def commit(self):
        self.committed += 1

    def rollback(self):
        return None


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def geos() -> list[Geo]:
    """España → una CCAA → cuatro provincias."""
    return [
        Geo(1, GeoLevel.PAIS, "ES", "España", None, 48_000_000, 505_939),
        Geo(2, GeoLevel.CCAA, "13", "Comunidad de Madrid", 1, 6_871_000, 8_028),
        Geo(3, GeoLevel.PROVINCIA, "28", "Madrid", 2, 6_871_000, 8_028),
        Geo(4, GeoLevel.PROVINCIA, "45", "Toledo", 2, 730_000, 15_370),
        Geo(5, GeoLevel.PROVINCIA, "19", "Guadalajara", 2, 268_000, 12_167),
        Geo(6, GeoLevel.PROVINCIA, "05", "Ávila", 2, 158_000, 8_050),
    ]


def _fact(geo_id: int, code: str, value: float | None, segment=None) -> Fact:
    return Fact(geo_id=geo_id, indicator=code, period=PERIOD, value=value,
                segment=segment or {}, source_ref="TEST")


@pytest.fixture
def facts(geos) -> list[Fact]:
    data = {
        3: {"dem.pop.total": 6_871_000, "dem.age.0_15": 1_030_000, "dem.age.16_64": 4_500_000,
            "dem.age.65p": 1_341_000, "dem.sex.women": 3_570_000, "dem.sex.men": 3_301_000,
            "dem.age.mean": 42.1, "dem.edu.university_pct": 38.0,
            "eco.income.household.mean": 47_000, "eco.income.household.median": 41_000,
            "eco.gini": 0.33, "cmp.count": 900, "cli.temp.annual": 15.0,
            "cli.sun.days": 200, "cli.rain.days": 63},
        4: {"dem.pop.total": 730_000, "dem.age.0_15": 118_000, "dem.age.16_64": 470_000,
            "dem.age.65p": 142_000, "dem.sex.women": 364_000, "dem.sex.men": 366_000,
            "dem.age.mean": 43.5, "dem.edu.university_pct": 21.0,
            "eco.income.household.mean": 30_000, "eco.income.household.median": 27_500,
            "eco.gini": 0.29, "cmp.count": 210, "cli.temp.annual": 15.6,
            "cli.sun.days": 190, "cli.rain.days": 58},
        5: {"dem.pop.total": 268_000, "dem.age.0_15": 44_000, "dem.age.16_64": 172_000,
            "dem.age.65p": 52_000, "dem.sex.women": 132_000, "dem.sex.men": 136_000,
            "dem.age.mean": 43.0, "dem.edu.university_pct": 24.0,
            "eco.income.household.mean": 33_500, "eco.income.household.median": 30_000,
            "eco.gini": 0.28, "cmp.count": 95, "cli.temp.annual": 13.4,
            "cli.sun.days": 180, "cli.rain.days": 70},
        6: {"dem.pop.total": 158_000, "dem.age.0_15": 20_000, "dem.age.16_64": 95_000,
            "dem.age.65p": 43_000, "dem.sex.women": 78_000, "dem.sex.men": 80_000,
            "dem.age.mean": 47.9, "dem.edu.university_pct": 19.0,
            # Ávila sin renta: simula el secreto estadístico del ADRH.
            "eco.income.household.mean": None, "eco.income.household.median": None,
            "eco.gini": None, "cmp.count": 40, "cli.temp.annual": 11.2,
            "cli.sun.days": 165, "cli.rain.days": 78},
    }
    out: list[Fact] = []
    for geo_id, values in data.items():
        for code, value in values.items():
            out.append(_fact(geo_id, code, value))
        pop = values["dem.pop.total"]
        out.append(_fact(geo_id, "dem.pop.segment", pop * 0.24))
        for age, share in (("18-35", 0.24), ("36-55", 0.30)):
            out.append(_fact(geo_id, "dem.pop.segment", pop * share, {"age": age}))
            for sex, split in (("F", 0.51), ("M", 0.49)):
                out.append(_fact(geo_id, "dem.pop.segment", pop * share * split,
                                 {"age": age, "sex": sex}))
    return out


@pytest.fixture
def uow(geos, facts) -> FakeUnitOfWork:
    return FakeUnitOfWork(geos, facts)


@pytest.fixture
def uow_factory(uow):
    return lambda: uow


@pytest.fixture
def project() -> Project:
    return Project(
        project_uuid=uuid4(),
        wp_user_id=7,
        wp_post_id=7818,
        scope=Scope(GeoLevel.CCAA, "13", GeoLevel.PROVINCIA),
        segments=Segments(age=("18-35",), sex=("F", "M")),
        business=BusinessProfile(sector="restauracion", avg_ticket=18.5, surface_m2=90),
        tier=Tier.BASICO,
    )


@pytest.fixture
def context(uow, project) -> SectionContext:
    from powergis.application.context import build_context

    return build_context(uow, project, tier=Tier.AVANZADO)


@pytest.fixture
def advanced_project(project) -> Project:
    project.tier = Tier.AVANZADO
    return project


__all__ = [
    "PERIOD",
    "FakeFactRepo",
    "FakeGeoRepo",
    "FakeUnitOfWork",
    "RunStatus",
    "Section",
    "Tier",
]
