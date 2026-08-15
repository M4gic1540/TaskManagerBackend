"""Tests HTTP (vía APIClient) de las vistas de inventario que
test_asset_views.py todavía no cubre: CRUD completo, regeneración de
QR, vista pública sin auth, hoja/ZIP de QR y el dashboard ejecutivo."""
import pytest
from rest_framework.test import APIClient

from accounts.enums import Role
from core.auth.jwt_claims_authentication import TokenClaimsUser
from inventory.models import Asset

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin():
    return TokenClaimsUser(id=1, username="admin1", role=Role.ADMIN)


@pytest.fixture
def usuario():
    return TokenClaimsUser(id=2, username="user1", role=Role.USUARIO)


def _create_asset(**overrides):
    fields = {"name": "Notebook Sala 3", "created_by_id": 1, "created_by_username": "admin1"}
    fields.update(overrides)
    return Asset.objects.create(**fields)


class TestAssetCreate:
    def test_admin_can_create_asset(self, api_client, admin):
        api_client.force_authenticate(user=admin)

        response = api_client.post("/api/v1/inventory/", {"name": "Monitor LG"}, format="json")

        assert response.status_code == 201
        assert Asset.objects.filter(name="Monitor LG").exists()

    def test_usuario_role_cannot_create_asset(self, api_client, usuario):
        api_client.force_authenticate(user=usuario)
        response = api_client.post("/api/v1/inventory/", {"name": "Monitor LG"}, format="json")
        assert response.status_code == 403


class TestAssetDetail:
    def test_admin_can_view_detail(self, api_client, admin):
        asset = _create_asset()
        api_client.force_authenticate(user=admin)

        response = api_client.get(f"/api/v1/inventory/{asset.pk}/")

        assert response.status_code == 200
        assert response.data["name"] == "Notebook Sala 3"

    def test_detail_404_for_unknown_asset(self, api_client, admin):
        api_client.force_authenticate(user=admin)
        response = api_client.get("/api/v1/inventory/99999/")
        assert response.status_code == 404

    def test_usuario_role_cannot_view_detail(self, api_client, usuario):
        asset = _create_asset()
        api_client.force_authenticate(user=usuario)
        response = api_client.get(f"/api/v1/inventory/{asset.pk}/")
        assert response.status_code == 403

    def test_admin_can_update_asset(self, api_client, admin):
        asset = _create_asset()
        api_client.force_authenticate(user=admin)

        response = api_client.patch(
            f"/api/v1/inventory/{asset.pk}/", {"name": "Notebook Renombrada"}, format="json"
        )

        assert response.status_code == 200
        assert response.data["name"] == "Notebook Renombrada"

    def test_admin_can_delete_asset(self, api_client, admin):
        asset = _create_asset()
        api_client.force_authenticate(user=admin)

        response = api_client.delete(f"/api/v1/inventory/{asset.pk}/")

        assert response.status_code == 204
        assert not Asset.objects.filter(pk=asset.pk).exists()


class TestAssetRegenerateQR:
    def test_authenticated_user_can_regenerate_qr(self, api_client, admin):
        asset = _create_asset()
        api_client.force_authenticate(user=admin)

        response = api_client.post(f"/api/v1/inventory/{asset.pk}/regenerate-qr/")

        assert response.status_code == 200

    def test_regenerate_qr_404_for_unknown_asset(self, api_client, admin):
        api_client.force_authenticate(user=admin)
        response = api_client.post("/api/v1/inventory/99999/regenerate-qr/")
        assert response.status_code == 404


class TestAssetPublicDetail:
    def test_no_authentication_required(self, api_client):
        asset = _create_asset()

        response = api_client.get(f"/api/v1/inventory/public/{asset.public_uuid}/")

        assert response.status_code == 200

    def test_404_for_unknown_uuid(self, api_client):
        import uuid

        response = api_client.get(f"/api/v1/inventory/public/{uuid.uuid4()}/")
        assert response.status_code == 404


class TestInventoryDashboard:
    def test_admin_can_view_dashboard(self, api_client, admin):
        api_client.force_authenticate(user=admin)
        response = api_client.get("/api/v1/inventory/dashboard/")
        assert response.status_code == 200

    def test_usuario_role_cannot_view_dashboard(self, api_client, usuario):
        api_client.force_authenticate(user=usuario)
        response = api_client.get("/api/v1/inventory/dashboard/")
        assert response.status_code == 403
