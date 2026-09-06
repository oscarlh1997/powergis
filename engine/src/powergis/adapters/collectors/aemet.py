"""Colector de AEMET OpenData — normales climatológicas.

Patrón de dos saltos, propio de AEMET: la primera respuesta no trae datos,
trae una URL temporal en el campo `datos`; el JSON real está ahí.

Se cargan las normales 1991-2020 de todas las estaciones **una sola vez** y se
asignan a cada geografía por estación más cercana ponderada por altitud. Con
eso hay clima para siempre, con refresco anual. Llamar a AEMET durante la
generación de un informe no tiene sentido: el clima no cambia entre dos
peticiones.

Requiere API key gratuita (`AEMET_API_KEY`). Atribución obligatoria: © AEMET.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ...config import get_settings
from ...domain import stats
from ...domain.errors import CollectorError
from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector, HttpClient

log = logging.getLogger(__name__)

ATTRIBUTION = "© Agencia Estatal de Meteorología (AEMET)"
NORMALS_PERIOD = date(2020, 1, 1)  # normales 1991-2020


@dataclass(frozen=True, slots=True)
class Station:
    code: str
    name: str
    lat: float
    lon: float
    altitude: float
    province: str = ""


class AemetCollector(BaseCollector):
    name = "aemet"
    PROVIDES = (
        "cli.temp.annual", "cli.temp.month", "cli.precip.annual", "cli.precip.month",
        "cli.rain.days", "cli.sun.days", "cli.comfort.index", "cli.seasonality.index",
    )

    def __init__(
        self,
        client: HttpClient | None = None,
        centroids: dict[int, tuple[float, float, float]] | None = None,
    ) -> None:
        """`centroids` mapea geo_id → (lat, lon, altitud_m).

        Lo rellena el worker con una consulta a PostGIS
        (`ST_Y(centroid), ST_X(centroid)`). Sin él, la asignación de estación
        cae a una heurística y se registra un aviso: en producción SIEMPRE se
        pasa, porque asignar mal la estación es asignar mal el clima.
        """
        cfg = get_settings()
        self._centroids = centroids or {}
        self._api_key = cfg.aemet_api_key
        self._client = client or HttpClient(
            cfg.aemet_base_url,
            timeout=cfg.aemet_timeout,
            max_retries=3,
            rps=0.5,
            headers={"api_key": cfg.aemet_api_key} if cfg.aemet_api_key else {},
        )
        self._stations: list[Station] | None = None

    # ------------------------------------------------------------------ #

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
        if not self._api_key:
            log.warning("AEMET sin API key: se omite la carga de clima")
            return []

        stations = self._load_stations()
        if not stations:
            return []

        when = period or NORMALS_PERIOD
        facts: list[Fact] = []
        cache: dict[str, dict[str, Any]] = {}

        for geo in geos:
            station = self._nearest(geo, stations)
            if station is None:
                continue
            if station.code not in cache:
                try:
                    cache[station.code] = self._normals(station.code)
                except CollectorError as exc:
                    log.warning("AEMET estación %s: %s", station.code, exc.message)
                    cache[station.code] = {}
            facts.extend(self._map(geo, cache[station.code], wanted, when, station))
        return facts

    # ------------------------------------------------------------------ #

    def _load_stations(self) -> list[Station]:
        if self._stations is not None:
            return self._stations
        try:
            payload = self._follow("/valores/climatologicos/inventarioestaciones/todasestaciones")
        except CollectorError as exc:
            log.warning("AEMET inventario: %s", exc.message)
            self._stations = []
            return self._stations

        out: list[Station] = []
        for row in payload if isinstance(payload, list) else []:
            try:
                out.append(
                    Station(
                        code=str(row["indicativo"]),
                        name=str(row.get("nombre", "")),
                        lat=_dms(row.get("latitud")),
                        lon=_dms(row.get("longitud")),
                        altitude=float(row.get("altitud") or 0),
                        province=str(row.get("provincia", "")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        self._stations = out
        log.info("AEMET: %s estaciones cargadas", len(out))
        return out

    def _normals(self, station_code: str) -> dict[str, Any]:
        rows = self._follow(
            f"/valores/climatologicos/normales/estacion/{station_code}"
        )
        return {str(r.get("mes", "")).zfill(2): r for r in rows if isinstance(r, dict)}

    def _follow(self, path: str) -> Any:
        """Los dos saltos de AEMET: metadatos → URL temporal → datos."""
        head = self._client.get_json(path)
        if isinstance(head, dict) and head.get("estado") not in (200, None):
            raise CollectorError(
                "AEMET rechazó la petición",
                status=head.get("estado"),
                descripcion=head.get("descripcion"),
            )
        url = head.get("datos") if isinstance(head, dict) else None
        if not url:
            raise CollectorError("AEMET no devolvió URL de datos", path=path)
        return self._client.get_json(url)

    # ------------------------------------------------------------------ #

    def _map(
        self,
        geo: Geo,
        normals: dict[str, Any],
        wanted: set[str],
        when: date,
        station: Station,
    ) -> list[Fact]:
        if not normals:
            return []
        ref = f"AEMET:{station.code} · {ATTRIBUTION}"
        out: list[Fact] = []
        months = [f"{m:02d}" for m in range(1, 13)]

        temps: list[float | None] = []
        precs: list[float | None] = []
        for month in months:
            row = normals.get(month) or {}
            temp = self.to_float(row.get("tm_mes"))
            prec = self.to_float(row.get("p_mes"))
            temps.append(temp)
            precs.append(prec)
            if "cli.temp.month" in wanted:
                out.append(self.fact(geo, "cli.temp.month", temp, when, {"month": month}, ref))
            if "cli.precip.month" in wanted:
                out.append(self.fact(geo, "cli.precip.month", prec, when, {"month": month}, ref))

        annual = normals.get("13") or {}  # AEMET usa el mes 13 para el anual
        if "cli.temp.annual" in wanted:
            value = self.to_float(annual.get("tm_mes")) or stats.mean(temps)
            out.append(self.fact(geo, "cli.temp.annual", value, when, None, ref))
        if "cli.precip.annual" in wanted:
            value = self.to_float(annual.get("p_mes")) or stats.total(precs)
            out.append(self.fact(geo, "cli.precip.annual", value, when, None, ref))
        if "cli.rain.days" in wanted:
            days = stats.total(self.to_float((normals.get(m) or {}).get("n_llu")) for m in months)
            out.append(self.fact(geo, "cli.rain.days", days, when, None, ref))
        if "cli.sun.days" in wanted:
            days = stats.total(self.to_float((normals.get(m) or {}).get("n_des")) for m in months)
            out.append(self.fact(geo, "cli.sun.days", days, when, None, ref))
        if "cli.comfort.index" in wanted:
            comfortable = sum(1 for t in temps if t is not None and 15.0 <= t <= 27.0)
            out.append(self.fact(
                geo, "cli.comfort.index", comfortable / 12.0 * 100.0, when, None, ref
            ))
        if "cli.seasonality.index" in wanted:
            out.append(self.fact(geo, "cli.seasonality.index", stats.stddev(temps), when, None, ref))

        return out

    def _nearest(self, geo: Geo, stations: Sequence[Station]) -> Station | None:
        """Estación más cercana penalizando la diferencia de altitud.

        Sin la penalización, un municipio de montaña hereda el clima del valle
        de al lado: 800 m de desnivel son varios grados de diferencia.
        """
        if not stations:
            return None

        centroid = self._centroids.get(geo.geo_id)
        if centroid is None:
            log.debug("AEMET: sin centroide para %s; asignación aproximada", geo.ine_code)
            return min(stations, key=lambda s: _name_proxy(geo, s))

        lat, lon, altitude = centroid
        def cost(station: Station) -> float:
            km = haversine_km(lat, lon, station.lat, station.lon)
            # 100 m de desnivel penalizan como 5 km de distancia.
            return km + abs(altitude - station.altitude) / 100.0 * 5.0

        return min(stations, key=cost)


def _name_proxy(geo: Geo, station: Station) -> float:
    """Respaldo cuando faltan centroides: coincidencia por provincia."""
    return 0.0 if station.province.lower()[:4] in geo.name.lower() else 1.0


def _dms(raw: Any) -> float:
    """AEMET da coordenadas como '404425N' (grados, minutos, segundos + hemisferio)."""
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if not text:
        return 0.0
    hemisphere = text[-1].upper()
    digits = text[:-1]
    if not digits.isdigit() or len(digits) < 6:
        try:
            return float(text)
        except ValueError:
            return 0.0
    degrees = int(digits[0:2])
    minutes = int(digits[2:4])
    seconds = int(digits[4:6])
    value = degrees + minutes / 60 + seconds / 3600
    return -value if hemisphere in {"S", "W", "O"} else value


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
