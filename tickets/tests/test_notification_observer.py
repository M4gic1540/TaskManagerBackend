"""Tests de la clasificación automática local y del correo de
respuesta saliente (tickets/observers.py). Todo corre vía
fire_and_forget, que cae a ejecución sync cuando no hay loop ASGI
corriendo (caso de los tests) — así que handle() ya aplica la
clasificación / deja el correo en mail.outbox sin mockear nada del
bridge async.

La clasificación se testea mockeando TicketClassifier/TicketService
(no el modelo entrenado real ni la BD): son tests unitarios del
Observer, no de scikit-learn ni del Service."""
import pytest
from django.core import mail

from tickets import observers
from tickets.events import TicketCommented, TicketCreated
from tickets.ml.classifier import ClassificationResult
from tickets.observers import TicketNotificationObserver


class _BrokenEmailBackend:
    """EMAIL_BACKEND que siempre revienta al instanciarse — simula un
    SMTP caído para probar que un correo fallido no tumba el flujo."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError("SMTP caído")


class _StubClassifier:
    """Reemplaza TicketClassifier.get() en los tests: `predict()`
    devuelve un ClassificationResult fijo (o None, o revienta) sin
    tocar ningún modelo entrenado real."""

    def __init__(self, result=None, *, raises=False):
        self._result = result
        self._raises = raises

    def get(self):
        return self

    def predict(self, title, description):
        if self._raises:
            raise RuntimeError("modelo corrupto")
        return self._result


def _recording_ticket_service(calls: list):
    """Reemplaza TicketService en los tests: en vez de tocar la BD,
    registra los kwargs con los que se llamó apply_ai_classification."""

    class _Service:
        def apply_ai_classification(self, **kwargs):
            calls.append(kwargs)

    return _Service


@pytest.fixture(autouse=True)
def _email_settings(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "no-reply@cmm.uchile.cl"
    settings.FRONTEND_URL = "http://localhost:5173"
    settings.TICKET_AI_CONFIDENCE_THRESHOLD = 0.5
    mail.outbox = []


@pytest.fixture(autouse=True)
def _no_ml_classification_by_default(monkeypatch):
    """Sin esto, cada test de correo de respuesta dispararía además la
    clasificación (modelo real sin entrenar en el entorno de test ->
    predict() devolvería None de todos modos, pero mejor no depender
    de eso)."""
    monkeypatch.setattr(observers, "TicketClassifier", _StubClassifier(result=None))


def _created_event(**overrides):
    defaults = dict(
        ticket_id=42, code="TCK-ABC123", requester_id=7,
        title="Impresora no funciona", description="No enciende desde ayer",
        category="HARDWARE", requester_username="jperez",
    )
    defaults.update(overrides)
    return TicketCreated(**defaults)


def _commented_event(**overrides):
    defaults = dict(
        ticket_id=42, author_id=2, is_internal=False, author_is_external=False,
        body="Se revisó el equipo y quedó funcionando.",
        ticket_code="TCK-ABC123", ticket_title="Impresora no funciona",
        requester_email="jperez@cmm.uchile.cl",
    )
    defaults.update(overrides)
    return TicketCommented(**defaults)


class TestMLClassificationOnTicketCreated:
    def test_applies_category_above_threshold(self, monkeypatch):
        result = ClassificationResult(category="RED", category_confidence=0.9)
        monkeypatch.setattr(observers, "TicketClassifier", _StubClassifier(result))
        calls: list = []
        monkeypatch.setattr(observers, "TicketService", _recording_ticket_service(calls))

        TicketNotificationObserver().handle(_created_event())

        assert calls == [{"ticket_id": 42, "category": "RED"}]

    def test_skips_when_below_confidence_threshold(self, monkeypatch):
        result = ClassificationResult(category="RED", category_confidence=0.2)
        monkeypatch.setattr(observers, "TicketClassifier", _StubClassifier(result))
        calls: list = []
        monkeypatch.setattr(observers, "TicketService", _recording_ticket_service(calls))

        TicketNotificationObserver().handle(_created_event())

        assert calls == []

    def test_does_nothing_when_model_not_trained_yet(self, monkeypatch):
        monkeypatch.setattr(observers, "TicketClassifier", _StubClassifier(result=None))
        calls: list = []
        monkeypatch.setattr(observers, "TicketService", _recording_ticket_service(calls))

        TicketNotificationObserver().handle(_created_event())

        assert calls == []

    def test_classifier_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(observers, "TicketClassifier", _StubClassifier(raises=True))
        calls: list = []
        monkeypatch.setattr(observers, "TicketService", _recording_ticket_service(calls))

        # No debe propagar la excepción — el ticket ya se creó igual.
        TicketNotificationObserver().handle(_created_event())

        assert calls == []


class TestCommentReplyEmail:
    """Hilo de conversación por correo (ver tickets/services/
    ticket_service.py::add_comment + create_ticket_from_email)."""

    def test_staff_reply_sends_email_to_requester(self):
        TicketNotificationObserver().handle(_commented_event())

        assert len(mail.outbox) == 1
        sent = mail.outbox[0]
        assert sent.to == ["jperez@cmm.uchile.cl"]
        assert "TCK-ABC123" in sent.subject
        assert "Impresora no funciona" in sent.subject
        assert sent.body == "Se revisó el equipo y quedó funcionando."
        assert sent.from_email == "no-reply@cmm.uchile.cl"

    def test_internal_note_never_sends_email(self):
        TicketNotificationObserver().handle(_commented_event(is_internal=True))
        assert len(mail.outbox) == 0

    def test_reply_from_external_requester_does_not_echo_back(self):
        """Si la 'respuesta' vino del propio correo del solicitante
        (detectada por el poller entrante), no hay que reenviársela."""
        TicketNotificationObserver().handle(_commented_event(author_is_external=True))
        assert len(mail.outbox) == 0

    def test_no_requester_email_means_no_email_sent(self):
        TicketNotificationObserver().handle(_commented_event(requester_email=""))
        assert len(mail.outbox) == 0

    def test_email_failure_does_not_raise(self, settings):
        settings.EMAIL_BACKEND = "tickets.tests.test_notification_observer._BrokenEmailBackend"
        # No debe propagar la excepción — un correo caído no puede
        # tumbar el flujo de creación del comentario.
        TicketNotificationObserver().handle(_commented_event())
