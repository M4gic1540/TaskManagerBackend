"""Service Layer: única capa con lógica de negocio de Tickets.
Orquesta Repository + Factory + Strategy + EventBus. Las vistas DRF
solo llaman a estos métodos (Separation of Concerns)."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from accounts.enums import Role
from core.events.base import EventBus
from core.exceptions import InvalidStateTransitionError, PermissionDeniedError, ValidationError
from tickets.events import TicketAssigned, TicketCommented, TicketCreated, TicketStatusChanged
from tickets.factories.ticket_factory import TicketFactory
from tickets.models import Ticket, TicketStatus
from tickets.repositories.ticket_repository import TicketRepository
from tickets.strategies.status_transitions import TransitionStrategyFactory


class TicketService:
    def __init__(self, repository: TicketRepository | None = None):
        self.repository = repository or TicketRepository()

    # --- Creación -----------------------------------------------------
    @transaction.atomic
    def create_ticket(
        self, *, title: str, description: str, category: str, priority: str | None, requester
    ) -> Ticket:
        if not title or not description:
            raise ValidationError("Título y descripción son obligatorios.")

        payload = TicketFactory.build_creation_payload(
            title=title, description=description, category=category,
            priority=priority, requester=requester,
        )
        ticket = self.repository.create(**payload)

        EventBus.publish(TicketCreated(
            ticket_id=ticket.id, code=ticket.code, requester_id=requester.id,
        ))
        return ticket

    # --- Asignación (solo Admin) ---------------------------------------
    @transaction.atomic
    def assign_technician(
        self, *, ticket_id: int, technician_id: int, technician_username: str, actor
    ) -> Ticket:
        """`technician_id`/`technician_username` vienen del payload (el
        Admin ya los obtuvo de GET /technicians/ en accounts) — no se
        valida contra la BD que ese id efectivamente tenga rol Técnico,
        porque este servicio no tiene acceso a la tabla de usuarios
        (trade-off aceptado de la separación de BD por microservicio)."""
        if actor.role != Role.ADMIN and not actor.is_superuser:
            raise PermissionDeniedError("Solo un Administrador puede asignar técnicos.")

        ticket = self.repository.get_by_id(ticket_id)
        ticket = self.repository.update(
            ticket,
            assigned_technician_id=technician_id,
            assigned_technician_username=technician_username,
            status=TicketStatus.ASIGNADO,
        )

        EventBus.publish(TicketAssigned(
            ticket_id=ticket.id, technician_id=technician_id, assigned_by_id=actor.id,
        ))
        return ticket

    # --- Auto-asignación (Técnico toma un ticket sin asignar) ------------
    @transaction.atomic
    def self_assign(self, *, ticket_id: int, technician) -> Ticket:
        if technician.role != Role.TECNICO:
            raise PermissionDeniedError("Solo un Técnico puede tomar tickets.")
        if not technician.is_active_technician:
            raise PermissionDeniedError("Tu cuenta de técnico está desactivada.")

        # select_for_update evita condición de carrera: dos técnicos
        # tomando el mismo ticket sin asignar al mismo tiempo.
        ticket = self.repository.get_for_update(ticket_id)

        if ticket.assigned_technician_id is not None:
            raise ValidationError("Este ticket ya tiene un técnico asignado.")
        if ticket.status != TicketStatus.ABIERTO:
            raise InvalidStateTransitionError(
                "Solo se pueden tomar tickets en estado ABIERTO."
            )

        ticket = self.repository.update(
            ticket,
            assigned_technician_id=technician.id,
            assigned_technician_username=technician.username,
            status=TicketStatus.ASIGNADO,
        )

        EventBus.publish(TicketAssigned(
            ticket_id=ticket.id, technician_id=technician.id, assigned_by_id=technician.id,
        ))
        return ticket

    # --- Cambio de estado (Strategy Pattern) ---------------------------
    @transaction.atomic
    def change_status(self, *, ticket_id: int, new_status: str, actor) -> Ticket:
        ticket = self.repository.get_by_id(ticket_id)
        strategy = TransitionStrategyFactory.get_strategy(ticket.status)
        strategy.validate(ticket, new_status, actor)

        old_status = ticket.status
        fields = {"status": new_status}
        if new_status == TicketStatus.CERRADO:
            fields["closed_at"] = timezone.now()

        ticket = self.repository.update(ticket, **fields)

        EventBus.publish(TicketStatusChanged(
            ticket_id=ticket.id, old_status=old_status, new_status=new_status,
            changed_by_id=actor.id,
        ))
        return ticket

    # --- Cierre con nota de resolución obligatoria ----------------------
    @transaction.atomic
    def close_ticket(self, *, ticket_id: int, resolution_notes: str, actor) -> Ticket:
        if not resolution_notes or not resolution_notes.strip():
            raise ValidationError("Se requiere nota de resolución para cerrar el ticket.")

        ticket = self.repository.get_by_id(ticket_id)
        if ticket.status != TicketStatus.RESUELTO:
            raise ValidationError("Solo se puede cerrar un ticket en estado RESUELTO.")

        strategy = TransitionStrategyFactory.get_strategy(ticket.status)
        strategy.validate(ticket, TicketStatus.CERRADO, actor)

        ticket = self.repository.update(
            ticket,
            status=TicketStatus.CERRADO,
            resolution_notes=resolution_notes.strip(),
            closed_at=timezone.now(),
        )

        EventBus.publish(TicketStatusChanged(
            ticket_id=ticket.id, old_status=TicketStatus.RESUELTO,
            new_status=TicketStatus.CERRADO, changed_by_id=actor.id,
        ))
        return ticket

    # --- Comentarios (todos los roles) ----------------------------------
    def add_comment(self, *, ticket_id: int, author, body: str):
        if not body or not body.strip():
            raise ValidationError("El comentario no puede estar vacío.")

        ticket = self.repository.get_by_id(ticket_id)
        comment = self.repository.add_comment(ticket, author, body.strip())

        EventBus.publish(TicketCommented(ticket_id=ticket.id, author_id=author.id))
        return comment

    # --- Registro de tiempo trabajado (solo Técnico) ---------------------
    def log_time(self, *, ticket_id: int, technician, minutes_spent: int, notes: str = ""):
        if technician.role != Role.TECNICO:
            raise PermissionDeniedError("Solo un Técnico puede registrar tiempo trabajado.")
        if minutes_spent <= 0:
            raise ValidationError("Los minutos trabajados deben ser mayores a 0.")

        ticket = self.repository.get_by_id(ticket_id)
        if ticket.assigned_technician_id != technician.id:
            raise PermissionDeniedError("Solo el técnico asignado puede registrar tiempo.")

        return self.repository.add_time_log(ticket, technician, minutes_spent, notes)

    # --- Consultas -------------------------------------------------------
    def get_ticket(self, ticket_id: int) -> Ticket:
        return self.repository.get_by_id(ticket_id)

    def list_tickets(self, spec=None):
        return self.repository.list(spec)
