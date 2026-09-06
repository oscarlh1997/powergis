"""Gráficos SVG generados en servidor, sin navegador.

Se usan en el PDF y en el PPTX. Salida vectorial, texto seleccionable y cero
dependencias de runtime: el mismo `Chart` que consume ECharts en el navegador
se renderiza aquí sin Node ni Chromium.

Paleta accesible en claro y oscuro, con contraste suficiente entre series
contiguas y ningún par que se confunda en daltonismo rojo-verde.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from ...domain.models import Chart

PALETTE = [
    "#2563eb",  # azul
    "#f59e0b",  # ámbar
    "#059669",  # verde
    "#7c3aed",  # violeta
    "#dc2626",  # rojo
    "#0891b2",  # cian
]

W, H = 720, 260
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 28, 62


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    import math

    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    for step in (1, 2, 2.5, 5, 10):
        if value <= base * step:
            return base * step
    return base * 10


def _clean_series(chart: Chart) -> list[tuple[str, list[float]]]:
    out: list[tuple[str, list[float]]] = []
    for serie in chart.series:
        data = [float(v) if isinstance(v, (int, float)) else 0.0 for v in serie.get("data", [])]
        out.append((str(serie.get("name", "")), data))
    return out


def _axis_and_legend(
    max_value: float, labels: Sequence[str], names: Sequence[str], plot_h: float
) -> list[str]:
    parts: list[str] = []
    # Rejilla y eje Y
    for i in range(5):
        y = PAD_T + plot_h - plot_h * i / 4
        value = max_value * i / 4
        parts.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="#e2e8f0" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{PAD_L - 8}" y="{y + 3:.1f}" text-anchor="end" '
            f'font-size="9" fill="#64748b">{_fmt_axis(value)}</text>'
        )
    # Etiquetas X (rotadas si son muchas)
    n = max(len(labels), 1)
    slot = (W - PAD_L - PAD_R) / n
    step = max(1, n // 14)
    for i, label in enumerate(labels):
        if i % step:
            continue
        x = PAD_L + slot * (i + 0.5)
        y = PAD_T + plot_h + 14
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="end" font-size="8.5" '
            f'fill="#475569" transform="rotate(-35 {x:.1f} {y:.1f})">'
            f"{_esc(_truncate(label, 16))}</text>"
        )
    # Leyenda
    # Acumulan desplazamientos fraccionarios, así que son float desde el
    # principio y no enteros que luego cambian de tipo.
    lx: float = PAD_L
    ly = H - 10
    for i, name in enumerate(names):
        color = PALETTE[i % len(PALETTE)]
        parts.append(f'<rect x="{lx}" y="{ly - 8}" width="9" height="9" rx="2" fill="{color}"/>')
        parts.append(
            f'<text x="{lx + 13}" y="{ly}" font-size="9" fill="#334155">'
            f"{_esc(_truncate(name, 22))}</text>"
        )
        lx += 16 + len(_truncate(name, 22)) * 5.2
    return parts


def bar_svg(chart: Chart) -> str:
    series = _clean_series(chart)
    labels = [str(x) for x in chart.x]
    if not series or not labels:
        return ""

    plot_h = H - PAD_T - PAD_B
    plot_w = W - PAD_L - PAD_R

    if chart.stack:
        totals = [sum(data[i] if i < len(data) else 0.0 for _, data in series)
                  for i in range(len(labels))]
        max_value = _nice_max(max(totals) if totals else 1.0)
    else:
        max_value = _nice_max(max((max(d) if d else 0.0) for _, d in series) or 1.0)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="{_esc(chart.title)}">',
        f'<text x="{PAD_L}" y="16" font-size="11" font-weight="600" fill="#0f172a">'
        f"{_esc(chart.title)}</text>",
    ]
    parts += _axis_and_legend(max_value, labels, [n for n, _ in series], plot_h)

    slot = plot_w / max(len(labels), 1)
    if chart.stack:
        bar_w = slot * 0.62
        for i in range(len(labels)):
            bottom: float = PAD_T + plot_h
            for s, (_, data) in enumerate(series):
                value = data[i] if i < len(data) else 0.0
                height = value / max_value * plot_h if max_value else 0
                bottom -= height
                parts.append(
                    f'<rect x="{PAD_L + slot * i + (slot - bar_w) / 2:.1f}" y="{bottom:.1f}" '
                    f'width="{bar_w:.1f}" height="{height:.1f}" '
                    f'fill="{PALETTE[s % len(PALETTE)]}"/>'
                )
    else:
        group_w = slot * 0.72
        bar_w = group_w / max(len(series), 1)
        for s, (_, data) in enumerate(series):
            for i in range(len(labels)):
                value = data[i] if i < len(data) else 0.0
                height = value / max_value * plot_h if max_value else 0
                x = PAD_L + slot * i + (slot - group_w) / 2 + bar_w * s
                parts.append(
                    f'<rect x="{x:.1f}" y="{PAD_T + plot_h - height:.1f}" '
                    f'width="{max(bar_w - 1, 1):.1f}" height="{height:.1f}" '
                    f'fill="{PALETTE[s % len(PALETTE)]}"/>'
                )

    parts.append(
        f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - PAD_R}" y2="{PAD_T + plot_h}" '
        f'stroke="#94a3b8" stroke-width="1"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def line_svg(chart: Chart) -> str:
    series = _clean_series(chart)
    labels = [str(x) for x in chart.x]
    if not series or not labels:
        return ""

    plot_h = H - PAD_T - PAD_B
    plot_w = W - PAD_L - PAD_R
    raw_max = max((max(d) if d else 0.0) for _, d in series)
    raw_min = min((min(d) if d else 0.0) for _, d in series)
    max_value = _nice_max(raw_max if raw_max > 0 else 1.0)
    base = min(raw_min, 0.0)
    span = max_value - base or 1.0

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="{_esc(chart.title)}">',
        f'<text x="{PAD_L}" y="16" font-size="11" font-weight="600" fill="#0f172a">'
        f"{_esc(chart.title)}</text>",
    ]
    parts += _axis_and_legend(max_value, labels, [n for n, _ in series], plot_h)

    step = plot_w / max(len(labels) - 1, 1)
    for s, (_, data) in enumerate(series):
        points = []
        for i in range(len(labels)):
            value = data[i] if i < len(data) else 0.0
            x = PAD_L + step * i
            y = PAD_T + plot_h - (value - base) / span * plot_h
            points.append(f"{x:.1f},{y:.1f}")
        color = PALETTE[s % len(PALETTE)]
        parts.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for point in points:
            # Nombres propios: `x` e `y` ya se usaron arriba como coordenadas
            # numéricas, y aquí son los dos trozos de texto de "x,y".
            px, py = point.split(",")
            parts.append(f'<circle cx="{px}" cy="{py}" r="2.4" fill="{color}"/>')

    parts.append("</svg>")
    return "".join(parts)


def _fmt_axis(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".", ",")
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}k"
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}".replace(".", ",")


def _truncate(text: str, size: int) -> str:
    return text if len(text) <= size else text[: size - 1] + "…"
