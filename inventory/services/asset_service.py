"""Service Layer: única capa con lógica de negocio de Inventario.
Orquesta Repository + generación de QR. Las vistas DRF solo llaman a
estos métodos (Separation of Concerns, igual que TicketService)."""
from __future__ import annotations

import io
import math

import qrcode
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

from accounts.models import Role
from core.exceptions import EntityNotFoundError, PermissionDeniedError, ValidationError
from inventory.models import Asset
from inventory.repositories.asset_repository import AssetRepository


class AssetService:
    def __init__(self, repository: AssetRepository | None = None):
        self.repository = repository or AssetRepository()

    # --- Helpers --------------------------------------------------------
    def _public_url(self, asset: Asset) -> str:
        """URL pública (sin login) que queda codificada en el QR."""
        base = settings.PUBLIC_ASSET_BASE_URL.rstrip("/")
        return f"{base}/{asset.public_uuid}"

    def _generate_qr_file(self, asset: Asset) -> ContentFile:
        img = qrcode.make(self._public_url(asset))
        img = img.resize((50, 50))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return ContentFile(buffer.getvalue(), name=f"{asset.code}.png")

    def _generate_qr_png_bytes(self, asset: Asset, *, box_size: int = 8) -> bytes:
        """QR en alta resolución para impresión (no el thumbnail 50x50 de
        `qr_image`, que se ve pixelado si se agranda en una hoja para imprimir)."""
        qr = qrcode.QRCode(box_size=box_size, border=2)
        qr.add_data(self._public_url(asset))
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    # --- Creación ---------------------------------------------------------
    @transaction.atomic
    def create_asset(self, *, actor, **fields) -> Asset:
        if actor.role not in (Role.ADMIN, Role.TECNICO) and not actor.is_superuser:
            raise PermissionDeniedError("Solo Admin o Técnico pueden registrar activos.")
        if not fields.get("name"):
            raise ValidationError("El nombre del activo es obligatorio.")

        asset = self.repository.create(created_by=actor, **fields)
        asset.qr_image.save(f"{asset.code}.png", self._generate_qr_file(asset), save=True)
        self.repository.add_history(asset, actor, "Activo creado y QR generado.")
        return asset

    # --- Edición ------------------------------------------------------------
    @transaction.atomic
    def update_asset(self, *, asset_id: int, actor, **fields) -> Asset:
        if actor.role not in (Role.ADMIN, Role.TECNICO) and not actor.is_superuser:
            raise PermissionDeniedError("Solo Admin o Técnico pueden editar activos.")
        asset = self.repository.get_by_id(asset_id)
        asset = self.repository.update(asset, **fields)
        self.repository.add_history(asset, actor, f"Activo actualizado: {', '.join(fields.keys())}")
        return asset

    @transaction.atomic
    def regenerate_qr(self, *, asset_id: int, actor) -> Asset:
        if actor.role not in (Role.ADMIN, Role.TECNICO) and not actor.is_superuser:
            raise PermissionDeniedError("Solo Admin o Técnico pueden regenerar el QR.")
        asset = self.repository.get_by_id(asset_id)
        asset.qr_image.save(f"{asset.code}.png", self._generate_qr_file(asset), save=True)
        self.repository.add_history(asset, actor, "QR regenerado.")
        return asset

    @transaction.atomic
    def delete_asset(self, *, asset_id: int, actor) -> None:
        if actor.role != Role.ADMIN and not actor.is_superuser:
            raise PermissionDeniedError("Solo un Administrador puede eliminar activos.")
        asset = self.repository.get_by_id(asset_id)
        self.repository.delete(asset)

    # --- Importación masiva (reemplazo del Excel legacy) --------------------
    def import_rows(self, *, rows: list[dict], actor) -> dict:
        """Crea un Asset por fila ya normalizada (ver `import_mapping.row_to_asset_fields`).
        No transacciona el batch completo: una fila mala no debe tumbar las
        149 filas buenas. Deduplica por (legacy_id, serial_number) para que
        la planilla se pueda re-subir sin generar activos repetidos —
        legacy_id solo no sirve como clave porque la planilla fuente trae
        ids de 'Serie GLPI' repetidos por error de tipeo en varias filas."""
        if actor.role not in (Role.ADMIN, Role.TECNICO) and not actor.is_superuser:
            raise PermissionDeniedError("Solo Admin o Técnico pueden importar inventario.")

        created, skipped, errors = [], [], []
        existing_keys = set(
            self.repository.get_queryset()
            .exclude(legacy_id="")
            .values_list("legacy_id", "serial_number")
        )

        for idx, fields in enumerate(rows, start=1):
            legacy_id = fields.get("legacy_id")
            dedup_key = (legacy_id, fields.get("serial_number", ""))
            if legacy_id and dedup_key in existing_keys:
                skipped.append({"row": idx, "legacy_id": legacy_id, "reason": "ya importado"})
                continue
            if not fields.get("name"):
                errors.append({"row": idx, "reason": "sin nombre/descripción"})
                continue
            try:
                with transaction.atomic():
                    asset = self.repository.create(created_by=actor, **fields)
                    asset.qr_image.save(f"{asset.code}.png", self._generate_qr_file(asset), save=True)
                    self.repository.add_history(asset, actor, "Activo importado desde planilla legacy.")
                created.append(asset.code)
                if legacy_id:
                    existing_keys.add(dedup_key)
            except Exception as exc:  # noqa: BLE001 - fila individual no debe tumbar el resto del import
                errors.append({"row": idx, "reason": str(exc)})

        return {"created": len(created), "skipped": len(skipped), "errors": errors, "skipped_detail": skipped}

    # --- Lectura -----------------------------------------------------------
    def get_public_detail(self, public_uuid) -> Asset:
        """Sin control de rol: esto es lo que se ve al escanear el QR."""
        return self.repository.get_by_uuid(public_uuid)

    # --- Hoja imprimible de QRs ---------------------------------------------
    def generate_qr_sheet_docx(self, *, asset_ids: list[int]) -> bytes:
        """Arma un .docx con una grilla de QR de los activos indicados, para
        imprimir y recortar como etiquetas físicas. Debajo de cada QR va
        únicamente el S/N real del activo (dato de GLPI) — nada generado
        por el sistema (ni `code` ni `name`), para no imprimir información
        que no viene de la fuente original. Solo lectura: no requiere
        restricción de rol."""
        assets = list(self.repository.get_queryset().filter(pk__in=asset_ids))
        if not assets:
            raise EntityNotFoundError("Ninguno de los activos solicitados existe.")

        order = {asset_id: position for position, asset_id in enumerate(asset_ids)}
        assets.sort(key=lambda asset: order.get(asset.pk, len(asset_ids)))

        document = Document()
        document.add_heading("Etiquetas QR de Inventario", level=1)

        columns = 3
        rows = math.ceil(len(assets) / columns)
        table = document.add_table(rows=rows, cols=columns)

        for index, asset in enumerate(assets):
            cell = table.cell(index // columns, index % columns)

            image_paragraph = cell.paragraphs[0]
            image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            image_paragraph.add_run().add_picture(
                io.BytesIO(self._generate_qr_png_bytes(asset)), width=Cm(2.5)
            )

            if asset.serial_number:
                serial_paragraph = cell.add_paragraph()
                serial_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                serial_paragraph.add_run(asset.serial_number).bold = True

        buffer = io.BytesIO()
        document.save(buffer)
        return buffer.getvalue()
