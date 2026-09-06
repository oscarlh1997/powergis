#!/usr/bin/env python3
"""Genera `src/powergis/seed/geographies.json`.

Semilla de arranque: país, comunidades autónomas y provincias con sus códigos
INE oficiales. Población y superficie son APROXIMADAS y solo sirven para poder
levantar el sistema; la carga real las sobreescribe con el Padrón continuo y
las geometrías del IGN.

    python tools/build_seed.py
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "powergis" / "seed" / "geographies.json"

CCAA: list[tuple[str, str]] = [
    ("01", "Andalucía"), ("02", "Aragón"), ("03", "Principado de Asturias"),
    ("04", "Illes Balears"), ("05", "Canarias"), ("06", "Cantabria"),
    ("07", "Castilla y León"), ("08", "Castilla-La Mancha"), ("09", "Cataluña"),
    ("10", "Comunitat Valenciana"), ("11", "Extremadura"), ("12", "Galicia"),
    ("13", "Comunidad de Madrid"), ("14", "Región de Murcia"),
    ("15", "Comunidad Foral de Navarra"), ("16", "País Vasco"),
    ("17", "La Rioja"), ("18", "Ceuta"), ("19", "Melilla"),
]

# (código, nombre, ccaa, población aprox., km² aprox.)
PROVINCIAS: list[tuple[str, str, str, int, float]] = [
    ("01", "Araba/Álava", "16", 335_000, 3_037),
    ("02", "Albacete", "08", 389_000, 14_926),
    ("03", "Alicante/Alacant", "10", 1_959_000, 5_817),
    ("04", "Almería", "01", 756_000, 8_775),
    ("05", "Ávila", "07", 158_000, 8_050),
    ("06", "Badajoz", "11", 669_000, 21_766),
    ("07", "Illes Balears", "04", 1_209_000, 4_992),
    ("08", "Barcelona", "09", 5_774_000, 7_728),
    ("09", "Burgos", "07", 356_000, 14_292),
    ("10", "Cáceres", "11", 389_000, 19_868),
    ("11", "Cádiz", "01", 1_252_000, 7_436),
    ("12", "Castellón/Castelló", "10", 596_000, 6_632),
    ("13", "Ciudad Real", "08", 493_000, 19_813),
    ("14", "Córdoba", "01", 776_000, 13_769),
    ("15", "A Coruña", "12", 1_124_000, 7_950),
    ("16", "Cuenca", "08", 195_000, 17_141),
    ("17", "Girona", "09", 802_000, 5_910),
    ("18", "Granada", "01", 932_000, 12_647),
    ("19", "Guadalajara", "08", 268_000, 12_167),
    ("20", "Gipuzkoa", "16", 727_000, 1_980),
    ("21", "Huelva", "01", 533_000, 10_128),
    ("22", "Huesca", "02", 227_000, 15_636),
    ("23", "Jaén", "01", 621_000, 13_496),
    ("24", "León", "07", 445_000, 15_581),
    ("25", "Lleida", "09", 444_000, 12_172),
    ("26", "La Rioja", "17", 323_000, 5_045),
    ("27", "Lugo", "12", 325_000, 9_856),
    ("28", "Madrid", "13", 6_871_000, 8_028),
    ("29", "Málaga", "01", 1_762_000, 7_308),
    ("30", "Murcia", "14", 1_570_000, 11_313),
    ("31", "Navarra", "15", 674_000, 10_390),
    ("32", "Ourense", "12", 305_000, 7_273),
    ("33", "Asturias", "03", 1_006_000, 10_604),
    ("34", "Palencia", "07", 158_000, 8_053),
    ("35", "Las Palmas", "05", 1_167_000, 4_066),
    ("36", "Pontevedra", "12", 947_000, 4_495),
    ("37", "Salamanca", "07", 327_000, 12_350),
    ("38", "Santa Cruz de Tenerife", "05", 1_072_000, 3_381),
    ("39", "Cantabria", "06", 588_000, 5_321),
    ("40", "Segovia", "07", 155_000, 6_921),
    ("41", "Sevilla", "01", 1_961_000, 14_036),
    ("42", "Soria", "07", 89_000, 10_306),
    ("43", "Tarragona", "09", 838_000, 6_303),
    ("44", "Teruel", "02", 134_000, 14_810),
    ("45", "Toledo", "08", 730_000, 15_370),
    ("46", "València", "10", 2_680_000, 10_807),
    ("47", "Valladolid", "07", 521_000, 8_110),
    ("48", "Bizkaia", "16", 1_155_000, 2_217),
    ("49", "Zamora", "07", 165_000, 10_561),
    ("50", "Zaragoza", "02", 986_000, 17_274),
    ("51", "Ceuta", "18", 83_000, 19),
    ("52", "Melilla", "19", 86_000, 13),
]


def build() -> list[dict]:
    rows: list[dict] = [{
        "level": "pais", "ine_code": "ES", "name": "España",
        "population": sum(p[3] for p in PROVINCIAS),
        "area_km2": round(sum(p[4] for p in PROVINCIAS), 1),
    }]

    by_ccaa_pop: dict[str, int] = {}
    by_ccaa_area: dict[str, float] = {}
    for _, _, ccaa, population, area in PROVINCIAS:
        by_ccaa_pop[ccaa] = by_ccaa_pop.get(ccaa, 0) + population
        by_ccaa_area[ccaa] = by_ccaa_area.get(ccaa, 0.0) + area

    for code, name in CCAA:
        rows.append({
            "level": "ccaa", "ine_code": code, "name": name,
            "parent_level": "pais", "parent_code": "ES",
            "population": by_ccaa_pop.get(code, 0),
            "area_km2": round(by_ccaa_area.get(code, 0.0), 1),
        })

    for code, name, ccaa, population, area in PROVINCIAS:
        rows.append({
            "level": "provincia", "ine_code": code, "name": name,
            "parent_level": "ccaa", "parent_code": ccaa,
            "population": population, "area_km2": float(area),
        })

    return rows


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(data)} geografías escritas en {OUT}")
