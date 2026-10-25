"""Estado de cada valor y referencia para el color (decisiones de Aldo, 20/10/2026).

Todo dato se enseña, con su etiqueta. Nunca se dice «dudoso»: el cliente ve

* «Dato de su provincia» / «Dato de su comunidad» (`heredado`): la fuente no
  baja a ese nivel y la zona lleva el valor de arriba;
* «Dato de su municipio» (`heredado_municipio`): igual, para los distritos y
  secciones censales que llevan el valor de su municipio (precio de la
  vivienda, turismo, clima, traslados…);
* «En actualización» (`provisional`): la tabla oficial está pendiente de
  verificar o de publicarse con el detalle que pide el informe;
* «Dato antiguo» (`antiguo`): el periodo tiene más de `ANIOS_ANTIGUO` años;
* «Estimado» (`estimado`): lo calcula PowerGIS con un modelo, no es una cifra
  publicada.

La referencia del color es la de la decisión 3: P25 y P75 de las zonas del
propio informe; con menos de `MIN_ZONAS` zonas con dato, el valor del total
nacional con una banda de ±`BANDA_NACIONAL`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date

from . import stats
from .models import Fact

HEREDADO = "heredado"
HEREDADO_MUNICIPIO = "heredado_municipio"
#: Las dos marcas de «valor de arriba»: no cuentan en los cortes del color.
HEREDADOS = frozenset({HEREDADO, HEREDADO_MUNICIPIO})
#: Lo que se añade a la fuente del hecho que un distrito o sección hereda.
REF_MUNICIPIO = "dato del municipio"
PROVISIONAL = "provisional"
ANTIGUO = "antiguo"
ESTIMADO = "estimado"

#: Texto que ve el cliente. El front usa estas mismas claves.
ETIQUETAS: dict[str, str] = {
    HEREDADO: "Dato de su provincia o comunidad",
    HEREDADO_MUNICIPIO: "Dato de su municipio",
    PROVISIONAL: "En actualización",
    ANTIGUO: "Dato antiguo",
    ESTIMADO: "Estimado",
}

#: Indicadores cuya tabla oficial está pendiente de verificar con
#: `powergis ine-verify` (marcas `pendiente`/`provisional` de los colectores
#: del INE). `tests/test_estado.py` comprueba que la lista no se desfasa.
EN_ACTUALIZACION: frozenset[str] = frozenset({
    "dem.age.0_15", "dem.age.16_64", "dem.age.65p", "dem.pop.segment",
    "dem.edu.primary_pct", "dem.edu.none_pct", "dem.nat.foreign_pct",
    "dem.civil.single_pct", "dem.civil.married_pct", "dem.edu.university_pct",
    "dem.edu.secondary_pct", "dem.edu.primary_or_less_pct",
    "eco.income.under15k_pct", "eco.income.over30k_pct", "eco.income.over60k_pct",
})

#: Indicadores que siempre son modelo, salga de donde salga el hecho.
#: El riesgo de pobreza ya no está: el Atlas lo publica (umbrales relativos)
#: y sólo es estimado cuando lo modela el colector de derivados, cuya fuente
#: dice «estimación modelada».
SIEMPRE_ESTIMADOS: frozenset[str] = frozenset({
    "sat.rent_m2", "inm.affordability.years",
    "inm.rent.effort_pct", "tur.index",
})

ANIOS_ANTIGUO = 4
MIN_ZONAS = 5
BANDA_NACIONAL = 0.05


def de_hecho(fact: Fact | None, code: str, *, hoy: date | None = None) -> list[str]:
    """Las marcas de un valor, en orden fijo. Vacío si es un dato oficial al día."""
    if fact is None or fact.value is None:
        return []
    ref = (fact.source_ref or "").lower()
    marcas: list[str] = []
    if "dato de la provincia" in ref or "dato de la comunidad" in ref:
        marcas.append(HEREDADO)
    elif REF_MUNICIPIO in ref:
        marcas.append(HEREDADO_MUNICIPIO)
    if code in EN_ACTUALIZACION or "provisional" in ref:
        marcas.append(PROVISIONAL)
    # Las normales climatológicas son una media de 30 años: no envejecen.
    hoy = hoy or date.today()
    if fact.period and hoy.year - fact.period.year > ANIOS_ANTIGUO and "normal" not in ref \
            and "aemet:" not in ref:
        marcas.append(ANTIGUO)
    if code in SIEMPRE_ESTIMADOS or "estimaci" in ref or "estimado" in ref:
        marcas.append(ESTIMADO)
    return marcas


def nivel_heredado(fact: Fact | None) -> str | None:
    ref = (fact.source_ref or "").lower() if fact else ""
    if "dato de la provincia" in ref:
        return "provincia"
    if "dato de la comunidad" in ref:
        return "comunidad"
    if REF_MUNICIPIO in ref:
        return "municipio"
    return None


def heredar_del_municipio(
    facts: Sequence[Fact],
    municipio_de: dict[int, int],
    codigos: Iterable[str],
) -> list[Fact]:
    """Copias de los hechos del municipio para sus distritos o secciones.

    `municipio_de` es zona → geo_id de su municipio. Sólo se hereda lo que la
    zona no tiene, y la copia lleva «dato del municipio» en la fuente para que
    salga con su etiqueta. Si el municipio ya lo tenía heredado de su
    provincia o comunidad, se copia tal cual: sigue siendo «Dato de su
    provincia», no del municipio.
    """
    codigos = set(codigos)
    propios = {(x.geo_id, x.indicator, x.segment_key()) for x in facts}
    por_municipio: dict[int, list[Fact]] = {}
    for x in facts:
        if x.indicator in codigos and x.value is not None:
            por_municipio.setdefault(x.geo_id, []).append(x)
    out: list[Fact] = []
    for zona, municipio in municipio_de.items():
        for x in por_municipio.get(municipio, ()):
            if (zona, x.indicator, x.segment_key()) in propios:
                continue
            ref = x.source_ref or ""
            if HEREDADO not in de_hecho(x, x.indicator):
                ref = f"{ref} · {REF_MUNICIPIO}" if ref else REF_MUNICIPIO
            out.append(replace(x, geo_id=zona, source_ref=ref))
    return out


def referencia(
    valores: Sequence[float | None],
    nacional: float | None,
    *,
    heredados: int = 0,
) -> dict | None:
    """Cortes del color: P25/P75 de las zonas, o el total nacional ±5 %.

    Los valores heredados no cuentan: todas las zonas de una provincia
    llevarían el mismo y la distribución no diría nada.
    """
    datos = [v for v in valores if v is not None]
    n = len(datos) - heredados
    if n >= MIN_ZONAS and len(set(datos)) > 1:
        return {
            "base": "zonas",
            "n": n,
            "p25": stats.quantile(datos, 0.25),
            "p75": stats.quantile(datos, 0.75),
        }
    if nacional is not None:
        margen = abs(nacional) * BANDA_NACIONAL
        return {
            "base": "nacional",
            "n": n,
            "valor": nacional,
            "p25": nacional - margen,
            "p75": nacional + margen,
        }
    return None


def clase(valor: float | None, ref: dict | None, direccion: int) -> str | None:
    """`favorable` / `media` / `desfavorable` según los cortes y el sentido."""
    if valor is None or ref is None or direccion == 0:
        return None
    alto, bajo = valor >= ref["p75"], valor <= ref["p25"]
    if alto == bajo:
        return "media"
    bueno = alto if direccion > 0 else bajo
    return "favorable" if bueno else "desfavorable"
