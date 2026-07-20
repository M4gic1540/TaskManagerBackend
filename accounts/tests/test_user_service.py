"""Tests de UserService. Usa DB real (pytest-django) porque
`select_for_update()` no tiene sentido con un fake en memoria — es
justamente la garantía transaccional lo que se está testeando."""
import pytest

from accounts.models import Role, User
from accounts.services.user_service import UserService
from core.events.base import EventBus
from core.exceptions import PermissionDeniedError, ValidationError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_event_bus():
    EventBus.reset()
    yield
    EventBus.reset()


@pytest.fixture
def admin():
    return User.objects.create_user(username="admin1", password="x", role=Role.ADMIN)


@pytest.fixture
def usuario():
    return User.objects.create_user(username="user1", password="x", role=Role.USUARIO)


class TestChangeRole:
    def test_admin_promotes_user_to_tecnico(self, admin, usuario):
        updated = UserService().change_role(user_id=usuario.id, new_role=Role.TECNICO, actor=admin)
        assert updated.role == Role.TECNICO

    def test_non_admin_cannot_change_roles(self, usuario):
        other = User.objects.create_user(username="user2", password="x", role=Role.USUARIO)
        with pytest.raises(PermissionDeniedError):
            UserService().change_role(user_id=other.id, new_role=Role.TECNICO, actor=usuario)

    def test_cannot_change_own_role(self, admin):
        with pytest.raises(ValidationError):
            UserService().change_role(user_id=admin.id, new_role=Role.USUARIO, actor=admin)

    def test_invalid_role_rejected(self, admin, usuario):
        with pytest.raises(ValidationError):
            UserService().change_role(user_id=usuario.id, new_role="SUPERUSER", actor=admin)

    def test_last_admin_protection(self):
        sole_admin = User.objects.create_user(username="solo_admin", password="x", role=Role.ADMIN)
        another_admin = User.objects.create_user(
            username="second_admin", password="x", role=Role.ADMIN
        )
        acting_admin = User.objects.create_user(
            username="acting_admin", password="x", role=Role.ADMIN
        )
        # degradar a 'another_admin': quedan sole_admin + acting_admin como admins
        UserService().change_role(
            user_id=another_admin.id, new_role=Role.USUARIO, actor=acting_admin
        )
        # degradar a 'sole_admin': queda acting_admin como único admin -> ok
        UserService().change_role(
            user_id=sole_admin.id, new_role=Role.USUARIO, actor=acting_admin
        )
        # ahora acting_admin es el ÚNICO admin activo restante; degradarlo
        # dejaría el sistema sin administradores -> debe bloquearse.
        # Se necesita otro actor Admin para intentarlo (nadie más queda,
        # así que usamos is_superuser para simular un super-admin externo).
        super_actor = User.objects.create_user(
            username="super_actor", password="x", role=Role.USUARIO, is_superuser=True
        )
        with pytest.raises(ValidationError):
            UserService().change_role(
                user_id=acting_admin.id, new_role=Role.USUARIO, actor=super_actor
            )

    def test_noop_when_role_unchanged(self, admin, usuario):
        result = UserService().change_role(user_id=usuario.id, new_role=Role.USUARIO, actor=admin)
        assert result.role == Role.USUARIO
