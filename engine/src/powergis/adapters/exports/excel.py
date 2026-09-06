"""Exportación a Excel (fase 8).

Una hoja por sección con sus tablas, más una hoja de portada, otra de KPIs y
otra de metodología y fuentes. Los formatos numéricos salen de la unidad del
indicador, así que el Excel se lee igual que el informe web.

Nota de licencia: se exportan **agregados**, no el listado de POIs de OSM.
Redistribuir la base de datos derivada activaría la cláusula de compartir-igual
de la ODbL; un agregado es *produced work* y basta con atribuir.
"""

from __future__ import annotations

import io
from typing import Any

import xlsxwriter

from ...domain.models import Report

NUMBER_FORMATS: dict[str, str] = {
    "int": "#,##0",
    "float": "#,##0.00",
    "pct": '#,##0.0"%"',
    "eur": '#,##0" €"',
    "index": "#,##0.00",
    "text": "@",
}


class ExcelExporter:
    extension = "xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def render(self, report: Report) -> bytes:
        self._format_cache: dict[str, Any] = {}
        buffer = io.BytesIO()
        book = xlsxwriter.Workbook(buffer, {"in_memory": True, "default_date_format": "dd/mm/yyyy"})
        styles = self._styles(book)

        self._cover(book, styles, report)
        self._kpis(book, styles, report)

        used: set[str] = set()
        for section in report.sections:
            if not section.available:
                continue
            name = self._sheet_name(section.title, used)
            sheet = book.add_worksheet(name)
            row = 0
            sheet.write(row, 0, section.title, styles["h1"])
            row += 2
            for sub in section.subsections:
                sheet.write(row, 0, sub.title, styles["h2"])
                row += 1
                for table in sub.tables:
                    row = self._table(book, sheet, styles, table, row) + 2

        if report.placerank:
            self._placerank(book, styles, report)

        self._methodology(book, styles, report)
        book.close()
        return buffer.getvalue()

    # ------------------------------------------------------------------ #

    @staticmethod
    def _styles(book: xlsxwriter.Workbook) -> dict[str, Any]:
        return {
            "h1": book.add_format({"bold": True, "font_size": 16, "font_color": "#0f172a"}),
            "h2": book.add_format({"bold": True, "font_size": 12, "font_color": "#334155"}),
            "th": book.add_format({
                "bold": True, "bg_color": "#1e293b", "font_color": "#ffffff",
                "border": 1, "text_wrap": True, "valign": "vcenter",
            }),
            "label": book.add_format({"bold": True}),
            "muted": book.add_format({"font_color": "#64748b", "italic": True}),
            "missing": book.add_format({"font_color": "#94a3b8", "italic": True, "border": 1}),
            "cell": book.add_format({"border": 1}),
        }

    def _number_format(self, book: xlsxwriter.Workbook, kind: str) -> Any:
        # Los formatos se cachean: xlsxwriter tiene un límite duro de formatos
        # por libro y una tabla grande crearía uno por celda.
        cache = self._format_cache
        if kind not in cache:
            cache[kind] = book.add_format({
                "border": 1, "num_format": NUMBER_FORMATS.get(kind, "#,##0.00")
            })
        return cache[kind]

    def _cover(self, book, styles, report: Report) -> None:
        sheet = book.add_worksheet("Portada")
        sheet.set_column(0, 0, 32)
        sheet.set_column(1, 1, 60)
        rows = [
            ("Informe", report.scope.get("name", "")),
            ("Ámbito", f"{report.scope.get('level')} · {report.scope.get('code')}"),
            ("Desagregación", report.scope.get("children_level", "")),
            ("Zonas comparadas", report.scope.get("children_count", "")),
            ("Nivel de informe", str(report.tier)),
            ("Versión", report.version),
            ("Motor", report.engine_version),
            ("Generado", report.generated_at.strftime("%d/%m/%Y %H:%M")),
            ("Sector", report.business.get("sector") or "—"),
            ("Empresa", report.business.get("company_name") or "—"),
        ]
        sheet.write(0, 0, "PowerGIS · Informe de geomarketing", styles["h1"])
        for i, (label, value) in enumerate(rows, start=2):
            sheet.write(i, 0, label, styles["label"])
            sheet.write(i, 1, value)
        if report.warnings:
            base = len(rows) + 4
            sheet.write(base, 0, "Avisos", styles["h2"])
            for i, warning in enumerate(report.warnings, start=base + 1):
                sheet.write(i, 0, warning, styles["muted"])

    def _kpis(self, book, styles, report: Report) -> None:
        sheet = book.add_worksheet("KPIs")
        sheet.set_column(0, 0, 26)
        sheet.set_column(1, 1, 42)
        sheet.set_column(2, 4, 16)
        headers = ["Sección", "Indicador", "Valor", "Unidad", "Percentil"]
        for col, title in enumerate(headers):
            sheet.write(0, col, title, styles["th"])
        row = 1
        for section in report.sections:
            if not section.available:
                continue
            for sub in section.subsections:
                for kpi in sub.kpis:
                    sheet.write(row, 0, section.title, styles["cell"])
                    sheet.write(row, 1, kpi.label, styles["cell"])
                    if kpi.value is None:
                        sheet.write(row, 2, "no disponible", styles["missing"])
                    else:
                        sheet.write_number(row, 2, kpi.value, styles["cell"])
                    sheet.write(row, 3, str(kpi.unit), styles["cell"])
                    sheet.write(row, 4, kpi.percentile if kpi.percentile is not None else "",
                                styles["cell"])
                    row += 1
        sheet.freeze_panes(1, 0)
        if row > 1:
            sheet.autofilter(0, 0, row - 1, len(headers) - 1)

    def _table(self, book, sheet, styles, table, start_row: int) -> int:
        sheet.write(start_row, 0, table.title, styles["h2"])
        header_row = start_row + 1
        for col, column in enumerate(table.columns):
            sheet.write(header_row, col, column.label, styles["th"])
            sheet.set_column(col, col, max(len(column.label) + 4, 14))

        for i, row_data in enumerate(table.rows, start=header_row + 1):
            for col, column in enumerate(table.columns):
                value = row_data.get(column.key)
                if value is None:
                    sheet.write(i, col, "n. d.", styles["missing"])
                elif isinstance(value, (int, float)):
                    sheet.write_number(i, col, value, self._number_format(book, column.type))
                else:
                    sheet.write(i, col, str(value), styles["cell"])

        last = header_row + len(table.rows)
        sheet.autofilter(header_row, 0, last, len(table.columns) - 1)
        if table.footnote:
            last += 1
            sheet.write(last, 0, table.footnote, styles["muted"])
        return last

    def _placerank(self, book, styles, report: Report) -> None:
        sheet = book.add_worksheet("PlaceRank")
        data = report.placerank or {}
        headers = ["#", "Zona", "Código", "Score", "Categoría",
                   "Económico", "Demográfico", "Ambiental", "Match"]
        for col, title in enumerate(headers):
            sheet.write(0, col, title, styles["th"])
            sheet.set_column(col, col, 16)
        for i, row in enumerate(data.get("rows", []), start=1):
            dims = row.get("dimensions", {})
            sheet.write_number(i, 0, row.get("rank", i), styles["cell"])
            sheet.write(i, 1, row.get("geo_name", ""), styles["cell"])
            sheet.write(i, 2, row.get("geo_code", ""), styles["cell"])
            sheet.write_number(i, 3, row.get("score", 0), self._number_format(book, "index"))
            sheet.write(i, 4, row.get("category", ""), styles["cell"])
            for col, key in enumerate(["economico", "demografico", "ambiental", "match"], start=5):
                sheet.write_number(i, col, dims.get(key, 0), self._number_format(book, "index"))
        sheet.freeze_panes(1, 0)

    def _methodology(self, book, styles, report: Report) -> None:
        sheet = book.add_worksheet("Metodología")
        sheet.set_column(0, 0, 34)
        sheet.set_column(1, 1, 80)
        sheet.write(0, 0, "Fuentes y metodología", styles["h1"])
        row = 2
        for source in report.sources:
            sheet.write(row, 0, source.get("name", ""), styles["label"])
            sheet.write(row, 1, source.get("attribution", ""))
            row += 1
        row += 1
        sheet.write(row, 0, "Glosario", styles["h2"])
        row += 1
        for entry in report.glossary:
            sheet.write(row, 0, entry.get("term", ""), styles["label"])
            sheet.write(row, 1, entry.get("definition", ""))
            row += 1

    @staticmethod
    def _sheet_name(title: str, used: set[str]) -> str:
        # Excel: 31 caracteres, sin  : \ / ? * [ ]
        clean = "".join(c for c in title if c not in ":\\/?*[]")[:31] or "Hoja"
        candidate, i = clean, 2
        while candidate in used:
            suffix = f" {i}"
            candidate = clean[: 31 - len(suffix)] + suffix
            i += 1
        used.add(candidate)
        return candidate
