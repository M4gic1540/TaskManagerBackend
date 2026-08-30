"""Service Layer: única capa con lógica de negocio de Tickets.
Orquesta Repository + Factory + Strategy + EventBus. Las vistas DRF
solo llaman a estos métodos (Separation of Concerns)."""
from __future__ import annotations

import logging
import re
from types import SimpleNamespace

from django.db import transaction
from django.utils import timezone

from accounts.enums import Role
from core.events.base import EventBus
from core.exceptions import InvalidStateTransitionError, PermissionDeniedError, ValidationError
from tickets.events import (
    TicketAIClassified,
    TicketAssigned,
    TicketCommented,
    TicketCreated,
    TicketStatusChanged,
)
from tickets.factories.ticket_factory import TicketFactory
from tickets.models import Ticket, TicketCategory, TicketStatus
from tickets.repositories.ticket_repository import TicketRepository
from tickets.strategies.status_transitions import TransitionStrategyFactory

logger = logging.getLogger("ticketera")

# Sentinel: los tickets/comentarios creados a partir de un correo
# entrante (sin cuenta real, ver create_ticket_from_email) usan este
# id — los ids reales de accounts.User parten en 1 (AutoField).
EXTERNAL_REQUESTER_ID = 0

_TICKET_CODE_RE = re.compile(r"TCK-[0-9A-Z]{8}")

# Debe coincidir con Ticket.title.max_length / Ticket.external_message_id.max_length
# — un correo real puede traer un asunto o un Message-ID más largos que la
# columna, y SQLite (dev/tests) los acepta sin quejarse mientras
# Postgres/MySQL (producción) los rechaza con un error de integridad. Truncar
# acá, en el borde de ingesta, evita que ese error tumbe el ticket completo.
_MAX_TITLE_LENGTH = 200
_MAX_MESSAGE_ID_LENGTH = 255


class TicketService:
    def __init__(self, repository: TicketRepository | None = None):
        self.repository = repository or TicketRepository()

    # --- Creación -----------------------------------------------------
    @transaction.atomic
    def create_ticket(
        self, *, title: str, description: str, category: str, requester,
        requester_email: str | None = None, external_message_id: str | None = None,
    ) -> Ticket:
        if not title or not description:
            raise ValidationError("Título y descripción son obligatorios.")

        payload = TicketFactory.build_creation_payload(
            title=title, description=description, category=category, requester=requester,
            requester_email=requester_email, external_message_id=external_message_id,
        )
        ticket = self.repository.create(**payload)

        event = TicketCreated(
            ticket_id=ticket.id, code=ticket.code, requester_id=requester.id,
            title=ticket.title, description=ticket.description,
            category=ticket.category, requester_username=ticket.requester_username,
        )
        # on_commit, no publish directo: los observers (clasificación
        # ML) releen el ticket por id, y sin loop ASGI registrado
        # (management commands, shell) fire_and_forget cae a ejecución
        # SÍNCRONA en otro thread — si el evento se publica antes de
        # que esta transacción (o la de create_ticket_from_email, que
        # anida esta vía savepoint) haga commit, esa lectura no ve la
        # fila todavía y revienta con EntityNotFoundError.
        transaction.on_commit(lambda: EventBus.publish(event))
        return ticket

    # --- Ingesta de correo (ver tickets/management/commands/poll_inbound_email.py) --
    @transaction.atomic
    def create_ticket_from_email(
        self, *, external_message_id: str, sender_email: str, sender_name: str,
        subject: str, body: str,
    ) -> Ticket:
        """Idempotente por `external_message_id` — tanto si el correo
        genera un ticket nuevo como si genera un comentario de
        respuesta (ver `get_comment_by_external_message_id`). Si el
        asunto trae el código de un ticket existente Y el remitente
        coincide con el solicitante original, se trata como una
        respuesta del hilo (comentario); si el código matchea pero el
        remitente es distinto, se descarta como respuesta (evita que
        cualquiera inyecte comentarios en un ticket ajeno solo por
        conocer su código) y se procesa como ticket nuevo, para no
        perder el mensaje."""
        external_message_id = (external_message_id or "")[:_MAX_MESSAGE_ID_LENGTH]

        existing_ticket = self.repository.get_by_external_message_id(external_message_id)
        if existing_ticket is not None:
            return existing_ticket
        existing_comment = self.repository.get_comment_by_external_message_id(external_message_id)
        if existing_comment is not None:
            return existing_comment.ticket

        requester = SimpleNamespace(
            id=EXTERNAL_REQUESTER_ID, username=(sender_name or sender_email)[:150],
        )
        title = ((subject or "").strip() or "Sin asunto")[:_MAX_TITLE_LENGTH]
        description = (body or "").strip() or "(El correo no traía contenido de texto legible.)"

        code_match = _TICKET_CODE_RE.search(subject or "")
        if code_match:
            ticket = self.repository.get_by_code(code_match.group(0))
            if ticket is not None:
                if (
                    ticket.requester_email
                    and ticket.requester_email.strip().lower() == sender_email.strip().lower()
                ):
                    self.add_comment(
                        ticket_id=ticket.id, author=requester, body=description,
                        is_internal=False, external_message_id=external_message_id,
                    )
                    return ticket
                logger.warning(
                    "Correo con código de ticket %s pero remitente distinto al "
                    "solicitante original (remitente=%s) — se descarta como respuesta "
                    "y se procesa como ticket nuevo.", ticket.code, sender_email,
                )

        return self.create_ticket(
            title=title,
            description=description,
            category=TicketCategory.OTRO,
            requester=requester,
            requester_email=sender_email,
            external_message_id=external_message_id,
        )

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

        event = TicketAssigned(
            ticket_id=ticket.id, technician_id=technician_id, assigned_by_id=actor.id,
        )
        transaction.on_commit(lambda: EventBus.publish(event))
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

        event = TicketAssigned(
            ticket_id=ticket.id, technician_id=technician.id, assigned_by_id=technician.id,
        )
        transaction.on_commit(lambda: EventBus.publish(event))
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

        event = TicketStatusChanged(
            ticket_id=ticket.id, old_status=old_status, new_status=new_status,
            changed_by_id=actor.id,
        )
        transaction.on_commit(lambda: EventBus.publish(event))
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

        event = TicketStatusChanged(
            ticket_id=ticket.id, old_status=TicketStatus.RESUELTO,
            new_status=TicketStatus.CERRADO, changed_by_id=actor.id,
        )
        transaction.on_commit(lambda: EventBus.publish(event))
        return ticket

    # --- Comentarios (personal técnico/admin + respuestas del hilo) ------
    def add_comment(
        self, *, ticket_id: int, author, body: str, is_internal: bool = False,
        external_message_id: str | None = None,
    ):
        if not body or not body.strip():
            raise ValidationError("El comentario no puede estar vacío.")

        ticket = self.repository.get_by_id(ticket_id)
        stripped_body = body.strip()
        comment = self.repository.add_comment(
            ticket, author, stripped_body, is_internal, external_message_id=external_message_id,
        )

        event = TicketCommented(
            ticket_id=ticket.id, author_id=author.id,
            is_internal=is_internal, author_is_external=author.id == EXTERNAL_REQUESTER_ID,
            body=stripped_body, ticket_code=ticket.code, ticket_title=ticket.title,
            requester_email=ticket.requester_email,
        )
        transaction.on_commit(lambda: EventBus.publish(event))
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

    # --- Clasificación automática (modelo local, ver tickets/ml/) --------
    def apply_ai_classification(self, *, ticket_id: int, category: str) -> Ticket:
        """Aplica la categoría sugerida por el clasificador local de
        tickets tras su creación (ver
        tickets/observers.py::_classify_ticket_with_ml). Solo actualiza
        metadata: no toca el estado ni pasa por el Strategy Pattern de
        transiciones."""
        if category not in TicketCategory.values:
            raise ValidationError(f"Categoría inválida: {category}.")

        ticket = self.repository.get_by_id(ticket_id)
        if ticket.status in (TicketStatus.CERRADO, TicketStatus.CANCELADO):
            raise ValidationError("No se puede reclasificar un ticket cerrado o cancelado.")

        old_category = ticket.category
        ticket = self.repository.update(ticket, category=category)

        event = TicketAIClassified(
            ticket_id=ticket.id, old_category=old_category, new_category=ticket.category,
        )
        transaction.on_commit(lambda: EventBus.publish(event))
        return ticket

    # --- Consultas -------------------------------------------------------
    def get_ticket(self, ticket_id: int) -> Ticket:
        return self.repository.get_by_id(ticket_id)

    def list_tickets(self, spec=None):
        return self.repository.list(spec)
