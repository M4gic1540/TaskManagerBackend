"""Eventos de dominio emitidos por TicketService."""
from dataclasses import dataclass

from core.events.base import DomainEvent


@dataclass(frozen=True)
class TicketCreated(DomainEvent):
    ticket_id: int = 0
    code: str = ""
    requester_id: int = 0
    title: str = ""
    description: str = ""
    category: str = ""
    requester_username: str = ""


@dataclass(frozen=True)
class TicketAssigned(DomainEvent):
    ticket_id: int = 0
    technician_id: int = 0
    assigned_by_id: int = 0


@dataclass(frozen=True)
class TicketStatusChanged(DomainEvent):
    ticket_id: int = 0
    old_status: str = ""
    new_status: str = ""
    changed_by_id: int = 0


@dataclass(frozen=True)
class TicketCommented(DomainEvent):
    """Campos denormalizados (código/título/correo del solicitante,
    cuerpo) para que el observer de correo saliente
    (tickets/observers.py::_send_comment_reply_email) no tenga que
    volver a golpear la BD — mismo criterio que TicketCreated."""

    ticket_id: int = 0
    author_id: int = 0
    is_internal: bool = False
    author_is_external: bool = False
    body: str = ""
    ticket_code: str = ""
    ticket_title: str = ""
    requester_email: str = ""


@dataclass(frozen=True)
class TicketAIClassified(DomainEvent):
    """Emitido cuando el clasificador local de tickets (ver
    tickets/ml/) aplica una categoría sugerida tras la creación del
    ticket — ver tickets/observers.py::_classify_ticket_with_ml."""

    ticket_id: int = 0
    old_category: str = ""
    new_category: str = ""
