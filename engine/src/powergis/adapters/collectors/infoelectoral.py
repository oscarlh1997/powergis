"""Resultados electorales por mesa — Ministerio del Interior, Infoelectoral.

Es la única fuente oficial y gratuita que baja de municipio: publica cada
convocatoria MESA A MESA, y cada mesa lleva su provincia, municipio, distrito
y sección censal. Sumando mesas sale la sección; sumando secciones, el
distrito; sumando todo, el municipio (análisis 8071, tabla #14).

    https://infoelectoral.interior.gob.es/estaticos/docxl/apliextr/{TT}{AAAA}{MM}_MESA.zip

`TT` es el tipo de elección (02 Congreso, 04 municipales, 07 europeas…). El
ZIP trae, entre otros, dos ficheros de ancho fijo:

* `09TTAAMM.DAT` — una línea por mesa: censo, votos en blanco, nulos y a
  candidaturas.
* `10TTAAMM.DAT` — una línea por mesa y candidatura: sus votos.

PROVISIONAL. Las posiciones de `CAMPOS_09` y `CAMPOS_10` son las del
documento de diseño de ficheros de Interior tal como se recuerdan; el proxy de
la sesión no llega a infoelectoral y no se han podido contrastar con un
fichero real. `powergis infoelectoral-verificar <zip>` las comprueba en el
VPS (cuadres internos y códigos que casan con `dim_geo`) antes de cargar. Por
eso los hechos llevan «provisional» en la fuente hasta que se quite la marca.

Lo que se escribe es agregado y sin interpretar: participación, cuota de la
candidatura más votada y número efectivo de partidos. Nada que permita
inferir el voto de nadie: la unidad mínima es la sección (más de 500
electores de media), no la mesa.
"""

from __future__ import annotations

import io
import logging
import os
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector

log = logging.getLogger(__name__)

URL = "https://infoelectoral.interior.gob.es/estaticos/docxl/apliextr/{tipo}{anio}{mes}_MESA.zip"
#: Marca de la fuente mientras las posiciones no estén verificadas.
PROVISIONAL = "provisional"

#: (inicio, fin) en posiciones 1-based, ambos incluidos.
CAMPOS_COMUNES = {
    "tipo": (1, 2), "anio": (3, 6), "mes": (7, 8), "vuelta": (9, 9),
    "provincia": (12, 13), "municipio": (14, 16), "distrito": (17, 18),
    "seccion": (19, 22), "mesa": (23, 23),
}
CAMPOS_09 = {**CAMPOS_COMUNES, "censo": (31, 37), "blancos": (66, 72), "nulos": (73, 79),
             "candidaturas": (80, 86)}
CAMPOS_10 = {**CAMPOS_COMUNES, "candidatura": (24, 29), "votos": (30, 36)}

#: Municipio 999: el voto de residentes ausentes (CERA), sin sección.
CERA = "999"


def _campo(linea: str, campos: dict[str, tuple[int, int]], nombre: str) -> str:
    ini, fin = campos[nombre]
    return linea[ini - 1:fin].strip()


def _entero(texto: str) -> int:
    return int(texto) if texto.isdigit() else 0


def seccion_de(linea: str, campos: dict[str, tuple[int, int]]) -> str | None:
    """Código INE de la sección (10 cifras) de una línea, o None si es CERA.

    La sección viene en 4 posiciones (tres cifras y, a veces, una letra de
    subsección o un cero delante): se quedan las tres últimas cifras.
    """
    municipio = _campo(linea, campos, "municipio")
    if municipio == CERA or not municipio.isdigit():
        return None
    cifras = "".join(c for c in _campo(linea, campos, "seccion") if c.isdigit())
    distrito = _campo(linea, campos, "distrito")
    if not cifras or not distrito.isdigit():
        return None
    return (_campo(linea, campos, "provincia").zfill(2) + municipio.zfill(3)
            + distrito.zfill(2) + cifras.zfill(3)[-3:])


@dataclass(slots=True)
class Totales:
    censo: int = 0
    blancos: int = 0
    nulos: int = 0
    candidaturas: int = 0
    votos: dict[str, int] = field(default_factory=dict)

    def sumar(self, otro: Totales) -> None:
        self.censo += otro.censo
        self.blancos += otro.blancos
        self.nulos += otro.nulos
        self.candidaturas += otro.candidaturas
        for cand, v in otro.votos.items():
            self.votos[cand] = self.votos.get(cand, 0) + v

    def indicadores(self) -> dict[str, float | None]:
        votantes = self.blancos + self.nulos + self.candidaturas
        validos = self.blancos + self.candidaturas
        por_cand = sum(self.votos.values())
        return {
            "pol.turnout_pct": 100.0 * votantes / self.censo if self.censo else None,
            "pol.winner_share_pct": (100.0 * max(self.votos.values()) / validos
                                     if self.votos and validos else None),
            # Laakso-Taagepera sobre el voto a candidaturas.
            "pol.effective_parties": (1.0 / sum((v / por_cand) ** 2 for v in self.votos.values())
                                      if por_cand else None),
        }


def por_seccion(lineas_09: Iterable[str], lineas_10: Iterable[str]) -> dict[str, Totales]:
    """Mesas → sección censal (código de 10 cifras)."""
    out: dict[str, Totales] = {}
    for linea in lineas_09:
        sec = seccion_de(linea, CAMPOS_09)
        if sec is None:
            continue
        out.setdefault(sec, Totales()).sumar(Totales(
            censo=_entero(_campo(linea, CAMPOS_09, "censo")),
            blancos=_entero(_campo(linea, CAMPOS_09, "blancos")),
            nulos=_entero(_campo(linea, CAMPOS_09, "nulos")),
            candidaturas=_entero(_campo(linea, CAMPOS_09, "candidaturas")),
        ))
    for linea in lineas_10:
        sec = seccion_de(linea, CAMPOS_10)
        if sec is None or sec not in out:
            continue
        cand = _campo(linea, CAMPOS_10, "candidatura")
        votos = out[sec].votos
        votos[cand] = votos.get(cand, 0) + _entero(_campo(linea, CAMPOS_10, "votos"))
    return out


def agregar(secciones: dict[str, Totales]) -> dict[str, Totales]:
    """Sección (10) → distrito (7) → municipio (5), por suma. Incluye las secciones."""
    out: dict[str, Totales] = {}
    for codigo, t in secciones.items():
        for clave in (codigo, codigo[:7], codigo[:5]):
            out.setdefault(clave, Totales()).sumar(t)
    return out


def leer_zip(datos: bytes) -> tuple[dict[str, str], list[str], list[str]]:
    """(cabecera, líneas del 09, líneas del 10) de un ZIP de mesas."""
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        nombres = z.namelist()

        def lineas(prefijo: str) -> list[str]:
            fichero = next((n for n in nombres
                            if Path(n).name.startswith(prefijo) and n.upper().endswith(".DAT")),
                           None)
            if fichero is None:
                raise ValueError(f"El ZIP no trae el fichero {prefijo}xxaamm.DAT")
            return z.read(fichero).decode("latin-1").splitlines()

        l09, l10 = lineas("09"), lineas("10")
    primera = next((x for x in l09 if x.strip()), "")
    cabecera = {k: _campo(primera, CAMPOS_09, k) for k in ("tipo", "anio", "mes")}
    return cabecera, l09, l10


class InfoelectoralCollector(BaseCollector):
    """Carga una convocatoria desde su ZIP de mesas.

    El ZIP se deja en el VPS (o se descarga de `URL`) y se indica con
    `POWERGIS_INFOELECTORAL` (ruta local o URL). Una convocatoria para todas
    las zonas: el informe dice cuál en la fuente.
    """

    name = "infoelectoral"
    TODAS_LAS_GEOS = True
    PROVIDES = ("pol.turnout_pct", "pol.winner_share_pct", "pol.effective_parties")

    def __init__(self, origen: str | None = None, client: Any = None) -> None:
        self._origen = origen or os.getenv("POWERGIS_INFOELECTORAL", "")
        self._client = client
        self.fallos: list[str] = []

    def _bytes(self) -> bytes:
        if self._origen.startswith("http"):
            import httpx

            respuesta = (self._client or httpx).get(self._origen, timeout=120)
            respuesta.raise_for_status()
            return respuesta.content
        return Path(self._origen).read_bytes()

    def collect(
        self,
        indicators: Sequence[str],
        geos: Sequence[Geo],
        segments: Segments,
        period: date | None = None,
    ) -> list[Fact]:
        self.fallos = []
        wanted = set(indicators) & set(self.PROVIDES)
        if not wanted or not geos:
            return []
        if not self._origen:
            # Sin convocatoria indicada no hay nada que cargar; no es un fallo
            # (la plantilla puede traer el dato municipal mientras tanto).
            log.warning("Infoelectoral: sin POWERGIS_INFOELECTORAL; no se carga nada")
            return []
        try:
            cabecera, l09, l10 = leer_zip(self._bytes())
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            self.fallos.append(f"no se pudo leer {self._origen}: {exc}")
            return []
        totales = agregar(por_seccion(l09, l10))
        cuando = period or date(_entero(cabecera["anio"]) or date.today().year,
                                _entero(cabecera["mes"]) or 1, 1)
        ref = (f"Interior:Infoelectoral tipo {cabecera['tipo']} "
               f"{cabecera['anio']}-{cabecera['mes']} · mesas · {PROVISIONAL}")
        out: list[Fact] = []
        for geo in geos:
            t = totales.get(geo.ine_code)
            if t is None:
                continue
            for code, value in t.indicadores().items():
                if code in wanted:
                    out.append(self.fact(geo, code, value, cuando, None, ref))
        if geos and not out:
            self.fallos.append("ninguna sección del ZIP casa con las geografías cargadas")
        return out

    def verificar(self, geos: Sequence[Geo] = ()) -> dict[str, Any]:
        """Cuadres para validar las posiciones en el VPS antes de cargar."""
        cabecera, l09, l10 = leer_zip(self._bytes())
        secciones = por_seccion(l09, l10)
        total = Totales()
        for t in secciones.values():
            total.sumar(t)
        descuadres = sum(1 for t in secciones.values() if sum(t.votos.values()) != t.candidaturas)
        codigos = {g.ine_code for g in geos}
        return {
            "cabecera": cabecera,
            "mesas": len(l09),
            "secciones": len(secciones),
            "ejemplos": sorted(secciones)[:5],
            "secciones_en_dim_geo": len(set(secciones) & codigos) if codigos else None,
            "participacion_total": total.indicadores()["pol.turnout_pct"],
            "secciones_con_descuadre": descuadres,
        }
