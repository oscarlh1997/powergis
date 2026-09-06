"""Caso de uso: ingesta (ETL).

Corre en su propia cola, con concurrencia 1 y de madrugada. Una carga masiva
del INE no puede dejar a un cliente esperando su informe: por eso las colas
están separadas.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from ..domain import indicators as catalog_mod
from ..domain.enums import GeoLevel
from ..domain.errors import CollectorError, CollectorUnavailable, GeoNotFound
from ..domain.models import Fact, Geo
from ..domain.ports import Collector, UnitOfWork


@dataclass(slots=True)
class IngestReport:
    collector: str
    requested: list[str]
    written: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "collector": self.collector,
            "requested": self.requested,
            "written": self.written,
            "skipped": self.skipped,
            "errors": self.errors,
            "seconds": (
                (self.finished_at - self.started_at).total_seconds()
                if self.finished_at else None
            ),
        }


class IngestData:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        collectors: dict[str, Collector],
        *,
        batch_size: int = 500,
    ) -> None:
        self._uow_factory = uow_factory
        self._collectors = collectors
        self._batch_size = batch_size

    # ------------------------------------------------------------------ #

    def by_collector(
        self,
        collector_name: str,
        indicators: Sequence[str],
        level: GeoLevel,
        parent_code: str | None = None,
        period: date | None = None,
    ) -> IngestReport:
        collector = self._collectors.get(collector_name)
        if collector is None:
            raise CollectorError("Colector desconocido", collector=collector_name)

        codes = list(indicators) or collector.provides()
        codes = [c for c in codes if c in collector.provides()]
        report = IngestReport(collector=collector_name, requested=codes)
        if not codes:
            report.finished_at = datetime.now(UTC)
            return report

        geos = self._target_geos(level, parent_code)
        if not geos:
            report.errors.append("No hay geografías para ese ámbito")
            report.finished_at = datetime.now(UTC)
            return report

        from ..domain.models import Segments

        for chunk in _chunks(geos, self._batch_size):
            try:
                facts = collector.collect(codes, chunk, Segments(), period)
            except CollectorUnavailable as exc:
                report.errors.append(f"{collector_name}: {exc.message} (reintentar)")
                raise
            except CollectorError as exc:
                report.errors.append(f"{collector_name}: {exc.message}")
                continue

            written = self._persist(facts)
            report.written += written

        report.finished_at = datetime.now(UTC)
        return report

    def by_indicators(
        self,
        indicators: Sequence[str],
        level: GeoLevel,
        parent_code: str | None = None,
        period: date | None = None,
    ) -> list[IngestReport]:
        """Enruta cada indicador a quien sabe cargarlo."""
        plan = self.plan(indicators)
        reports: list[IngestReport] = []
        for name, codes in plan.items():
            reports.append(self.by_collector(name, codes, level, parent_code, period))
        return reports

    def plan(self, indicators: Sequence[str]) -> dict[str, list[str]]:
        """Reparte indicadores entre colectores. Los derivados se calculan aparte."""
        out: dict[str, list[str]] = {}
        for code in indicators:
            for name, collector in self._collectors.items():
                if code in collector.provides():
                    out.setdefault(name, []).append(code)
                    break
        return out

    def unroutable(self, indicators: Sequence[str]) -> list[str]:
        routed = {c for codes in self.plan(indicators).values() for c in codes}
        return [c for c in indicators if c not in routed]

    # ------------------------------------------------------------------ #

    def _target_geos(self, level: GeoLevel, parent_code: str | None) -> list[Geo]:
        with self._uow_factory() as uow:
            if parent_code is None:
                root = uow.geos.get(GeoLevel.PAIS, "ES")
                if root is None:
                    raise GeoNotFound("Falta la geografía raíz; ejecuta `powergis seed`")
                return uow.geos.descendants(root.geo_id, level)
            for candidate in (GeoLevel.CCAA, GeoLevel.PROVINCIA, GeoLevel.MUNICIPIO, GeoLevel.PAIS):
                parent = uow.geos.get(candidate, parent_code)
                if parent is not None:
                    return uow.geos.descendants(parent.geo_id, level)
        return []

    def _persist(self, facts: Sequence[Fact]) -> int:
        if not facts:
            return 0
        with self._uow_factory() as uow:
            written = uow.facts.upsert_many(facts)
            uow.commit()
        return written


# --------------------------------------------------------------------------- #
# Indicadores derivados
# --------------------------------------------------------------------------- #


class ComputeDerived:
    """Calcula los indicadores con `formula` a partir de los ya cargados.

    Se ejecuta al final de cada ingesta. Mantiene la regla de oro: los
    derivados también viven en `fact_indicator`, así el informe no tiene que
    saber cuáles son primarios y cuáles calculados.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def __call__(self, level: GeoLevel, parent_code: str | None = None) -> int:
        from ..domain import stats

        with self._uow_factory() as uow:
            root = (
                uow.geos.get(GeoLevel.PAIS, "ES")
                if parent_code is None
                else _first_match(uow, parent_code)
            )
            if root is None:
                return 0
            geos = uow.geos.descendants(root.geo_id, level)
            geo_ids = [g.geo_id for g in geos]
            base_codes = [
                "dem.pop.total", "dem.age.0_15", "dem.age.16_64", "dem.age.65p",
                "dem.sex.women", "dem.sex.men", "dem.pop.segment",
            ]
            facts = uow.facts.fetch(geo_ids, base_codes, [{}])
            index = {(f.geo_id, f.indicator): f.value for f in facts}
            period = max((f.period for f in facts), default=date.today())

            derived: list[Fact] = []
            areas = {g.geo_id: g.area_km2 for g in geos}
            for geo_id in geo_ids:
                # `current` se liga por valor: sin esto la clausura leería la
                # última iteración del bucle.
                def v(code: str, current: int = geo_id) -> float | None:
                    return index.get((current, code))

                pairs = {
                    "dem.dependency.total": stats.dependency_ratio(
                        v("dem.age.0_15"), v("dem.age.16_64"), v("dem.age.65p")
                    ),
                    "dem.ageing.index": stats.ageing_index(v("dem.age.65p"), v("dem.age.0_15")),
                    "dem.femininity.index": stats.femininity_index(
                        v("dem.sex.women"), v("dem.sex.men")
                    ),
                    "dem.sex.women_pct": stats.relative_share(
                        v("dem.sex.women"), v("dem.pop.total")
                    ),
                    "dem.pop.density": stats.density(v("dem.pop.total"), areas.get(geo_id)),
                    "dem.pop.segment_pct": stats.relative_share(
                        v("dem.pop.segment"), v("dem.pop.total")
                    ),
                }
                for code, value in pairs.items():
                    if value is None or code not in catalog_mod.BY_CODE:
                        continue
                    derived.append(
                        Fact(
                            geo_id=geo_id, indicator=code, period=period,
                            value=value, segment={}, source_ref="derivado",
                            ingested_at=datetime.now(UTC),
                        )
                    )

            written = uow.facts.upsert_many(derived)
            uow.commit()
            return written


def _first_match(uow: UnitOfWork, code: str) -> Geo | None:
    for level in (GeoLevel.CCAA, GeoLevel.PROVINCIA, GeoLevel.MUNICIPIO, GeoLevel.PAIS):
        geo = uow.geos.get(level, code)
        if geo is not None:
            return geo
    return None


def _chunks(items: Sequence, size: int):
    for i in range(0, len(items), size):
        yield list(items[i:i + size])
