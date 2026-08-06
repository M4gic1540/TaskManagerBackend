"""Lee un archivo subido (CSV o XLSX) y lo convierte en list[dict] con
las columnas originales de la planilla de compras. Sin pandas: csv
estándar + openpyxl, evita otra dependencia pesada."""
from __future__ import annotations

import csv
import io

import openpyxl

from core.exceptions import ValidationError


def parse_uploaded_inventory_file(uploaded_file) -> list[dict]:
    name = (uploaded_file.name or "").lower()

    if name.endswith(".csv"):
        raw = uploaded_file.read()
        text = raw.decode("utf-8-sig")  # -sig: tolera BOM de Excel
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    if name.endswith(".xlsx"):
        wb = openpyxl.load_workbook(uploaded_file, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
        rows = []
        for raw_row in rows_iter:
            if all(cell is None for cell in raw_row):
                continue  # fila vacía al final del excel
            row = {}
            for header, cell in zip(headers, raw_row):
                if not header:
                    continue
                row[header] = "" if cell is None else str(cell)
            rows.append(row)
        return rows

    raise ValidationError("Formato no soportado. Sube un archivo .csv o .xlsx")
