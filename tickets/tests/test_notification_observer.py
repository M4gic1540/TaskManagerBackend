"""Tests del correo de 'ticket creado' (tickets/observers.py). El
envío corre vía fire_and_forget, que cae a ejecución sync cuando no hay
loop ASGI corriendo (caso de los tests) — así que handle() ya deja el
correo en mail.outbox sin mockear nada del bridge async."""
import pytest
from django.core import mail

from tickets.events import TicketCreated
from tickets.observers import TicketNotificationObserver


class _BrokenEmailBackend:
    """EMAIL_BACKEND que siempre revienta al instanciarse — simula un
    SMTP caído para probar que un correo fallido no tumba el flujo."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("SMTP caído")


@pytest.fixture(autouse=True)
def _email_settings(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "no-reply@cmm.uchile.cl"
    settings.TICKET_NOTIFICATION_EMAIL = "sistemas@cmm.uchile.cl"
    settings.FRONTEND_URL = "http://localhost:5173"
    mail.outbox = []


def _event(**overrides):
    defaults = dict(
        ticket_id=42, code="TCK-ABC123", requester_id=7,
        title="Impresora no funciona", category="HARDWARE",
        priority="BAJA", requester_username="jperez",
    )
    defaults.update(overrides)
    return TicketCreated(**defaults)


class TestTicketCreatedEmail:
    def test_sends_email_to_sistemas_regardless_of_priority(self):
        for priority in ("BAJA", "MEDIA", "ALTA", "CRITICA"):
            mail.outbox.clear()
            TicketNotificationObserver().handle(_event(priority=priority))

            assert len(mail.outbox) == 1
            sent = mail.outbox[0]
            assert sent.to == ["sistemas@cmm.uchile.cl"]
            assert priority in sent.body

    def test_email_contains_ticket_details_and_link(self):
        TicketNotificationObserver().handle(_event())

        sent = mail.outbox[-1]
        assert "TCK-ABC123" in sent.subject
        assert "Impresora no funciona" in sent.subject
        assert "HARDWARE" in sent.body
        assert "jperez" in sent.body
        assert "http://localhost:5173/tickets/42" in sent.body
        assert sent.from_email == "no-reply@cmm.uchile.cl"

    def test_email_failure_does_not_raise(self, settings):
        settings.EMAIL_BACKEND = "tickets.tests.test_notification_observer._BrokenEmailBackend"
        # No debe propagar la excepción — un correo caído no puede
        # tumbar el flujo de creación de tickets.
        TicketNotificationObserver().handle(_event())

    def test_other_events_do_not_send_ticket_created_email(self):
        from tickets.events import TicketCommented

        TicketNotificationObserver().handle(TicketCommented(ticket_id=1, author_id=1))
        assert len(mail.outbox) == 0
