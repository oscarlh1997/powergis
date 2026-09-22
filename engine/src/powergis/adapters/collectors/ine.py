"""Colector del INE — API JSON (Tempus3).

    https://servicios.ine.es/wstempus/js/ES/{FUNCION}/{ID}

Funciones usadas:
    DATOS_TABLA/{id}                  datos de una tabla  (?nult=, ?tip=A, ?det=)
    GRUPOS_TABLA/{id}                 variables de filtrado de la tabla
    VALORES_GRUPOSTABLA/{id}/{grupo}  valores posibles    (tv=variable:valor)
    SERIES_TABLA/{id}                 metadatos de series

Principio de diseño: **el INE no se consulta con un usuario esperando.** Es un
catálogo que cambia una o dos veces al año, así que aquí se descarga la tabla
entera y se vuelca a `fact_indicator`. El informe lee del almacén.

Los IDs de tabla se declaran en `TABLES` y se pueden sobreescribir por
variable de entorno sin tocar código: el INE republica y renumera tablas, y no
queremos un despliegue por eso.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from ...config import get_settings
from ...domain.errors import CollectorError
from ...domain.models import Fact, Geo, Segments
from .base import BaseCollector, HttpClient

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Una tabla del INE y cómo mapear sus series a nuestros indicadores."""

    table_id: str
    indicator: str
    level: str                       # nivel geográfico de las filas
    match: tuple[str, ...] = ()      # tokens que deben aparecer en el nombre de la SERIE
    exclude: tuple[str, ...] = ()
    segment_from: str | None = None  # 'age' | 'sex' | 'nationality' | 'month'
    scale: float = 1.0

    #: Operación del INE a la que pertenece la tabla, si se conoce.
    #:
    #: El ID de tabla es lo que el INE renumera al republicar; el de la
    #: operación es estable. Declarándola, el motor puede preguntar cuál es la
    #: edición vigente en vez de quedarse con la que se escribió aquí el día
    #: que se montó el sistema.
    operacion: int | None = None

    #: Tokens que deben aparecer en el nombre de la TABLA. No confundir con
    #: `match`, que filtra series DENTRO de una tabla.
    #:
    #: Hacen falta porque una operación no tiene una tabla por año: la 22 tiene
    #: una por provincia («Albacete: Población por municipios y sexo»), la 353
    #: tiene 540 llamadas todas igual, y la 10 seis llamadas «Demografía».
    #: Quedarse sin más con «la más reciente de la operación» elegiría una
    #: cualquiera — probablemente de otra provincia — y el informe saldría
    #: lleno de datos que no son de donde dice.
    table_match: tuple[str, ...] = ()

    #: Usar TODAS las tablas que encajen, no sólo la más reciente.
    #:
    #: El Atlas de renta publica una tabla por provincia, las 54 con el mismo
    #: nombre. Quedarse con «la más reciente» daría los municipios de una
    #: provincia y ninguno del resto — que es exactamente cómo la población de
    #: España acabó saliendo de la tabla de La Rioja.
    varias_tablas: bool = False

    #: Prefijo de la variable de entorno que fija el ID a mano. Cada colector
    #: tiene el suyo para que dos fuentes distintas no compartan interruptor.
    env_prefix: str = "INE_TABLE_"

    #: Motivo por el que este indicador todavía no tiene fuente buena.
    #:
    #: Un spec pendiente no se descarga ni se carga, pero `ine-verify` lo sigue
    #: enseñando. Sin esta marca había dos opciones malas: borrarlo —y el
    #: indicador desaparecía también de la lista de cosas por hacer— o dejarlo
    #: fallando, y entonces `make ingest-ine`, que se niega a cargar si algo
    #: falla, no cargaba nunca nada.
    pendiente: str | None = None

    @property
    def env_key(self) -> str:
        return f"{self.env_prefix}{self.indicator.upper().replace('.', '_')}"

    @property
    def fijada_a_mano(self) -> bool:
        """True si una variable de entorno fija el ID.

        Cuando alguien la pone, manda: es la vía de escape para cuando la
        resolución automática se equivoca, y una resolución que la ignorase
        dejaría a esa persona sin forma de corregir nada.
        """
        return os.getenv(self.env_key) is not None

    def resolved_id(self) -> str:
        return os.getenv(self.env_key, self.table_id)


# Semilla de tablas. Los IDs son el respaldo: cuando el spec declara
# `operacion`, el motor pregunta al INE cuál es la tabla vigente y usa esa.
# Comprobarlo con `powergis ine-tablas <operacion>` y `powergis ine-verify`.
#
# ---------------------------------------------------------------------------
# POBLACIÓN MUNICIPAL — por qué la 29005 y no la que había
#
# Aquí ponía `2879`, y `2879` es **la tabla de La Rioja**. La operación 22 tiene
# una tabla por provincia («Albacete: Población por municipios y sexo», «Rioja,
# La: …»), así que la población, los hombres y las mujeres de toda España
# salían de 174 municipios. No fallaba nada: las series son municipales, el
# detector de nivel las aprueba, y el resto del país sencillamente no aparecía.
#
# La única municipal y nacional de esa operación es la 29005 —24.414 series—,
# y sus nombres van sin código: «Ababuj. Total. Total habitantes. Personas.».
#
# `dem.pop.total` lleva `exclude` en vez de `match`: las tres series de cada
# municipio contienen «Total habitantes», así que filtrar por «total» las
# cogería las tres y escribiría tres hechos del mismo indicador para la misma
# geografía. Lo que distingue al total es que NO dice ni hombres ni mujeres.
# ---------------------------------------------------------------------------
TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "29005", "dem.pop.total", "municipio",
        exclude=("hombres", "mujeres"),
        operacion=22, table_match=("cifras oficiales del padron por municipio",),
    ),
    TableSpec(
        "29005", "dem.sex.men", "municipio", match=("hombres",),
        operacion=22, table_match=("cifras oficiales del padron por municipio",),
    ),
    TableSpec(
        "29005", "dem.sex.women", "municipio", match=("mujeres",),
        operacion=22, table_match=("cifras oficiales del padron por municipio",),
    ),
    # -----------------------------------------------------------------------
    # EDAD Y HOGARES — Atlas de distribución de renta de los hogares (op. 353)
    #
    # La única fuente del INE con estos indicadores POR MUNICIPIO para todo el
    # país. Una tabla por provincia, las 54 llamadas «Indicadores
    # demográficos»; de ahí `varias_tablas`. Series comprobadas en la tabla
    # de Albacete:
    #
    #     Abengibre. Edad media de la población. Dato base.
    #     Abengibre. Porcentaje de población menor de 18 años. Dato base.
    #     Abengibre. Porcentaje de población de 65 y más años. Dato base.
    #     Abengibre. Tamaño medio del hogar. Dato base.
    #     Abengibre. Porcentaje de hogares unipersonales. Dato base.
    #
    # Mezclan municipios con distritos y secciones censales. No hace falta
    # filtrarlos: el índice por nombre sólo conoce municipios, así que las
    # secciones no resuelven y se cuentan como series sin geografía.
    #
    # Los tramos son los del Atlas —menor de 18 y 65+, en PORCENTAJE—, que no
    # son los de personas con corte 15/16 del catálogo. Son indicadores
    # distintos y llevan códigos distintos.
    # -----------------------------------------------------------------------
    TableSpec("30814", "dem.age.mean", "municipio", match=("edad media de la poblacion",),
              operacion=353, table_match=("indicadores demograficos",), varias_tablas=True),
    TableSpec("30814", "dem.age.u18_pct", "municipio", match=("menor de 18",),
              operacion=353, table_match=("indicadores demograficos",), varias_tablas=True),
    TableSpec("30814", "dem.age.65p_pct", "municipio", match=("65 y mas",),
              operacion=353, table_match=("indicadores demograficos",), varias_tablas=True),
    TableSpec("30814", "dem.household.size", "municipio", match=("tamano medio del hogar",),
              operacion=353, table_match=("indicadores demograficos",), varias_tablas=True),
    TableSpec("30814", "dem.household.single_pct", "municipio",
              match=("hogares unipersonales",),
              operacion=353, table_match=("indicadores demograficos",), varias_tablas=True),

    # -----------------------------------------------------------------------
    # SIN FUENTE VERIFICADA — se dejan declarados para que `ine-verify` los
    # siga señalando. Un indicador que desaparece del mapeo desaparece
    # también de la lista de pendientes.
    #
    #   · `56934` es NACIONAL («Total Nacional. Todas las edades…»). La fuente
    #     buena para tramos de edad en personas y para el público objetivo es
    #     «Población por sexo, municipios y edad (grupos quinquenales)», de la
    #     Estadística del Padrón continuo: una tabla por provincia, en una
    #     operación que no está en OPERACIONES_DISPONIBLES. Se localiza con
    #     `powergis ine-buscar --desde-tabla 33956`.
    #   · `59524` es una tabla de VIVIENDA, no de nacionalidad.
    #   · `61399` no existe. La educación municipal completa sólo la publica el
    #     Censo 2021; los Indicadores Urbanos (op. 10) la dan por niveles ISCED
    #     pero sólo en ciudades grandes y mezclando ciudad y área urbana, y un
    #     «Madrid» área metropolitana casaría con el municipio de Madrid.
    # -----------------------------------------------------------------------
    TableSpec("56934", "dem.age.0_15", "municipio", match=("0-15",),
              pendiente="56934 es nacional; la fuente es el Padrón continuo por edad"),
    TableSpec("56934", "dem.age.16_64", "municipio", match=("16-64",),
              pendiente="56934 es nacional; la fuente es el Padrón continuo por edad"),
    TableSpec("56934", "dem.age.65p", "municipio", match=("65",),
              pendiente="56934 es nacional; mientras, dem.age.65p_pct del Atlas"),
    TableSpec("56934", "dem.pop.segment", "municipio", segment_from="age",
              pendiente="necesita la población por edad del Padrón continuo"),
    TableSpec("59524", "dem.nat.foreign_pct", "municipio", match=("extranjer",),
              pendiente="59524 es una tabla de vivienda; buscar en el Padrón continuo"),
    TableSpec("61399", "dem.edu.university_pct", "municipio", match=("superior",),
              pendiente="61399 no existe; la fuente completa es el Censo 2021"),
    TableSpec("61399", "dem.edu.secondary_pct", "municipio", match=("segunda etapa",),
              pendiente="61399 no existe; la fuente completa es el Censo 2021"),
    TableSpec("61399", "dem.edu.primary_pct", "municipio", match=("primera etapa",),
              pendiente="61399 no existe; la fuente completa es el Censo 2021"),
    TableSpec("61399", "dem.edu.none_pct", "municipio", match=("analfabet", "sin estudios"),
              pendiente="61399 no existe; la fuente completa es el Censo 2021"),

    # `1470` y `67223` se llaman las dos «Tasa Bruta de Natalidad por
    # provincia» y tienen la misma fecha de modificación: sólo las distingue el
    # identificador, y la republicada es la de número mayor. La resolución por
    # operación se queda con esa sola.
    #
    # Hay versión municipal, pero con reservas: `30664` sólo trae 155 series
    # —los municipios grandes—, así que a nivel municipal la mayoría del país
    # saldría con hueco. Por eso sigue declarada provincial.
    TableSpec(
        "67223", "dem.birth.rate", "provincia", match=("fecundidad",),
        operacion=33, table_match=("natalidad por provincia",),
    ),
)

_AGE_TOKEN = re.compile(r"(\d{1,3})\s*(?:-|a)\s*(\d{1,3})|(\d{1,3})\s*(?:y más|o más|\+)")
_YEAR = re.compile(r"(19|20)\d{2}")


def _fold(text: str) -> str:
    """Minúsculas sin acentos: 'Municipios' y 'MUNICIPIOS' son lo mismo."""
    import unicodedata

    normalised = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalised if not unicodedata.combining(c)).lower().strip()


class IneCollector(BaseCollector):
    """Colector de tablas del INE.

    `SPECS` es atributo de clase para que otras fuentes del mismo organismo
    —el Atlas de renta— hereden TODO lo que hay aquí: edición vigente, varias
    tablas por indicador, series sin código, nombres repetidos, acentos. Cada
    una de esas cosas costó encontrar un fallo silencioso; tenerlas
    duplicadas garantiza que el siguiente arreglo llegue sólo a la mitad.
    """

    name = "ine"
    TODAS_LAS_GEOS = True
    SPECS: tuple[TableSpec, ...] = TABLES
    PROVIDES = tuple({spec.indicator for spec in TABLES})

    def __init_subclass__(cls, **kw: Any) -> None:
        super().__init_subclass__(**kw)
        cls.PROVIDES = tuple({spec.indicator for spec in cls.SPECS})

    def __init__(self, client: HttpClient | None = None) -> None:
        cfg = get_settings()
        #: Se guarda sólo para poder escribir en los errores el `curl` exacto
        #: que reproduce el fallo. Un diagnóstico que no se puede repetir a
        #: mano obliga a adivinar.
        self._base_url = cfg.ine_base_url.rstrip("/")
        #: Listado de tablas por operación. Una ingesta toca seis tablas de
        #: tres operaciones; sin esto se pediría el listado entero una vez por
        #: indicador.
        self._tablas_cache: dict[int, list[dict[str, Any]]] = {}
        #: Filas por tabla DURANTE UNA CARGA. Varios indicadores leen la misma
        #: tabla —tres la 29005, cinco las 54 del Atlas— y sin esto cada uno
        #: la volvía a descargar: 270 peticiones donde bastan 54, a la tasa
        #: que el INE tolera y con cinco veces más papeletas para que alguna
        #: falle a medias. Se vacía al empezar y al acabar `collect`, para
        #: que un worker de larga vida no arrastre datos de la carga anterior.
        self._filas_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
        #: Lo que falló en la última carga. `IngestData` lo pasa al informe de
        #: la carga y `powergis ingest` sale con error: sin esto un indicador
        #: entero podía no cargarse y la orden terminaba «bien».
        self.fallos: list[str] = []
        self._client = client or HttpClient(
            cfg.ine_base_url,
            timeout=cfg.ine_timeout,
            max_retries=cfg.ine_max_retries,
            rps=cfg.ine_rps,
        )

    # ------------------------------------------------------------------ #

    def collect(
        self,
        indicators: Sequence[str],
        geos: Sequence[Geo],
        segments: Segments,
        period: date | None = None,
    ) -> list[Fact]:
        wanted = set(indicators) & set(self.PROVIDES)
        self.fallos = []
        if not wanted or not geos:
            return []
        self._filas_cache.clear()

        by_code = {g.ine_code.zfill(5): g for g in geos}
        by_code.update({g.ine_code: g for g in geos})
        by_name = self._indice_por_nombre(geos)
        facts: list[Fact] = []

        niveles = {str(g.level) for g in geos}
        for spec in self.SPECS:
            if spec.indicator not in wanted:
                continue
            # Un spec pendiente no tiene tabla buena: descargarla sería traer
            # datos que no son lo que dice el indicador.
            if spec.pendiente:
                continue
            # Cada spec sólo contra geografías de SU nivel. Cargando municipios
            # no tiene sentido bajar la tabla provincial de natalidad, ni
            # cargando provincias las 54 del Atlas.
            if spec.level not in niveles:
                continue
            try:
                rows = self._table(spec)
            except CollectorError as exc:
                log.warning("INE tabla %s (%s): %s", spec.resolved_id(), spec.indicator, exc.message)
                self.fallos.append(f"{spec.indicator}: {exc.message}")
                continue
            facts.extend(self._map(spec, rows, by_code, by_name, segments, period))

        self._filas_cache.clear()
        return self._sin_conflictos(facts)

    @staticmethod
    def _sin_conflictos(facts: list[Fact]) -> list[Fact]:
        """Quita los hechos que aparecen dos veces con valores DISTINTOS.

        Dos valores para el mismo municipio, indicador, periodo y segmento
        quieren decir que dos series han casado con la misma geografía y no
        hay forma de saber cuál es la buena. Quedarse con una sería elegir a
        ciegas; se quitan las dos y se avisa. Además PostgreSQL rechaza el
        lote entero si un `INSERT … ON CONFLICT` trae la misma clave dos veces,
        así que un solo conflicto tumbaba mil hechos buenos.

        Las repeticiones con el MISMO valor sí se funden en una: son la misma
        cifra llegada por dos tablas, no una contradicción.
        """
        por_clave: dict[tuple[Any, ...], list[Fact]] = {}
        for f in facts:
            clave = (f.geo_id, f.indicator, f.period, f.segment_key())
            por_clave.setdefault(clave, []).append(f)

        limpios: list[Fact] = []
        conflictos = 0
        for grupo in por_clave.values():
            if len({g.value for g in grupo}) == 1:
                limpios.append(grupo[0])
                continue
            # De tablas DISTINTAS: la primera es la más reciente (las tablas se
            # leen de la más nueva a la más vieja), y una edición nueva manda
            # sobre la vieja. Dentro de la MISMA tabla sí es una contradicción:
            # dos series para un sitio, y no hay forma de saber cuál es.
            primera = grupo[0].source_ref
            de_la_primera = {g.value for g in grupo if g.source_ref == primera}
            if len({g.source_ref for g in grupo}) > 1 and len(de_la_primera) == 1:
                limpios.append(grupo[0])
            else:
                conflictos += 1
        if conflictos:
            log.warning(
                "INE: %d combinaciones geografía/indicador con valores contradictorios; "
                "se descartan en vez de elegir uno a ciegas", conflictos,
            )
        return limpios

    @staticmethod
    def _indice_por_nombre(geos: Sequence[Geo]) -> dict[tuple[str, str], Geo]:
        """Índice (nivel, nombre normalizado) → geografía.

        Hace falta porque **la mitad del catálogo del INE no pone el código en
        el nombre de la serie**. La tabla municipal nacional del padrón dice
        «Ababuj. Total. Total habitantes.», sin el 44001 por ningún lado, y la
        de natalidad provincial dice «Fecundidad. Albacete.». Sin resolver por
        nombre, esas tablas no aportan un solo dato.

        Dos decisiones que no se ven en el tipo:

        · **Se indexa por NIVEL además de por nombre.** Ceuta y Melilla son a
          la vez municipio, provincia y comunidad; sin el nivel, una serie
          provincial podría casar con el municipio.

        · **Los nombres repetidos se DESCARTAN, no se resuelven a cualquiera.**
          Si dos municipios se llaman igual, no hay forma de saber cuál es, y
          elegir uno metería el dato de un pueblo en la ficha de otro sin que
          nada lo delatara. Preferimos el hueco: un hueco se ve, un dato
          equivocado no.
        """
        vistos: dict[tuple[str, str], Geo] = {}
        ambiguos: set[tuple[str, str]] = set()

        for geo in geos:
            clave = (str(geo.level), _fold(geo.name))
            if clave in vistos and vistos[clave].geo_id != geo.geo_id:
                ambiguos.add(clave)
                continue
            vistos[clave] = geo

        for clave in ambiguos:
            vistos.pop(clave, None)

        if ambiguos:
            log.info(
                "%d nombres repetidos entre geografías; esas series se dejarán sin "
                "resolver en vez de asignarlas a la primera que coincida",
                len(ambiguos),
            )
        return vistos

    # ------------------------------------------------------------------ #

    def _table(self, spec: TableSpec, nult: int = 1) -> list[dict[str, Any]]:
        """Las filas de un spec, vengan de una tabla o de cincuenta y cuatro.

        Con `varias_tablas` se concatenan. Un fallo en una NO tumba las demás:
        si el Atlas deja de responder para Soria, es preferible el almacén con
        52 provincias y un hueco visible que ninguna provincia y una excepción.
        """
        tablas, motivo = self.resolver_tablas(spec)
        if tablas != [spec.table_id]:
            log.info("%s → %s (%s)", spec.indicator, ", ".join(tablas[:3]), motivo)

        if len(tablas) == 1:
            return self._one_table(tablas[0], nult)

        filas: list[dict[str, Any]] = []
        fallidas = 0
        for tabla in tablas:
            try:
                filas.extend(self._one_table(tabla, nult))
            except CollectorError as exc:
                fallidas += 1
                log.warning("INE tabla %s (%s): %s", tabla, spec.indicator, exc.message)
        if fallidas:
            log.warning(
                "INE %s: %d de %d tablas no respondieron; el almacén quedará con huecos",
                spec.indicator, fallidas, len(tablas),
            )
            self.fallos.append(
                f"{spec.indicator}: {fallidas} de {len(tablas)} tablas no respondieron"
            )
        if not filas:
            raise CollectorError(
                f"Ninguna de las {len(tablas)} tablas de {spec.indicator} devolvió datos",
                indicator=spec.indicator,
            )
        return filas

    def _one_table(self, tabla: str, nult: int = 1) -> list[dict[str, Any]]:
        clave = (tabla, nult)
        if clave in self._filas_cache:
            return self._filas_cache[clave]
        payload = self._client.get_json(
            f"DATOS_TABLA/{tabla}", {"nult": nult, "tip": "A", "det": 2}
        )
        if isinstance(payload, dict):
            payload = payload.get("Data") or payload.get("data") or []
        if not isinstance(payload, list):
            raise CollectorError("Respuesta inesperada del INE", table=tabla)
        filas = [self._esencial(f) for f in payload if isinstance(f, dict)]
        for fila in filas:
            fila["Tabla"] = tabla
        self._filas_cache[clave] = filas
        return filas

    #: Marca de «esta serie es de otro nivel territorial»: provincia, comunidad,
    #: total nacional, distrito o sección.
    NO_MUNICIPIO = "-"

    #: Variables territoriales que NO son municipio, por nombre exacto (plegado).
    #: Por subcadena no: «nacional» casaría con «Nacionalidad».
    _OTROS_NIVELES = frozenset({
        "provincias", "comunidades y ciudades autonomas", "comunidades autonomas",
        "total nacional", "totales territoriales", "islas",
    })

    @staticmethod
    def _municipio_de_metadatos(fila: dict[str, Any]) -> str | None:
        """Código INE del municipio de la serie, según sus metadatos.

        `det=2` acompaña cada serie de los valores de sus variables. El de
        «Municipios» (variable 19) trae el código de cinco cifras, que es lo
        único que distingue a dos pueblos que se llaman igual: la 29005 y el
        Atlas los nombran sin código ni provincia.

        Devuelve:
          · el código, si la serie es de un municipio;
          · `NO_MUNICIPIO`, si es de otro nivel (provincia, distrito,
            sección…): una fila provincial «Albacete.» no puede acabar en el
            municipio de Albacete;
          · None si no trae metadatos territoriales: entonces se resuelve por
            el nombre, como siempre.
        """
        codigo: str | None = None
        otro_nivel = False
        for meta in fila.get("MetaData") or fila.get("metadata") or []:
            if not isinstance(meta, dict):
                continue
            variable = meta.get("Variable") or {}
            if not isinstance(variable, dict):
                continue
            nombre_var = _fold(str(variable.get("Nombre") or ""))
            if nombre_var.startswith(("seccion", "distrito")):
                return IneCollector.NO_MUNICIPIO
            valor = str(meta.get("Codigo") or "").strip()
            if variable.get("Id") == 19 or nombre_var.startswith("municipio"):
                if valor.isdigit() and len(valor) == 5:
                    codigo = valor
            elif nombre_var in IneCollector._OTROS_NIVELES:
                otro_nivel = True
        if codigo:
            return codigo
        return IneCollector.NO_MUNICIPIO if otro_nivel else None

    @staticmethod
    def _esencial(fila: dict[str, Any]) -> dict[str, Any]:
        """Sólo lo que el mapeo usa: el nombre de la serie y sus puntos.

        Con `det=2` cada serie trae además sus metadatos completos —variables,
        unidad, escala, periodicidad—, unas diez veces lo que pesa el dato. Con
        TODOS los municipios en una sola llamada, las 54 tablas del Atlas
        (municipios, distritos y secciones) se quedaban enteras en memoria a
        la vez; recortadas caben de sobra en el worker.
        """
        puntos = fila.get("Data") or fila.get("data") or []
        return {
            "Nombre": fila.get("Nombre") or fila.get("nombre") or "",
            "Municipio": IneCollector._municipio_de_metadatos(fila),
            "Data": [
                {
                    "Valor": p.get("Valor", p.get("valor")),
                    "Anyo": p.get("Anyo") or p.get("anyo"),
                    "Fecha": p.get("Fecha") or p.get("fecha"),
                    "Secreto": p.get("Secreto", p.get("secreto")),
                }
                for p in puntos if isinstance(p, dict)
            ],
        }

    def _map(
        self,
        spec: TableSpec,
        rows: Iterable[dict[str, Any]],
        by_code: dict[str, Geo],
        by_name: dict[tuple[str, str], Geo],
        segments: Segments,
        period: date | None,
    ) -> list[Fact]:
        out: list[Fact] = []
        sin_resolver = 0
        de_otro_nivel = 0
        casadas = 0
        wanted_ages = {a.lower() for a in segments.age}
        wanted_sex = {s.upper() for s in segments.sex}

        for row in rows:
            name = str(row.get("Nombre") or row.get("nombre") or "")
            lower = name.lower()
            # Los filtros comparan SIN acentos por los dos lados: las series
            # dicen «población», «tamaño» y «65 y más», y un token sin acento
            # no casaría nunca. Se pliega en una variable aparte y `lower` se
            # deja como está, porque el lector de tramos de edad busca
            # literalmente «y más»; plegarlo le haría perder el último tramo.
            plegado = _fold(name)
            if spec.match and not any(_fold(t) in plegado for t in spec.match):
                continue
            if spec.exclude and any(_fold(t) in plegado for t in spec.exclude):
                continue

            casadas += 1
            meta = row.get("Municipio") if spec.level == "municipio" else None
            if meta == self.NO_MUNICIPIO:
                de_otro_nivel += 1      # provincia, distrito o sección
                continue
            # El código de los metadatos manda sobre el nombre. Si no está entre
            # las geografías, la serie no es de aquí: NO se prueba por nombre,
            # porque así es como el Castejón de Cuenca acababa en el de Navarra.
            geo = (
                self._por_codigo(str(meta), plegado, by_code) if meta
                else self._geo_of(name, by_code, by_name, spec.level)
            )
            if geo is None:
                sin_resolver += 1
                continue

            segment: dict[str, str] = {}
            if spec.segment_from == "age":
                age = self._age_of(lower)
                if age is None:
                    continue
                if wanted_ages and age.lower() not in wanted_ages:
                    continue
                segment["age"] = age
            # El sexo sólo se convierte en SEGMENTO cuando el indicador está
            # declarado como segmentado. Antes bastaba con que la serie dijera
            # «Hombres»: `dem.sex.men` —cuyo código ya dice que son hombres—
            # se guardaba además con `{sex: M}`, y el cálculo de derivados,
            # que lo busca sin segmento, no lo encontraba nunca. El índice de
            # feminidad y el % de mujeres no se llegaron a calcular ni una vez.
            if spec.segment_from in ("sex", "age") and ("hombres" in lower or "mujeres" in lower):
                sex = "M" if "hombres" in lower else "F"
                if not wanted_sex or sex in wanted_sex:
                    segment["sex"] = sex

            for value, point_period in self._points(row):
                out.append(
                    self.fact(
                        geo,
                        spec.indicator,
                        None if value is None else value * spec.scale,
                        period or point_period,
                        segment or None,
                        # La tabla de la que sale DE VERDAD, no la semilla: con
                        # 54 tablas por indicador, «INE:30814» no decía nada.
                        source_ref=f"INE:{row.get('Tabla') or spec.resolved_id()}",
                    )
                )

        # Que una tabla no case con ninguna geografía es el fallo más caro del
        # colector: devuelve cero hechos, no lanza nada, y el informe sale con
        # huecos que parecen secreto estadístico. Así al menos queda en el log.
        if sin_resolver:
            log.warning(
                "INE %s (tabla %s): %d series sin geografía reconocible",
                spec.indicator, spec.resolved_id(), sin_resolver,
            )
        if de_otro_nivel:
            log.info("INE %s: %d series de provincia, distrito o sección apartadas",
                     spec.indicator, de_otro_nivel)
        if casadas and not out:
            self.fallos.append(
                f"{spec.indicator}: {casadas} series encajan con el filtro y ninguna "
                "resolvió a una geografía"
            )
        return out

    @staticmethod
    def _por_codigo(codigo: str, plegado: str, by_code: dict[str, Geo]) -> Geo | None:
        """El municipio del código, si la serie lleva además su nombre.

        El código desempata entre homónimos; el nombre impide que una serie de
        sección o distrito —que cita el código de su municipio y cuya variable
        no se llame como esperamos— acabe guardada como el municipio entero.
        """
        geo = by_code.get(codigo)
        if geo is None:
            return None
        campos = {parte.strip() for parte in plegado.split(".") if parte.strip()}
        return geo if _fold(geo.name) in campos else None

    def _points(self, row: dict[str, Any]) -> list[tuple[float | None, date]]:
        data = row.get("Data") or row.get("data") or []
        out: list[tuple[float | None, date]] = []
        for point in data:
            value = self.to_float(point.get("Valor", point.get("valor")))
            # Un dato bajo secreto estadístico es un HUECO. Si el INE lo marca
            # así, da igual lo que ponga en `Valor`: no se guarda un cero.
            if point.get("Secreto") is True or point.get("secreto") is True:
                value = None
            year = point.get("Anyo") or point.get("anyo") or point.get("Fecha")
            out.append((value, self._period_of(year)))
        return out

    @staticmethod
    def _period_of(raw: Any) -> date:
        if isinstance(raw, int):
            return date(raw, 1, 1)
        text = str(raw or "")
        if text.isdigit() and len(text) == 13:  # timestamp ms
            from datetime import UTC, datetime

            return datetime.fromtimestamp(int(text) / 1000, UTC).date()
        match = _YEAR.search(text)
        return date(int(match.group(0)), 1, 1) if match else date.today()

    @staticmethod
    def _geo_of(
        name: str,
        by_code: dict[str, Geo],
        by_name: dict[tuple[str, str], Geo] | None = None,
        level: str | None = None,
    ) -> Geo | None:
        """Localiza la geografía de una serie del INE.

        No hay UN formato, hay tres, y los tres aparecen en tablas que
        usamos:

            '28079 Madrid. Total. Personas.'   ← código delante
            'Ababuj. Total. Total habitantes.' ← sólo el nombre, y va primero
            'Fecundidad. Albacete.'            ← sólo el nombre, y va segundo

        Por eso se recorren TODOS los campos separados por puntos en vez de
        mirar sólo el primero. Mirar sólo el primero es lo que dejaba las
        tablas del tercer tipo sin un solo dato.

        El nivel esperado del spec acota la búsqueda y evita el falso positivo
        evidente: 'Ceuta' es municipio, provincia y comunidad a la vez.
        """
        campos = [parte.strip() for parte in name.split(".") if parte.strip()]

        # Primero por código, que es inequívoco.
        for campo in campos:
            token = campo.split(" ")[0].strip()
            if token.isdigit():
                geo = (
                    by_code.get(token)
                    or by_code.get(token.zfill(5))
                    or by_code.get(token.zfill(2))
                )
                if geo is not None:
                    return geo

        if not by_name:
            return None

        # Y sólo entonces por nombre, con el nivel como filtro. Se devuelve el
        # PRIMER campo que resuelva: en 'Fecundidad. Albacete.' el primero no
        # es una geografía y el segundo sí.
        niveles = [level] if level else sorted({lvl for lvl, _ in by_name})
        for campo in campos:
            plegado = _fold(campo)
            for lvl in niveles:
                geo = by_name.get((str(lvl), plegado))
                if geo is not None:
                    return geo
        return None

    @staticmethod
    def _age_of(text: str) -> str | None:
        match = _AGE_TOKEN.search(text)
        if not match:
            return None
        if match.group(1) and match.group(2):
            return f"{match.group(1)}-{match.group(2)}"
        if match.group(3):
            return f"{match.group(3)}+"
        return None

    # ------------------------------------------------------------------ #
    # Descubrimiento: sin esto, mapear una tabla del INE es adivinar
    # ------------------------------------------------------------------ #

    def discover(self, table_id: str) -> dict[str, Any]:
        """Variables y valores de una tabla. Úsalo antes de añadir un TableSpec.

            powergis ine-discover 56934
        """
        groups = self._client.get_json(f"GRUPOS_TABLA/{table_id}")
        out: dict[str, Any] = {"table": table_id, "groups": []}
        for group in groups if isinstance(groups, list) else []:
            gid = group.get("Id") or group.get("id")
            values = self._client.get_json(f"VALORES_GRUPOSTABLA/{table_id}/{gid}")
            out["groups"].append({
                "id": gid,
                "name": group.get("Nombre") or group.get("nombre"),
                "values": [
                    {"id": v.get("Id"), "name": v.get("Nombre")}
                    for v in (values if isinstance(values, list) else [])[:60]
                ],
            })
        return out

    def sample(self, table_id: str, limit: int = 5) -> list[str]:
        rows = self._client.get_json(f"DATOS_TABLA/{table_id}", {"nult": 1, "tip": "A"})
        rows = rows if isinstance(rows, list) else []
        return [str(r.get("Nombre", "")) for r in rows[:limit]]

    # ------------------------------------------------------------------ #
    # Verificación: los IDs de TABLES son una SEMILLA, no una certeza
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Resolver la edición vigente en vez de arrastrar la que se escribió
    # ------------------------------------------------------------------ #

    def tablas_de_operacion(self, operacion: int) -> list[dict[str, Any]]:
        """Todas las tablas de una operación. Se pide una vez por proceso."""
        if operacion in self._tablas_cache:
            return self._tablas_cache[operacion]
        payload = self._client.get_json(f"TABLAS_OPERACION/{operacion}")
        tablas = [t for t in payload if isinstance(t, dict)] if isinstance(payload, list) else []
        self._tablas_cache[operacion] = tablas
        return tablas

    @staticmethod
    def _recencia(tabla: dict[str, Any]) -> tuple[int, int, int]:
        """Cómo de nueva es una tabla: (año del dato, modificación, id).

        Tres cosas que hay que saber del formato real, porque ninguna es la
        que uno esperaría:

        · **Los años vienen como TEXTO.** `"Anyo_Periodo_fin": "2021"`, no
          2021. Filtrarlos por `isinstance(int)` los descarta todos, y
          entonces no hay ninguna fecha con la que ordenar.

        · **`FechaRef_fin` suele ser la cadena `"null"`.** No `None`: el texto
          literal. Está presente en las operaciones demográficas y de renta,
          y no lleva ninguna fecha dentro.

        · **`Anyo_Periodo_ini` NO sirve para esto.** Es cuándo EMPIEZA la
          serie, no cuándo acaba. Ordenar por él pondría arriba la tabla que
          arranca más tarde, que no tiene nada que ver con cuál trae el dato
          más nuevo.

        Así que el año sale sólo de `Anyo_Periodo_fin`, y cuando no está
        —operaciones 33 y 353— manda `Ultima_Modificacion`, que es un
        timestamp en milisegundos y el único indicio de frescura que queda.

        El Id cierra el desempate. Es una heurística, no un dato: el INE los
        asigna crecientes, así que entre dos tablas idénticas en nombre y
        fecha la de número mayor suele ser la republicada. Se usa la última
        porque sin ella el desempate sería el orden de llegada, que no
        significa nada en absoluto.
        """
        ano = 0
        match = _YEAR.search(str(tabla.get("Anyo_Periodo_fin") or ""))
        if match:
            ano = int(match.group(0))
        if not ano:
            match = _YEAR.search(str(tabla.get("FechaRef_fin") or ""))
            if match:
                ano = int(match.group(0))

        modificacion = tabla.get("Ultima_Modificacion")
        marca = modificacion if isinstance(modificacion, int) else 0

        try:
            identificador = int(tabla.get("Id") or 0)
        except (TypeError, ValueError):
            identificador = 0

        return (ano, marca, identificador)

    @staticmethod
    def etiqueta_fecha(tabla: dict[str, Any]) -> str:
        """Cómo se enseña la frescura de una tabla en pantalla.

        Cuando hay año de fin del periodo, ese es el dato. Cuando no, se
        enseña el año de la última modificación con una marca —«mod. 2025»—
        para que no se confunda con el año de los datos, que es otra cosa.
        """
        match = _YEAR.search(str(tabla.get("Anyo_Periodo_fin") or ""))
        if match:
            return match.group(0)

        modificacion = tabla.get("Ultima_Modificacion")
        if isinstance(modificacion, int) and modificacion > 0:
            from datetime import UTC, datetime

            return f"mod. {datetime.fromtimestamp(modificacion / 1000, UTC).year}"
        return "?"

    def resolver_tablas(self, spec: TableSpec) -> tuple[list[str], str]:
        """Todas las tablas que un spec necesita.

        Con `varias_tablas`, el indicador se alimenta del conjunto que encaja
        con `table_match`. Sin él se comporta como siempre: una sola tabla.
        """
        if spec.varias_tablas and spec.fijada_a_mano:
            # Con varias tablas la variable de entorno lleva la LISTA, separada
            # por comas y DE LA MÁS NUEVA A LA MÁS VIEJA: si dos tablas traen el
            # mismo municipio, manda la primera. Una sola tabla sería una sola
            # provincia.
            ids = [t.strip() for t in spec.resolved_id().split(",") if t.strip()]
            return ids, f"fijadas en {spec.env_key}"
        if not spec.varias_tablas or spec.operacion is None:
            unica, motivo = self.resolver_tabla(spec)
            return [unica], motivo

        # Aquí NO se cae a la tabla semilla si algo falla, al revés que con
        # una tabla sola: la semilla es UNA provincia, y cargarla creyendo que
        # es el país es exactamente el fallo de La Rioja. Mejor que la carga
        # de este indicador falle y `ine-verify` lo diga.
        try:
            tablas = self.tablas_de_operacion(spec.operacion)
        except Exception as exc:
            raise CollectorError(
                f"La operación {spec.operacion} no responde; sin su listado sólo se "
                "cargaría una provincia", indicator=spec.indicator,
            ) from exc

        tokens = [_fold(t) for t in spec.table_match]
        candidatas = [
            t for t in tablas
            if all(tok in _fold(str(t.get("Nombre") or "")) for tok in tokens)
        ]
        if not candidatas:
            raise CollectorError(
                f"Ninguna tabla de la operación {spec.operacion} contiene "
                f"{list(spec.table_match)}", indicator=spec.indicator,
            )
        candidatas.sort(key=self._recencia, reverse=True)
        ids = [str(t.get("Id")) for t in candidatas if t.get("Id") is not None]
        return ids, f"las {len(ids)} tablas de la operación {spec.operacion}"

    def resolver_tabla(self, spec: TableSpec) -> tuple[str, str]:
        """Devuelve (id_de_tabla, explicación) para un spec.

        El orden de preferencia no es arbitrario:

          1. La variable de entorno, si está. Quien la pone manda.
          2. La tabla más reciente de la operación cuyo nombre encaje.
          3. El ID de la semilla.

        Nunca lanza: si el INE no responde o nada encaja, se cae al ID de
        siempre y lo dice. Una carga que se niega a empezar porque el
        descubrimiento falló es peor que una carga con la tabla de ayer.
        """
        if spec.fijada_a_mano:
            return spec.resolved_id(), f"fijada en {spec.env_key}"
        if spec.operacion is None:
            return spec.table_id, "sin operación declarada"

        try:
            tablas = self.tablas_de_operacion(spec.operacion)
        except Exception as exc:  # el descubrimiento nunca bloquea una carga
            log.warning("No se pudo listar la operación %s: %s", spec.operacion, exc)
            return spec.table_id, f"la operación {spec.operacion} no responde"

        tokens = [_fold(t) for t in spec.table_match]
        candidatas = [
            t for t in tablas
            if all(tok in _fold(str(t.get("Nombre") or "")) for tok in tokens)
        ] if tokens else list(tablas)

        if not candidatas:
            return spec.table_id, f"ninguna tabla de {spec.operacion} contiene {list(spec.table_match)}"

        elegida = max(candidatas, key=self._recencia)
        return (
            str(elegida.get("Id") or spec.table_id),
            f"la más reciente de {len(candidatas)} en la operación {spec.operacion}"
            f" ({self.etiqueta_fecha(elegida)})",
        )

    #: A partir de cuántos años de antigüedad una tabla se considera vieja.
    #:
    #: El INE publica con retraso —el Padrón de un año sale al siguiente—, así
    #: que uno o dos años de diferencia son normales y no significan nada. Tres
    #: ya no: o la operación dejó de publicarse, o la republicaron con otro
    #: identificador y el nuestro se quedó apuntando a la edición vieja.
    MAX_ANTIGUEDAD_ANOS: int = 3

    @staticmethod
    def _ultimo_ano(rows: Sequence[dict[str, Any]]) -> int | None:
        """El año más reciente que aparece en los datos de una tabla."""
        anos: list[int] = []
        for row in rows:
            for point in row.get("Data") or row.get("data") or []:
                bruto = point.get("Anyo") or point.get("anyo") or point.get("Fecha")
                if isinstance(bruto, int) and 1900 < bruto < 2200:
                    anos.append(bruto)
                    continue
                match = _YEAR.search(str(bruto or ""))
                if match:
                    anos.append(int(match.group(0)))
        return max(anos) if anos else None

    def verify(self, specs: Sequence[TableSpec] | None = None) -> dict[str, Any]:
        """Contrasta cada `TableSpec` con la API real del INE.

        Existe porque el INE renumera tablas al republicar una operación y
        porque `match` son subcadenas del nombre de la serie: los dos fallan
        en silencio. Un filtro que deja de acertar no lanza una excepción,
        simplemente devuelve cero hechos, y el informe sale con huecos que
        parecen secreto estadístico. Esto lo convierte en un fallo ruidoso.

        Se descarga UNA vez por tabla distinta, no por spec: las 16 entradas
        de `TABLES` son 6 tablas.
        """
        specs = specs or self.SPECS
        cache: dict[tuple[str, ...], list[dict[str, Any]] | None] = {}
        results: list[dict[str, Any]] = []
        self._filas_cache.clear()

        for spec in specs:
            if spec.pendiente:
                results.append({
                    "indicator": spec.indicator, "table": spec.table_id,
                    "overridden": False, "resolution": "", "expected_level": spec.level,
                    "status": "PENDING", "detail": spec.pendiente,
                })
                continue
            try:
                tablas, motivo = self.resolver_tablas(spec)
            except CollectorError as exc:
                results.append({
                    "indicator": spec.indicator, "table": spec.table_id,
                    "overridden": False, "resolution": exc.message,
                    "expected_level": spec.level,
                    "status": "UNREACHABLE", "detail": exc.message,
                })
                continue
            clave = tuple(tablas)
            if clave not in cache:
                try:
                    cache[clave] = self._table(spec, nult=1)
                except CollectorError as exc:
                    log.warning("INE tabla %s no responde: %s", tablas[0], exc.message)
                    cache[clave] = None
                except Exception as exc:  # un verificador que se cae no verifica nada
                    log.warning("INE tabla %s: %s", tablas[0], exc)
                    cache[clave] = None

            rows = cache[clave]
            entry: dict[str, Any] = {
                "indicator": spec.indicator,
                # Con varias tablas se enseña cuántas, no una cualquiera: ver
                # «30814» cuando la carga usa 54 volvería a esconder el error
                # de leer una provincia creyendo leer el país.
                "table": tablas[0] if len(tablas) == 1 else f"{len(tablas)} tablas",
                "overridden": tablas != [spec.table_id],
                "resolution": motivo,
                "expected_level": spec.level,
            }

            if rows is None:
                entry.update(status="UNREACHABLE", detail="la tabla no responde o no existe")
                results.append(entry)
                continue

            names = [str(r.get("Nombre") or r.get("nombre") or "") for r in rows]
            entry["series"] = len(names)

            # El año de los datos, siempre. Una tabla puede responder, traer
            # series de sobra, encajar con los filtros y ser la edición de
            # 2019: pasa las cuatro comprobaciones y el informe sale con datos
            # viejos sin que nada lo diga. Enseñar el año en cada línea es lo
            # que convierte eso en algo que se ve de un vistazo.
            entry["year"] = self._ultimo_ano(rows)

            if not names:
                entry.update(status="EMPTY", detail="la tabla existe pero no devuelve series")
                results.append(entry)
                continue

            detected = self._detect_level(names)
            entry["detected_level"] = detected

            # El MISMO filtro que usará la carga, `exclude` incluido. Sin él,
            # `dem.pop.total` salía con 24.414 coincidencias cuando va a usar
            # 8.138: un verificador que cuenta otra cosa que la carga no
            # verifica la carga.
            hits = [
                n for n in names
                if (not spec.match or any(_fold(t) in _fold(n) for t in spec.match))
                and not (spec.exclude and any(_fold(t) in _fold(n) for t in spec.exclude))
            ]
            entry["matched"] = len(hits)
            entry["sample"] = hits[:3] if hits else names[:3]
            if not hits:
                entry.update(
                    status="NO_MATCH",
                    detail=(
                        f"ninguna serie contiene {list(spec.match)}" if spec.match
                        else f"todas las series quedan excluidas por {list(spec.exclude)}"
                    ),
                )
                results.append(entry)
                continue

            if detected and detected != spec.level:
                entry.update(
                    status="LEVEL_MISMATCH",
                    detail=f"se esperaba '{spec.level}' y las series son de '{detected}'",
                )
                results.append(entry)
                continue

            ano = entry["year"]
            if ano is not None and date.today().year - ano > self.MAX_ANTIGUEDAD_ANOS:
                entry.update(
                    status="STALE",
                    detail=(
                        f"el dato más reciente es de {ano}. Busca la edición nueva "
                        f"con `powergis ine-discover` y fíjala en {spec.env_key}"
                    ),
                )
                results.append(entry)
                continue

            entry.update(status="OK", detail="")
            results.append(entry)

        # `STALE` se cuenta aparte de `broken`, y a propósito. Una tabla vieja
        # responde y devuelve datos: no es un mapeo roto, es una decisión
        # —seguir con esa edición o buscar la nueva— y quien la toma es una
        # persona. Meterla en `broken` haría fallar el verificador por algo que
        # a veces es correcto, y un verificador que falla cuando no debe acaba
        # ignorándose entero.
        # PENDING tampoco cuenta como roto: es un indicador que se sabe que no
        # tiene fuente, declarado a propósito. Si contara, `make ingest-ine`
        # no cargaría nunca nada.
        broken = [r for r in results if r["status"] not in ("OK", "STALE", "PENDING")]
        pendientes = [r for r in results if r["status"] == "PENDING"]
        stale = [r for r in results if r["status"] == "STALE"]
        return {
            "checked": len(results),
            "ok": len(results) - len(broken) - len(stale) - len(pendientes),
            "stale": len(stale),
            "pending": len(pendientes),
            "broken": len(broken),
            "results": results,
        }

    # ------------------------------------------------------------------ #
    # Padrón de municipios: sin esto no hay almacén municipal
    # ------------------------------------------------------------------ #

    #: Nombres de variable del INE que designan el municipio. Se busca POR
    #: NOMBRE y no por ID porque los IDs de variable no son estables entre
    #: republicaciones y un ID equivocado carga 8.000 filas de basura en
    #: silencio. El nombre sí es estable.
    MUNICIPIO_VARIABLE_HINTS: tuple[str, ...] = ("municipio",)

    #: Operación del INE que lista los valores de UNA variable. En singular.
    #:
    #: El plural (`VALORES_VARIABLES`) no existe, y la trampa está en cómo lo
    #: dice el INE: contesta **200** con el texto plano «La operación indicada
    #: no existe (…)» en vez de un 404. Para el cliente HTTP eso es una
    #: respuesta correcta, así que el fallo sólo aparecía al intentar leerla
    #: como JSON, en forma de `JSONDecodeError` sin contexto.
    #:
    #: El nombre vive aquí, y no incrustado en la ruta, para que la prueba
    #: pueda fijarlo: es un error de una sola letra que no da error.
    OP_VALORES: str = "VALORES_VARIABLE"

    def municipality_variable_id(self) -> int:
        """Localiza la variable 'Municipios' preguntándole al propio INE."""
        payload = self._client.get_json("VARIABLES")
        candidates: list[tuple[int, str]] = []
        for var in payload if isinstance(payload, list) else []:
            name = _fold(str(var.get("Nombre") or var.get("nombre") or ""))
            vid = var.get("Id") or var.get("id")
            if vid is None:
                continue
            if any(hint in name for hint in self.MUNICIPIO_VARIABLE_HINTS):
                candidates.append((int(vid), name))

        if not candidates:
            raise CollectorError(
                "El INE no expone ninguna variable cuyo nombre contenga 'municipio'. "
                "Revisa la API antes de cargar geografías."
            )
        # El nombre más corto es el genérico ("Municipios") frente a variantes
        # como "Municipios de residencia".
        candidates.sort(key=lambda item: len(item[1]))
        return candidates[0][0]

    def municipalities(self, variable_id: int | None = None) -> list[dict[str, str]]:
        """Relación completa de municipios: código INE de 5 dígitos y nombre.

        La provincia NO se le pregunta al INE: son los dos primeros dígitos
        del código municipal, por definición del propio sistema de codificación.
        Derivarla es más fiable que arrastrar otro campo que puede venir vacío.
        """
        vid = variable_id if variable_id is not None else self.municipality_variable_id()
        ruta = f"{self.OP_VALORES}/{vid}"

        # Primero de una vez. Es lo normal y lo más barato.
        fallo_directo: Exception | None = None
        try:
            payload = self._client.get_json(ruta)
            valores = list(payload) if isinstance(payload, list) else []
        except CollectorError as exc:
            fallo_directo = exc
            valores = []

        # Los municipios son la lista más larga que publica el INE (~8.100
        # valores) y es justo la que a veces no cabe: contesta 200 con el
        # cuerpo vacío. Para eso existe `?page=`, así que se reintenta paginado
        # antes de darse por vencido. Si sale bien, el usuario no se entera; si
        # sale mal, el error dice las dos cosas que se intentaron.
        if not valores:
            log.warning(
                "%s no devolvió nada de una vez (%s); reintento paginado",
                ruta, fallo_directo or "lista vacía",
            )
            try:
                valores = self._paginar(ruta)
            except CollectorError as exc:
                raise CollectorError(
                    f"El INE no devuelve los valores de la variable {vid} ni entero ni "
                    f"paginado.\n  Entero:   {fallo_directo or 'lista vacía'}\n"
                    f"  Paginado: {exc}\n"
                    f"Compruébalo a mano:\n"
                    f'  curl -sS -i "{self._base_url}/{ruta}?page=1" | head -20',
                    variable=vid,
                ) from exc

        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for value in valores:
            code = str(value.get("Codigo") or value.get("codigo") or "").strip()
            name = str(value.get("Nombre") or value.get("nombre") or "").strip()
            if not code.isdigit() or len(code) != 5 or not name:
                continue
            if code in seen:
                continue
            seen.add(code)
            out.append({"ine_code": code, "name": name, "province_code": code[:2]})

        if not out:
            raise CollectorError(
                f"La variable {vid} devolvió {len(valores)} valores, pero ninguno "
                f"parece un municipio (código de 5 dígitos). Probablemente no sea "
                f"la variable de municipios: `powergis ine-discover` la localiza.",
                variable=vid,
                recibidos=len(valores),
            )
        return out

    #: El INE pagina a 500 registros cuando se le pasa `?page=`. Es el único
    #: camino cuando la lista entera no le cabe en una respuesta.
    PAGE_SIZE: int = 500
    #: ~8.100 municipios a 500 por página son 17. El tope deja margen de sobra
    #: y evita un bucle infinito si un día `page` deja de tener efecto.
    MAX_PAGES: int = 60

    def _paginar(self, ruta: str) -> list[dict[str, Any]]:
        """Recorre `?page=1,2,3…` hasta que se acaba la lista.

        Se para en tres sitios, y los tres importan:

          · una página vacía — fin normal;
          · una página más corta que `PAGE_SIZE` — la última;
          · una página que no aporta ningún valor nuevo — significa que la API
            está IGNORANDO `page` y devolviendo siempre lo mismo. Sin esta
            comprobación el bucle daría 60 vueltas para acabar con la misma
            lista repetida 60 veces.
        """
        acumulado: list[dict[str, Any]] = []
        vistos: set[str] = set()

        for pagina in range(1, self.MAX_PAGES + 1):
            trozo = self._client.get_json(ruta, params={"page": pagina})
            if not isinstance(trozo, list) or not trozo:
                break

            nuevos = 0
            for value in trozo:
                clave = str(
                    value.get("Id")
                    or value.get("Codigo")
                    or value.get("codigo")
                    or ""
                )
                if clave and clave in vistos:
                    continue
                if clave:
                    vistos.add(clave)
                acumulado.append(value)
                nuevos += 1

            if nuevos == 0:
                log.warning(
                    "El INE ignora ?page= en %s: la página %d repite lo anterior",
                    ruta, pagina,
                )
                break
            if len(trozo) < self.PAGE_SIZE:
                break

        return acumulado

    @staticmethod
    def _detect_level(names: Sequence[str]) -> str | None:
        """Deduce el nivel por la longitud del código que encabeza la serie.

        El INE nombra '28079 Madrid. …' (municipio, 5) frente a '28 Madrid. …'
        (provincia, 2). Se mira la mayoría, no la primera fila: las tablas
        suelen traer un total nacional delante.
        """
        counts: dict[str, int] = {}
        for name in names:
            token = name.split(".")[0].strip().split(" ")[0].strip()
            if not token.isdigit():
                continue
            level = {2: "provincia", 5: "municipio", 7: "seccion"}.get(len(token))
            if level:
                counts[level] = counts.get(level, 0) + 1
        if not counts:
            return None
        return max(counts, key=lambda k: counts[k])
