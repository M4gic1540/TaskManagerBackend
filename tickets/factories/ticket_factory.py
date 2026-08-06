"""Factory Pattern: construye Ticket aplicando reglas por categoría
(ej. prioridad default) sin ensuciar el Service con condicionales."""
from __future__ import annotations

from tickets.models import TicketCategory, TicketPriority

_DEFAULT_PRIORITY_BY_CATEGORY: dict[str, str] = {
    TicketCategory.RED: TicketPriority.ALTA,
    TicketCategory.ACCESOS: TicketPriority.ALTA,
    TicketCategory.HARDWARE: TicketPriority.MEDIA,
    TicketCategory.SOFTWARE: TicketPriority.MEDIA,
    TicketCategory.RECLAMOS: TicketPriority.BAJA,
    TicketCategory.SUGERENCIAS: TicketPriority.BAJA,
    TicketCategory.RESERVA_DE_SALAS: TicketPriority.BAJA,
    TicketCategory.OTRO: TicketPriority.BAJA,
}


class TicketFactory:
    """Encapsula reglas de creación. Si el llamador no especifica
    prioridad, se infiere de la categoría."""

    @staticmethod
    def build_creation_payload(
        *, title: str, description: str, category: str, priority: str | None, requester
    ) -> dict:
        resolved_priority = priority or _DEFAULT_PRIORITY_BY_CATEGORY.get(
            category, TicketPriority.MEDIA
        )
        return {
            "title": title.strip(),
            "description": description.strip(),
            "category": category,
            "priority": resolved_priority,
            "requester": requester,
        }
