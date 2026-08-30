"""El usuario final ya no tiene acceso al sistema (solo interactúa por
correo, ver tickets/management/commands/poll_inbound_email.py) —
CustomTokenObtainPairSerializer.validate() rechaza el login de
cualquier cuenta con rol USUARIO, sin importar la contraseña."""
import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import Role, User

pytestmark = pytest.mark.django_db


def _create_user(username, role, password="Pocosegura123"):
    user = User.objects.create(username=username, email=f"{username}@example.com", role=role)
    user.set_password(password)
    user.save()
    return user


class TestLoginBlockedForUsuario:
    def test_usuario_cannot_login(self):
        _create_user("usuario1", Role.USUARIO)

        response = Client().post(
            reverse("token_obtain_pair"),
            data={"username": "usuario1", "password": "Pocosegura123"},
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_tecnico_can_login(self):
        _create_user("tecnico1", Role.TECNICO)

        response = Client().post(
            reverse("token_obtain_pair"),
            data={"username": "tecnico1", "password": "Pocosegura123"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert "access" in response.json()

    def test_admin_can_login(self):
        _create_user("admin1", Role.ADMIN)

        response = Client().post(
            reverse("token_obtain_pair"),
            data={"username": "admin1", "password": "Pocosegura123"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert "access" in response.json()
