"""Eventos de dominio emitidos por UserService."""
from dataclasses import dataclass

from core.events.base import DomainEvent


@dataclass(frozen=True)
class UserRoleChanged(DomainEvent):
    user_id: int = 0
    old_role: str = ""
    new_role: str = ""
    changed_by_id: int = 0
