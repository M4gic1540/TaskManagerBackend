"""Test HTTP del registro público. Cubre el wrapper con rate-limit
agregado sobre RegisterView.post (antes solo heredaba el AnonRateThrottle
genérico de 20/min compartido por todos los endpoints anónimos)."""
import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User

pytestmark = pytest.mark.django_db


def test_register_creates_usuario_role_account():
    client = APIClient()

    response = client.post(
        "/api/v1/auth/register/",
        {
            "username": "nuevo.usuario",
            "email": "nuevo@example.com",
            "password": "Str0ngP@ssw0rd!2026",
        },
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(username="nuevo.usuario")
    assert user.role == Role.USUARIO
    assert user.check_password("Str0ngP@ssw0rd!2026")
