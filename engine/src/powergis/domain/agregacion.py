"""Del municipio a la provincia, la comunidad y el país.

El INE publica casi todo lo que usamos POR MUNICIPIO, y el formulario ofrece
informes que comparan provincias («ccaa») y comunidades («nacional»). Sin este
paso esas zonas no tenían más dato que la natalidad: el informe salía vacío.

Dos reglas, y la diferencia se dice en la fuente de cada hecho:

* **Suma** — personas. Las cifras del Padrón son aditivas: la suma de los
  municipios de una provincia ES la población oficial de la provincia. Sólo se
  escribe si TODOS los municipios con datos tienen el suyo y del mismo año; con
  uno solo en hueco, la suma sería menor que la real y no avisaría de nada.

* **Media ponderada** — porcentajes, medias y rentas, ponderadas por lo que
  corresponde: personas para lo que se mide por persona, hogares (población
  entre tamaño medio del hogar) para lo que se mide por hogar. Es muy buena
  aproximación pero no el dato oficial —los pesos son del Padrón y el Atlas
  es de otro año—, así que se marca como tal. Exige que los municipios con
  dato sumen al menos el 95 % de la población.

Lo que no se puede agregar no se agrega: una mediana o un índice de Gini de
una provincia NO salen de las de sus municipios. Se quedan en hueco.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

SUMA = "suma"
MEDIA = "media"
HOGARES = "hogares"

FUENTE_SUMA = "agregado de municipios · suma"
FUENTE_MEDIA = "agregado de municipios · media ponderada"
PREFIJO_FUENTE = "agregado de municipios"

#: Parte mínima del peso que tiene que tener dato para dar una media.
COBERTURA_MEDIA = 0.95


@dataclass(frozen=True, slots=True)
class Regla:
    modo: str
    peso: str | None = None


REGLAS: dict[str, Regla] = {
    "dem.pop.total": Regla(SUMA),
    "dem.sex.men": Regla(SUMA),
    "dem.sex.women": Regla(SUMA),
    "dem.age.mean": Regla(MEDIA, "dem.pop.total"),
    "dem.age.u18_pct": Regla(MEDIA, "dem.pop.total"),
    "dem.age.65p_pct": Regla(MEDIA, "dem.pop.total"),
    "dem.household.size": Regla(MEDIA, HOGARES),
    "dem.household.single_pct": Regla(MEDIA, HOGARES),
    "eco.income.household.mean": Regla(MEDIA, HOGARES),
    "eco.income.household.net": Regla(MEDIA, HOGARES),
    "eco.income.percapita": Regla(MEDIA, "dem.pop.total"),
}

Valor = tuple[float | None, date]
#: Lo que se sabe de un municipio: código → (valor, periodo).
Hijo = Mapping[str, Valor]


def codigos_necesarios() -> list[str]:
    return sorted(set(REGLAS) | {"dem.pop.total", "dem.household.size"})


def _peso(hijo: Hijo, regla: Regla) -> float | None:
    poblacion = hijo.get("dem.pop.total", (None, date.min))[0]
    if regla.peso == HOGARES:
        tamano = hijo.get("dem.household.size", (None, date.min))[0]
        if poblacion is None or not tamano:
            return None
        return poblacion / tamano
    if regla.peso is None:
        return None
    return hijo.get(regla.peso, (None, date.min))[0]


def agregar(hijos: Sequence[Hijo]) -> dict[str, tuple[float, date, str]]:
    """Valores del padre a partir de los de sus municipios.

    Sólo cuentan los municipios «vivos», los que tienen algún dato: el
    nomenclátor arrastra municipios fusionados o desaparecidos que ya no
    publica nadie, y exigir su dato dejaría sin suma a la provincia entera.
    """
    vivos = [h for h in hijos if any(v is not None for v, _ in h.values())]
    if not vivos:
        return {}

    out: dict[str, tuple[float, date, str]] = {}
    for codigo, regla in REGLAS.items():
        if regla.modo == SUMA:
            valores = [h.get(codigo) for h in vivos]
            if any(v is None or v[0] is None for v in valores):
                continue
            periodos = {v[1] for v in valores if v is not None}
            if len(periodos) != 1:
                continue
            total = sum(v[0] for v in valores if v is not None and v[0] is not None)
            out[codigo] = (float(total), periodos.pop(), FUENTE_SUMA)
            continue

        # La cobertura se mide SIEMPRE en población, aunque el peso sea de
        # hogares: si se midiera con el propio peso, un municipio sin tamaño
        # del hogar saldría del numerador y del denominador a la vez, y la
        # comprobación del 95 % no comprobaría nada.
        poblacion_total = 0.0
        poblacion_con_dato = 0.0
        peso_con_dato = 0.0
        acumulado = 0.0
        periodos_media: list[date] = []
        for h in vivos:
            poblacion = h.get("dem.pop.total", (None, date.min))[0]
            if poblacion is None or poblacion <= 0:
                continue
            poblacion_total += poblacion
            peso = _peso(h, regla)
            valor = h.get(codigo)
            if peso is None or peso <= 0 or valor is None or valor[0] is None:
                continue
            poblacion_con_dato += poblacion
            peso_con_dato += peso
            acumulado += valor[0] * peso
            periodos_media.append(valor[1])
        if poblacion_total <= 0 or poblacion_con_dato / poblacion_total < COBERTURA_MEDIA:
            continue
        out[codigo] = (acumulado / peso_con_dato, max(periodos_media), FUENTE_MEDIA)
    return out
