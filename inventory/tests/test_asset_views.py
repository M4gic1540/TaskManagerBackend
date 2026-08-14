"""Tests HTTP (vía APIClient) de las vistas de inventario. No había
ningún test a nivel de vista todavía -las escrituras ya se testeaban
indirecto vía AssetService- así que esto cubre específicamente los dos
fixes de seguridad de este branch: solo Admin/Técnico puede leer
inventario (antes cualquier autenticado), y el import rechaza archivos
que superen el tope de tamaño."""
import io

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User
from inventory.models import Asset

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin():
    return User.objects.create_user(username="admin1", password="x", role=Role.ADMIN)


@pytest.fixture
def usuario():
    return User.objects.create_user(username="user1", password="x", role=Role.USUARIO)


class TestAssetListPermissions:
    def test_admin_can_list_assets(self, api_client, admin):
        Asset.objects.create(name="Notebook Sala 3")
        api_client.force_authenticate(user=admin)

        response = api_client.get("/api/v1/inventory/")

        assert response.status_code == 200

    def test_usuario_role_cannot_read_inventory(self, api_client, usuario):
        Asset.objects.create(name="Notebook Sala 3")
        api_client.force_authenticate(user=usuario)

        response = api_client.get("/api/v1/inventory/")

        assert response.status_code == 403


class TestAssetImportSizeLimit:
    def test_oversized_file_is_rejected_before_parsing(self, api_client, admin):
        api_client.force_authenticate(user=admin)
        oversized = io.BytesIO(b"0" * (11 * 1024 * 1024))
        oversized.name = "inventario.csv"

        response = api_client.post(
            "/api/v1/inventory/import/", {"file": oversized}, format="multipart"
        )

        assert response.status_code == 400
        assert "10MB" in response.data["detail"]

    def test_usuario_role_cannot_import(self, api_client, usuario):
        api_client.force_authenticate(user=usuario)
        small_file = io.BytesIO(b"col1,col2\nval1,val2\n")
        small_file.name = "inventario.csv"

        response = api_client.post(
            "/api/v1/inventory/import/", {"file": small_file}, format="multipart"
        )

        assert response.status_code == 403
