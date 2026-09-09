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

    @property
    def env_key(self) -> str:
        return f"INE_TABLE_{self.indicator.upper().replace('.', '_')}"

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


# Semilla de tablas. Verificar los IDs con `powergis ine-discover <id>` antes
# de una carga masiva: el INE los renumera al republicar una operación.
TABLES: tuple[TableSpec, ...] = (
    TableSpec("2879", "dem.pop.total", "municipio"),
    TableSpec("2879", "dem.sex.men", "municipio", match=("hombres",)),
    TableSpec("2879", "dem.sex.women", "municipio", match=("mujeres",)),
    TableSpec("56934", "dem.age.0_15", "municipio", match=("0-15",)),
    TableSpec("56934", "dem.age.16_64", "municipio", match=("16-64",)),
    TableSpec("56934", "dem.age.65p", "municipio", match=("65",)),
    TableSpec("56934", "dem.age.mean", "municipio", match=("edad media",)),
    TableSpec("56934", "dem.pop.segment", "municipio", segment_from="age"),
    TableSpec("59524", "dem.nat.foreign_pct", "municipio", match=("extranjer",)),
    TableSpec("61399", "dem.edu.university_pct", "municipio", match=("superior",)),
    TableSpec("61399", "dem.edu.secondary_pct", "municipio", match=("segunda etapa",)),
    TableSpec("61399", "dem.edu.primary_pct", "municipio", match=("primera etapa",)),
    TableSpec("61399", "dem.edu.none_pct", "municipio", match=("analfabet", "sin estudios")),
    TableSpec("61250", "dem.household.size", "municipio", match=("tamaño medio",)),
    TableSpec("61250", "dem.household.single_pct", "municipio", match=("unipersonal",)),
    TableSpec("1470", "dem.birth.rate", "provincia", match=("natalidad",)),
)

_AGE_TOKEN = re.compile(r"(\d{1,3})\s*(?:-|a)\s*(\d{1,3})|(\d{1,3})\s*(?:y más|o más|\+)")
_YEAR = re.compile(r"(19|20)\d{2}")


def _fold(text: str) -> str:
    """Minúsculas sin acentos: 'Municipios' y 'MUNICIPIOS' son lo mismo."""
    import unicodedata

    normalised = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalised if not unicodedata.combining(c)).lower().strip()


class IneCollector(BaseCollector):
    name = "ine"
    PROVIDES = tuple({spec.indicator for spec in TABLES})

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
        if not wanted or not geos:
            return []

        by_code = {g.ine_code.zfill(5): g for g in geos}
        by_code.update({g.ine_code: g for g in geos})
        facts: list[Fact] = []

        for spec in TABLES:
            if spec.indicator not in wanted:
                continue
            try:
                rows = self._table(spec)
            except CollectorError as exc:
                log.warning("INE tabla %s (%s): %s", spec.resolved_id(), spec.indicator, exc.message)
                continue
            facts.extend(self._map(spec, rows, by_code, segments, period))

        return facts

    # ------------------------------------------------------------------ #

    def _table(self, spec: TableSpec, nult: int = 1) -> list[dict[str, Any]]:
        tabla, motivo = self.resolver_tabla(spec)
        if tabla != spec.table_id:
            log.info("%s → tabla %s (%s)", spec.indicator, tabla, motivo)
        payload = self._client.get_json(
            f"DATOS_TABLA/{tabla}", {"nult": nult, "tip": "A", "det": 2}
        )
        if isinstance(payload, dict):
            payload = payload.get("Data") or payload.get("data") or []
        if not isinstance(payload, list):
            raise CollectorError("Respuesta inesperada del INE", table=tabla)
        return payload

    def _map(
        self,
        spec: TableSpec,
        rows: Iterable[dict[str, Any]],
        by_code: dict[str, Geo],
        segments: Segments,
        period: date | None,
    ) -> list[Fact]:
        out: list[Fact] = []
        wanted_ages = {a.lower() for a in segments.age}
        wanted_sex = {s.upper() for s in segments.sex}

        for row in rows:
            name = str(row.get("Nombre") or row.get("nombre") or "")
            lower = name.lower()

            if spec.match and not any(token in lower for token in spec.match):
                continue
            if spec.exclude and any(token in lower for token in spec.exclude):
                continue

            geo = self._geo_of(name, by_code)
            if geo is None:
                continue

            segment: dict[str, str] = {}
            if spec.segment_from == "age":
                age = self._age_of(lower)
                if age is None:
                    continue
                if wanted_ages and age.lower() not in wanted_ages:
                    continue
                segment["age"] = age
            if spec.segment_from == "sex" or "hombres" in lower or "mujeres" in lower:
                sex = "M" if "hombres" in lower else ("F" if "mujeres" in lower else None)
                if sex and (not wanted_sex or sex in wanted_sex):
                    segment["sex"] = sex

            for value, point_period in self._points(row):
                out.append(
                    self.fact(
                        geo,
                        spec.indicator,
                        None if value is None else value * spec.scale,
                        period or point_period,
                        segment or None,
                        source_ref=f"INE:{spec.resolved_id()}",
                    )
                )
        return out

    def _points(self, row: dict[str, Any]) -> list[tuple[float | None, date]]:
        data = row.get("Data") or row.get("data") or []
        out: list[tuple[float | None, date]] = []
        for point in data:
            value = self.to_float(point.get("Valor", point.get("valor")))
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
    def _geo_of(name: str, by_code: dict[str, Geo]) -> Geo | None:
        """El INE nombra las series como '28079 Madrid. Total. ...'."""
        head = name.split(".")[0].strip()
        token = head.split(" ")[0].strip()
        if token.isdigit():
            return by_code.get(token) or by_code.get(token.zfill(5)) or by_code.get(token.zfill(2))
        lowered = head.lower()
        for geo in by_code.values():
            if geo.name.lower() == lowered:
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
    def _recencia(tabla: dict[str, Any]) -> tuple[int, int]:
        """Cómo de nueva es una tabla: (año del dato, última modificación).

        Los campos no son los mismos en todas las operaciones — las de
        población traen `Anyo_Periodo_fin`, las demográficas y de renta traen
        `FechaRef_fin` — así que se prueban por orden y se usa el primero que
        haya. `Ultima_Modificacion` sí está en todas, pero sólo desempata: una
        tabla vieja puede haberse retocado ayer, y eso no la hace reciente.
        """
        ano = 0
        for campo in ("Anyo_Periodo_fin", "Anyo_Periodo_ini"):
            valor = tabla.get(campo)
            if isinstance(valor, int) and 1900 < valor < 2200:
                ano = max(ano, valor)
        if not ano:
            match = _YEAR.search(str(tabla.get("FechaRef_fin") or ""))
            if match:
                ano = int(match.group(0))

        modificacion = tabla.get("Ultima_Modificacion")
        marca = modificacion if isinstance(modificacion, int) else 0
        return (ano, marca)

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
        ano = self._recencia(elegida)[0]
        return (
            str(elegida.get("Id") or spec.table_id),
            f"la más reciente de {len(candidatas)} en la operación {spec.operacion}"
            + (f", datos de {ano}" if ano else ""),
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
        specs = specs or TABLES
        cache: dict[str, list[dict[str, Any]] | None] = {}
        results: list[dict[str, Any]] = []

        for spec in specs:
            table_id, motivo = self.resolver_tabla(spec)
            if table_id not in cache:
                try:
                    cache[table_id] = self._table(spec, nult=1)
                except CollectorError as exc:
                    log.warning("INE tabla %s no responde: %s", table_id, exc.message)
                    cache[table_id] = None
                except Exception as exc:  # un verificador que se cae no verifica nada
                    log.warning("INE tabla %s: %s", table_id, exc)
                    cache[table_id] = None

            rows = cache[table_id]
            entry: dict[str, Any] = {
                "indicator": spec.indicator,
                "table": table_id,
                "overridden": table_id != spec.table_id,
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

            if spec.match:
                hits = [n for n in names if any(t in n.lower() for t in spec.match)]
                entry["matched"] = len(hits)
                entry["sample"] = hits[:3] if hits else names[:3]
                if not hits:
                    entry.update(
                        status="NO_MATCH",
                        detail=f"ninguna serie contiene {list(spec.match)}",
                    )
                    results.append(entry)
                    continue
            else:
                entry["matched"] = len(names)
                entry["sample"] = names[:3]

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
        broken = [r for r in results if r["status"] not in ("OK", "STALE")]
        stale = [r for r in results if r["status"] == "STALE"]
        return {
            "checked": len(results),
            "ok": len(results) - len(broken) - len(stale),
            "stale": len(stale),
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
