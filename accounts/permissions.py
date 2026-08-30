"""RBAC: permission classes de DRF, una por rol. Se combinan en las
vistas vía `permission_classes = [IsAdmin | IsTechnician]`.
"""
from rest_framework.permissions import BasePermission

from accounts.enums import Role


class IsAdmin(BasePermission):
    message = "Requiere rol Administrador."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == Role.ADMIN
        )


class IsTechnician(BasePermission):
    message = "Requiere rol Técnico."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == Role.TECNICO
        )


class IsRequester(BasePermission):
    message = "Requiere rol Usuario."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == Role.USUARIO
        )


class IsOwnerOrAssignedTechnicianOrAdmin(BasePermission):
    """Object-level: dueño del ticket, técnico asignado, o admin."""

    message = "No tiene acceso a este ticket."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.role == Role.ADMIN:
            return True
        if user.role == Role.TECNICO:
            return obj.assigned_technician_id == user.id
        return obj.requester_id == user.id


class IsOwnerOrTechnicianOrAdmin(BasePermission):
    """Object-level: dueño del ticket, cualquier técnico, o admin.

    A diferencia de IsOwnerOrAssignedTechnicianOrAdmin, no exige que el
    técnico sea el asignado: ver el detalle y cambiar el estado son
    acciones que cualquier técnico debe poder hacer (p.ej. antes de
    autoasignarse un ticket del pool de abiertos).
    """

    message = "No tiene acceso a este ticket."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.role in (Role.ADMIN, Role.TECNICO):
            return True
        return obj.requester_id == user.id
