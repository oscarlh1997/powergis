#!/usr/bin/env python3
"""Genera la plantilla Excel que rellena el equipo de datos.

La lee `PlantillaCollector` (`adapters/collectors/plantilla.py`): las columnas,
las hojas y los códigos salen de allí, así que la plantilla y el cargador no
pueden desincronizarse.

    python tools/build_plantilla.py [salida.xlsx]
    python tools/build_plantilla.py salida.xlsx --desde plantilla-rellena.xlsx

Con `--desde`, la plantilla nueva se rellena con todo lo que traía la vieja:
cada valor (o fórmula) va a la misma fila y al mismo código de columna; el
periodo y la fuente de «Indicadores», las filas de «Educacion por edad» y de
«Series historicas», y las hojas que el equipo añadió por su cuenta (notas,
cálculos auxiliares) se copian tal cual. Lo que la plantilla nueva ya no tiene
(una columna que se quitó del catálogo) se lista al terminar.
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
    COLUMNAS_HISTORICO,
    HOJA_EDAD,
    HOJA_HISTORICO,
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
    "dem.nat.diversity_index": "No. Simpson/Blau con los grupos de nacionalidad.",
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
    "cli.humidity.annual": "No. Alta del equipo de datos (18/10/2026).",
    "cli.sun.hours.annual": "No. Alta del equipo de datos (18/10/2026).",
    "pol.turnout_pct": "No. Infoelectoral publica ficheros por convocatoria, sin API.",
    "pol.winner_share_pct": "No. Se calcula con los ficheros de Infoelectoral.",
    "pol.effective_parties": "No. Se calcula con los ficheros de Infoelectoral.",
    "mov.interprov.in_rate": "No. INE EMCR: descarga por año, sin API confirmada.",
    "mov.interprov.out_rate": "No. INE EMCR.",
    "mov.interprov.net_rate": "No. INE EMCR.",
    "tur.hotel.travellers": "No. INE EOH (tablas 2074 y 2078), API sin verificar.",
    "tur.hotel.overnight": "No. INE EOH.",
    "tur.hotel.stay_mean": "No. INE EOH.",
    "tur.overnight_per_1000hab": "No. INE EOH / Padrón.",
    "inm.sales.dwellings": "No. INE ETDP (tablas 6149/6150), sólo hasta provincia.",
    "inm.sales.per_1000hab": "No. INE ETDP / Padrón. Municipios heredan la provincia.",
    "inm.dwellings.main_pct": "No. Censo 2021 (consulta a medida, sin API).",
    "inm.dwellings.empty_pct": "No. Censo 2021.",
    "inm.price.m2": "No. MIVAU, CSV VDP006_01. Municipios heredan la provincia.",
    "inm.price.yoy_change": "No. MIVAU.",
    "inm.rent.m2": "No. MIVAU SERPAVI (tablas resumen; sin API).",
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
                # Sólo la compra online: la semilla de la ECP no es una columna.
                if fila["indicador"] == "eco.consumer.online_pct":
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
        ("8. «Series historicas»: una fila por territorio, indicador y año (formato largo). "
         "Sólo para el valor tasado (inm.price.m2) y el alquiler (inm.rent.m2).", False),
        ("9. Negativos: sólo en el saldo de traslados y en la variación del valor tasado. "
         "En lo demás, un negativo se rechaza.", False),
        ("10. Podéis usar fórmulas y hojas auxiliares propias: se lee el valor calculado. "
         "Guardad el fichero con Excel o LibreOffice para que el valor quede grabado.", False),
        ("", False),
        ("REGLAS DEL MOTOR", True),
        ("· Si un indicador ya lo trae una API oficial, la plantilla solo rellena HUECOS "
         "(columna «¿Lo trae ya la API?» de la hoja Indicadores).", False),
        ("· La compra online es solo por comunidad autónoma: provincias y municipios heredan "
         "el dato de su comunidad. Ya está precargada con la TIC-H 2025.", False),
        ("· El valor tasado y las compraventas por habitante son provinciales, y el clima anual "
         "de esta plantilla también: los municipios heredan el dato de su provincia (si AEMET "
         "da el del municipio, manda AEMET).", False),
        ("· Las series de resultados electorales, traslados, turismo y vivienda son las capas que "
         "el cliente enciende o apaga en el formulario. Lo que no carguéis sale como «sin datos».",
         False),
        ("· El NSE (clases sociales) se eliminó del formulario y del motor el 18/10/2026: ya no "
         "hay columnas para él. El perfil económico se mide con la renta.", False),
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

    # -- Series históricas ----------------------------------------------------
    hist = libro.create_sheet(HOJA_HISTORICO)
    _cabecera(
        hist,
        ["Nivel", "Código INE", "Territorio", "Indicador", "Año", "Valor"],
        ["nivel", "codigo_ine", "territorio", "indicador", "anio", "valor"],
    )
    hist.freeze_panes = "A3"
    niveles_h = DataValidation(type="list", formula1='"pais,ccaa,provincia,municipio"',
                               allow_blank=True)
    indicadores_h = DataValidation(type="list", formula1='"' + ",".join(COLUMNAS_HISTORICO) + '"',
                                   allow_blank=True)
    hist.add_data_validation(niveles_h)
    hist.add_data_validation(indicadores_h)
    niveles_h.add("A3:A20000")
    indicadores_h.add("D3:D20000")
    hist.column_dimensions["B"].number_format = "@"
    hist.column_dimensions["D"].width = 22

    salida.parent.mkdir(parents=True, exist_ok=True)
    libro.save(salida)
    return salida


# --------------------------------------------------------------------------- #
# Migrar una plantilla rellena a la estructura nueva
# --------------------------------------------------------------------------- #

#: Columnas fijas (no indicadores) de las hojas en formato largo.
_FIJAS = {"nivel", "codigo_ine", "territorio", "edad", "indicador", "anio", "valor"}


def migrar(vieja: Path, nueva: Path) -> list[str]:
    """Pasa a `nueva` (recién construida) todo lo que trae `vieja`.

    Devuelve los avisos: columnas o filas que no tienen sitio en la nueva.
    """
    from openpyxl import load_workbook

    origen = load_workbook(vieja)              # con fórmulas, no valores
    destino = load_workbook(nueva)
    avisos: list[str] = []

    # 1. Hojas por nivel: misma fila (código INE) y misma columna (código).
    for hoja in HOJAS:
        if hoja not in origen.sheetnames:
            continue
        o, d = origen[hoja], destino[hoja]
        cols_o = {str(c.value or "").strip(): c.column for c in o[2] if c.value}
        cols_d = {str(c.value or "").strip(): c.column for c in d[2] if c.value}
        filas_d = {_clave(d.cell(row=r, column=1).value): r for r in range(3, d.max_row + 1)
                   if d.cell(row=r, column=1).value not in (None, "")}
        for r in range(3, o.max_row + 1):
            codigo = o.cell(row=r, column=1).value
            if codigo in (None, ""):
                continue
            fila = filas_d.get(_clave(codigo))
            if fila is None:
                fila = d.max_row + 1
                d.cell(row=fila, column=1, value=str(codigo)).number_format = "@"
                d.cell(row=fila, column=2, value=o.cell(row=r, column=2).value)
                filas_d[_clave(codigo)] = fila
            for code, col in cols_o.items():
                if code in ("codigo_ine", "territorio"):
                    continue
                valor = o.cell(row=r, column=col).value
                if valor in (None, ""):
                    continue
                if code not in cols_d:
                    avisos.append(f"{hoja}!{o.cell(row=r, column=col).coordinate}: la columna "
                                  f"«{code}» ya no existe; valor «{valor}» no copiado")
                    continue
                d.cell(row=fila, column=cols_d[code], value=valor)
        quitadas = sorted(set(cols_o) - set(cols_d) - {"codigo_ine", "territorio"})
        if quitadas:
            avisos.append(f"{hoja}: columnas que ya no están (vacías, sin pérdida si no hay "
                          f"avisos de valor): {', '.join(quitadas)}")

    # 2. Indicadores: periodo y fuente; y las filas que añadió el equipo.
    if HOJA_INDICADORES in origen.sheetnames:
        o, d = origen[HOJA_INDICADORES], destino[HOJA_INDICADORES]
        filas_d = {str(d.cell(row=r, column=1).value).strip(): r for r in range(2, d.max_row + 1)
                   if d.cell(row=r, column=1).value}
        for r in range(2, o.max_row + 1):
            code = str(o.cell(row=r, column=1).value or "").strip()
            if not code:
                continue
            if code not in filas_d:
                avisos.append(f"Indicadores: «{code}» ya no está en el catálogo; fila no copiada")
                continue
            for col in (7, 8):   # periodo, fuente
                valor = o.cell(row=r, column=col).value
                if valor not in (None, ""):
                    d.cell(row=filas_d[code], column=col, value=valor)

    # 3. Formato largo: se copian las filas tal cual, por nombre de columna.
    for hoja in (HOJA_EDAD, HOJA_HISTORICO):
        if hoja not in origen.sheetnames:
            continue
        o, d = origen[hoja], destino[hoja]
        cols_o = [str(c.value or "").strip() for c in o[2]]
        cols_d = {str(c.value or "").strip(): c.column for c in d[2] if c.value}
        for r in range(3, o.max_row + 1):
            valores = [o.cell(row=r, column=j + 1).value for j in range(len(cols_o))]
            if all(v in (None, "") for v in valores):
                continue
            fila = d.max_row + 1
            for code, valor in zip(cols_o, valores, strict=True):
                if valor in (None, ""):
                    continue
                if code not in cols_d:
                    avisos.append(f"{hoja}!fila {r}: la columna «{code}» ya no existe")
                    continue
                d.cell(row=fila, column=cols_d[code], value=valor)

    # 4. Hojas propias del equipo (notas, cálculos auxiliares): tal cual y en
    #    el mismo sitio, para que sus fórmulas sigan apuntando a lo mismo.
    propias = [n for n in origen.sheetnames if n not in destino.sheetnames]
    for nombre in propias:
        _copiar_hoja(origen[nombre], destino.create_sheet(nombre))
        destino.move_sheet(nombre, offset=origen.sheetnames.index(nombre)
                           - destino.sheetnames.index(nombre))

    destino.save(nueva)
    return avisos


def _clave(codigo: object) -> str:
    if isinstance(codigo, float) and codigo.is_integer():
        codigo = int(codigo)
    texto = str(codigo).strip()
    if texto.isdigit():
        return texto.lstrip("0") or "0"   # «08019» y 8019 son el mismo municipio
    return texto


def _copiar_hoja(o, d) -> None:
    from copy import copy

    for fila in o.iter_rows():
        for c in fila:
            if c.value is None and not c.has_style:
                continue
            nueva = d.cell(row=c.row, column=c.column, value=c.value)
            if c.has_style:
                nueva.font = copy(c.font)
                nueva.fill = copy(c.fill)
                nueva.alignment = copy(c.alignment)
                nueva.border = copy(c.border)
                nueva.number_format = c.number_format
    for letra, dim in o.column_dimensions.items():
        d.column_dimensions[letra].width = dim.width
    for n, dim in o.row_dimensions.items():
        if dim.height:
            d.row_dimensions[n].height = dim.height
    for rango in o.merged_cells.ranges:
        d.merge_cells(str(rango))
    d.freeze_panes = o.freeze_panes


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("salida", nargs="?", default="plantilla-equipo-datos.xlsx")
    parser.add_argument("--desde", help="plantilla rellena cuyos datos se pasan a la nueva")
    args = parser.parse_args()
    destino = construir(Path(args.salida))
    if args.desde:
        for aviso in migrar(Path(args.desde), destino):
            print("AVISO:", aviso)
    print(destino)
