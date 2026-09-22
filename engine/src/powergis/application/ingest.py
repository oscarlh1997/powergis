"""Caso de uso: ingesta (ETL).

Corre en su propia cola, con concurrencia 1 y de madrugada. Una carga masiva
del INE no puede dejar a un cliente esperando su informe: por eso las colas
están separadas.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from ..domain import indicators as catalog_mod
from ..domain.enums import GeoLevel
from ..domain.errors import CollectorError, CollectorUnavailable, GeoNotFound
from ..domain.models import Fact, Geo
from ..domain.ports import Collector, UnitOfWork

log = logging.getLogger(__name__)


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

        # Un colector de tablas NACIONALES recibe siempre el nivel entero,
        # aunque la carga la pida un informe de una sola provincia. La tabla
        # se descarga entera igual, y con sólo las geografías del ámbito el
        # índice de nombres no ve los homónimos de fuera: el Castejón de
        # Cuenca parecía único cargando Navarra y se quedaba el dato del otro.
        todas = getattr(collector, "TODAS_LAS_GEOS", False)
        geos = self._target_geos(level, None if todas else parent_code)
        if not geos:
            report.errors.append("No hay geografías para ese ámbito")
            report.finished_at = datetime.now(UTC)
            return report

        from ..domain.models import Segments

        # Las tablas nacionales se leen de una vez y con todas las geografías
        # delante: ver `BaseCollector.TODAS_LAS_GEOS`. La escritura sigue
        # troceada, en `upsert_many`.
        lotes = [list(geos)] if getattr(collector, "TODAS_LAS_GEOS", False) else _chunks(
            geos, self._batch_size
        )
        for chunk in lotes:
            try:
                facts = collector.collect(codes, chunk, Segments(), period)
            except CollectorUnavailable as exc:
                report.errors.append(f"{collector_name}: {exc.message} (reintentar)")
                raise
            except CollectorError as exc:
                report.errors.append(f"{collector_name}: {exc.message}")
                continue
            report.errors.extend(
                f"{collector_name}: {fallo}" for fallo in getattr(collector, "fallos", [])
            )

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
        from ..domain import derivados, stats

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
                "dem.age.u18_pct", "dem.age.65p_pct",
                "dem.sex.women", "dem.sex.men", "dem.pop.segment",
            ]
            facts = uow.facts.fetch(geo_ids, base_codes, [{}])
            index = {(f.geo_id, f.indicator): f.value for f in facts}
            periodos = {
                (f.geo_id, f.indicator): f.period for f in facts if f.value is not None
            }
            period = max((f.period for f in facts), default=date.today())

            derived: list[Fact] = []
            areas = {g.geo_id: g.area_km2 for g in geos}
            for geo_id in geo_ids:
                # `current` se liga por valor: sin esto la clausura leería la
                # última iteración del bucle.
                def v(code: str, current: int = geo_id) -> float | None:
                    return index.get((current, code))

                # La misma función que el colector de derivados: si la fórmula
                # viviera en dos sitios, acabaría dando dos resultados.
                dependencia, envejecimiento, activo = stats.razones_de_edad(v)

                pairs = {
                    "dem.age.18_64_pct": activo,
                    "dem.dependency.total": dependencia,
                    "dem.ageing.index": envejecimiento,
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
                    # Con la fecha de SUS datos: ver `domain.derivados`.
                    fechas = [
                        p for c in derivados.ENTRADAS.get(code, ())
                        if (p := periodos.get((geo_id, c))) is not None
                    ]
                    cuando = max(fechas) if fechas else period
                    derived.append(
                        Fact(
                            geo_id=geo_id, indicator=code, period=cuando,
                            value=value, segment={}, source_ref="derivado",
                            ingested_at=datetime.now(UTC),
                        )
                    )

            written = uow.facts.upsert_many(derived)
            uow.commit()
            return written


# --------------------------------------------------------------------------- #
# Agregación a provincia, comunidad y país
# --------------------------------------------------------------------------- #


class AggregateUp:
    """Escribe en provincias, comunidades y país lo que se sabe por municipio.

    Las reglas —qué se suma, qué se promedia y con qué peso, qué no se toca—
    viven en `domain.agregacion`. Aquí sólo se lee y se escribe.

    Nunca pisa un dato propio del nivel: si una provincia tiene su población
    de una fuente provincial, esa manda y el agregado no se escribe.
    """

    NIVELES = (GeoLevel.PROVINCIA, GeoLevel.CCAA, GeoLevel.PAIS)

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def __call__(self) -> dict[str, int]:
        from ..domain import agregacion

        escritos: dict[str, int] = {}
        with self._uow_factory() as uow:
            root = uow.geos.get(GeoLevel.PAIS, "ES")
            if root is None:
                raise GeoNotFound("Falta la geografía raíz; ejecuta `powergis seed`")

            municipios = uow.geos.descendants(root.geo_id, GeoLevel.MUNICIPIO)
            codigos = agregacion.codigos_necesarios()
            hechos = uow.facts.fetch([g.geo_id for g in municipios], codigos, [{}])
            por_municipio: dict[int, dict[str, tuple[float | None, date]]] = {}
            for f in hechos:
                por_municipio.setdefault(f.geo_id, {})[f.indicator] = (f.value, f.period)
            sin_nada = sum(
                1 for g in municipios
                if not any(v is not None for v, _ in por_municipio.get(g.geo_id, {}).values())
            )
            if sin_nada:
                log.warning(
                    "Agregación: %d de %d municipios sin ningún dato; no cuentan en las "
                    "sumas (fusionados o desaparecidos, o series sin resolver: revisa "
                    "los avisos de la carga)", sin_nada, len(municipios),
                )

            for nivel in self.NIVELES:
                padres = [root] if nivel == GeoLevel.PAIS else uow.geos.descendants(
                    root.geo_id, nivel
                )
                if not padres:
                    continue
                existentes = uow.facts.fetch(
                    [p.geo_id for p in padres], list(agregacion.REGLAS), [{}]
                )
                propios = {
                    (f.geo_id, f.indicator) for f in existentes
                    if f.value is not None
                    and not (f.source_ref or "").startswith(agregacion.PREFIJO_FUENTE)
                    and f.source_ref != "DEMO-SINTÉTICO"
                }

                nuevos: list[Fact] = []
                for padre in padres:
                    hijos = municipios if nivel == GeoLevel.PAIS else uow.geos.descendants(
                        padre.geo_id, GeoLevel.MUNICIPIO
                    )
                    valores = agregacion.agregar(
                        [por_municipio.get(h.geo_id, {}) for h in hijos]
                    )
                    for codigo, (valor, periodo, fuente) in valores.items():
                        if (padre.geo_id, codigo) in propios:
                            continue
                        if codigo not in catalog_mod.BY_CODE:
                            continue
                        nuevos.append(Fact(
                            geo_id=padre.geo_id, indicator=codigo, period=periodo,
                            value=valor, segment={}, source_ref=fuente,
                            ingested_at=datetime.now(UTC),
                        ))
                escritos[str(nivel)] = uow.facts.upsert_many(nuevos)
            uow.commit()
        return escritos


def _first_match(uow: UnitOfWork, code: str) -> Geo | None:
    for level in (GeoLevel.CCAA, GeoLevel.PROVINCIA, GeoLevel.MUNICIPIO, GeoLevel.PAIS):
        geo = uow.geos.get(level, code)
        if geo is not None:
            return geo
    return None


def _chunks(items: Sequence, size: int):
    for i in range(0, len(items), size):
        yield list(items[i:i + size])
