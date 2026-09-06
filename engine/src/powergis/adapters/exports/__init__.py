"""Exportadores del informe (fase 8)."""

from .excel import ExcelExporter
from .pdf import PdfExporter
from .pptx import PptxExporter

EXPORTERS = {
    "xlsx": ExcelExporter,
    "pdf": PdfExporter,
    "pptx": PptxExporter,
}


def get_exporter(kind: str):
    cls = EXPORTERS.get(kind.lower())
    if cls is None:
        raise ValueError(f"Formato no soportado: {kind}. Disponibles: {sorted(EXPORTERS)}")
    return cls()


__all__ = ["EXPORTERS", "ExcelExporter", "PdfExporter", "PptxExporter", "get_exporter"]
