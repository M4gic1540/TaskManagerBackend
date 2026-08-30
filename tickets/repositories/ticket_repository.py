"""Repository concreto de Ticket. Único punto que toca `Ticket.objects`
directamente; Services siempre pasan por acá."""
from __future__ import annotations

from django.db.models import QuerySet

from core.repositories.base import DjangoRepository
from core.specifications.base import Specification
from tickets.models import Ticket, TicketComment, TicketTimeLog


class TicketRepository(DjangoRepository[Ticket]):
    model = Ticket

    def get_queryset(self) -> QuerySet[Ticket]:
        return super().get_queryset()

    def get_for_update(self, ticket_id: int) -> Ticket:
        """Lock a nivel de fila (SELECT FOR UPDATE): usado por
        self_assign para evitar que dos técnicos tomen el mismo ticket
        sin asignar en una condición de carrera."""
        from core.exceptions import EntityNotFoundError
        try:
            return self.get_queryset().select_for_update().get(pk=ticket_id)
        except Ticket.DoesNotExist as exc:
            raise EntityNotFoundError(f"Ticket con id={ticket_id} no existe.") from exc

    def list(self, spec: Specification | None = None) -> QuerySet[Ticket]:
        return super().list(spec).prefetch_related("comments", "time_logs")

    def get_by_code(self, code: str) -> Ticket | None:
        return self.get_queryset().filter(code=code).first()

    def get_by_external_message_id(self, message_id: str) -> Ticket | None:
        return self.get_queryset().filter(external_message_id=message_id).first()

    def get_comment_by_external_message_id(self, message_id: str) -> TicketComment | None:
        """Idempotencia de respuestas de correo: un `Message-ID` de
        respuesta ya procesado no debe generar un segundo comentario."""
        return TicketComment.objects.filter(external_message_id=message_id).first()

    def add_comment(
        self, ticket: Ticket, author, body: str, is_internal: bool = False,
        external_message_id: str | None = None,
    ) -> TicketComment:
        return TicketComment.objects.create(
            ticket=ticket, author_id=author.id, author_username=author.username,
            body=body, is_internal=is_internal, external_message_id=external_message_id,
        )

    def add_time_log(
        self, ticket: Ticket, technician, minutes_spent: int, notes: str = ""
    ) -> TicketTimeLog:
        return TicketTimeLog.objects.create(
            ticket=ticket,
            technician_id=technician.id,
            technician_username=technician.username,
            minutes_spent=minutes_spent,
            notes=notes,
        )

    def total_minutes_spent(self, ticket: Ticket) -> int:
        return sum(ticket.time_logs.values_list("minutes_spent", flat=True))
