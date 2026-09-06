"""Colector del Catastro y del DIRCE (demografía empresarial del INE).

Cubre lo que OSM no puede dar: parque de locales comerciales, ocupación,
rotación empresarial y supervivencia a tres años. Es la respuesta honesta a
las métricas de la maqueta que no existen en fuente abierta con granularidad
fina.

Lo que SÍ hay:
* Catastro (Sede Electrónica / servicios INSPIRE): número y superficie de
  inmuebles por uso, a nivel de municipio y referencia catastral.
* INE/DIRCE: altas, bajas y supervivencia de empresas, a nivel provincial.

Lo que NO hay y por tanto se marca como estimación:
* Precio de alquiler comercial por m². No existe fuente pública con esta
  granularidad. Se modela desde renta y densidad, y viaja siempre con
  `source_ref = "estimación modelada"`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date

from ...config import get_settings
from ...domain import stats
from ...domain.errors import CollectorError
from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector, HttpClient

log = logging.getLogger(__name__)

MODELLED_REF = "estimación modelada · elaboración propia"


class CatastroCollector(BaseCollector):
    name = "catastro"
    PROVIDES = (
        "sat.available_units", "sat.occupancy", "sat.rent_m2",
        "sat.turnover", "sat.survival3y",
    )

    def __init__(self, client: HttpClient | None = None, facts_lookup=None) -> None:
        cfg = get_settings()
        self._client = client or HttpClient(
            cfg.catastro_wfs_url, timeout=60, max_retries=3, rps=1.0
        )
        self._ine = HttpClient(cfg.ine_base_url, timeout=cfg.ine_timeout, rps=cfg.ine_rps)
        self._lookup = facts_lookup or (lambda geo_id, code: None)

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

        when = period or date.today()
        out: list[Fact] = []

        for geo in geos:
            try:
                out.extend(self._commercial_stock(geo, wanted, when))
            except CollectorError as exc:
                log.warning("Catastro %s: %s", geo.ine_code, exc.message)
            out.extend(self._modelled(geo, wanted, when))

        if {"sat.turnover", "sat.survival3y"} & wanted:
            out.extend(self._dirce(geos, wanted, when))
        return out

    # ------------------------------------------------------------------ #

    def _commercial_stock(self, geo: Geo, wanted: set[str], when: date) -> list[Fact]:
        """Inmuebles de uso comercial. Requiere el servicio WFS del Catastro.

        Se deja aislado para que un fallo de Catastro no impida el resto de la
        sección: sin stock, `sat.occupancy` simplemente no se emite.
        """
        if not {"sat.available_units", "sat.occupancy"} & wanted:
            return []
        # El servicio INSPIRE del Catastro devuelve GML por municipio. La
        # implementación completa exige parsear GML y filtrar por uso; se deja
        # el punto de extensión explícito en vez de fingir un dato.
        log.debug("Catastro: stock comercial pendiente de implementar para %s", geo.ine_code)
        return []

    def _modelled(self, geo: Geo, wanted: set[str], when: date) -> list[Fact]:
        """Precio de alquiler estimado. Declarado como estimación, siempre."""
        if "sat.rent_m2" not in wanted:
            return []
        income = self._lookup(geo.geo_id, "eco.income.household.median")
        density = self._lookup(geo.geo_id, "dem.pop.density")
        if income is None:
            return []
        # Modelo simple y auditable: el alquiler comercial escala con la renta
        # mediana y, más suavemente, con la densidad de población.
        base = income / 1000.0 * 0.42
        if density:
            base *= 1.0 + min(density / 5000.0, 1.2)
        return [self.fact(geo, "sat.rent_m2", round(base, 2), when, None, MODELLED_REF)]

    def _dirce(self, geos: Sequence[Geo], wanted: set[str], when: date) -> list[Fact]:
        """Rotación y supervivencia empresarial (INE/DIRCE, nivel provincial)."""
        out: list[Fact] = []
        try:
            rows = self._ine.get_json("DATOS_TABLA/28981", {"nult": 1, "tip": "A"})
        except CollectorError as exc:
            log.warning("DIRCE: %s", exc.message)
            return out

        by_name = {g.name.lower(): g for g in geos}
        for row in rows if isinstance(rows, list) else []:
            name = str(row.get("Nombre", "")).lower()
            geo = next((g for key, g in by_name.items() if key and key in name), None)
            if geo is None:
                continue
            for point in row.get("Data", []):
                value = self.to_float(point.get("Valor"))
                if value is None:
                    continue
                if "supervivencia" in name and "sat.survival3y" in wanted:
                    out.append(self.fact(geo, "sat.survival3y", value, when, None, "INE:DIRCE"))
                elif ("baja" in name or "rotación" in name) and "sat.turnover" in wanted:
                    out.append(self.fact(geo, "sat.turnover", value, when, None, "INE:DIRCE"))
        return out


def estimate_isc(
    competitors: float | None,
    population: float | None,
    sector_penetration: float = 0.0012,
) -> float | None:
    """Índice de saturación comercial: oferta / demanda potencial.

    `sector_penetration` es cuántos locales por habitante soporta el sector en
    equilibrio; sale de la media nacional y se recalibra por sector.
    """
    if competitors is None or not population:
        return None
    expected = population * sector_penetration
    return stats.safe_div(competitors, expected)
