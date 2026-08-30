"""Observers concretos. Se registran en tickets/apps.py al arrancar
la app (AppConfig.ready), manteniendo el Service ciego a estos efectos."""
import asyncio
import logging

from django.conf import settings
from django.core.mail import send_mail

from core.async_support.bridge import fire_and_forget, to_async
from core.events.base import EventObserver
from tickets.events import (
    TicketAIClassified,
    TicketAssigned,
    TicketCommented,
    TicketCreated,
    TicketStatusChanged,
)
from tickets.ml.classifier import TicketClassifier
from tickets.services.ticket_service import TicketService

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
            logger.info("AUDIT ticket_commented id=%s by=%s internal=%s req=%s",
                        event.ticket_id, event.author_id, event.is_internal, event.request_id)
        elif isinstance(event, TicketAIClassified):
            logger.info(
                "AUDIT ticket_ai_classified id=%s category=%s->%s req=%s",
                event.ticket_id, event.old_category, event.new_category, event.request_id,
            )


async def _send_notification(message: str) -> None:
    """Simula I/O real (llamada a proveedor de email/push). Al ser
    corutina, no bloquea el event loop mientras 'espera' la red.
    Reemplazar el cuerpo por una llamada real (httpx.AsyncClient, etc.)
    no requiere tocar el Observer ni el Service."""
    await asyncio.sleep(0.05)
    logger.info(message)


def _classify_ticket_with_ml(event: TicketCreated) -> None:
    """Clasificación automática local (categoría) con el modelo
    entrenado en tickets/ml/ (TF-IDF + regresión logística,
    scikit-learn). Reemplaza al workflow de n8n + API de IA externa —
    corre en el mismo proceso, sin red ni secretos compartidos.

    Si el modelo todavía no fue entrenado (`predict()` devuelve None,
    ver tickets/ml/classifier.py) o la confianza no supera
    TICKET_AI_CONFIDENCE_THRESHOLD, no se toca nada — mismo criterio
    best-effort que ya tenía el resto de este Observer."""
    try:
        result = TicketClassifier.get().predict(event.title, event.description)
        if result is None:
            return

        threshold = getattr(settings, "TICKET_AI_CONFIDENCE_THRESHOLD", 0.5)
        if result.category_confidence < threshold:
            return

        TicketService().apply_ai_classification(
            ticket_id=event.ticket_id, category=result.category,
        )
    except Exception:
        # Best-effort: una falla del clasificador nunca puede tumbar la
        # creación del ticket, que ya se guardó en BD antes de este punto.
        logger.exception("No se pudo clasificar automáticamente el ticket id=%s", event.ticket_id)


def _send_comment_reply_email(event: TicketCommented) -> None:
    """Correo saliente al solicitante cuando un Técnico/Admin responde
    un ticket — mantiene el hilo de conversación por correo. No-op en
    tres casos: nota interna (nunca sale), comentario del propio
    solicitante externo (evita reenviarle su propio correo de vuelta),
    o ticket sin correo de contacto (creado sin ese dato)."""
    if event.is_internal or event.author_is_external or not event.requester_email:
        return
    try:
        send_mail(
            subject=f"Re: [{event.ticket_code}] {event.ticket_title}",
            message=event.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[event.requester_email],
            fail_silently=False,
        )
    except Exception:
        # Best-effort: un correo que no sale nunca debe tumbar la
        # creación del comentario (ya se guardó en BD antes de este punto).
        logger.exception("No se pudo enviar el correo de respuesta ticket_id=%s", event.ticket_id)


class TicketNotificationObserver(EventObserver):
    """Punto de extensión para email/push. El envío se agenda como
    tarea async fire-and-forget: la petición HTTP no espera a que la
    notificación termine de enviarse."""

    def handle(self, event) -> None:
        if isinstance(event, TicketCreated):
            fire_and_forget(to_async(_classify_ticket_with_ml)(event))
        elif isinstance(event, TicketAssigned):
            fire_and_forget(_send_notification(
                f"NOTIFY técnico {event.technician_id}: nuevo ticket asignado (id={event.ticket_id})"
            ))
        elif isinstance(event, TicketStatusChanged) and event.new_status == "RESUELTO":
            fire_and_forget(_send_notification(
                f"NOTIFY solicitante: ticket {event.ticket_id} marcado como resuelto"
            ))
        elif isinstance(event, TicketCommented):
            fire_and_forget(to_async(_send_comment_reply_email)(event))
