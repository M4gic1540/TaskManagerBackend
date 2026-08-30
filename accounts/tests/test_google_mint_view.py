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

    def test_rejects_unknown_email(self):
        """Ya no auto-provisiona cuentas: el usuario final no tiene
        acceso al sistema, así que un email sin cuenta previa se
        rechaza en vez de crear un USUARIO nuevo."""
        response = Client().post(
            reverse("google-mint"),
            data={"email": "desconocido@example.com", "first_name": "Ana"},
            content_type="application/json",
            headers={"X-Internal-Auth": "test-shared-secret"},
        )

        assert response.status_code == 403
        assert not User.objects.filter(email="desconocido@example.com").exists()

    def test_rejects_usuario_role(self):
        User.objects.create(username="usuario1", email="usuario1@example.com", role=Role.USUARIO)

        response = Client().post(
            reverse("google-mint"),
            data={"email": "usuario1@example.com"},
            content_type="application/json",
            headers={"X-Internal-Auth": "test-shared-secret"},
        )

        assert response.status_code == 403

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
