"""Tests de AssetService: hasta ahora solo se ejercitaba indirecto vía
vistas HTTP (test_asset_views.py, 2 casos de permisos). Este archivo
cubre la lógica de negocio directamente — permisos por rol, generación
de QR, deduplicación en import_rows y las exportaciones .docx/.zip."""
from types import SimpleNamespace

import pytest

from accounts.enums import Role
from core.exceptions import EntityNotFoundError, PermissionDeniedError, ValidationError
from inventory.models import Asset
from inventory.services.asset_service import AssetService

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return SimpleNamespace(id=1, username="admin1", role=Role.ADMIN, is_superuser=False)


@pytest.fixture
def tecnico():
    return SimpleNamespace(id=2, username="tec1", role=Role.TECNICO, is_superuser=False)


@pytest.fixture
def usuario():
    return SimpleNamespace(id=3, username="user1", role=Role.USUARIO, is_superuser=False)


class TestCreateAsset:
    def test_admin_can_create_asset_with_qr(self, admin):
        asset = AssetService().create_asset(actor=admin, name="Notebook Sala 3")

        assert asset.pk is not None
        assert asset.created_by_id == admin.id
        assert asset.created_by_username == admin.username
        assert asset.qr_image.name

    def test_tecnico_can_create_asset(self, tecnico):
        asset = AssetService().create_asset(actor=tecnico, name="Monitor LG")
        assert asset.created_by_username == "tec1"

    def test_usuario_role_cannot_create_asset(self, usuario):
        service = AssetService()
        with pytest.raises(PermissionDeniedError):
            service.create_asset(actor=usuario, name="Notebook")

    def test_missing_name_is_rejected(self, admin):
        service = AssetService()
        with pytest.raises(ValidationError):
            service.create_asset(actor=admin, name="")


class TestUpdateAsset:
    def test_admin_can_update_asset(self, admin):
        asset = AssetService().create_asset(actor=admin, name="Notebook")

        updated = AssetService().update_asset(asset_id=asset.pk, actor=admin, name="Notebook Actualizado")

        assert updated.name == "Notebook Actualizado"

    def test_usuario_role_cannot_update_asset(self, admin, usuario):
        asset = AssetService().create_asset(actor=admin, name="Notebook")
        service = AssetService()

        with pytest.raises(PermissionDeniedError):
            service.update_asset(asset_id=asset.pk, actor=usuario, name="Hackeado")

    def test_update_nonexistent_asset_raises_not_found(self, admin):
        service = AssetService()
        with pytest.raises(EntityNotFoundError):
            service.update_asset(asset_id=99999, actor=admin, name="x")


class TestRegenerateQR:
    def test_admin_can_regenerate_qr(self, admin):
        asset = AssetService().create_asset(actor=admin, name="Notebook")
        original_qr_name = asset.qr_image.name

        regenerated = AssetService().regenerate_qr(asset_id=asset.pk, actor=admin)

        assert regenerated.qr_image.name is not None
        assert original_qr_name is not None

    def test_usuario_role_cannot_regenerate_qr(self, admin, usuario):
        asset = AssetService().create_asset(actor=admin, name="Notebook")
        service = AssetService()

        with pytest.raises(PermissionDeniedError):
            service.regenerate_qr(asset_id=asset.pk, actor=usuario)


class TestDeleteAsset:
    def test_admin_can_delete_asset(self, admin):
        asset = AssetService().create_asset(actor=admin, name="Notebook")

        AssetService().delete_asset(asset_id=asset.pk, actor=admin)

        assert not Asset.objects.filter(pk=asset.pk).exists()

    def test_tecnico_cannot_delete_asset(self, admin, tecnico):
        """Solo Admin borra — a diferencia de crear/editar, donde Técnico
        también puede."""
        asset = AssetService().create_asset(actor=admin, name="Notebook")
        service = AssetService()

        with pytest.raises(PermissionDeniedError):
            service.delete_asset(asset_id=asset.pk, actor=tecnico)


class TestImportRows:
    def test_creates_asset_per_valid_row(self, admin):
        rows = [{"name": "Notebook 1", "legacy_id": "INV-1", "serial_number": "SN1"}]

        result = AssetService().import_rows(rows=rows, actor=admin)

        assert result["created"] == 1
        assert result["errors"] == []
        assert Asset.objects.count() == 1

    def test_row_without_name_is_reported_as_error_not_raised(self, admin):
        rows = [{"legacy_id": "INV-2", "serial_number": "SN2"}]

        result = AssetService().import_rows(rows=rows, actor=admin)

        assert result["created"] == 0
        assert len(result["errors"]) == 1
        assert result["errors"][0]["reason"] == "sin nombre/descripción"

    def test_duplicate_legacy_id_and_serial_is_skipped_on_reimport(self, admin):
        Asset.objects.create(
            name="Ya existente", legacy_id="INV-3", serial_number="SN3",
            created_by_id=admin.id, created_by_username=admin.username,
        )
        rows = [{"name": "Ya existente", "legacy_id": "INV-3", "serial_number": "SN3"}]

        result = AssetService().import_rows(rows=rows, actor=admin)

        assert result["created"] == 0
        assert result["skipped_detail"][0]["reason"] == "ya importado"

    def test_one_bad_row_does_not_abort_the_rest_of_the_batch(self, admin):
        rows = [
            {"legacy_id": "INV-4"},  # sin nombre -> error
            {"name": "Notebook OK", "legacy_id": "INV-5", "serial_number": "SN5"},
        ]

        result = AssetService().import_rows(rows=rows, actor=admin)

        assert result["created"] == 1
        assert len(result["errors"]) == 1

    def test_usuario_role_cannot_import(self, usuario):
        service = AssetService()
        with pytest.raises(PermissionDeniedError):
            service.import_rows(rows=[{"name": "x"}], actor=usuario)


class TestGetPublicDetail:
    def test_returns_asset_by_public_uuid(self, admin):
        asset = AssetService().create_asset(actor=admin, name="Notebook")

        found = AssetService().get_public_detail(asset.public_uuid)

        assert found.pk == asset.pk

    def test_unknown_uuid_raises_not_found(self):
        import uuid

        service = AssetService()
        with pytest.raises(EntityNotFoundError):
            service.get_public_detail(uuid.uuid4())


class TestQRExports:
    def test_generate_qr_sheet_docx_returns_zip_bytes(self, admin):
        asset = AssetService().create_asset(actor=admin, name="Notebook", serial_number="SN9")

        content = AssetService().generate_qr_sheet_docx(asset_ids=[asset.pk])

        assert content[:2] == b"PK"  # .docx es un zip

    def test_generate_qr_sheet_docx_raises_when_no_match(self):
        service = AssetService()
        with pytest.raises(EntityNotFoundError):
            service.generate_qr_sheet_docx(asset_ids=[99999])

    def test_generate_qr_images_zip_returns_zip_bytes(self, admin):
        asset = AssetService().create_asset(actor=admin, name="Notebook", serial_number="SN10")

        content = AssetService().generate_qr_images_zip(asset_ids=[asset.pk])

        assert content[:2] == b"PK"

    def test_generate_qr_images_zip_dedupes_filenames_for_same_serial(self, admin):
        a1 = AssetService().create_asset(actor=admin, name="Notebook A", serial_number="SAME")
        a2 = AssetService().create_asset(actor=admin, name="Notebook B", serial_number="SAME")

        content = AssetService().generate_qr_images_zip(asset_ids=[a1.pk, a2.pk])

        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
        assert len(names) == 2
        assert len(set(names)) == 2

    def test_generate_qr_images_zip_raises_when_no_match(self):
        service = AssetService()
        with pytest.raises(EntityNotFoundError):
            service.generate_qr_images_zip(asset_ids=[99999])
