"""Estado de cada valor y referencia para el color (decisiones de Aldo, 20/10/2026).

Todo dato se enseña, con su etiqueta. Nunca se dice «dudoso»: el cliente ve

* «Dato de su provincia» / «Dato de su comunidad» (`heredado`): la fuente no
  baja a ese nivel y la zona lleva el valor de arriba;
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

from collections.abc import Sequence
from datetime import date

from . import stats
from .models import Fact

HEREDADO = "heredado"
PROVISIONAL = "provisional"
ANTIGUO = "antiguo"
ESTIMADO = "estimado"

#: Texto que ve el cliente. El front usa estas mismas claves.
ETIQUETAS: dict[str, str] = {
    HEREDADO: "Dato de su provincia o comunidad",
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
SIEMPRE_ESTIMADOS: frozenset[str] = frozenset({
    "eco.poverty.risk_pct", "sat.rent_m2", "inm.affordability.years",
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
    return None


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
