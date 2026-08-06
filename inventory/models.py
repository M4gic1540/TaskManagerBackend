"""Modelo de dominio de Inventario. Reemplaza GLPI: activos propios +
QR con vista pública de detalle (impresa en etiqueta física)."""
import uuid

from django.conf import settings
from django.db import models


class AssetCategory(models.TextChoices):
    PC = "PC", "Computador de Escritorio"
    LAPTOP = "LAPTOP", "Notebook"
    MONITOR = "MONITOR", "Monitor"
    IMPRESORA = "IMPRESORA", "Impresora"
    RED = "RED", "Equipo de Red"
    PROYECTOR = "PROYECTOR", "Proyector"
    TELEFONO = "TELEFONO", "Teléfono / Celular"
    PERIFERICO = "PERIFERICO", "Periférico"
    SERVIDOR = "SERVIDOR", "Servidor"
    OTRO = "OTRO", "Otro"


class AssetStatus(models.TextChoices):
    ACTIVO = "ACTIVO", "En uso"
    BODEGA = "BODEGA", "En bodega"
    MANTENIMIENTO = "MANTENIMIENTO", "En mantención"
    BAJA = "BAJA", "Dado de baja"
    PRESTADO = "PRESTADO", "Prestado"


def _asset_code() -> str:
    return f"AST-{uuid.uuid4().hex[:8].upper()}"


class Asset(models.Model):
    """Activo de inventario. `public_uuid` es lo que va codificado en el
    QR (no el `id` autoincremental, para no exponer/enumerar activos)."""

    code = models.CharField(max_length=20, unique=True, default=_asset_code, editable=False)
    public_uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    name = models.CharField(max_length=200, help_text="Ej: Notebook Sala Docentes 3")
    description = models.TextField(blank=True, help_text="Descripción breve del activo")
    category = models.CharField(max_length=20, choices=AssetCategory.choices, default=AssetCategory.OTRO)
    status = models.CharField(max_length=20, choices=AssetStatus.choices, default=AssetStatus.ACTIVO, db_index=True)

    serial_number = models.CharField(max_length=100, blank=True, db_index=True)
    brand = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)

    location = models.CharField(max_length=150, blank=True, help_text="Ej: Piso 2 - Oficina 204")
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets_responsible",
    )

    purchase_date = models.DateField(null=True, blank=True)
    warranty_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    # --- Campos de compra/procedencia (vienen del Excel de inventario) ---
    purchase_company = models.CharField(max_length=150, blank=True, help_text="Proveedor/empresa de compra")
    invoice_number = models.CharField(max_length=100, blank=True, help_text="N° de factura")
    raw_type = models.CharField(
        max_length=150, blank=True,
        help_text="Tipo/categoría tal cual venía en la planilla original (texto libre, sin normalizar)",
    )
    legacy_id = models.CharField(
        max_length=50, blank=True, db_index=True,
        help_text="ID correlativo del Excel/GLPI original (columna 'Serie GLPI'). "
        "NO es unique: la planilla fuente tiene ids repetidos por error de tipeo, "
        "la deduplicación de reimportación se hace por (legacy_id + serial_number).",
    )

    qr_image = models.ImageField(upload_to="asset_qr/%Y/%m/", blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="assets_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_asset"
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["serial_number"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class AssetHistory(models.Model):
    """Bitácora de cambios relevantes del activo (auditoría simple)."""

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="history")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inventory_asset_history"
        ordering = ["-created_at"]
