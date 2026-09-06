"""Estadística del dominio: normalización, KPIs, rankings y cortes de mapa.

Solo stdlib. Cada función trata `None` como «no publicado» (secreto
estadístico) y nunca lo convierte en cero: ése es el error que convierte un
informe en una mentira.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from .enums import BreakMethod, Direction

Number = float | int | None


# --------------------------------------------------------------------------- #
# Utilidades básicas
# --------------------------------------------------------------------------- #


def clean(values: Iterable[Number]) -> list[float]:
    """Descarta nulos y NaN. El resto de funciones asume su salida."""
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            continue
        out.append(f)
    return out


def safe_div(numerator: Number, denominator: Number, scale: float = 1.0) -> float | None:
    if numerator is None or denominator is None:
        return None
    d = float(denominator)
    if d == 0:
        return None
    return float(numerator) / d * scale


def total(values: Iterable[Number]) -> float | None:
    vals = clean(values)
    return sum(vals) if vals else None


def mean(values: Iterable[Number]) -> float | None:
    vals = clean(values)
    return sum(vals) / len(vals) if vals else None


def weighted_mean(values: Sequence[Number], weights: Sequence[Number]) -> float | None:
    num = 0.0
    den = 0.0
    for v, w in zip(values, weights, strict=False):
        if v is None or w is None:
            continue
        num += float(v) * float(w)
        den += float(w)
    return num / den if den else None


def median(values: Iterable[Number]) -> float | None:
    vals = sorted(clean(values))
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def stddev(values: Iterable[Number]) -> float | None:
    vals = clean(values)
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def quantile(values: Iterable[Number], q: float) -> float | None:
    """Percentil por interpolación lineal (mismo criterio que numpy)."""
    vals = sorted(clean(values))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    q = min(max(q, 0.0), 1.0)
    pos = q * (len(vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return vals[int(pos)]
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def percentile_of(value: Number, population: Sequence[Number]) -> float | None:
    """Percentil (0-100) que ocupa `value` dentro de `population`."""
    if value is None:
        return None
    vals = clean(population)
    if not vals:
        return None
    below = sum(1 for v in vals if v < float(value))
    equal = sum(1 for v in vals if v == float(value))
    return (below + 0.5 * equal) / len(vals) * 100.0


def winsorize(values: Sequence[Number], lower: float = 0.05, upper: float = 0.95) -> list[float | None]:
    """Recorta por percentiles.

    Cuidado: con pocas zonas (una CCAA tiene 2-9 provincias) el percentil 95
    cae *dentro* del propio outlier y no recorta nada. Para normalizar usa
    `clip_outliers`, que sí aguanta muestras pequeñas.
    """
    lo = quantile(values, lower)
    hi = quantile(values, upper)
    if lo is None or hi is None:
        return [None if v is None else float(v) for v in values]
    return [None if v is None else min(max(float(v), lo), hi) for v in values]


def tukey_fences(values: Sequence[Number], k: float = 1.5) -> tuple[float, float] | None:
    """Vallas de Tukey: Q1 - k·IQR, Q3 + k·IQR.

    Robustas con muestras pequeñas, que es exactamente nuestro caso: un
    informe de la Comunidad de Madrid compara 1 provincia gigante con 4
    pequeñas, y el percentil 95 clásico no recorta nada ahí.
    """
    q1 = quantile(values, 0.25)
    q3 = quantile(values, 0.75)
    if q1 is None or q3 is None:
        return None
    iqr = q3 - q1
    if iqr == 0:
        vals = clean(values)
        return (min(vals), max(vals)) if vals else None
    return q1 - k * iqr, q3 + k * iqr


def clip_outliers(values: Sequence[Number], k: float = 1.5) -> list[float | None]:
    """Recorta a las vallas de Tukey conservando los huecos."""
    fences = tukey_fences(values, k)
    if fences is None:
        return [None if v is None else float(v) for v in values]
    lo, hi = fences
    return [None if v is None else min(max(float(v), lo), hi) for v in values]


def gini(values: Iterable[Number]) -> float | None:
    vals = sorted(clean(values))
    n = len(vals)
    if n < 2:
        return None
    s = sum(vals)
    if s == 0:
        return None
    cum = sum((i + 1) * v for i, v in enumerate(vals))
    return (2 * cum) / (n * s) - (n + 1) / n


def shannon_diversity(counts: Iterable[Number]) -> float | None:
    """Índice de diversidad (nacionalidades, tipos de servicio). Normalizado 0-1."""
    vals = [v for v in clean(counts) if v > 0]
    if len(vals) < 2:
        return 0.0 if vals else None
    total_ = sum(vals)
    h = -sum((v / total_) * math.log(v / total_) for v in vals)
    return h / math.log(len(vals))


def herfindahl(shares: Iterable[Number]) -> float | None:
    """HHI de concentración competitiva sobre cuotas en tanto por uno."""
    vals = clean(shares)
    if not vals:
        return None
    s = sum(vals)
    if s == 0:
        return None
    return sum((v / s) ** 2 for v in vals)


# --------------------------------------------------------------------------- #
# Normalización para scoring
# --------------------------------------------------------------------------- #


def normalize_percentile(
    values: Sequence[Number],
    direction: Direction = Direction.HIGHER_IS_BETTER,
) -> list[float | None]:
    """Normaliza a 0-100 por rango percentil DENTRO del ámbito consultado.

    Es el método por defecto del PlaceRank: robusto a outliers y siempre
    reparte el rango completo, así que ningún informe regional sale «en gris».
    """
    out: list[float | None] = []
    for v in values:
        p = percentile_of(v, values)
        if p is None:
            out.append(None)
        elif direction is Direction.LOWER_IS_BETTER:
            out.append(100.0 - p)
        else:
            out.append(p)
    return out


def normalize_minmax(
    values: Sequence[Number],
    direction: Direction = Direction.HIGHER_IS_BETTER,
    winsor: tuple[float, float] | None = None,
    tukey_k: float | None = 1.5,
) -> list[float | None]:
    """Min-max robusto. Útil cuando la escala importa (no solo el orden).

    Por defecto recorta con vallas de Tukey, que aguantan muestras pequeñas.
    Pasa `winsor=(0.05, 0.95)` para forzar el recorte por percentiles, o
    `tukey_k=None` y `winsor=None` para un min-max puro (no recomendado: un
    solo outlier deja al resto pegado a cero).
    """
    if winsor is not None:
        base = winsorize(values, *winsor)
    elif tukey_k is not None:
        base = clip_outliers(values, tukey_k)
    else:
        base = [None if v is None else float(v) for v in values]
    vals = clean(base)
    if not vals:
        return [None] * len(values)
    lo, hi = min(vals), max(vals)
    span = hi - lo
    out: list[float | None] = []
    for v in base:
        if v is None:
            out.append(None)
        elif span == 0:
            out.append(50.0)
        else:
            score = (v - lo) / span * 100.0
            out.append(100.0 - score if direction is Direction.LOWER_IS_BETTER else score)
    return out


def zscore(values: Sequence[Number]) -> list[float | None]:
    m = mean(values)
    sd = stddev(values)
    if m is None or sd in (None, 0):
        return [None] * len(values)
    return [None if v is None else (float(v) - m) / sd for v in values]  # type: ignore[operator]


# --------------------------------------------------------------------------- #
# Rankings
# --------------------------------------------------------------------------- #


def rank_items(
    items: Sequence[tuple[str, Number]],
    direction: Direction = Direction.HIGHER_IS_BETTER,
) -> list[tuple[str, float, int]]:
    """Ordena (clave, valor) y devuelve (clave, valor, posición). Nulos fuera."""
    valid = [(k, float(v)) for k, v in items if v is not None]
    reverse = direction is not Direction.LOWER_IS_BETTER
    valid.sort(key=lambda kv: kv[1], reverse=reverse)
    return [(k, v, i + 1) for i, (k, v) in enumerate(valid)]


def top_bottom(
    items: Sequence[tuple[str, Number]],
    n: int = 3,
    direction: Direction = Direction.HIGHER_IS_BETTER,
) -> dict[str, list[str]]:
    """Las n mejores y las n peores. Si hay menos de 2n, no se solapan."""
    ranked = rank_items(items, direction)
    if not ranked:
        return {"top": [], "bottom": []}
    keys = [k for k, _, _ in ranked]
    cut = min(n, len(keys) // 2) if len(keys) < 2 * n else n
    cut = max(cut, 0)
    return {"top": keys[:cut], "bottom": keys[len(keys) - cut:][::-1] if cut else []}


# --------------------------------------------------------------------------- #
# Cortes para coropletas (GeoLens)
# --------------------------------------------------------------------------- #


def compute_breaks(
    values: Sequence[Number],
    classes: int = 5,
    method: BreakMethod = BreakMethod.QUANTILES,
) -> list[float]:
    """Devuelve los `classes + 1` límites de clase."""
    vals = sorted(clean(values))
    if not vals:
        return []
    if len(set(vals)) == 1:
        return [vals[0], vals[0]]

    if method is BreakMethod.EQUAL_INTERVAL:
        lo, hi = vals[0], vals[-1]
        step = (hi - lo) / classes
        return [round(lo + step * i, 6) for i in range(classes + 1)]

    if method is BreakMethod.STDDEV:
        m = mean(vals) or 0.0
        sd = stddev(vals) or 0.0
        if sd == 0:
            return [vals[0], vals[-1]]
        half = classes / 2
        return [round(m + sd * (i - half), 6) for i in range(classes + 1)]

    # QUANTILES por defecto
    return [round(quantile(vals, i / classes) or 0.0, 6) for i in range(classes + 1)]


# --------------------------------------------------------------------------- #
# Indicadores derivados frecuentes
# --------------------------------------------------------------------------- #


def dependency_ratio(under_16: Number, working: Number, over_64: Number) -> float | None:
    """(0-15 + 65+) / 16-64 × 100."""
    if working in (None, 0):
        return None
    young = float(under_16 or 0)
    old = float(over_64 or 0)
    return (young + old) / float(working) * 100.0  # type: ignore[arg-type]


def ageing_index(over_64: Number, under_16: Number) -> float | None:
    return safe_div(over_64, under_16, 100.0)


def femininity_index(women: Number, men: Number) -> float | None:
    return safe_div(women, men, 100.0)


def density(population: Number, area_km2: Number) -> float | None:
    return safe_div(population, area_km2)


def relative_share(part: Number, whole: Number) -> float | None:
    return safe_div(part, whole, 100.0)


def yoy_change(current: Number, previous: Number) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (float(current) - float(previous)) / abs(float(previous)) * 100.0  # type: ignore[arg-type]
