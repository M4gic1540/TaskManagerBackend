"""Strategy Pattern: cada estado de Ticket define su propia estrategia
de transición válida. Agregar un estado nuevo = agregar una clase, sin
tocar `if/elif` gigante en el Service (Open/Closed).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from accounts.enums import Role
from core.exceptions import InvalidStateTransitionError, PermissionDeniedError
from tickets.models import Ticket, TicketStatus


class TransitionStrategy(ABC):
    """Contrato: valida si `actor` puede mover el ticket a `target_status`."""

    allowed_targets: set[str] = set()

    @abstractmethod
    def allowed_roles(self) -> set[str]:
        raise NotImplementedError

    def validate(self, ticket: Ticket, target_status: str, actor) -> None:
        if target_status not in self.allowed_targets:
            raise InvalidStateTransitionError(
                f"No se puede pasar de {ticket.status} a {target_status}."
            )
        if actor.role not in self.allowed_roles() and not actor.is_superuser:
            raise PermissionDeniedError(
                f"Rol {actor.role} no puede realizar esta transición."
            )


class AbiertoStrategy(TransitionStrategy):
    allowed_targets = {TicketStatus.ASIGNADO, TicketStatus.CANCELADO}

    def allowed_roles(self) -> set[str]:
        return {Role.ADMIN}


class AsignadoStrategy(TransitionStrategy):
    allowed_targets = {TicketStatus.EN_PROGRESO, TicketStatus.ABIERTO}

    def allowed_roles(self) -> set[str]:
        return {Role.ADMIN, Role.TECNICO}


class EnProgresoStrategy(TransitionStrategy):
    allowed_targets = {TicketStatus.RESUELTO, TicketStatus.ASIGNADO}

    def allowed_roles(self) -> set[str]:
        return {Role.ADMIN, Role.TECNICO}


class ResueltoStrategy(TransitionStrategy):
    allowed_targets = {TicketStatus.CERRADO, TicketStatus.EN_PROGRESO}

    def allowed_roles(self) -> set[str]:
        return {Role.ADMIN, Role.TECNICO, Role.USUARIO}


class CerradoStrategy(TransitionStrategy):
    allowed_targets: set[str] = set()  # estado terminal

    def allowed_roles(self) -> set[str]:
        return set()


class CanceladoStrategy(TransitionStrategy):
    allowed_targets: set[str] = set()  # estado terminal

    def allowed_roles(self) -> set[str]:
        return set()


_STRATEGY_REGISTRY: dict[str, type[TransitionStrategy]] = {
    TicketStatus.ABIERTO: AbiertoStrategy,
    TicketStatus.ASIGNADO: AsignadoStrategy,
    TicketStatus.EN_PROGRESO: EnProgresoStrategy,
    TicketStatus.RESUELTO: ResueltoStrategy,
    TicketStatus.CERRADO: CerradoStrategy,
    TicketStatus.CANCELADO: CanceladoStrategy,
}


class TransitionStrategyFactory:
    """Factory Pattern: entrega la estrategia correcta según estado actual."""

    @staticmethod
    def get_strategy(current_status: str) -> TransitionStrategy:
        strategy_cls = _STRATEGY_REGISTRY.get(current_status)
        if strategy_cls is None:
            raise InvalidStateTransitionError(f"Estado desconocido: {current_status}")
        return strategy_cls()
