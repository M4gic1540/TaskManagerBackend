"""Mapeo de datos legacy (planilla Excel/CSV de compras) hacia el
modelo Asset. Centralizado acá para que tanto el comando de management
como el endpoint de importación usen exactamente las mismas reglas."""
from __future__ import annotations

import re
from datetime import date, datetime

from inventory.models import AssetCategory, AssetStatus

# Tipo textual libre de la planilla -> categoría fija del sistema.
# Todo lo que no matchee cae en OTRO (se preserva igual en `raw_type`).
_TYPE_TO_CATEGORY = {
    "desktop": AssetCategory.PC,
    "laptop": AssetCategory.LAPTOP,
    "monitor": AssetCategory.MONITOR,
    "monitor 27''": AssetCategory.MONITOR,
    "escaner": AssetCategory.IMPRESORA,
    "switch": AssetCategory.RED,
    "cables jumper": AssetCategory.RED,
    "rele": AssetCategory.RED,
    "relé": AssetCategory.RED,
    "camara videoconferencia": AssetCategory.PROYECTOR,
    "smarphone": AssetCategory.TELEFONO,
    "smartphone": AssetCategory.TELEFONO,
    "mouse": AssetCategory.PERIFERICO,
    "mousepad": AssetCategory.PERIFERICO,
    "teclado": AssetCategory.PERIFERICO,
    "trackpad": AssetCategory.PERIFERICO,
    "webcam": AssetCategory.PERIFERICO,
    "docking": AssetCategory.PERIFERICO,
    "multipuerto": AssetCategory.PERIFERICO,
    "hardware": AssetCategory.PERIFERICO,
    "herramienta computacional": AssetCategory.PERIFERICO,
    "rack": AssetCategory.SERVIDOR,
}

_STATUS_MAP = {
    "asignado": AssetStatus.ACTIVO,
    "en bodega": AssetStatus.BODEGA,
}


def map_category(raw_type: str) -> str:
    key = (raw_type or "").strip().lower()
    return _TYPE_TO_CATEGORY.get(key, AssetCategory.OTRO)


def map_status(raw_status: str) -> str:
    key = (raw_status or "").strip().lower()
    return _STATUS_MAP.get(key, AssetStatus.BODEGA)


def map_location(oficina: str) -> str:
    oficina = (oficina or "").strip()
    if not oficina:
        return ""
    # Números puros son código de oficina interno; el resto (ej "U Concepcion") es un nombre de sede.
    if re.fullmatch(r"\d+", oficina):
        return f"Oficina {oficina}"
    return oficina


def parse_legacy_date(value: str) -> date | None:
    """La planilla usa dd/mm/YYYY. Devuelve None si viene vacío o mal formado
    (nunca revienta la fila completa por una fecha rara)."""
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def row_to_asset_fields(row: dict) -> dict:
    """Convierte una fila cruda de la planilla (dict con las columnas
    originales en español) al dict de kwargs que espera `AssetService.create_asset`."""
    raw_type = (row.get("Tipo") or "").strip()
    serial = (row.get("Serial Number") or "").strip()
    if serial.upper() in ("SN", "S/N", "S / N"):
        serial = ""

    notes_parts = []
    if row.get("Comentario", "").strip():
        notes_parts.append(row["Comentario"].strip())
    if row.get("Garantia", "").strip():
        notes_parts.append(f"Garantía: {row['Garantia'].strip()}")
    if row.get("Valor?", "").strip():
        notes_parts.append(f"Valor: {row['Valor?'].strip()}")

    return {
        "name": (row.get("Decripción") or row.get("Descripción") or "").strip() or "Activo sin descripción",
        "description": "",
        "category": map_category(raw_type),
        "raw_type": raw_type,
        "status": map_status(row.get("Status")),
        "serial_number": serial,
        "brand": (row.get("Marca") or "").strip(),
        "model": (row.get("Modelo") or "").strip(),
        "location": map_location(row.get("Oficina")),
        "purchase_date": parse_legacy_date(row.get("Fecha de Compra")),
        "purchase_company": (row.get("Empresa") or "").strip(),
        "invoice_number": (row.get("Factura") or "").strip(),
        "legacy_id": (row.get("Serie GLPI") or "").strip(),
        "notes": " | ".join(notes_parts),
    }
