"""Perfil de cliente objetivo y cálculo del Match%.

Esta es la pieza que faltaba. El formulario de powergis.es no pregunta solo
*dónde*: pregunta *a quién* quieres vender —formación, NSE, renta, estructura
familiar, clima, tráfico— y eso es exactamente la dimensión **Match** del
PlaceRank («Match% perfil» en la tabla del informe de ejemplo).

Sin esto, la dimensión Match se calculaba con indicadores genéricos etiquetados
como tales, lo cual es una aproximación. Con esto, Match significa lo que dice
que significa: **qué parte del perfil declarado por el usuario cumple la zona**.

Cómo se puntúa cada criterio, dentro del ámbito consultado:

    'higher'  → percentil de la zona (más es mejor)
    'lower'   → 100 - percentil
    'range'   → 100 dentro del intervalo, decae fuera de forma proporcional

«Indiferente» no puntúa: el criterio se descarta en vez de meter ruido.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from . import stats
from .enums import Direction

# --------------------------------------------------------------------------- #
# Criterios
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Criterion:
    """Un requisito del perfil traducido a un indicador del almacén."""

    indicator: str
    kind: str = "higher"              # higher | lower | range
    weight: float = 1.0
    minimum: float | None = None
    maximum: float | None = None
    label: str = ""

    def score(self, value: float | None, population: Sequence[float | None]) -> float | None:
        if value is None:
            return None

        if self.kind == "range":
            lo = self.minimum if self.minimum is not None else float("-inf")
            hi = self.maximum if self.maximum is not None else float("inf")
            if lo <= value <= hi:
                return 100.0
            # Fuera del intervalo: decae con la distancia relativa al borde.
            span = (hi - lo) if hi != float("inf") and lo != float("-inf") else abs(value) or 1.0
            distance = (lo - value) if value < lo else (value - hi)
            return max(0.0, 100.0 - (distance / max(span, 1e-9)) * 100.0)

        percentile = stats.percentile_of(value, population)
        if percentile is None:
            return None
        return 100.0 - percentile if self.kind == "lower" else percentile


# --------------------------------------------------------------------------- #
# Traducción del formulario a criterios
# --------------------------------------------------------------------------- #

INDIFERENTE = {"", "indiferente", "any", "cualquiera", "no_relevante"}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


# nivel de formación declarado → indicador que lo representa
EDUCATION: dict[str, tuple[str, str]] = {
    "sin_estudios":      ("dem.edu.none_pct", "higher"),
    "secundaria":        ("dem.edu.secondary_pct", "higher"),
    "tecnico_superior":  ("dem.edu.secondary_pct", "higher"),
    "universitario":     ("dem.edu.university_pct", "higher"),
    "postgrado":         ("dem.edu.postgrad_pct", "higher"),
}

# estructura familiar → indicador
FAMILY: dict[str, tuple[str, str]] = {
    "soltero":            ("dem.household.single_pct", "higher"),
    "soltero(a)":         ("dem.household.single_pct", "higher"),
    "pareja_sin_hijos":   ("dem.civil.married_pct", "higher"),
    "nido_lleno":         ("dem.household.with_children_pct", "higher"),
    "nido_adolescentes":  ("dem.household.with_children_pct", "higher"),
    "nido_vacio":         ("dem.age.65p", "higher"),
    "monoparental":       ("dem.household.monoparental_pct", "higher"),
}

# nivel socioeconómico declarado → clase que hay que maximizar
NSE: dict[str, tuple[str, str]] = {
    "a/b":  ("eco.class.high_pct", "higher"),
    "a":    ("eco.class.high_pct", "higher"),
    "b":    ("eco.class.high_pct", "higher"),
    "c+":   ("eco.nse.upper_middle_pct", "higher"),
    "c":    ("eco.class.mid_pct", "higher"),
    "d+":   ("eco.class.lower_mid_pct", "higher"),
    "d/e":  ("eco.class.low_pct", "higher"),
    "d":    ("eco.class.low_pct", "higher"),
    "e":    ("eco.class.low_pct", "higher"),
}

# tramos de renta bruta anual del hogar (€)
INCOME_BRACKETS: dict[str, tuple[float | None, float | None]] = {
    "<12k":      (None, 12_000),
    "12-24k":    (12_000, 24_000),
    "24-45k":    (24_000, 45_000),
    "45-75k":    (45_000, 75_000),
    "75-150k":   (75_000, 150_000),
    ">150k":     (150_000, None),
}

# tramos de renta mensual disponible (€)
DISPOSABLE_BRACKETS: dict[str, tuple[float | None, float | None]] = {
    "<300":      (None, 300),
    "301-800":   (301, 800),
    "801-2500":  (801, 2_500),
    ">2500":     (2_500, None),
}

# ticket promedio declarado → gasto mensual esperado en el sector (€)
TICKET_BRACKETS: dict[str, tuple[float | None, float | None]] = {
    "micro":      (None, 10),
    "bajo":       (10, 50),
    "medio":      (51, 200),
    # 201–1.000 € faltaba: el formulario ofrece «Medio-Alto (201€ - 1.000€)»
    # y aquí no había tramo, así que quien lo marcaba se quedaba sin criterio
    # de ticket. No daba error: simplemente no puntuaba.
    "medio_alto": (201, 1_000),
    "alto":       (1_001, 5_000),
    "lujo":       (5_000, None),
}

# intensidad declarada → percentil mínimo aceptable
INTENSITY: dict[str, float] = {
    "muy_alto": 90.0,
    "alto":     70.0,
    "medio":    45.0,
    "bajo":     20.0,
}

# preferencia climática → indicador e intervalo de temperatura media anual (°C)
CLIMATE: dict[str, tuple[str, str, float | None, float | None]] = {
    "calido":    ("cli.temp.annual", "range", 17.0, 25.0),
    "templado":  ("cli.temp.annual", "range", 13.0, 18.0),
    "frio":      ("cli.temp.annual", "range", 5.0, 13.0),
    "seco":      ("cli.rain.days", "lower", None, None),
    "humedo":    ("cli.rain.days", "higher", None, None),
}


@dataclass(slots=True)
class TargetProfile:
    """Perfil de cliente objetivo tal y como lo declara el formulario.

    Los nombres de los campos son los del formulario de powergis.es
    (`/crear-proyecto-geolocalizado/`), para que el mapeo sea evidente.
    """

    age_range: tuple[str, ...] = ()
    gender: str | None = None
    family_status: str | None = None
    education_level: str | None = None
    nationality: str | None = None
    nse: tuple[str, ...] = ()
    annual_income: str | None = None
    monthly_available_income: str | None = None
    average_ticket: str | None = None
    climate: tuple[str, ...] = ()
    pedestrian_traffic: str | None = None
    vehicular_traffic: str | None = None
    traffic_generators_high: tuple[str, ...] = ()
    traffic_generators_medium: tuple[str, ...] = ()
    direct_competition: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #

    def is_empty(self) -> bool:
        return not self.criteria()

    def criteria(self) -> list[Criterion]:
        """Traduce el perfil declarado a criterios medibles.

        Todo lo que el usuario marcó como «indiferente» simplemente no aparece:
        un criterio sin preferencia no debe empujar el score en ninguna
        dirección.
        """
        out: list[Criterion] = []

        # -- público objetivo: siempre pesa el doble, es el corazón del match
        out.append(Criterion("dem.pop.segment", "higher", 2.0, label="Público objetivo"))

        education = _norm(self.education_level)
        if education not in INDIFERENTE and education in EDUCATION:
            code, kind = EDUCATION[education]
            out.append(Criterion(code, kind, 1.5, label="Nivel de formación"))

        family = _norm(self.family_status)
        if family not in INDIFERENTE and family in FAMILY:
            code, kind = FAMILY[family]
            out.append(Criterion(code, kind, 1.0, label="Estructura familiar"))

        for level in self.nse:
            key = _norm(level).replace("_", "/")
            if key in INDIFERENTE:
                continue
            entry = NSE.get(key) or NSE.get(_norm(level))
            if entry:
                code, kind = entry
                out.append(Criterion(code, kind, 1.5 / max(len(self.nse), 1), label="NSE"))

        bracket = _bracket(self.annual_income, INCOME_BRACKETS)
        if bracket:
            lo, hi = bracket
            out.append(Criterion(
                "eco.income.household.mean", "range", 1.5, lo, hi, "Renta bruta anual"
            ))

        bracket = _bracket(self.monthly_available_income, DISPOSABLE_BRACKETS)
        if bracket:
            lo, hi = bracket
            out.append(Criterion(
                "eco.disposable.monthly", "range", 1.2, lo, hi, "Renta disponible"
            ))

        bracket = _bracket(self.average_ticket, TICKET_BRACKETS)
        if bracket:
            lo, hi = bracket
            out.append(Criterion(
                "eco.sector_spend", "range", 1.0, lo, hi, "Capacidad de gasto en el sector"
            ))

        for preference in self.climate:
            key = _norm(preference)
            if key in INDIFERENTE or key not in CLIMATE:
                continue
            code, kind, lo, hi = CLIMATE[key]
            out.append(Criterion(code, kind, 0.8, lo, hi, "Clima"))

        if _norm(self.pedestrian_traffic) not in INDIFERENTE:
            out.append(Criterion("tra.pedestrian.index", "higher", 1.3, label="Tráfico peatonal"))
        if _norm(self.vehicular_traffic) not in INDIFERENTE:
            out.append(Criterion("tra.vehicle.index", "higher", 1.0, label="Tráfico vehicular"))

        if self.traffic_generators_high or self.traffic_generators_medium:
            out.append(Criterion("anc.attraction.index", "higher", 1.2, label="Generadores de tráfico"))

        if self.direct_competition is False:
            # Declaró que NO quiere competencia directa cerca.
            out.append(Criterion("cmp.density_km2", "lower", 1.5, label="Competencia directa"))

        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "age_range": list(self.age_range),
            "gender": self.gender,
            "family_status": self.family_status,
            "education_level": self.education_level,
            "nationality": self.nationality,
            "nse": list(self.nse),
            "annual_income": self.annual_income,
            "monthly_available_income": self.monthly_available_income,
            "average_ticket": self.average_ticket,
            "climate": list(self.climate),
            "pedestrian_traffic": self.pedestrian_traffic,
            "vehicular_traffic": self.vehicular_traffic,
            "traffic_generators_high": list(self.traffic_generators_high),
            "traffic_generators_medium": list(self.traffic_generators_medium),
            "direct_competition": self.direct_competition,
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> TargetProfile:
        data = data or {}

        def tup(key: str) -> tuple[str, ...]:
            raw = data.get(key) or []
            if isinstance(raw, str):
                raw = [raw]
            return tuple(str(v) for v in raw if str(v).strip())

        def one(key: str) -> str | None:
            value = data.get(key)
            return str(value) if value not in (None, "") else None

        return cls(
            age_range=tup("age_range"),
            gender=one("gender"),
            family_status=one("family_status"),
            education_level=one("education_level"),
            nationality=one("nationality"),
            nse=tup("nse"),
            annual_income=one("annual_income"),
            monthly_available_income=one("monthly_available_income"),
            average_ticket=one("average_ticket"),
            climate=tup("climate"),
            pedestrian_traffic=one("pedestrian_traffic"),
            vehicular_traffic=one("vehicular_traffic"),
            traffic_generators_high=tup("traffic_generators_high"),
            traffic_generators_medium=tup("traffic_generators_medium"),
            direct_competition=data.get("direct_competition"),
        )


def _bracket(
    value: str | None, table: dict[str, tuple[float | None, float | None]]
) -> tuple[float | None, float | None] | None:
    key = _norm(value)
    if key in INDIFERENTE:
        return None

    # Coincidencia exacta primero. El prefijo se prueba DESPUÉS y de más
    # largo a más corto: si no, `medio_alto` entra por `medio` (que va antes
    # en la tabla) y se lleva el tramo 51–200 en vez de 201–1.000. No falla
    # ruidosamente, devuelve el tramo equivocado, que es peor.
    for candidate, bounds in table.items():
        if _norm(candidate) == key:
            return bounds

    for candidate, bounds in sorted(table.items(), key=lambda kv: -len(_norm(kv[0]))):
        if key.startswith(_norm(candidate)):
            return bounds

    return None


# --------------------------------------------------------------------------- #
# Cálculo del Match%
# --------------------------------------------------------------------------- #


def match_scores(ctx, target: TargetProfile) -> dict[int, float | None]:
    """Match% de cada zona hija frente al perfil declarado.

    Devuelve `geo_id → 0-100`, o `None` si no hay ningún criterio con datos
    suficientes: mejor decir «no evaluable» que inventar un 50.
    """
    criteria = target.criteria()
    if not criteria or not ctx.children:
        return {geo.geo_id: None for geo in ctx.children}

    usable: list[tuple[Criterion, list[float | None]]] = []
    descartados: dict[str, float] = {}   # etiqueta → peso perdido

    for criterion in criteria:
        if criterion.indicator not in ctx.catalog:
            descartados[criterion.label] = descartados.get(criterion.label, 0) + criterion.weight
            continue
        values = ctx.values(criterion.indicator)
        filled = sum(1 for v in values if v is not None)
        if filled < max(1, len(ctx.children) // 2):
            # Cobertura insuficiente: es ruido, no señal.
            descartados[criterion.label] = descartados.get(criterion.label, 0) + criterion.weight
            continue
        usable.append((criterion, values))

    # Descartar en silencio es lo que convierte un hueco de datos en un
    # Match% que parece bajo. El cliente declaró un criterio y tiene derecho
    # a saber que no se ha podido medir: medido en un motor real, NSE,
    # estructura familiar y postgrado suman el 29 % del peso y ninguno tiene
    # colector todavía.
    if descartados:
        perdido = sum(descartados.values())
        total = sum(c.weight for c in criteria)
        ctx.warnings.append(
            "No se han podido evaluar estos criterios de tu perfil por falta de "
            f"datos en el ámbito consultado: {', '.join(sorted(descartados))}. "
            f"Suponen el {round(100 * perdido / total)} % del peso del Match, "
            "que se ha repartido entre los criterios restantes."
        )

    if not usable:
        return {geo.geo_id: None for geo in ctx.children}

    out: dict[int, float | None] = {}
    for index, geo in enumerate(ctx.children):
        scores: list[float | None] = []
        weights: list[float | None] = []
        for criterion, values in usable:
            score = criterion.score(values[index], values)
            scores.append(score)
            weights.append(criterion.weight if score is not None else None)
        out[geo.geo_id] = stats.weighted_mean(scores, weights)
    return out


def explain_match(ctx, target: TargetProfile, geo_id: int) -> list[dict[str, Any]]:
    """Desglose del Match% de una zona. Sin esto no se puede justificar."""
    criteria = target.criteria()
    index = next((i for i, g in enumerate(ctx.children) if g.geo_id == geo_id), None)
    if index is None:
        return []

    out: list[dict[str, Any]] = []
    for criterion in criteria:
        if criterion.indicator not in ctx.catalog:
            continue
        values = ctx.values(criterion.indicator)
        indicator = ctx.catalog[criterion.indicator]
        out.append({
            "criterio": criterion.label or indicator.label,
            "indicador": criterion.indicator,
            "valor": values[index],
            "unidad": str(indicator.unit),
            "cumplimiento": criterion.score(values[index], values),
            "peso": criterion.weight,
        })
    return out


def direction_of(criterion: Criterion) -> Direction:
    if criterion.kind == "lower":
        return Direction.LOWER_IS_BETTER
    if criterion.kind == "higher":
        return Direction.HIGHER_IS_BETTER
    return Direction.NEUTRAL
