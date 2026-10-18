"""Datos que el equipo de datos rellena a mano — la plantilla Excel.

Hay datos que ninguna API publica al nivel que pide el informe: aforos de
tráfico, número medio de hijos por hogar, diversidad cultural, estado civil en
municipios de menos de 500 habitantes… El equipo de datos los consigue y los
pone en una plantilla (la genera `tools/build_plantilla.py`), que se deja en
el VPS y se carga con:

    powergis ingest plantilla --level municipio      (y ccaa, provincia, seccion)

Reglas, en este orden de importancia:

1. **La API manda.** Si un indicador también lo trae una fuente oficial
   (INE, Atlas, AEMET…), la plantilla sólo rellena HUECOS: donde ya hay un
   dato oficial para esa geografía, la fila de la plantilla no se escribe.
2. **Nada sin periodo ni fuente.** Cada indicador lleva en la hoja
   «Indicadores» su periodo de referencia y su fuente; sin periodo no se carga
   ese indicador y la orden sale con error.
3. **Lo que sólo se publica por arriba se hereda.** La compra online (TIC-H)
   es por comunidad; provincias y municipios llevan el dato de su comunidad.
   El precio tasado y las compraventas por habitante son provinciales, y el
   clima anual que trae la plantilla también: los municipios llevan el de su
   provincia. La fuente lo dice siempre, y lo oficial sigue mandando.
4. **Las series anuales van aparte.** La hoja «Series historicas» (formato
   largo: nivel, código, indicador, año, valor) guarda el histórico del
   precio y del alquiler de la vivienda con segmento de año.

La semilla `seed/compra_online_ccaa_2025.csv` trae ya la compra online de 2025,
así que funciona aunque la plantilla todavía no exista.
"""

from __future__ import annotations

import csv
import logging
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ...domain.enums import GeoLevel
from ...domain.models import Fact, Geo, Segments
from ...domain.territorio import ccaa_de, provincia_de
from .base import BaseCollector

log = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent.parent / "seed"
SEMILLAS = (SEED_DIR / "compra_online_ccaa_2025.csv",)

#: Dónde busca la plantilla rellena. Se cambia con `POWERGIS_PLANTILLA`.
RUTA_POR_DEFECTO = "/data/plantilla-equipo-datos.xlsx"

#: Prefijo de `source_ref` de todo lo que viene de la plantilla.
PREFIJO = "Equipo de datos"

#: Hojas de la plantilla y el nivel de sus filas.
HOJAS: dict[str, GeoLevel] = {
    "Nacional": GeoLevel.PAIS,
    "Comunidades": GeoLevel.CCAA,
    "Provincias": GeoLevel.PROVINCIA,
    "Municipios": GeoLevel.MUNICIPIO,
    "Secciones censales": GeoLevel.SECCION,
}
HOJA_EDAD = "Educacion por edad"
HOJA_INDICADORES = "Indicadores"
HOJA_HISTORICO = "Series historicas"

#: Cifras del código INE por nivel. Excel se come los ceros a la izquierda
#: si alguien escribe el código como número; se reponen aquí.
_CIFRAS = {GeoLevel.CCAA: 2, GeoLevel.PROVINCIA: 2, GeoLevel.MUNICIPIO: 5,
           GeoLevel.DISTRITO: 7, GeoLevel.SECCION: 10}


@dataclass(frozen=True, slots=True)
class Columna:
    """Una columna de la plantilla."""

    code: str
    etiqueta: str
    niveles: tuple[GeoLevel, ...]
    nota: str = ""


_TODOS = (GeoLevel.PAIS, GeoLevel.CCAA, GeoLevel.PROVINCIA, GeoLevel.MUNICIPIO,
          GeoLevel.SECCION)
_LOCAL = (GeoLevel.MUNICIPIO, GeoLevel.SECCION)
_TERR = (GeoLevel.PAIS, GeoLevel.CCAA, GeoLevel.PROVINCIA, GeoLevel.MUNICIPIO)
_HASTA_PROVINCIA = (GeoLevel.PAIS, GeoLevel.CCAA, GeoLevel.PROVINCIA)
_SIN_PAIS = (GeoLevel.CCAA, GeoLevel.PROVINCIA, GeoLevel.MUNICIPIO)

#: Lo que la plantilla puede traer, en el orden de las columnas.
COLUMNAS: tuple[Columna, ...] = (
    Columna("tra.vehicle.imd", "Tráfico vehicular · IMD (vehículos/día)", _LOCAL,
            "Intensidad media diaria de la vía principal del ámbito. Usad la fuente más "
            "completa, reciente y detallada entre el mapa de tráfico (DGT/comunidad) y el "
            "aforo municipal, e indicad cuál en «Indicadores»."),
    Columna("tra.pedestrian.aforo", "Tráfico peatonal · aforo (personas/día)", _LOCAL,
            "Paso medio diario de peatones medido en la zona. Misma regla: la fuente más "
            "completa, reciente y detallada (aforo municipal, conteo propio…)."),
    Columna("eco.consumer.online_pct", "% compra online (16-74 años, últimos 3 meses)",
            (GeoLevel.PAIS, GeoLevel.CCAA),
            "SOLO comunidad autónoma y nacional. Provincias y municipios heredan el dato "
            "de su comunidad. Precargado con la TIC-H 2025."),
    Columna("dem.nat.diversity_index", "Índice de diversidad cultural (0-1)", _TODOS,
            "Recomendado Simpson/Blau: 1 − Σ pᵢ² con los grupos de nacionalidad del Censo."),
    Columna("dem.nat.foreign_pct", "% población extranjera", _TODOS,
            "El motor ya lo saca del Censo anual por municipio; rellenad solo huecos y "
            "secciones censales."),
    Columna("dem.civil.single_pct", "% población soltera (16+)", _TODOS,
            "El INE lo da en municipios de 500+ habitantes; rellenad los menores si los tenéis."),
    Columna("dem.civil.married_pct", "% población casada (16+)", _TODOS),
    Columna("dem.birth.rate", "Tasa bruta de natalidad (‰)", _TERR,
            "Nacimientos por 1.000 habitantes. El motor la carga por provincia; aquí, municipal."),
    Columna("dem.children.mean", "Nº medio de hijos por hogar", _TODOS,
            "Todos los hijos del hogar, sin límite de edad: nº total de hijos / nº de hogares."),
    Columna("dem.household.with_children_pct", "% hogares con hijos", _TODOS),
    Columna("dem.household.monoparental_pct", "% hogares monoparentales", _TODOS),
    Columna("dem.edu.primary_or_less_pct", "% sin estudios o con estudios primarios (15+)", _TODOS,
            "El motor lo saca del Censo anual en municipios de 500+; rellenad huecos."),
    Columna("dem.edu.university_pct", "% con estudios superiores (15+)", _TODOS,
            "Índice de cualificación universitaria."),
    Columna("cli.temp.annual", "Clima · temperatura media anual (°C)", _TERR,
            "Solo si se desvincula AEMET."),
    Columna("cli.precip.annual", "Clima · precipitación anual (mm)", _TERR),
    Columna("cli.sun.days", "Clima · días de sol al año", _TERR),
    Columna("cli.rain.days", "Clima · días de lluvia al año", _TERR),
    # Altas del equipo de datos en la entrega del 18/10/2026. Van detrás de
    # las anteriores para no mover ninguna columna: las fórmulas de la hoja
    # «Clima - calculo CCAA» apuntan a ellas por letra.
    Columna("cli.humidity.annual", "Clima · humedad relativa media anual (%)", _TERR,
            "Media anual de humedad relativa. Si es una aproximación (media del mes más "
            "húmedo y del más seco), decidlo en la columna Fuente."),
    Columna("cli.sun.hours.annual", "Clima · horas de sol anuales (h)", _TERR,
            "Horas de sol al año, NO días: no confundir con «días de sol»."),
    # -- Capas complementarias del formulario (interruptores) -----------------
    Columna("pol.turnout_pct", "Elecciones · participación (%)", _TERR,
            "Votantes / censo electoral de la última convocatoria. En «Indicadores», "
            "Periodo = fecha de la elección y Fuente = tipo de elección (generales, "
            "municipales…) e Infoelectoral. Una sola convocatoria para todas las filas."),
    Columna("pol.winner_share_pct", "Elecciones · voto a la candidatura más votada (%)", _TERR,
            "Porcentaje de votos válidos de la candidatura más votada. Misma convocatoria."),
    Columna("pol.effective_parties", "Elecciones · nº efectivo de partidos", _TERR,
            "1 / Σ pᵢ² con las cuotas de voto válido de cada candidatura. Misma convocatoria."),
    Columna("mov.interprov.in_rate", "Traslados · llegadas desde otras provincias (‰)", _SIN_PAIS,
            "Altas por cambio de residencia con origen en otra provincia por 1.000 hab. "
            "(INE, EMCR)."),
    Columna("mov.interprov.out_rate", "Traslados · salidas hacia otras provincias (‰)", _SIN_PAIS,
            "Bajas por cambio de residencia con destino otra provincia por 1.000 hab."),
    Columna("mov.interprov.net_rate", "Traslados · saldo entre provincias (‰)", _SIN_PAIS,
            "Llegadas − salidas por 1.000 hab. Puede ser negativo."),
    Columna("tur.hotel.travellers", "Turismo · viajeros en hoteles (año)", _TERR,
            "INE, Encuesta de Ocupación Hotelera, total anual. Municipios: sólo los puntos "
            "turísticos del INE; el resto en blanco, nunca 0."),
    Columna("tur.hotel.overnight", "Turismo · pernoctaciones hoteleras (año)", _TERR,
            "Total anual de pernoctaciones (EOH). Mismo criterio para municipios."),
    Columna("tur.hotel.stay_mean", "Turismo · estancia media (días)", _TERR,
            "Pernoctaciones / viajeros."),
    Columna("tur.overnight_per_1000hab", "Turismo · pernoctaciones por 1.000 hab.", _TERR,
            "Pernoctaciones / población × 1.000. Es la que compara zonas de distinto tamaño."),
    Columna("inm.sales.dwellings", "Vivienda · compraventas de viviendas (año)",
            _HASTA_PROVINCIA,
            "INE, ETDP, total anual. No hay dato municipal: no lo pongáis por municipio."),
    Columna("inm.sales.per_1000hab", "Vivienda · compraventas por 1.000 hab.", _HASTA_PROVINCIA,
            "Compraventas / población × 1.000. Los municipios heredan el de su provincia."),
    Columna("inm.dwellings.main_pct", "Vivienda · % viviendas principales", _TODOS,
            "INE, Censo 2021: viviendas principales / total de viviendas × 100."),
    Columna("inm.dwellings.empty_pct", "Vivienda · % viviendas vacías", _TODOS,
            "INE, Censo 2021: viviendas vacías / total × 100. Las de uso esporádico NO "
            "cuentan como vacías ni como segunda residencia."),
    Columna("inm.price.m2", "Vivienda · valor tasado medio (€/m²)", _HASTA_PROVINCIA,
            "MIVAU, valor tasado medio de la vivienda libre, último trimestre. Los "
            "municipios heredan el de su provincia. El histórico va en «Series historicas»."),
    Columna("inm.price.yoy_change", "Vivienda · variación interanual del valor tasado (%)",
            _HASTA_PROVINCIA, "Puede ser negativa (−3,2)."),
    Columna("inm.rent.m2", "Vivienda · alquiler de referencia (€/m² al mes)", _TERR,
            "MIVAU, SERPAVI (tablas resumen). Es una referencia, no un contrato."),
)

#: Indicadores con serie anual (hoja «Series historicas», segmento {"year"}).
#: Tienen que coincidir con `domain.sections.inmobiliario.SERIES_HISTORICAS`.
COLUMNAS_HISTORICO: tuple[str, ...] = ("inm.price.m2", "inm.rent.m2")

#: Indicadores que admiten valores negativos (el resto, no).
ADMITEN_NEGATIVOS = frozenset({"mov.interprov.net_rate", "inm.price.yoy_change"})

#: Columnas de la hoja de educación por tramo de edad (se guardan con segmento).
COLUMNAS_EDAD: tuple[str, ...] = (
    "dem.edu.primary_or_less_pct", "dem.edu.secondary_pct", "dem.edu.university_pct",
)

#: Lo que sólo se publica por arriba y de dónde lo heredan los niveles de
#: debajo, en orden: el primero que tenga dato. Sólo tasas, precios y medias:
#: un total (compraventas, pernoctaciones) no se hereda nunca.
HEREDA: dict[str, tuple[GeoLevel, ...]] = {
    # INE TIC-H: sólo por comunidad autónoma.
    "eco.consumer.online_pct": (GeoLevel.CCAA,),
    # ETDP y valor tasado del MIVAU: por provincia.
    "inm.sales.per_1000hab": (GeoLevel.PROVINCIA,),
    "inm.price.m2": (GeoLevel.PROVINCIA,),
    "inm.price.yoy_change": (GeoLevel.PROVINCIA,),
    # Clima anual de la plantilla (AEMET por capital de provincia). Si AEMET
    # da el dato del municipio, manda AEMET: esto sólo rellena huecos.
    "cli.temp.annual": (GeoLevel.PROVINCIA,),
    "cli.precip.annual": (GeoLevel.PROVINCIA,),
    "cli.sun.days": (GeoLevel.PROVINCIA,),
    "cli.rain.days": (GeoLevel.PROVINCIA,),
    "cli.humidity.annual": (GeoLevel.PROVINCIA,),
    "cli.sun.hours.annual": (GeoLevel.PROVINCIA,),
}
#: Compatibilidad: lo que se hereda de la comunidad autónoma.
POR_COMUNIDAD = frozenset(c for c, de in HEREDA.items() if de == (GeoLevel.CCAA,))

_NOMBRE_NIVEL = {GeoLevel.CCAA: "comunidad autónoma", GeoLevel.PROVINCIA: "provincia"}

CargadorDeHechos = Callable[[list[int], list[str]], list[Fact]]


@dataclass(frozen=True, slots=True)
class Registro:
    nivel: GeoLevel
    codigo: str
    indicador: str
    valor: float | None
    periodo: date
    fuente: str
    edad: str = ""
    anio: str = ""
    #: Hoja de la que sale (para el informe de validación).
    hoja: str = ""

    @property
    def segmento(self) -> dict[str, str]:
        if self.edad:
            return {"age": self.edad}
        if self.anio:
            return {"year": self.anio}
        return {}


class PlantillaCollector(BaseCollector):
    name = "plantilla"
    TODAS_LAS_GEOS = True
    PROVIDES = tuple(dict.fromkeys(
        [c.code for c in COLUMNAS] + list(COLUMNAS_EDAD) + list(COLUMNAS_HISTORICO)
    ))

    def __init__(
        self,
        ruta: str | Path | None = None,
        *,
        facts_loader: CargadorDeHechos | None = None,
        oficiales: Iterable[str] = (),
        semillas: Sequence[Path] = SEMILLAS,
    ) -> None:
        """
        * `ruta`: la plantilla rellena (.xlsx, o .csv en formato largo).
        * `facts_loader`: acceso al almacén para no pisar datos oficiales.
        * `oficiales`: indicadores que también trae una API; de ellos sólo se
          rellenan huecos.
        """
        self._ruta = Path(ruta or os.getenv("POWERGIS_PLANTILLA") or RUTA_POR_DEFECTO)
        self._loader = facts_loader
        self._oficiales = frozenset(oficiales)
        self._semillas = tuple(semillas)
        self.fallos: list[str] = []

    # ------------------------------------------------------------------ #

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

        registros = [r for r in self.leer() if r.indicador in wanted]
        propios: dict[tuple[str, str, str], list[Registro]] = {}
        for r in registros:
            propios.setdefault((str(r.nivel), r.codigo, r.indicador), []).append(r)

        ocupados = self._ocupados(geos, wanted & self._oficiales)

        out: list[Fact] = []
        heredados = 0
        for geo in geos:
            nivel = GeoLevel(geo.level)
            for code in sorted(wanted):
                suyos = propios.get((str(nivel), geo.ine_code, code), [])
                for r in suyos:
                    # La API manda: sólo se rellenan huecos de lo oficial. Lo
                    # segmentado (edad, año) no compite con lo oficial.
                    if not r.segmento and (geo.geo_id, code) in ocupados:
                        continue
                    out.append(self.fact(
                        geo, code, r.valor, period or r.periodo,
                        r.segmento or None, source_ref=self._ref(r.fuente),
                    ))
                if any(not r.segmento for r in suyos) or (geo.geo_id, code) in ocupados:
                    continue
                heredado = self._heredado(propios, nivel, geo.ine_code, code)
                if heredado is None:
                    continue
                r, de = heredado
                heredados += 1
                out.append(self.fact(
                    geo, code, r.valor, period or r.periodo, None,
                    source_ref=f"{self._ref(r.fuente)} · dato de la {_NOMBRE_NIVEL[de]}",
                ))
        if heredados:
            log.info("plantilla: %d valores heredados de su provincia o comunidad", heredados)
        return out

    @staticmethod
    def _heredado(
        propios: dict[tuple[str, str, str], list[Registro]],
        nivel: GeoLevel,
        codigo: str,
        code: str,
    ) -> tuple[Registro, GeoLevel] | None:
        """El dato de la provincia o comunidad de la que cuelga, si se hereda."""
        for de in HEREDA.get(code, ()):
            if nivel.rank <= de.rank:
                continue
            if de is GeoLevel.CCAA:
                padre = ccaa_de(nivel, codigo)
            elif nivel is GeoLevel.PROVINCIA:
                padre = None
            else:
                padre = provincia_de(nivel, codigo)
            filas = [r for r in propios.get((str(de), padre or "", code), []) if not r.segmento]
            if filas:
                return filas[0], de
        return None

    # ------------------------------------------------------------------ #

    @staticmethod
    def _ref(fuente: str) -> str:
        # Las semillas oficiales (INE TIC-H) conservan su fuente tal cual; lo
        # que rellena el equipo lleva el prefijo para poder distinguirlo.
        return fuente if fuente.startswith("INE") else f"{PREFIJO} · {fuente}"

    def _ocupados(self, geos: Sequence[Geo], codigos: set[str]) -> set[tuple[int, str]]:
        """(geo, indicador) que ya tienen dato OFICIAL en el almacén."""
        if not codigos or self._loader is None:
            return set()
        hechos = self._loader([g.geo_id for g in geos], sorted(codigos))
        return {
            (h.geo_id, h.indicator) for h in hechos
            if h.value is not None and not (h.source_ref or "").startswith(PREFIJO)
        }

    # ------------------------------------------------------------------ #
    # Lectura
    # ------------------------------------------------------------------ #

    def leer(self) -> list[Registro]:
        """Semillas + plantilla. Lo de la plantilla pisa a la semilla."""
        registros: dict[tuple[str, str, str, str, str], Registro] = {}
        for ruta in self._semillas:
            for r in self._leer_csv(ruta):
                registros[(str(r.nivel), r.codigo, r.indicador, r.edad, r.anio)] = r
        if self._ruta.exists():
            leidos = (
                self._leer_csv(self._ruta) if self._ruta.suffix.lower() == ".csv"
                else self._leer_xlsx(self._ruta)
            )
            for r in leidos:
                registros[(str(r.nivel), r.codigo, r.indicador, r.edad, r.anio)] = r
        else:
            log.info("plantilla: no hay fichero en %s; sólo semillas", self._ruta)
        return list(registros.values())

    def _leer_csv(self, ruta: Path) -> list[Registro]:
        """Formato largo: nivel;codigo_ine;territorio;indicador;valor;periodo;fuente[;edad]."""
        out: list[Registro] = []
        with ruta.open(encoding="utf-8-sig", newline="") as fh:
            muestra = fh.read(2048)
            fh.seek(0)
            separador = ";" if muestra.count(";") >= muestra.count(",") else ","
            for n, fila in enumerate(csv.DictReader(fh, delimiter=separador), start=2):
                fila = {(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
                if not fila.get("valor"):
                    continue
                try:
                    nivel = GeoLevel(fila["nivel"].lower())
                except (KeyError, ValueError):
                    self.fallos.append(f"{ruta.name}:{n}: nivel desconocido «{fila.get('nivel')}»")
                    continue
                anio = _anio(fila.get("anio") or fila.get("año") or "")
                r = self._registro(
                    nivel, fila.get("codigo_ine", ""), fila.get("indicador", ""),
                    fila.get("valor"), fila.get("periodo") or anio, fila.get("fuente", ""),
                    fila.get("edad", ""), anio=anio, donde=f"{ruta.name}:{n}",
                )
                if r is not None:
                    out.append(r)
        return out

    def _leer_xlsx(self, ruta: Path) -> list[Registro]:
        from openpyxl import load_workbook

        libro = load_workbook(ruta, read_only=True, data_only=True)
        meta = self._meta_indicadores(libro)
        out: list[Registro] = []
        for hoja, nivel in HOJAS.items():
            if hoja not in libro.sheetnames:
                continue
            filas = list(libro[hoja].iter_rows(values_only=True))
            if len(filas) < 3:
                continue
            codigos = [str(c or "").strip() for c in filas[1]]
            for n, fila in enumerate(filas[2:], start=3):
                codigo = fila[0] if fila else None
                if codigo in (None, ""):
                    continue
                for j, code in enumerate(codigos[2:], start=2):
                    if not code or j >= len(fila) or fila[j] in (None, ""):
                        continue
                    periodo, fuente = meta.get(code, (None, ""))
                    r = self._registro(nivel, codigo, code, fila[j], periodo, fuente,
                                       donde=f"{hoja}!fila {n}")
                    if r is not None:
                        out.append(r)
        if HOJA_EDAD in libro.sheetnames:
            filas = list(libro[HOJA_EDAD].iter_rows(values_only=True))
            codigos = [str(c or "").strip() for c in filas[1]] if len(filas) > 1 else []
            for n, fila in enumerate(filas[2:], start=3):
                if not fila or fila[0] in (None, "") or fila[1] in (None, ""):
                    continue
                try:
                    nivel = GeoLevel(str(fila[0]).strip().lower())
                except ValueError:
                    self.fallos.append(f"{HOJA_EDAD}!fila {n}: nivel desconocido «{fila[0]}»")
                    continue
                edad = _tramo(fila[3] if len(fila) > 3 else None)
                if not edad:
                    self.fallos.append(f"{HOJA_EDAD}!fila {n}: tramo de edad vacío o ilegible")
                    continue
                for j, code in enumerate(codigos[4:], start=4):
                    if not code or j >= len(fila) or fila[j] in (None, ""):
                        continue
                    periodo, fuente = meta.get(code, (None, ""))
                    r = self._registro(nivel, fila[1], code, fila[j], periodo, fuente,
                                       edad=edad, donde=f"{HOJA_EDAD}!fila {n}")
                    if r is not None:
                        out.append(r)
        if HOJA_HISTORICO in libro.sheetnames:
            out += self._leer_historico(libro[HOJA_HISTORICO], meta)
        libro.close()
        return out

    def _leer_historico(self, hoja: Any, meta: dict[str, tuple[Any, str]]) -> list[Registro]:
        """Formato largo: nivel | codigo_ine | territorio | indicador | año | valor."""
        out: list[Registro] = []
        filas = list(hoja.iter_rows(values_only=True))
        for n, fila in enumerate(filas[2:], start=3):
            if not fila or len(fila) < 6 or all(v in (None, "") for v in fila):
                continue
            if fila[5] in (None, ""):
                continue
            donde = f"{HOJA_HISTORICO}!fila {n}"
            try:
                nivel = GeoLevel(str(fila[0] or "").strip().lower())
            except ValueError:
                self.fallos.append(f"{donde}: nivel desconocido «{fila[0]}»")
                continue
            code = str(fila[3] or "").strip()
            if code not in COLUMNAS_HISTORICO:
                self.fallos.append(
                    f"{donde}: «{code}» no tiene serie histórica (solo "
                    + ", ".join(COLUMNAS_HISTORICO) + ")"
                )
                continue
            anio = _anio(fila[4])
            if not anio:
                self.fallos.append(f"{donde}: año vacío o ilegible «{fila[4]}»")
                continue
            _, fuente = meta.get(code, (None, ""))
            r = self._registro(nivel, fila[1], code, fila[5], int(anio), fuente,
                               anio=anio, donde=donde)
            if r is not None:
                out.append(r)
        return out

    def _meta_indicadores(self, libro: Any) -> dict[str, tuple[Any, str]]:
        """Periodo y fuente de cada indicador, de la hoja «Indicadores»."""
        if HOJA_INDICADORES not in libro.sheetnames:
            self.fallos.append("falta la hoja «Indicadores» con periodo y fuente")
            return {}
        filas = list(libro[HOJA_INDICADORES].iter_rows(values_only=True))
        if not filas:
            return {}
        cabecera = [_pliega(str(c or "")) for c in filas[0]]
        try:
            i_cod = cabecera.index("codigo")
            i_per = next(i for i, c in enumerate(cabecera) if c.startswith("periodo"))
            i_fue = next(i for i, c in enumerate(cabecera) if c.startswith("fuente"))
        except (ValueError, StopIteration):
            self.fallos.append("la hoja «Indicadores» no tiene las columnas código/periodo/fuente")
            return {}
        out: dict[str, tuple[Any, str]] = {}
        for fila in filas[1:]:
            if not fila or not fila[i_cod]:
                continue
            out[str(fila[i_cod]).strip()] = (fila[i_per], str(fila[i_fue] or "").strip())
        return out

    def _registro(
        self,
        nivel: GeoLevel,
        codigo: Any,
        indicador: str,
        valor: Any,
        periodo: Any,
        fuente: str,
        edad: str = "",
        *,
        anio: str = "",
        donde: str,
    ) -> Registro | None:
        indicador = str(indicador or "").strip()
        if indicador not in self.PROVIDES:
            self.fallos.append(f"{donde}: indicador desconocido «{indicador}»")
            return None
        numero = _numero(valor)
        if numero is None:
            self.fallos.append(f"{donde}: «{valor}» no es un número ({indicador})")
            return None
        if indicador.endswith("_pct") and not 0.0 <= numero <= 100.0:
            self.fallos.append(f"{donde}: {indicador} = {numero} está fuera de 0–100")
            return None
        if numero < 0 and indicador not in ADMITEN_NEGATIVOS:
            self.fallos.append(f"{donde}: {indicador} = {numero} no puede ser negativo")
            return None
        fecha = _periodo(periodo)
        if fecha is None:
            self.fallos.append(
                f"{donde}: {indicador} sin periodo de referencia (hoja «Indicadores»)"
            )
            return None
        return Registro(
            nivel=nivel,
            codigo=_codigo(nivel, codigo),
            indicador=indicador,
            valor=numero,
            periodo=fecha,
            fuente=fuente or "sin fuente indicada",
            edad=edad,
            anio=anio,
            hoja=donde.split("!")[0],
        )


# --------------------------------------------------------------------------- #
# Validación sin base de datos (`powergis plantilla-validar`)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Validacion:
    """Lo que pasaría al cargar la plantilla, hoja por hoja."""

    cargados: dict[str, dict[str, int]]          # hoja → indicador → valores
    rechazos: dict[str, list[str]]               # hoja → motivos
    vacias: dict[str, list[str]]                 # hoja → columnas sin un valor
    formulas_sin_valor: list[str]                # celdas con fórmula y sin resultado guardado

    @property
    def ok(self) -> bool:
        return not any(self.rechazos.values()) and not self.formulas_sin_valor

    def total(self) -> int:
        return sum(sum(v.values()) for v in self.cargados.values())


def validar(ruta: str | Path) -> Validacion:
    """Lee la plantilla como lo haría la carga, sin tocar el almacén."""
    from openpyxl import load_workbook

    ruta = Path(ruta)
    colector = PlantillaCollector(ruta, semillas=())
    registros = colector.leer()

    cargados: dict[str, dict[str, int]] = {}
    for r in registros:
        cuenta = cargados.setdefault(r.hoja or "?", {})
        cuenta[r.indicador] = cuenta.get(r.indicador, 0) + 1

    rechazos: dict[str, list[str]] = {}
    for fallo in colector.fallos:
        donde = fallo.split("!")[0] if "!" in fallo else "General"
        rechazos.setdefault(donde, []).append(fallo)

    vacias: dict[str, list[str]] = {}
    formulas: list[str] = []
    if ruta.suffix.lower() != ".csv":
        con_formulas = load_workbook(ruta, read_only=True, data_only=False)
        con_valores = load_workbook(ruta, read_only=True, data_only=True)
        for hoja in (*HOJAS, HOJA_EDAD, HOJA_HISTORICO):
            if hoja not in con_formulas.sheetnames:
                continue
            f_filas = list(con_formulas[hoja].iter_rows(values_only=True))
            v_filas = list(con_valores[hoja].iter_rows(values_only=True))
            codigos = [str(c or "").strip() for c in (f_filas[1] if len(f_filas) > 1 else ())]
            for i, (ff, vv) in enumerate(zip(f_filas[2:], v_filas[2:], strict=False), start=3):
                for j, (f, v) in enumerate(zip(ff, vv, strict=False)):
                    if isinstance(f, str) and f.startswith("=") and v is None:
                        from openpyxl.utils import get_column_letter

                        formulas.append(f"{hoja}!{get_column_letter(j + 1)}{i}")
            if hoja in HOJAS:
                rellenas = {
                    codigos[j] for fila in v_filas[2:] for j, v in enumerate(fila)
                    if j >= 2 and j < len(codigos) and v not in (None, "")
                }
                vacias[hoja] = [c for c in codigos[2:] if c and c not in rellenas]
        con_formulas.close()
        con_valores.close()
    return Validacion(cargados=cargados, rechazos=rechazos, vacias=vacias,
                      formulas_sin_valor=formulas)


# --------------------------------------------------------------------------- #


def _pliega(texto: str) -> str:
    import unicodedata

    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def _codigo(nivel: GeoLevel, raw: Any) -> str:
    if nivel is GeoLevel.PAIS:
        return "ES"
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    texto = str(raw).strip()
    cifras = _CIFRAS.get(nivel)
    return texto.zfill(cifras) if cifras and texto.isdigit() else texto


def _numero(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    texto = str(raw or "").strip().replace("%", "").replace("‰", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _periodo(raw: Any) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, int | float) and 1900 < raw < 2100:
        return date(int(raw), 1, 1)
    texto = str(raw or "").strip()
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto):
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", texto):
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    if m := re.search(r"(19|20)\d{2}", texto):
        return date(int(m.group(0)), 1, 1)
    return None


def _anio(raw: Any) -> str:
    """2019, '2019', 2019.0, '2019-T4' → '2019'."""
    if isinstance(raw, datetime | date):
        return str(raw.year)
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    m = re.search(r"(19|20)\d{2}", str(raw or ""))
    return m.group(0) if m else ""


def _tramo(raw: Any) -> str:
    """'25-34', '25 a 34', 'De 25 a 34 años' → '25-34'; '65 y más' → '65+'."""
    texto = _pliega(str(raw or ""))
    if m := re.search(r"(\d{1,3})\s*(?:-|a)\s*(\d{1,3})", texto):
        return f"{m.group(1)}-{m.group(2)}"
    if m := re.search(r"(\d{1,3})\s*(?:\+|y mas|o mas)", texto):
        return f"{m.group(1)}+"
    return ""
