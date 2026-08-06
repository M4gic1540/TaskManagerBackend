"""Observers concretos. Se registran en tickets/apps.py al arrancar
la app (AppConfig.ready), manteniendo el Service ciego a estos efectos."""
import asyncio
import logging

from core.async_support.bridge import fire_and_forget
from core.events.base import EventObserver
from tickets.events import (
    TicketAssigned,
    TicketCommented,
    TicketCreated,
    TicketStatusChanged,
)

logger = logging.getLogger("ticketera")


class TicketAuditObserver(EventObserver):
    """Deja traza de auditoría (cumple requisito 'Auditoría' del Admin)."""

    def handle(self, event) -> None:
        if isinstance(event, TicketCreated):
            logger.info("AUDIT ticket_created id=%s code=%s by=%s req=%s",
                        event.ticket_id, event.code, event.requester_id, event.request_id)
        elif isinstance(event, TicketAssigned):
            logger.info("AUDIT ticket_assigned id=%s technician=%s by=%s req=%s",
                        event.ticket_id, event.technician_id, event.assigned_by_id, event.request_id)
        elif isinstance(event, TicketStatusChanged):
            logger.info("AUDIT ticket_status_changed id=%s %s->%s by=%s req=%s",
                        event.ticket_id, event.old_status, event.new_status, event.changed_by_id,
                        event.request_id)
        elif isinstance(event, TicketCommented):
            logger.info("AUDIT ticket_commented id=%s by=%s req=%s",
                        event.ticket_id, event.author_id, event.request_id)


async def _send_notification(message: str) -> None:
    """Simula I/O real (llamada a proveedor de email/push). Al ser
    corutina, no bloquea el event loop mientras 'espera' la red.
    Reemplazar el cuerpo por una llamada real (httpx.AsyncClient, etc.)
    no requiere tocar el Observer ni el Service."""
    await asyncio.sleep(0.05)
    logger.info(message)


class TicketNotificationObserver(EventObserver):
    """Punto de extensión para email/push. El envío se agenda como
    tarea async fire-and-forget: la petición HTTP no espera a que la
    notificación termine de enviarse."""

    def handle(self, event) -> None:
        if isinstance(event, TicketAssigned):
            fire_and_forget(_send_notification(
                f"NOTIFY técnico {event.technician_id}: nuevo ticket asignado (id={event.ticket_id})"
            ))
        elif isinstance(event, TicketStatusChanged) and event.new_status == "RESUELTO":
            fire_and_forget(_send_notification(
                f"NOTIFY solicitante: ticket {event.ticket_id} marcado como resuelto"
            ))
