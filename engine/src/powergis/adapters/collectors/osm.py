"""Colector de OpenStreetMap: competencia, anclas y tráfico.

Dos modos, y el que importa es el segundo:

* `OverpassSource` — instancia pública. Sirve para desarrollo. Su límite
  orientativo es < 10.000 consultas/día y < 1 GB/día, con HTTP 429 cuando te
  pasas. **No es aceptable para un producto de pago.**
* `LocalPostgisSource` — extracto de España de Geofabrik cargado en tu propio
  PostGIS (osmium + osm2pgsql), actualizado semanalmente. Consultas locales,
  instantáneas y sin límites. Es lo que se usa en producción (`USE_LOCAL_OSM=1`).

Licencia: OSM es ODbL. Obliga a atribución («© Colaboradores de
OpenStreetMap») en el mapa y en el informe, y la cláusula de compartir-igual
entra si se redistribuye la base de datos derivada. Un informe con recuentos
agregados es normalmente *produced work* (basta atribuir); exportar un Excel
con la lista completa de POIs se acerca a redistribuir datos. Por eso el
exportador solo saca agregados.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from datetime import date
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...config import get_settings
from ...domain import stats
from ...domain.errors import CollectorError
from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector, HttpClient

log = logging.getLogger(__name__)

ATTRIBUTION = "© Colaboradores de OpenStreetMap (ODbL)"

# Sector de negocio → etiquetas OSM de competencia directa e indirecta.
SECTOR_TAGS: dict[str, dict[str, list[str]]] = {
    "restauracion": {
        "direct": ["amenity=restaurant", "amenity=fast_food"],
        "indirect": ["amenity=cafe", "amenity=bar", "amenity=pub"],
    },
    "cafeteria": {
        "direct": ["amenity=cafe"],
        "indirect": ["amenity=restaurant", "amenity=fast_food", "shop=bakery"],
    },
    "retail": {
        "direct": ["shop=clothes", "shop=shoes", "shop=boutique"],
        "indirect": ["shop=department_store", "shop=mall"],
    },
    "alimentacion": {
        "direct": ["shop=supermarket", "shop=convenience"],
        "indirect": ["shop=greengrocer", "shop=butcher", "shop=bakery"],
    },
    "salud": {
        "direct": ["amenity=pharmacy"],
        "indirect": ["amenity=clinic", "amenity=doctors"],
    },
    "belleza": {
        "direct": ["shop=hairdresser", "shop=beauty"],
        "indirect": ["leisure=fitness_centre", "shop=massage"],
    },
    "fitness": {
        "direct": ["leisure=fitness_centre"],
        "indirect": ["leisure=sports_centre", "leisure=swimming_pool"],
    },
    "generico": {"direct": ["shop=*"], "indirect": ["amenity=*"]},
}

# Anclas: qué etiqueta alimenta qué indicador y cuánto tráfico genera.
ANCHORS: dict[str, tuple[list[str], float]] = {
    "anc.supermarkets": (["shop=supermarket"], 3.0),
    "anc.schools": (["amenity=school", "amenity=kindergarten", "amenity=university"], 2.5),
    "anc.health": (["amenity=hospital", "amenity=clinic", "amenity=doctors"], 2.0),
    "anc.green": (["leisure=park", "leisure=garden"], 1.5),
    "anc.admin": (["amenity=townhall", "office=government"], 1.5),
    "anc.hotels": (["tourism=hotel", "tourism=hostel", "tourism=apartment"], 2.0),
}

TRANSIT = ["highway=bus_stop", "railway=station", "railway=subway_entrance", "railway=tram_stop"]
PARKING = ["amenity=parking"]


class OsmSource(Protocol):
    def count_by_tags(self, geo: Geo, tags: Sequence[str]) -> int: ...

    def category_counts(self, geo: Geo) -> dict[str, int]: ...

    def road_length_km(self, geo: Geo, classes: Sequence[str]) -> float: ...


# --------------------------------------------------------------------------- #


class LocalPostgisSource:
    """Extracto de Geofabrik en PostGIS. El modo de producción.

    Espera las tablas de osm2pgsql (`planet_osm_point`, `planet_osm_polygon`,
    `planet_osm_line`) en el mismo servidor, y hace el recorte espacial contra
    `dim_geo.geom`. Cero llamadas de red, cero límite de tasa.
    """

    def __init__(self, session: Session) -> None:
        self._s = session

    @staticmethod
    def _where(tags: Sequence[str]) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        for i, tag in enumerate(tags):
            key, _, value = tag.partition("=")
            if value in {"", "*"}:
                clauses.append(f"(tags ? :k{i})")
                params[f"k{i}"] = key
            else:
                clauses.append(f"(tags ->> :k{i} = :v{i})")
                params[f"k{i}"] = key
                params[f"v{i}"] = value
        return " OR ".join(clauses) or "FALSE", params

    def count_by_tags(self, geo: Geo, tags: Sequence[str]) -> int:
        where, params = self._where(tags)
        params["geo_id"] = geo.geo_id
        # `where` se construye SOLO con marcadores :kN/:vN generados aquí; las
        # claves y valores de las etiquetas viajan como parámetros ligados.
        sql = text(f"""
            SELECT count(*)
            FROM osm_poi p
            JOIN dim_geo g ON g.geo_id = :geo_id
            WHERE ST_Intersects(p.geom, g.geom) AND ({where})
        """)  # noqa: S608
        return int(self._s.execute(sql, params).scalar() or 0)

    def category_counts(self, geo: Geo) -> dict[str, int]:
        sql = text("""
            SELECT p.category, count(*)
            FROM osm_poi p
            JOIN dim_geo g ON g.geo_id = :geo_id
            WHERE ST_Intersects(p.geom, g.geom)
            GROUP BY p.category
        """)
        return {row[0]: int(row[1]) for row in self._s.execute(sql, {"geo_id": geo.geo_id})}

    def road_length_km(self, geo: Geo, classes: Sequence[str]) -> float:
        sql = text("""
            SELECT COALESCE(SUM(ST_Length(ST_Intersection(r.geom, g.geom)::geography)) / 1000.0, 0)
            FROM osm_road r
            JOIN dim_geo g ON g.geo_id = :geo_id
            WHERE r.highway = ANY(:classes) AND ST_Intersects(r.geom, g.geom)
        """)
        return float(
            self._s.execute(sql, {"geo_id": geo.geo_id, "classes": list(classes)}).scalar() or 0.0
        )


class OverpassSource:
    """Instancia pública de Overpass. Solo desarrollo.

    Respeta el 429 y espera; aun así, no la uses para cargar España entera.
    """

    def __init__(self, client: HttpClient | None = None) -> None:
        cfg = get_settings()
        self._client = client or HttpClient(
            cfg.overpass_url, timeout=cfg.overpass_timeout, max_retries=3, rps=0.4
        )
        self._timeout = cfg.overpass_timeout

    def _query(self, geo: Geo, tags: Sequence[str]) -> int:
        area = f'area["ref:ine"="{geo.ine_code}"]->.a;'
        parts = []
        for tag in tags:
            key, _, value = tag.partition("=")
            selector = f'["{key}"]' if value in {"", "*"} else f'["{key}"="{value}"]'
            parts.append(f"nwr{selector}(area.a);")
        body = f"[out:json][timeout:{self._timeout}];{area}({''.join(parts)});out count;"
        try:
            payload = self._client.post_text("", body)
        except CollectorError:
            raise
        import json

        data = json.loads(payload)
        for element in data.get("elements", []):
            if element.get("type") == "count":
                return int(element.get("tags", {}).get("total", 0))
        return 0

    def count_by_tags(self, geo: Geo, tags: Sequence[str]) -> int:
        return self._query(geo, tags)

    def category_counts(self, geo: Geo) -> dict[str, int]:
        out: dict[str, int] = {}
        for code, (tags, _) in ANCHORS.items():
            out[code] = self._query(geo, tags)
        return out

    def road_length_km(self, geo: Geo, classes: Sequence[str]) -> float:
        # Overpass no da longitudes agregadas sin descargar geometrías.
        return 0.0


# --------------------------------------------------------------------------- #


class OsmCollector(BaseCollector):
    name = "osm"
    PROVIDES = (
        "cmp.count", "cmp.count_indirect", "cmp.density_km2", "cmp.per_1000hab",
        "cmp.opportunity.index",
        *ANCHORS.keys(),
        "anc.poi.count", "anc.diversity.index", "anc.attraction.index",
        "tra.transit.stops", "tra.parking.capacity", "tra.road.primary_km",
        "tra.pedestrian.index", "tra.vehicle.index",
    )

    def __init__(
        self,
        source: OsmSource | None = None,
        session: Session | None = None,
        sector: str = "generico",
    ) -> None:
        cfg = get_settings()
        # La competencia depende del sector: un colector se instancia por sector
        # y sus hechos se guardan con ese `source_ref`.
        self.sector = sector if sector in SECTOR_TAGS else "generico"
        if source is not None:
            self._source = source
        elif cfg.use_local_osm and session is not None:
            self._source = LocalPostgisSource(session)
        else:
            log.warning(
                "OSM: usando Overpass público. Válido en desarrollo; en producción "
                "carga el extracto de Geofabrik en PostGIS (USE_LOCAL_OSM=1)."
            )
            self._source = OverpassSource()

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
        tags = SECTOR_TAGS[self.sector]
        facts: list[Fact] = []

        for geo in geos:
            try:
                facts.extend(self._for_geo(geo, wanted, tags, when))
            except CollectorError as exc:
                log.warning("OSM %s: %s", geo.ine_code, exc.message)
                continue
        return facts

    # ------------------------------------------------------------------ #

    def _for_geo(
        self, geo: Geo, wanted: set[str], tags: dict[str, list[str]], when: date
    ) -> list[Fact]:
        out: list[Fact] = []
        ref = f"OSM · {ATTRIBUTION}"

        direct = indirect = None
        if {"cmp.count", "cmp.density_km2", "cmp.per_1000hab", "cmp.opportunity.index"} & wanted:
            direct = self._source.count_by_tags(geo, tags["direct"])
            out.append(self.fact(geo, "cmp.count", float(direct), when, None, ref))
        if "cmp.count_indirect" in wanted:
            indirect = self._source.count_by_tags(geo, tags["indirect"])
            out.append(self.fact(geo, "cmp.count_indirect", float(indirect), when, None, ref))

        if direct is not None and geo.area_km2:
            out.append(self.fact(
                geo, "cmp.density_km2", stats.safe_div(direct, geo.area_km2), when, None, ref
            ))
        if direct is not None and geo.population:
            out.append(self.fact(
                geo, "cmp.per_1000hab",
                stats.safe_div(direct, geo.population, 1000.0), when, None, ref
            ))

        # Anclas
        anchor_counts: dict[str, int] = {}
        for code, (anchor_tags, _) in ANCHORS.items():
            if code not in wanted and not {"anc.poi.count", "anc.diversity.index",
                                           "anc.attraction.index"} & wanted:
                continue
            count = self._source.count_by_tags(geo, anchor_tags)
            anchor_counts[code] = count
            if code in wanted:
                out.append(self.fact(geo, code, float(count), when, None, ref))

        if anchor_counts:
            total = sum(anchor_counts.values())
            if "anc.poi.count" in wanted:
                out.append(self.fact(geo, "anc.poi.count", float(total), when, None, ref))
            if "anc.diversity.index" in wanted:
                out.append(self.fact(
                    geo, "anc.diversity.index",
                    stats.shannon_diversity(anchor_counts.values()), when, None, ref
                ))
            if "anc.attraction.index" in wanted:
                weighted = sum(
                    anchor_counts.get(code, 0) * weight for code, (_, weight) in ANCHORS.items()
                )
                out.append(self.fact(
                    geo, "anc.attraction.index",
                    stats.safe_div(weighted, geo.area_km2) if geo.area_km2 else float(weighted),
                    when, None, ref,
                ))

        # Tráfico: índices RELATIVOS, nunca aforos.
        transit = parking = primary = None
        if {"tra.transit.stops", "tra.pedestrian.index"} & wanted:
            transit = self._source.count_by_tags(geo, TRANSIT)
            if "tra.transit.stops" in wanted:
                out.append(self.fact(geo, "tra.transit.stops", float(transit), when, None, ref))
        if {"tra.parking.capacity", "tra.vehicle.index"} & wanted:
            parking = self._source.count_by_tags(geo, PARKING)
            if "tra.parking.capacity" in wanted:
                out.append(self.fact(geo, "tra.parking.capacity", float(parking), when, None, ref))
        if {"tra.road.primary_km", "tra.vehicle.index"} & wanted:
            primary = self._source.road_length_km(geo, ["primary", "secondary", "trunk"])
            if "tra.road.primary_km" in wanted:
                out.append(self.fact(geo, "tra.road.primary_km", primary, when, None, ref))

        if "tra.pedestrian.index" in wanted:
            raw = (transit or 0) * 2.0 + sum(anchor_counts.values())
            out.append(self.fact(
                geo, "tra.pedestrian.index",
                stats.safe_div(raw, geo.area_km2) if geo.area_km2 else float(raw),
                when, None, f"{ref} · índice relativo, no aforo",
            ))
        if "tra.vehicle.index" in wanted:
            raw = (primary or 0.0) * 3.0 + (parking or 0) * 0.5
            out.append(self.fact(
                geo, "tra.vehicle.index",
                stats.safe_div(raw, geo.area_km2) if geo.area_km2 else float(raw),
                when, None, f"{ref} · índice relativo, no aforo",
            ))

        return out


def category_histogram(counts: dict[str, int]) -> Counter:
    return Counter(counts)
