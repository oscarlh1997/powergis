"""A qué comunidad autónoma pertenece cada provincia (códigos INE).

Hace falta para los datos que el INE sólo publica por comunidad —el hábito de
compra online de la encuesta TIC-H—: provincias y municipios se quedan con el
dato de su comunidad, y eso exige saber cuál es sin consultar la base de
datos. Los códigos de provincia y de comunidad del INE son estables.
"""

from __future__ import annotations

from .enums import GeoLevel

PROVINCIA_A_CCAA: dict[str, str] = {
    # 01 Andalucía
    **dict.fromkeys(("04", "11", "14", "18", "21", "23", "29", "41"), "01"),
    # 02 Aragón
    **dict.fromkeys(("22", "44", "50"), "02"),
    "33": "03",                                     # Principado de Asturias
    "07": "04",                                     # Illes Balears
    **dict.fromkeys(("35", "38"), "05"),            # Canarias
    "39": "06",                                     # Cantabria
    # 07 Castilla y León
    **dict.fromkeys(("05", "09", "24", "34", "37", "40", "42", "47", "49"), "07"),
    # 08 Castilla-La Mancha
    **dict.fromkeys(("02", "13", "16", "19", "45"), "08"),
    **dict.fromkeys(("08", "17", "25", "43"), "09"),  # Cataluña
    **dict.fromkeys(("03", "12", "46"), "10"),        # Comunitat Valenciana
    **dict.fromkeys(("06", "10"), "11"),              # Extremadura
    **dict.fromkeys(("15", "27", "32", "36"), "12"),  # Galicia
    "28": "13",                                     # Comunidad de Madrid
    "30": "14",                                     # Región de Murcia
    "31": "15",                                     # Comunidad Foral de Navarra
    **dict.fromkeys(("01", "20", "48"), "16"),        # País Vasco
    "26": "17",                                     # La Rioja
    "51": "18",                                     # Ceuta
    "52": "19",                                     # Melilla
}

_POR_DEBAJO_DE_PROVINCIA = (
    GeoLevel.MUNICIPIO, GeoLevel.DISTRITO, GeoLevel.SECCION,
)


def ccaa_de(level: GeoLevel | str, ine_code: str) -> str | None:
    """Código de la comunidad autónoma de una geografía, o None.

    Municipios (5 cifras), distritos (7) y secciones (10) empiezan por el
    código de su provincia, así que basta con las dos primeras cifras.
    """
    nivel = GeoLevel(level)
    codigo = str(ine_code).strip()
    if nivel is GeoLevel.CCAA:
        return codigo.zfill(2)
    if nivel is GeoLevel.PROVINCIA:
        return PROVINCIA_A_CCAA.get(codigo.zfill(2))
    if nivel in _POR_DEBAJO_DE_PROVINCIA and len(codigo) >= 4:
        return PROVINCIA_A_CCAA.get(codigo.zfill(5)[:2])
    return None


def provincia_de(level: GeoLevel | str, ine_code: str) -> str | None:
    """Código de la provincia de un municipio, distrito o sección, o None.

    Lo necesitan los datos que sólo se publican por provincia (el valor
    tasado de la vivienda, las compraventas por habitante): los municipios
    llevan el dato de su provincia.
    """
    nivel = GeoLevel(level)
    codigo = str(ine_code).strip()
    if nivel is GeoLevel.PROVINCIA:
        return codigo.zfill(2)
    if nivel in _POR_DEBAJO_DE_PROVINCIA and len(codigo) >= 4:
        provincia = codigo.zfill(5)[:2]
        return provincia if provincia in PROVINCIA_A_CCAA else None
    return None
