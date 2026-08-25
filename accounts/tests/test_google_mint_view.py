"""Tests de auth/google-mint/: el BFF llega acá DESPUÉS de verificar el
id_token con Google, este endpoint solo confía en el secreto interno
compartido (X-Internal-Auth) — nunca vuelve a hablar con Google."""
import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import Role, User

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _internal_secret(settings):
    settings.INTERNAL_AUTH_SECRET = "test-shared-secret"


class TestGoogleAuthMintView:
    def test_rejects_without_internal_header(self):
        response = Client().post(
            reverse("google-mint"),
            data={"email": "nuevo@example.com"},
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_rejects_wrong_secret(self):
        response = Client().post(
            reverse("google-mint"),
            data={"email": "nuevo@example.com"},
            content_type="application/json",
            headers={"X-Internal-Auth": "wrong"},
        )
        assert response.status_code == 403

    def test_rejects_when_secret_not_configured(self, settings):
        settings.INTERNAL_AUTH_SECRET = ""
        response = Client().post(
            reverse("google-mint"),
            data={"email": "nuevo@example.com"},
            content_type="application/json",
            headers={"X-Internal-Auth": ""},
        )
        assert response.status_code == 403

    def test_creates_user_and_mints_tokens_for_new_email(self):
        response = Client().post(
            reverse("google-mint"),
            data={"email": "Nuevo@Example.com", "first_name": "Ana", "last_name": "Soto"},
            content_type="application/json",
            headers={"X-Internal-Auth": "test-shared-secret"},
        )

        assert response.status_code == 200
        body = response.json()
        assert "access" in body and "refresh" in body

        user = User.objects.get(email="nuevo@example.com")
        assert user.username == "nuevo@example.com"
        assert user.first_name == "Ana"
        assert user.role == Role.USUARIO
        assert not user.has_usable_password()

    def test_reuses_existing_user_by_email_without_touching_role(self):
        existing = User.objects.create(
            username="tecnico1", email="tec@example.com", role=Role.TECNICO
        )

        response = Client().post(
            reverse("google-mint"),
            data={"email": "tec@example.com", "first_name": "X"},
            content_type="application/json",
            headers={"X-Internal-Auth": "test-shared-secret"},
        )

        assert response.status_code == 200
        existing.refresh_from_db()
        assert existing.role == Role.TECNICO
        assert User.objects.filter(email="tec@example.com").count() == 1

    def test_requires_email(self):
        response = Client().post(
            reverse("google-mint"),
            data={},
            content_type="application/json",
            headers={"X-Internal-Auth": "test-shared-secret"},
        )
        assert response.status_code == 400
