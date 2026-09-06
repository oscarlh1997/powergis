"""Exportación a PDF (fase 8).

HTML + CSS de impresión renderizado con WeasyPrint. Sin navegador headless:
un Chromium por PDF en un VPS de 16 GB es la forma más rápida de quedarse sin
memoria un viernes por la tarde.

Los gráficos se incrustan como SVG generados en servidor (ECharts SSR o el
generador mínimo de `charts.py`), no como capturas de pantalla: el PDF queda
vectorial, ligero y con texto seleccionable.
"""

from __future__ import annotations

import html
import logging
from typing import Any

from ...domain.models import Report
from .charts import bar_svg, line_svg

log = logging.getLogger(__name__)

CSS = """
@page { size: A4; margin: 18mm 14mm 20mm 14mm;
        @bottom-center { content: "PowerGIS · página " counter(page) " de " counter(pages);
                         font-size: 8pt; color: #64748b; } }
* { box-sizing: border-box; }
body { font-family: "DejaVu Sans", "Helvetica", sans-serif; font-size: 9.5pt;
       color: #0f172a; line-height: 1.45; }
h1 { font-size: 20pt; margin: 0 0 4mm; letter-spacing: -0.3pt; }
h2 { font-size: 13pt; margin: 8mm 0 2mm; border-bottom: 1.5pt solid #1e293b;
     padding-bottom: 1.5mm; page-break-after: avoid; }
h3 { font-size: 11pt; margin: 5mm 0 1.5mm; color: #334155; page-break-after: avoid; }
.cover { page-break-after: always; padding-top: 45mm; }
.cover .meta { margin-top: 12mm; }
.cover .meta div { margin-bottom: 1.6mm; }
.badge { display: inline-block; background: #1e293b; color: #fff; padding: 1mm 3mm;
         border-radius: 2mm; font-size: 8pt; text-transform: uppercase; letter-spacing: .5pt; }
.kpis { display: flex; flex-wrap: wrap; gap: 3mm; margin: 3mm 0 5mm; }
.kpi { border: 0.6pt solid #cbd5e1; border-radius: 2mm; padding: 2.5mm 3mm; min-width: 42mm; }
.kpi .label { font-size: 7.5pt; color: #64748b; text-transform: uppercase; letter-spacing: .3pt; }
.kpi .value { font-size: 13pt; font-weight: 700; }
.kpi .unit { font-size: 8pt; color: #64748b; font-weight: 400; }
.kpi.missing .value { color: #94a3b8; font-size: 10pt; font-style: italic; }
table { width: 100%; border-collapse: collapse; margin: 2mm 0 3mm; font-size: 7.8pt; }
th { background: #1e293b; color: #fff; text-align: left; padding: 1.5mm 2mm; font-weight: 600; }
td { border-bottom: 0.4pt solid #e2e8f0; padding: 1.2mm 2mm; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.na { color: #94a3b8; font-style: italic; }
tr.top td { background: #f0fdf4; }
tr.bottom td { background: #fef2f2; }
.footnote { font-size: 7.5pt; color: #64748b; margin: 1mm 0 4mm; }
.warning { background: #fffbeb; border-left: 2pt solid #f59e0b; padding: 2mm 3mm;
           font-size: 8pt; margin: 2mm 0; }
.chart { margin: 3mm 0; page-break-inside: avoid; }
.sources { font-size: 8pt; color: #475569; }
.locked { color: #94a3b8; font-style: italic; }
"""


class PdfExporter:
    extension = "pdf"
    media_type = "application/pdf"

    def render(self, report: Report) -> bytes:
        try:
            import weasyprint  # import perezoso: arrastra pango, cairo y gdk-pixbuf
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "WeasyPrint no está instalado. `pip install weasyprint` y las "
                "librerías del sistema (pango, cairo, gdk-pixbuf)."
            ) from exc

        document = weasyprint.HTML(string=self.to_html(report))
        return document.write_pdf(stylesheets=[weasyprint.CSS(string=CSS)])

    # ------------------------------------------------------------------ #

    def to_html(self, report: Report) -> str:
        parts: list[str] = [
            "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>",
            f"<title>PowerGIS · {esc(report.scope.get('name', ''))}</title></head><body>",
            self._cover(report),
        ]

        if report.executive_summary:
            parts.append(self._summary(report))

        for section in report.sections:
            if not section.available:
                parts.append(
                    f"<h2>{esc(section.title)}</h2>"
                    "<p class='locked'>Sección disponible en el informe avanzado.</p>"
                )
                continue
            parts.append(f"<h2>{esc(section.title)}</h2>")
            for sub in section.subsections:
                parts.append(f"<h3>{esc(sub.title)}</h3>")
                parts.append(self._kpis(sub.kpis))
                for chart in sub.charts:
                    parts.append(self._chart(chart))
                for table in sub.tables:
                    parts.append(self._table(table))
                if sub.narrative:
                    parts.append(f"<p>{esc(sub.narrative)}</p>")

        if report.placerank:
            parts.append(self._placerank(report.placerank))

        parts.append(self._appendix(report))
        parts.append("</body></html>")
        return "".join(parts)

    # ------------------------------------------------------------------ #

    def _cover(self, report: Report) -> str:
        scope = report.scope
        meta = [
            ("Ámbito", f"{scope.get('name', '')} ({scope.get('level', '')})"),
            ("Desagregación", scope.get("children_level", "")),
            ("Zonas comparadas", scope.get("children_count", "")),
            ("Sector", report.business.get("sector") or "—"),
            ("Empresa", report.business.get("company_name") or "—"),
            ("Generado", report.generated_at.strftime("%d/%m/%Y %H:%M")),
            ("Versión", f"{report.version} · motor {report.engine_version}"),
        ]
        rows = "".join(
            f"<div><strong>{esc(k)}:</strong> {esc(v)}</div>" for k, v in meta
        )
        return (
            f"<div class='cover'><span class='badge'>Informe {esc(str(report.tier))}</span>"
            f"<h1>Análisis de localización comercial</h1>"
            f"<div class='meta'>{rows}</div></div>"
        )

    def _summary(self, report: Report) -> str:
        summary = report.executive_summary or {}
        head = "".join(
            f"<div class='kpi'><div class='label'>{esc(item['label'])}</div>"
            f"<div class='value'>{fmt(item.get('value'))} "
            f"<span class='unit'>{esc(item.get('unit', ''))}</span></div></div>"
            for item in summary.get("headline", [])
        )
        blocks = [f"<h2>Resumen ejecutivo</h2><div class='kpis'>{head}</div>"]
        narrative = summary.get("narrative")
        if isinstance(narrative, dict):
            if narrative.get("resumen"):
                blocks.append(f"<p>{esc(narrative['resumen'])}</p>")
            for title, key in (("Fortalezas", "fortalezas"), ("Riesgos", "riesgos")):
                items = narrative.get(key) or []
                if items:
                    lis = "".join(f"<li>{esc(i)}</li>" for i in items)
                    blocks.append(f"<h3>{title}</h3><ul>{lis}</ul>")
        for warning in report.warnings:
            blocks.append(f"<div class='warning'>{esc(warning)}</div>")
        return "".join(blocks)

    def _kpis(self, kpis) -> str:
        if not kpis:
            return ""
        cards = []
        for kpi in kpis:
            if kpi.value is None:
                cards.append(
                    f"<div class='kpi missing'><div class='label'>{esc(kpi.label)}</div>"
                    f"<div class='value'>no disponible</div></div>"
                )
            else:
                cards.append(
                    f"<div class='kpi'><div class='label'>{esc(kpi.label)}</div>"
                    f"<div class='value'>{fmt(kpi.value, kpi.decimals)} "
                    f"<span class='unit'>{esc(str(kpi.unit))}</span></div></div>"
                )
        return f"<div class='kpis'>{''.join(cards)}</div>"

    def _chart(self, chart) -> str:
        try:
            svg = line_svg(chart) if chart.type in {"line", "area"} else bar_svg(chart)
        except Exception as exc:
            log.warning("No se pudo renderizar el gráfico %s: %s", chart.id, exc)
            return ""
        return f"<div class='chart'>{svg}</div>"

    def _table(self, table) -> str:
        head = "".join(f"<th>{esc(c.label)}</th>" for c in table.columns)
        tops = set(table.highlights.get("top", []))
        bottoms = set(table.highlights.get("bottom", []))

        body: list[str] = []
        for row in table.rows:
            code = row.get("geo_code")
            css = "top" if code in tops else ("bottom" if code in bottoms else "")
            cells = []
            for column in table.columns:
                value = row.get(column.key)
                if value is None:
                    cells.append("<td class='na'>n. d.</td>")
                elif isinstance(value, (int, float)):
                    cells.append(f"<td class='num'>{fmt(value, column.decimals)}</td>")
                else:
                    cells.append(f"<td>{esc(value)}</td>")
            body.append(f"<tr class='{css}'>{''.join(cells)}</tr>")

        note = f"<p class='footnote'>{esc(table.footnote)}</p>" if table.footnote else ""
        return (
            f"<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>{note}"
        )

    def _placerank(self, placerank: dict[str, Any]) -> str:
        weights = " · ".join(
            f"{k} {int(v * 100)}%" for k, v in (placerank.get("weights") or {}).items()
        )
        rows = "".join(
            f"<tr><td class='num'>{r.get('rank')}</td><td>{esc(r.get('geo_name'))}</td>"
            f"<td class='num'>{fmt(r.get('score'), 1)}</td><td>{esc(r.get('category'))}</td></tr>"
            for r in placerank.get("rows", [])[:40]
        )
        return (
            "<h2>PlaceRank</h2>"
            f"<p class='footnote'>{esc(placerank.get('method', ''))} · Pesos: {esc(weights)}</p>"
            "<table><thead><tr><th>#</th><th>Zona</th><th>Score</th><th>Categoría</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

    def _appendix(self, report: Report) -> str:
        sources = "".join(
            f"<li><strong>{esc(s.get('name'))}</strong> — {esc(s.get('attribution'))}</li>"
            for s in report.sources
        )
        glossary = "".join(
            f"<li><strong>{esc(g['term'])}</strong>: {esc(g['definition'])}</li>"
            for g in report.glossary[:60]
        )
        return (
            "<h2>Anexos</h2><h3>Fuentes</h3>"
            f"<ul class='sources'>{sources}</ul>"
            "<h3>Glosario y metodología</h3>"
            f"<ul class='sources'>{glossary}</ul>"
        )


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def fmt(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "n. d."
    if isinstance(value, (int, float)):
        text = f"{value:,.{decimals}f}"
        # Formato español: 1.234,56
        return text.replace(",", " ").replace(".", ",").replace(" ", ".")
    return esc(value)
