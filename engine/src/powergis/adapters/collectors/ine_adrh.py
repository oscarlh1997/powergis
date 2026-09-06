"""Atlas de Distribución de Renta de los Hogares (ADRH) del INE.

Es la fuente REAL de los datos económicos del informe — no Overpass, que da
POIs, no renta. Publica renta media, mediana, per cápita, distribución por
tramos y Gini a nivel de municipio, distrito y **sección censal**.

Tres avisos que están implementados, no solo documentados:

1. Es **estadística experimental** con ~2 años de desfase. El periodo del dato
   se guarda tal cual; el informe muestra el año.
2. Hay **secreto estadístico** en unidades pequeñas: el ADRH no publica. Aquí
   se emite un `Fact` con `value=None`, nunca un cero. La UI lo muestra como
   «no disponible».
3. Los IDs de tabla cambian al republicar. Se sobreescriben por entorno.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ...config import get_settings
from ...domain.errors import CollectorError
from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector, HttpClient

log = logging.getLogger(__name__)

SECRETO_MARKERS = {"..", ".", "", "-", "n/a"}


@dataclass(frozen=True, slots=True)
class AdrhSpec:
    table_id: str
    indicator: str
    match: tuple[str, ...]
    level: str = "municipio"
    scale: float = 1.0

    @property
    def env_key(self) -> str:
        return f"ADRH_TABLE_{self.indicator.upper().replace('.', '_')}"

    def resolved_id(self) -> str:
        return os.getenv(self.env_key, self.table_id)


SPECS: tuple[AdrhSpec, ...] = (
    AdrhSpec("30824", "eco.income.household.mean", ("renta neta media por hogar",)),
    AdrhSpec("30824", "eco.income.percapita", ("renta neta media por persona",)),
    AdrhSpec("30832", "eco.income.household.median", ("mediana",)),
    AdrhSpec("37677", "eco.gini", ("gini",)),
    AdrhSpec("37677", "eco.nse.risk_pct", ("riesgo de pobreza",)),
    AdrhSpec("30833", "eco.income.under15k_pct", ("menos de 15",)),
    AdrhSpec("30833", "eco.income.over30k_pct", ("más de 30",)),
    AdrhSpec("30833", "eco.income.over60k_pct", ("más de 60",)),
)


class AdrhCollector(BaseCollector):
    name = "ine_adrh"
    PROVIDES = tuple({s.indicator for s in SPECS})

    def __init__(self, client: HttpClient | None = None) -> None:
        cfg = get_settings()
        self._client = client or HttpClient(
            cfg.ine_base_url, timeout=cfg.ine_timeout,
            max_retries=cfg.ine_max_retries, rps=cfg.ine_rps,
        )

    def collect(
        self,
        indicators: Sequence[str],
        geos: Sequence[Geo],
        segments: Segments,
        period: date | None = None,
    ) -> list[Fact]:
        wanted = set(indicators) & set(self.PROVIDES)
        if not wanted or not geos:
            return []

        index = {g.ine_code: g for g in geos}
        index.update({g.ine_code.zfill(5): g for g in geos})
        facts: list[Fact] = []
        suppressed = 0

        for spec in SPECS:
            if spec.indicator not in wanted:
                continue
            try:
                rows = self._client.get_json(
                    f"DATOS_TABLA/{spec.resolved_id()}", {"nult": 1, "tip": "A", "det": 2}
                )
            except CollectorError as exc:
                log.warning("ADRH %s: %s", spec.indicator, exc.message)
                continue

            for row in rows if isinstance(rows, list) else []:
                name = str(row.get("Nombre", ""))
                if not any(token in name.lower() for token in spec.match):
                    continue
                geo = self._geo_of(name, index)
                if geo is None:
                    continue
                for point in row.get("Data", []):
                    raw = point.get("Valor")
                    value = self.to_float(raw)
                    if value is None and str(raw).strip().lower() in SECRETO_MARKERS:
                        suppressed += 1
                    facts.append(
                        self.fact(
                            geo, spec.indicator,
                            None if value is None else value * spec.scale,
                            period or self._period(point),
                            None,
                            source_ref=f"INE:ADRH:{spec.resolved_id()}",
                        )
                    )

        if suppressed:
            log.info(
                "ADRH: %s valores no publicados por secreto estadístico "
                "(se guardan como NULL, no como 0)", suppressed,
            )
        return facts

    @staticmethod
    def _period(point: dict[str, Any]) -> date:
        year = point.get("Anyo") or point.get("anyo")
        try:
            return date(int(year), 1, 1)
        except (TypeError, ValueError):
            return date.today()

    @staticmethod
    def _geo_of(name: str, index: dict[str, Geo]) -> Geo | None:
        head = name.split(".")[0].strip()
        token = head.split(" ")[0].strip()
        if token.isdigit():
            return index.get(token) or index.get(token.zfill(5))
        lowered = head.lower()
        for geo in index.values():
            if geo.name.lower() == lowered:
                return geo
        return None
