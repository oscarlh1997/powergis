"""Vocabulario del dominio.

Todo lo que aquí se define es estable y no depende de ninguna librería externa:
es el lenguaje que comparten WordPress, el motor y la base de datos.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class GeoLevel(StrEnum):
    """Niveles de la jerarquía administrativa española (códigos INE)."""

    PAIS = "pais"
    CCAA = "ccaa"
    PROVINCIA = "provincia"
    MUNICIPIO = "municipio"
    DISTRITO = "distrito"
    SECCION = "seccion"

    @property
    def child(self) -> GeoLevel | None:
        return _CHILD_OF.get(self)

    @property
    def rank(self) -> int:
        return _ORDER.index(self)

    def contains(self, other: GeoLevel) -> bool:
        return self.rank < other.rank


_ORDER: list[GeoLevel] = [
    GeoLevel.PAIS,
    GeoLevel.CCAA,
    GeoLevel.PROVINCIA,
    GeoLevel.MUNICIPIO,
    GeoLevel.DISTRITO,
    GeoLevel.SECCION,
]

_CHILD_OF: dict[GeoLevel, GeoLevel] = {
    GeoLevel.PAIS: GeoLevel.CCAA,
    GeoLevel.CCAA: GeoLevel.PROVINCIA,
    GeoLevel.PROVINCIA: GeoLevel.MUNICIPIO,
    GeoLevel.MUNICIPIO: GeoLevel.DISTRITO,
    GeoLevel.DISTRITO: GeoLevel.SECCION,
}


class Section(StrEnum):
    """Secciones del informe. El orden es el de presentación."""

    DEMOGRAFIA = "demografia"
    SOCIOECONOMICO = "socioeconomico"
    COMPETENCIA = "competencia"
    CLIMA = "clima"
    TRAFICO = "trafico"


class Tier(StrEnum):
    BASICO = "basico"
    AVANZADO = "avanzado"

    @property
    def includes(self) -> frozenset[Tier]:
        if self is Tier.AVANZADO:
            return frozenset({Tier.BASICO, Tier.AVANZADO})
        return frozenset({Tier.BASICO})


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    DONE = "done"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {RunStatus.DONE, RunStatus.FAILED}


class Direction(IntEnum):
    """Sentido de bondad de un indicador para el scoring.

    HIGHER_IS_BETTER: renta media, población objetivo.
    LOWER_IS_BETTER:  densidad competitiva, índice de saturación.
    NEUTRAL:          no participa en el score (solo informativo).
    """

    HIGHER_IS_BETTER = 1
    NEUTRAL = 0
    LOWER_IS_BETTER = -1


class Dimension(StrEnum):
    """Dimensiones del PlaceRank (pesos por defecto 35/30/20/15)."""

    ECONOMICO = "economico"
    DEMOGRAFICO = "demografico"
    AMBIENTAL = "ambiental"
    MATCH = "match"


DEFAULT_DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.ECONOMICO: 0.35,
    Dimension.DEMOGRAFICO: 0.30,
    Dimension.AMBIENTAL: 0.20,
    Dimension.MATCH: 0.15,
}


class ScoreCategory(StrEnum):
    OPTIMA = "Óptima"
    EXCELENTE = "Excelente"
    BUENA = "Buena"
    ACEPTABLE = "Aceptable"
    DEFICIENTE = "Deficiente"
    PESIMA = "Pésima"

    @staticmethod
    def from_score(score: float) -> ScoreCategory:
        for threshold, category in _CATEGORY_CUTS:
            if score >= threshold:
                return category
        return ScoreCategory.PESIMA


_CATEGORY_CUTS: list[tuple[float, ScoreCategory]] = [
    (85.0, ScoreCategory.OPTIMA),
    (70.0, ScoreCategory.EXCELENTE),
    (55.0, ScoreCategory.BUENA),
    (40.0, ScoreCategory.ACEPTABLE),
    (25.0, ScoreCategory.DEFICIENTE),
    (0.0, ScoreCategory.PESIMA),
]


class BreakMethod(StrEnum):
    """Métodos de corte para las capas coropléticas de GeoLens."""

    QUANTILES = "quantiles"
    EQUAL_INTERVAL = "equal_interval"
    STDDEV = "stddev"


class Unit(StrEnum):
    PERSONAS = "personas"
    PORCENTAJE = "%"
    EUROS = "EUR"
    INDICE = "indice"
    RATIO = "ratio"
    ANIOS = "años"
    GRADOS_C = "°C"
    MM = "mm"
    DIAS = "días"
    KM2 = "km²"
    UNIDADES = "ud"
