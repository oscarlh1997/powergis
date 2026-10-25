"""Atlas de Distribución de Renta de los Hogares (ADRH) del INE — operación 353.

La fuente REAL de los datos económicos del informe. Publica renta, Gini y
distribución a nivel de municipio, distrito y sección censal.

Avisos que están implementados, no sólo documentados:

1. **Estadística experimental** con unos dos años de desfase. El periodo del
   dato se guarda tal cual y el informe enseña el año.
2. **Secreto estadístico** en unidades pequeñas: el Atlas no publica. Se
   guarda `None`, nunca un cero.
3. **Una tabla por provincia**: se leen todas (`varias_tablas`).

QUÉ SE CORRIGIÓ
---------------
Era un colector aparte con su propio `_geo_of` y su propio filtro, y tenía los
mismos fallos que ya se habían arreglado en `IneCollector`: apuntaba a `30824`,
que es la tabla de UNA provincia; sólo miraba el primer campo del nombre; y
asignaba un nombre de municipio repetido al primero que coincidiera. Ninguno
salía en `ine-verify`, que sólo miraba las tablas de `ine`. Ahora hereda.

Y dos mapeos estaban cruzados:

- La mediana se pedía a `30832`, que pertenece a «Indicadores demográficos» y
  no tiene una sola serie de renta.
- `eco.income.household.mean` —«Renta BRUTA media por hogar» en el catálogo—
  recibía la renta NETA. El modelo de renta disponible la trataba como bruta y
  le restaba impuestos otra vez. Ahora cada una va a su código, y la neta se
  usa directamente como renta disponible, observada en vez de estimada.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from datetime import date
from typing import Any

from ...domain.models import Fact, Geo, Segments
from .ine import IneCollector, TableSpec

log = logging.getLogger(__name__)

#: Valores con los que el INE marca «no publicado por secreto estadístico».
SECRETO_MARKERS = {"..", ".", "", "-", "n/a"}

_ATLAS: dict[str, Any] = {"operacion": 353, "varias_tablas": True, "env_prefix": "ADRH_TABLE_"}
#: Familia de tablas con las seis series de renta (nombres comprobados):
#: renta neta media por persona / por hogar, media y mediana de la renta por
#: unidad de consumo, renta bruta media por persona / por hogar.
_RENTA = ("indicadores de renta media y mediana",)

#: Municipio, distrito y sección: el Atlas publica los tres en cada tabla y
#: antes se apartaban los dos últimos (análisis 8071).
_INFERIORES = ("distrito", "seccion")
#: Dos periodos: la variación interanual de la renta (`eco.income.yoy`) es un
#: derivado y con un solo año no sale nunca.
_DOS_ANOS = 2

#: Los desgloses por sexo y edad de las familias de umbrales: sólo el total.
_SIN_DESGLOSE = ("hombres", "mujeres", "menos de 18", "18 a 64", "65 y mas")
_POR_VERIFICAR = ("mapeo escrito sin ver la tabla: comprobar con "
                  "`powergis ine-tablas 353 --contiene umbrales` y `powergis ine-verify`")

SPECS: tuple[TableSpec, ...] = (
    TableSpec("30824", "eco.income.household.mean", "municipio",
              match=("renta bruta media por hogar",), table_match=_RENTA,
              tambien=_INFERIORES, nult=_DOS_ANOS, **_ATLAS),
    TableSpec("30824", "eco.income.household.net", "municipio",
              match=("renta neta media por hogar",), table_match=_RENTA,
              tambien=_INFERIORES, nult=_DOS_ANOS, **_ATLAS),
    TableSpec("30824", "eco.income.percapita", "municipio",
              match=("renta neta media por persona",), table_match=_RENTA,
              tambien=_INFERIORES, nult=_DOS_ANOS, **_ATLAS),
    TableSpec("30824", "eco.income.household.median", "municipio",
              match=("mediana de la renta por unidad de consumo",),
              table_match=_RENTA, tambien=_INFERIORES, nult=_DOS_ANOS, **_ATLAS),

    # «Índice de Gini y Distribución de la renta P80/P20». Si el INE cambia el
    # nombre de la familia, `ine-verify` lo dirá: ninguna tabla encajará.
    TableSpec("37677", "eco.gini", "municipio", match=("gini",),
              table_match=("gini",), tambien=_INFERIORES, **_ATLAS),

    # -----------------------------------------------------------------------
    # PROVISIONALES — familias de «umbrales relativos» y «umbrales fijos».
    #
    # Desglosan cada zona por sexo y tramos de edad; `exclude` deja sólo el
    # total. Los tokens se escribieron sin ver los nombres exactos de las
    # series (el proxy de la sesión no llega al INE): un spec provisional que
    # no casa no bloquea la carga ni escribe nada, y `ine-verify` enseña los
    # «ej.:» para ajustarlo. Si los umbrales fijos del Atlas no son 15.000,
    # 30.000 y 60.000 €, el indicador no casará y habrá que decidir si se
    # cambia la etiqueta del catálogo al umbral que sí se publica.
    # -----------------------------------------------------------------------
    TableSpec("37677", "eco.poverty.risk_pct", "municipio", match=("60%",),
              exclude=_SIN_DESGLOSE, table_match=("umbrales relativos",),
              tambien=_INFERIORES, provisional=_POR_VERIFICAR, **_ATLAS),
    TableSpec("30833", "eco.income.under15k_pct", "municipio", match=("debajo de 15.000",),
              exclude=_SIN_DESGLOSE, table_match=("umbrales fijos",),
              tambien=_INFERIORES, provisional=_POR_VERIFICAR, **_ATLAS),
    TableSpec("30833", "eco.income.over30k_pct", "municipio", match=("encima de 30.000",),
              exclude=_SIN_DESGLOSE, table_match=("umbrales fijos",),
              tambien=_INFERIORES, provisional=_POR_VERIFICAR, **_ATLAS),
    TableSpec("30833", "eco.income.over60k_pct", "municipio", match=("encima de 60.000",),
              exclude=_SIN_DESGLOSE, table_match=("umbrales fijos",),
              tambien=_INFERIORES, provisional=_POR_VERIFICAR, **_ATLAS),
)


class AdrhCollector(IneCollector):
    """Igual que `IneCollector`, con el recuento del secreto estadístico."""

    name = "ine_adrh"
    SPECS = SPECS

    def _map(
        self,
        spec: TableSpec,
        rows: Iterable[dict[str, Any]],
        by_code: dict[str, Geo],
        by_name: dict[tuple[str, str], Geo],
        segments: Segments,
        period: date | None,
    ) -> list[Fact]:
        filas = list(rows)
        facts = super()._map(spec, filas, by_code, by_name, segments, period)
        if spec.indicator == "eco.gini":
            facts = [_gini_en_tanto_por_uno(f) for f in facts]

        # El hueco ya se guarda como NULL; aquí se cuenta cuántos hay. En un
        # ámbito de pueblos pequeños pueden ser la mayoría, y entonces el
        # indicador no es que salga bajo: es que no está.
        callados = sum(
            1
            for fila in filas
            for punto in (fila.get("Data") or fila.get("data") or [])
            if punto.get("Secreto") is True
            or str(punto.get("Valor", "")).strip().lower() in SECRETO_MARKERS
        )
        if callados:
            log.info(
                "ADRH %s: %d valores no publicados por secreto estadístico "
                "(NULL, nunca 0)", spec.indicator, callados,
            )
        return facts


def _gini_en_tanto_por_uno(fact: Fact) -> Fact:
    """El Atlas publica el Gini de 0 a 100 (31,5); el catálogo y los índices
    de resistencia económica lo usan de 0 a 1 (0,315).

    Sin esto, `min(gini, 0.6)` daba siempre 0,6: todas las zonas parecían
    igual de desiguales, la resistencia salía multiplicada por 0,7 en todas partes y
    el Gini dejaba de distinguir nada. Se convierte sólo si viene en la escala
    grande, así que un cambio de formato del INE no lo rompe.
    """
    if fact.value is not None and fact.value > 1.0:
        return replace(fact, value=fact.value / 100.0)
    return fact
