#!/usr/bin/env python3
"""Genera la plantilla Excel que rellena el equipo de datos.

La lee `PlantillaCollector` (`adapters/collectors/plantilla.py`): las columnas,
las hojas y los códigos salen de allí, así que la plantilla y el cargador no
pueden desincronizarse.

    python tools/build_plantilla.py [salida.xlsx]
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from powergis.adapters.collectors.plantilla import (  # noqa: E402
    COLUMNAS,
    COLUMNAS_EDAD,
    HOJA_EDAD,
    HOJA_INDICADORES,
    HOJAS,
    SEMILLAS,
)
from powergis.domain.enums import GeoLevel  # noqa: E402
from powergis.domain.indicators import BY_CODE  # noqa: E402

SEED = RAIZ / "src" / "powergis" / "seed" / "geographies.json"

#: Qué cubre ya el motor por API, para que el equipo no rellene de más.
YA_POR_API: dict[str, str] = {
    "tra.vehicle.imd": "No. El motor da un índice relativo (OSM), no vehículos reales.",
    "tra.pedestrian.aforo": "No. El motor da un índice relativo (OSM), no personas reales.",
    "eco.consumer.online_pct": "INE TIC-H solo por comunidad. Ya precargado con 2025.",
    "eco.class.high_pct": "No. El motor calcula un índice NSE 0-100 con la renta del Atlas.",
    "eco.nse.upper_middle_pct": "No (ver clase alta).",
    "eco.class.mid_pct": "No (ver clase alta).",
    "eco.class.lower_mid_pct": "No (ver clase alta).",
    "eco.class.low_pct": "No (ver clase alta).",
    "dem.nat.diversity_index": "No. Índice propio a partir del Censo.",
    "dem.nat.foreign_pct": "Sí por municipio (Censo anual). Solo huecos y secciones.",
    "dem.civil.single_pct": "Sí en municipios de 500+ hab. Solo los menores.",
    "dem.civil.married_pct": "Sí en municipios de 500+ hab. Solo los menores.",
    "dem.birth.rate": "Sí por provincia. Aquí, municipal.",
    "dem.children.mean": "No (ECEPOV 2021 solo para zonas grandes).",
    "dem.household.with_children_pct": "No.",
    "dem.household.monoparental_pct": "No.",
    "dem.edu.primary_or_less_pct": "Sí en municipios de 500+ hab. Solo los menores.",
    "dem.edu.university_pct": "Sí en municipios de 500+ hab. Solo los menores.",
    "cli.temp.annual": "AEMET, si sigue conectada.",
    "cli.precip.annual": "AEMET, si sigue conectada.",
    "cli.sun.days": "AEMET, si sigue conectada.",
    "cli.rain.days": "AEMET, si sigue conectada.",
    "dem.edu.secondary_pct": "Sí en municipios de 500+ hab. Solo los menores.",
}

AZUL = PatternFill("solid", fgColor="1F4E79")
GRIS = PatternFill("solid", fgColor="E7E6E6")
AMARILLO = PatternFill("solid", fgColor="FFF2CC")
BLANCA = Font(color="FFFFFF", bold=True)
PEQUENA = Font(color="7F7F7F", size=8, italic=True)

NOMBRE_NIVEL = {
    GeoLevel.PAIS: "nacional", GeoLevel.CCAA: "comunidad", GeoLevel.PROVINCIA: "provincia",
    GeoLevel.MUNICIPIO: "municipio", GeoLevel.SECCION: "sección censal",
}


def _semilla_online() -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for ruta in SEMILLAS:
        with ruta.open(encoding="utf-8") as fh:
            for fila in csv.DictReader(fh, delimiter=";"):
                out[(fila["nivel"], fila["codigo_ine"])] = float(fila["valor"])
    return out


def _cabecera(ws, etiquetas: list[str], codigos: list[str]) -> None:
    ws.append(etiquetas)
    ws.append(codigos)
    for celda in ws[1]:
        celda.fill = AZUL
        celda.font = BLANCA
        celda.alignment = Alignment(wrap_text=True, vertical="center")
    for celda in ws[2]:
        celda.fill = GRIS
        celda.font = PEQUENA
    ws.row_dimensions[1].height = 48
    ws.freeze_panes = "C3"
    for i in range(1, len(etiquetas) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14 if i > 2 else 22
    ws.column_dimensions["A"].number_format = "@"


def construir(salida: Path) -> Path:
    geos = json.loads(SEED.read_text(encoding="utf-8"))
    online = _semilla_online()
    libro = Workbook()

    # -- LEEME --------------------------------------------------------------
    leeme = libro.active
    leeme.title = "LEEME"
    leeme.column_dimensions["A"].width = 120
    lineas = [
        ("PLANTILLA DE DATOS DEL EQUIPO DE DATOS — PowerGIS", True),
        ("Datos que ninguna API publica al nivel que pide el informe. Se actualiza cada 6 meses.", False),
        ("", False),
        ("CÓMO RELLENARLA", True),
        ("1. En «Indicadores», poned para cada indicador que rellenéis el PERIODO de referencia "
         "(año, o dd/mm/aaaa) y la FUENTE. Sin periodo, ese indicador no se carga.", False),
        ("2. Cada hoja es un nivel: Nacional, Comunidades, Provincias, Municipios y Secciones "
         "censales. Una fila por territorio, una columna por indicador.", False),
        ("3. Columna A = código INE como TEXTO (municipio 5 cifras, p. ej. 08019; sección 10 "
         "cifras). Comunidades y provincias ya vienen rellenas.", False),
        ("4. Dejad en blanco lo que no tengáis. Un hueco es un hueco; nunca pongáis 0 si no es 0.", False),
        ("5. Porcentajes de 0 a 100 (12,5 y no 0,125). Decimales con coma o punto.", False),
        ("6. «Educacion por edad»: una fila por territorio y tramo de edad (25-34, 65+…).", False),
        ("7. La fila 2 (gris) son los códigos que lee el motor: no la toquéis.", False),
        ("", False),
        ("REGLAS DEL MOTOR", True),
        ("· Si un indicador ya lo trae una API oficial, la plantilla solo rellena HUECOS "
         "(columna «¿Lo trae ya la API?» de la hoja Indicadores).", False),
        ("· La compra online es solo por comunidad autónoma: provincias y municipios heredan "
         "el dato de su comunidad. Ya está precargada con la TIC-H 2025.", False),
        ("· Si necesitáis otro dato que no está aquí, añadidlo en «Indicadores» y avisad: "
         "hay que darlo de alta en el catálogo antes de cargarlo.", False),
        ("", False),
        ("ENTREGA", True),
        ("Devolved este mismo .xlsx. En el VPS se copia a /data/plantilla-equipo-datos.xlsx y se "
         "carga con `make cargar-plantilla`.", False),
    ]
    for texto, negrita in lineas:
        leeme.append([texto])
        leeme.cell(row=leeme.max_row, column=1).font = Font(bold=negrita, size=12 if negrita else 11)
        leeme.cell(row=leeme.max_row, column=1).alignment = Alignment(wrap_text=True)

    # -- Indicadores ----------------------------------------------------------
    ind = libro.create_sheet(HOJA_INDICADORES)
    cab = ["Código", "Indicador", "Niveles a rellenar", "Unidad", "Qué poner",
           "¿Lo trae ya la API?", "Periodo de referencia", "Fuente / bibliografía"]
    ind.append(cab)
    for celda in ind[1]:
        celda.fill = AZUL
        celda.font = BLANCA
    codigos_vistos = []
    for col in COLUMNAS:
        codigos_vistos.append(col.code)
        unidad = str(BY_CODE[col.code].unit) if col.code in BY_CODE else ""
        periodo, fuente = ("", "")
        if col.code == "eco.consumer.online_pct":
            periodo, fuente = ("2025", "INE, Encuesta TIC-H 2025")
        ind.append([col.code, col.etiqueta, ", ".join(NOMBRE_NIVEL[n] for n in col.niveles),
                    unidad, col.nota, YA_POR_API.get(col.code, ""), periodo, fuente])
    for code in COLUMNAS_EDAD:
        if code in codigos_vistos:
            continue
        ind.append([code, BY_CODE[code].label + " (solo hoja Educacion por edad)",
                    "por tramo de edad", str(BY_CODE[code].unit), "",
                    YA_POR_API.get(code, ""), "", ""])
    for fila in ind.iter_rows(min_row=2):
        fila[6].fill = AMARILLO
        fila[7].fill = AMARILLO
        for celda in fila:
            celda.alignment = Alignment(wrap_text=True, vertical="top")
    for letra, ancho in zip("ABCDEFGH", (26, 38, 22, 10, 50, 40, 16, 40), strict=True):
        ind.column_dimensions[letra].width = ancho
    ind.freeze_panes = "C2"

    # -- Hojas por nivel ------------------------------------------------------
    for hoja, nivel in HOJAS.items():
        ws = libro.create_sheet(hoja)
        cols = [c for c in COLUMNAS if nivel in c.niveles]
        _cabecera(ws, ["Código INE", "Territorio"] + [c.etiqueta for c in cols],
                  ["codigo_ine", "territorio"] + [c.code for c in cols])
        filas: list[tuple[str, str]] = []
        if nivel is GeoLevel.PAIS:
            filas = [("ES", "España")]
        elif nivel in (GeoLevel.CCAA, GeoLevel.PROVINCIA):
            filas = [(g["ine_code"], g["name"]) for g in geos if g["level"] == str(nivel)]
        for codigo, nombre in filas:
            valores: list[object] = [codigo, nombre]
            for c in cols:
                v = online.get((str(nivel), codigo)) if c.code == "eco.consumer.online_pct" else None
                valores.append(v)
            ws.append(valores)
        for fila in ws.iter_rows(min_row=3, max_col=1):
            fila[0].number_format = "@"

    # -- Educación por edad ---------------------------------------------------
    edad = libro.create_sheet(HOJA_EDAD)
    _cabecera(
        edad,
        ["Nivel", "Código INE", "Territorio", "Tramo de edad"]
        + [BY_CODE[c].label for c in COLUMNAS_EDAD],
        ["nivel", "codigo_ine", "territorio", "edad", *COLUMNAS_EDAD],
    )
    edad.freeze_panes = "E3"
    niveles = DataValidation(type="list", formula1='"pais,ccaa,provincia,municipio,seccion"',
                             allow_blank=True)
    edad.add_data_validation(niveles)
    niveles.add("A3:A5000")
    edad.column_dimensions["B"].number_format = "@"

    salida.parent.mkdir(parents=True, exist_ok=True)
    libro.save(salida)
    return salida


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("plantilla-equipo-datos.xlsx")
    print(construir(destino))
