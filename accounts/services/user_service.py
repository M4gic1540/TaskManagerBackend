"""Service Layer: lógica de negocio de gestión de usuarios.
Separado de TicketService porque es un dominio distinto (accounts vs
tickets) — Separation of Concerns."""
from __future__ import annotations

from django.db import transaction

from accounts.events import UserRoleChanged
from accounts.models import Role, User
from core.events.base import EventBus
from core.exceptions import PermissionDeniedError, ValidationError


class UserService:
    @transaction.atomic
    def change_role(self, *, user_id: int, new_role: str, actor: User) -> User:
        if actor.role != Role.ADMIN and not actor.is_superuser:
            raise PermissionDeniedError("Solo un Administrador puede cambiar roles.")

        if new_role not in Role.values:
            raise ValidationError(f"Rol inválido: {new_role}")

        target = User.objects.select_for_update().get(pk=user_id)

        if target.id == actor.id:
            raise ValidationError("No podés cambiar tu propio rol.")

        old_role = target.role
        if old_role == new_role:
            return target  # no-op idempotente, sin evento ni escritura

        if old_role == Role.ADMIN and new_role != Role.ADMIN:
            remaining_admins = User.objects.filter(
                role=Role.ADMIN, is_active=True
            ).exclude(pk=target.pk).count()
            if remaining_admins == 0:
                raise ValidationError(
                    "No se puede quitar el rol Admin al último administrador activo."
                )

        target.role = new_role
        target.save(update_fields=["role"])

        EventBus.publish(UserRoleChanged(
            user_id=target.id, old_role=old_role, new_role=new_role, changed_by_id=actor.id,
        ))
        return target
