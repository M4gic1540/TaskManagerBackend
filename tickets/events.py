"""Eventos de dominio emitidos por TicketService."""
from dataclasses import dataclass

from core.events.base import DomainEvent


@dataclass(frozen=True)
class TicketCreated(DomainEvent):
    ticket_id: int = 0
    code: str = ""
    requester_id: int = 0


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
    ticket_id: int = 0
    author_id: int = 0
