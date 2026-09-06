"""Exportadores. Se comprueba que el fichero se genera y que respeta el tier."""

from __future__ import annotations

import io
import zipfile

import pytest

from powergis.adapters.exports import get_exporter
from powergis.adapters.exports.charts import bar_svg, line_svg
from powergis.domain.enums import Tier
from powergis.domain.report import ReportBuilder


@pytest.fixture
def report(advanced_project, context):
    return ReportBuilder("1.0.0-test").build(
        advanced_project, context, version=2, tier=Tier.AVANZADO
    )


class TestExcel:
    def test_genera_un_xlsx_valido(self, report):
        data = get_exporter("xlsx").render(report)
        assert data[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            assert "xl/workbook.xml" in book.namelist()

    def test_incluye_hojas_de_portada_kpis_y_metodologia(self, report):
        data = get_exporter("xlsx").render(report)
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            workbook = book.read("xl/workbook.xml").decode("utf-8")
        for hoja in ("Portada", "KPIs", "Metodolog"):
            assert hoja in workbook

    def test_no_falla_con_valores_nulos(self, report):
        assert get_exporter("xlsx").render(report)


class TestPowerPoint:
    def test_genera_un_pptx_valido(self, report):
        data = get_exporter("pptx").render(report)
        assert data[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(data)) as deck:
            assert "ppt/presentation.xml" in deck.namelist()

    def test_tiene_varias_diapositivas(self, report):
        data = get_exporter("pptx").render(report)
        with zipfile.ZipFile(io.BytesIO(data)) as deck:
            slides = [n for n in deck.namelist() if n.startswith("ppt/slides/slide")]
        assert len(slides) >= 4


class TestPdfHtml:
    """WeasyPrint es pesado; aquí se valida el HTML que se le pasa."""

    def test_el_html_lleva_las_secciones(self, report):
        html = get_exporter("pdf").to_html(report)
        assert "<html" in html
        assert "Resumen ejecutivo" in html
        assert "PlaceRank" in html

    def test_las_secciones_bloqueadas_se_anuncian_sin_datos(self, basic_report):
        html = get_exporter("pdf").to_html(basic_report)
        assert "informe avanzado" in html
        assert "eco.income.household.mean" not in html

    def test_los_huecos_se_marcan_como_no_disponible(self, report):
        html = get_exporter("pdf").to_html(report)
        assert "n. d." in html

    def test_escapa_el_html_de_los_datos(self, report):
        report.scope["name"] = "<script>alert(1)</script>"
        html = get_exporter("pdf").to_html(report)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


@pytest.fixture
def basic_report(project, context):
    context.tier = Tier.BASICO
    return ReportBuilder("1.0.0-test").build(project, context, version=1, tier=Tier.BASICO)


class TestGraficosSvg:
    def test_barras_produce_svg(self, report):
        chart = report.sections[0].subsections[0].charts[0]
        svg = bar_svg(chart)
        assert svg.startswith("<svg")
        assert "</svg>" in svg

    def test_lineas_produce_svg(self, report):
        chart = next(
            c for s in report.sections if s.available
            for sub in s.subsections for c in sub.charts
            if c.type == "line"
        )
        assert line_svg(chart).startswith("<svg")

    def test_un_grafico_vacio_no_revienta(self):
        from powergis.domain.models import Chart

        assert bar_svg(Chart(id="x", title="", type="bar", x=[], series=[])) == ""

    def test_los_titulos_se_escapan(self):
        from powergis.domain.models import Chart

        svg = bar_svg(Chart(
            id="x", title="<b>malo</b>", type="bar", x=["a"],
            series=[{"name": "s", "data": [1]}],
        ))
        assert "<b>malo</b>" not in svg


class TestFormatoDesconocido:
    def test_lanza_error_claro(self):
        with pytest.raises(ValueError, match="no soportado"):
            get_exporter("docx")
