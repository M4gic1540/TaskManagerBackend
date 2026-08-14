"""Tests de parse_uploaded_inventory_file: lectura de CSV/XLSX subidos
sin pandas (csv estándar + openpyxl)."""
import io

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.exceptions import ValidationError
from inventory.import_parser import parse_uploaded_inventory_file


def _csv_file(name: str, content: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content.encode("utf-8-sig"), content_type="text/csv")


def _xlsx_file(name: str, headers: list[str], rows: list[list]) -> SimpleUploadedFile:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/vnd.openxmlformats")


class TestParseCSV:
    def test_parses_rows_into_dicts(self):
        content = "Decripción,Tipo\nNotebook,Laptop\nMonitor,Monitor\n"
        result = parse_uploaded_inventory_file(_csv_file("planilla.csv", content))

        assert result == [
            {"Decripción": "Notebook", "Tipo": "Laptop"},
            {"Decripción": "Monitor", "Tipo": "Monitor"},
        ]

    def test_tolerates_bom(self):
        """Excel suele exportar CSV con BOM UTF-8 al inicio del archivo."""
        content = "Decripción,Tipo\nNotebook,Laptop\n"
        result = parse_uploaded_inventory_file(_csv_file("planilla.csv", content))
        assert result[0]["Decripción"] == "Notebook"


class TestParseXLSX:
    def test_parses_rows_into_dicts(self):
        upload = _xlsx_file("planilla.xlsx", ["Decripción", "Tipo"], [["Notebook", "Laptop"]])
        result = parse_uploaded_inventory_file(upload)
        assert result == [{"Decripción": "Notebook", "Tipo": "Laptop"}]

    def test_skips_fully_empty_trailing_rows(self):
        upload = _xlsx_file(
            "planilla.xlsx", ["Decripción"], [["Notebook"], [None]],
        )
        result = parse_uploaded_inventory_file(upload)
        assert len(result) == 1

    def test_skips_columns_with_no_header(self):
        upload = _xlsx_file("planilla.xlsx", ["Decripción", ""], [["Notebook", "basura"]])
        result = parse_uploaded_inventory_file(upload)
        assert result == [{"Decripción": "Notebook"}]

    def test_none_cell_becomes_empty_string(self):
        upload = _xlsx_file("planilla.xlsx", ["Decripción", "Marca"], [["Notebook", None]])
        result = parse_uploaded_inventory_file(upload)
        assert result[0]["Marca"] == ""


class TestUnsupportedFormat:
    def test_raises_validation_error_for_unknown_extension(self):
        upload = SimpleUploadedFile("planilla.pdf", b"%PDF-1.4", content_type="application/pdf")
        with pytest.raises(ValidationError):
            parse_uploaded_inventory_file(upload)
