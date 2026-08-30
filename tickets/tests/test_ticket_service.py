"""Tests de TicketService usando un FakeRepository en memoria.
Demuestra Dependency Injection real: el Service no sabe si habla con
Django ORM o con un dict en memoria (Dependency Inversion Principle)."""
from types import SimpleNamespace

import pytest

from core.events.base import EventBus
from core.exceptions import InvalidStateTransitionError, PermissionDeniedError, ValidationError
from tickets.models import TicketStatus
from tickets.services.ticket_service import EXTERNAL_REQUESTER_ID, TicketService


class FakeTicketRepository:
    """Doble de test: implementa el mismo contrato que TicketRepository
    sin tocar la base de datos."""

    def __init__(self):
        self._store = {}
        self._comments = {}
        self._next_id = 1
        self._next_comment_id = 1

    def create(self, **fields):
        defaults = dict(
            id=self._next_id, status=TicketStatus.ABIERTO,
            code=f"TCK-TEST{self._next_id:04d}",
            assigned_technician_id=None, assigned_technician_username="",
            requester_email="", external_message_id=None,
        )
        defaults.update(fields)
        ticket = SimpleNamespace(**defaults)
        self._store[ticket.id] = ticket
        self._next_id += 1
        return ticket

    def get_by_id(self, entity_id):
        return self._store[entity_id]

    def get_by_code(self, code):
        return next((t for t in self._store.values() if t.code == code), None)

    def get_by_external_message_id(self, message_id):
        return next(
            (t for t in self._store.values() if t.external_message_id == message_id), None
        )

    def get_comment_by_external_message_id(self, message_id):
        if message_id is None:
            return None
        return next(
            (c for c in self._comments.values() if c.external_message_id == message_id), None
        )

    def update(self, entity, **fields):
        for k, v in fields.items():
            setattr(entity, k, v)
        return entity

    def add_comment(self, ticket, author, body, is_internal=False, external_message_id=None):
        comment = SimpleNamespace(
            id=self._next_comment_id, ticket=ticket, author_id=author.id,
            author_username=author.username, body=body, is_internal=is_internal,
            external_message_id=external_message_id,
        )
        self._comments[comment.id] = comment
        self._next_comment_id += 1
        return comment

    def add_time_log(self, ticket, technician, minutes_spent, notes=""):
        return SimpleNamespace(
            ticket=ticket,
            technician_id=technician.id,
            technician_username=technician.username,
            minutes_spent=minutes_spent,
            notes=notes,
        )


@pytest.fixture(autouse=True)
def _reset_event_bus():
    EventBus.reset()
    yield
    EventBus.reset()


@pytest.fixture
def service():
    return TicketService(repository=FakeTicketRepository())


pytestmark = pytest.mark.django_db  # atomic() de Service exige conexión abierta


def _user(role, user_id=1):
    return SimpleNamespace(id=user_id, username=f"user{user_id}", role=role, is_superuser=False)


class TestTicketCreation:
    def test_creates_ticket(self, service):
        requester = _user("USUARIO")
        ticket = service.create_ticket(
            title="Sin internet", description="No hay conexión en sala 3",
            category="RED", requester=requester,
        )
        assert ticket.category == "RED"
        assert ticket.status == TicketStatus.ABIERTO

    def test_rejects_empty_title(self, service):
        requester = _user("USUARIO")
        with pytest.raises(ValidationError):
            service.create_ticket(title="", description="desc", category="OTRO", requester=requester)


class TestAssignment:
    def test_only_admin_can_assign(self, service):
        requester = _user("USUARIO", 1)
        technician = _user("TECNICO", 2)
        ticket = service.create_ticket(
            title="Falla impresora", description="No imprime", category="HARDWARE", requester=requester,
        )
        actor_usuario = _user("USUARIO", 1)
        with pytest.raises(PermissionDeniedError):
            service.assign_technician(
                ticket_id=ticket.id,
                technician_id=technician.id,
                technician_username=technician.username,
                actor=actor_usuario,
            )

    def test_admin_assigns_successfully(self, service):
        requester = _user("USUARIO", 1)
        technician = _user("TECNICO", 2)
        admin = _user("ADMIN", 3)
        ticket = service.create_ticket(
            title="Falla impresora", description="No imprime", category="HARDWARE", requester=requester,
        )
        updated = service.assign_technician(
            ticket_id=ticket.id,
            technician_id=technician.id,
            technician_username=technician.username,
            actor=admin,
        )
        assert updated.status == TicketStatus.ASIGNADO
        assert updated.assigned_technician_id == technician.id
        assert updated.assigned_technician_username == technician.username


class TestStatusTransitionStrategy:
    def test_cannot_skip_states(self, service):
        requester = _user("USUARIO", 1)
        admin = _user("ADMIN", 3)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", requester=requester,
        )
        with pytest.raises(InvalidStateTransitionError):
            # ABIERTO -> RESUELTO no está permitido (debe pasar por ASIGNADO/EN_PROGRESO)
            service.change_status(ticket_id=ticket.id, new_status=TicketStatus.RESUELTO, actor=admin)

    def test_terminal_state_has_no_further_transitions(self, service):
        from tickets.strategies.status_transitions import TransitionStrategyFactory
        strategy = TransitionStrategyFactory.get_strategy(TicketStatus.CERRADO)
        assert strategy.allowed_targets == set()


class TestCloseRequiresResolutionNotes:
    def test_close_without_notes_fails(self, service):
        requester = _user("USUARIO", 1)
        technician = _user("TECNICO", 2)
        admin = _user("ADMIN", 3)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", requester=requester,
        )
        service.assign_technician(
            ticket_id=ticket.id,
            technician_id=technician.id,
            technician_username=technician.username,
            actor=admin,
        )
        service.change_status(ticket_id=ticket.id, new_status=TicketStatus.EN_PROGRESO, actor=technician)
        service.change_status(ticket_id=ticket.id, new_status=TicketStatus.RESUELTO, actor=technician)

        with pytest.raises(ValidationError):
            service.close_ticket(ticket_id=ticket.id, resolution_notes="   ", actor=technician)


class TestTimeLogRestrictedToTechnician:
    def test_requester_cannot_log_time(self, service):
        requester = _user("USUARIO", 1)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", requester=requester,
        )
        with pytest.raises(PermissionDeniedError):
            service.log_time(ticket_id=ticket.id, technician=requester, minutes_spent=10)


class TestAIClassification:
    def test_applies_suggested_category(self, service):
        requester = _user("USUARIO", 1)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", requester=requester,
        )
        updated = service.apply_ai_classification(ticket_id=ticket.id, category="RED")
        assert updated.category == "RED"

    def test_rejects_invalid_category(self, service):
        requester = _user("USUARIO", 1)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", requester=requester,
        )
        with pytest.raises(ValidationError):
            service.apply_ai_classification(ticket_id=ticket.id, category="NO_EXISTE")

    def test_rejects_reclassifying_closed_ticket(self, service):
        requester = _user("USUARIO", 1)
        technician = _user("TECNICO", 2)
        admin = _user("ADMIN", 3)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", requester=requester,
        )
        service.assign_technician(
            ticket_id=ticket.id, technician_id=technician.id,
            technician_username=technician.username, actor=admin,
        )
        service.change_status(ticket_id=ticket.id, new_status=TicketStatus.EN_PROGRESO, actor=technician)
        service.change_status(ticket_id=ticket.id, new_status=TicketStatus.RESUELTO, actor=technician)
        service.close_ticket(ticket_id=ticket.id, resolution_notes="listo", actor=technician)

        with pytest.raises(ValidationError):
            service.apply_ai_classification(ticket_id=ticket.id, category="RED")


class TestCreateTicketFromEmail:
    def test_creates_new_ticket_from_unknown_sender(self, service):
        ticket = service.create_ticket_from_email(
            external_message_id="<abc@correo.cmm.uchile.cl>",
            sender_email="pedro.perez@uchile.cl",
            sender_name="Pedro Pérez",
            subject="No me funciona el wifi",
            body="Desde esta mañana no logro conectarme a la red del piso 3.",
        )
        assert ticket.title == "No me funciona el wifi"
        assert ticket.requester_id == EXTERNAL_REQUESTER_ID
        assert ticket.requester_username == "Pedro Pérez"
        assert ticket.requester_email == "pedro.perez@uchile.cl"
        assert ticket.external_message_id == "<abc@correo.cmm.uchile.cl>"

    def test_is_idempotent_on_duplicate_message_id(self, service):
        first = service.create_ticket_from_email(
            external_message_id="<dup@correo.cmm.uchile.cl>",
            sender_email="ana@uchile.cl", sender_name="Ana",
            subject="Problema con el correo", body="No puedo enviar adjuntos.",
        )
        second = service.create_ticket_from_email(
            external_message_id="<dup@correo.cmm.uchile.cl>",
            sender_email="ana@uchile.cl", sender_name="Ana",
            subject="Problema con el correo", body="No puedo enviar adjuntos.",
        )
        assert second.id == first.id

    def test_reply_with_known_ticket_code_becomes_comment_not_new_ticket(self, service):
        requester = _user("USUARIO", 1)
        original = service.create_ticket(
            title="Problema de acceso", description="No puedo entrar al sistema", category="ACCESOS",
            requester=requester, requester_email="pedro.perez@uchile.cl",
        )

        result = service.create_ticket_from_email(
            external_message_id="<reply@correo.cmm.uchile.cl>",
            sender_email="pedro.perez@uchile.cl", sender_name="Pedro Pérez",
            subject=f"Re: [{original.code}] Problema de acceso",
            body="Sigo sin poder entrar, ¿alguna novedad?",
        )
        assert result.id == original.id

    def test_reply_ignores_case_and_whitespace_when_matching_sender(self, service):
        requester = _user("USUARIO", 1)
        original = service.create_ticket(
            title="Problema de acceso", description="No puedo entrar", category="ACCESOS",
            requester=requester, requester_email="Pedro.Perez@uchile.cl",
        )

        result = service.create_ticket_from_email(
            external_message_id="<reply2@correo.cmm.uchile.cl>",
            sender_email=" pedro.perez@uchile.cl ", sender_name="Pedro Pérez",
            subject=f"Re: [{original.code}] Problema de acceso",
            body="Otra respuesta.",
        )
        assert result.id == original.id

    def test_reply_from_different_sender_does_not_attach_to_foreign_ticket(self, service):
        """Regresión de seguridad: conocer el código de un ticket (viaja
        en el asunto de cada respuesta saliente) no debe alcanzar para
        inyectar comentarios en el hilo de otra persona."""
        owner = _user("USUARIO", 1)
        original = service.create_ticket(
            title="Problema de acceso", description="No puedo entrar", category="ACCESOS",
            requester=owner, requester_email="dueño@uchile.cl",
        )

        result = service.create_ticket_from_email(
            external_message_id="<intruso@correo.cmm.uchile.cl>",
            sender_email="cualquiera@gmail.com", sender_name="Cualquiera",
            subject=f"Re: [{original.code}] Problema de acceso",
            body="Ya está resuelto, cierren el ticket.",
        )

        assert result.id != original.id
        assert result.requester_email == "cualquiera@gmail.com"

    def test_reply_is_idempotent_on_duplicate_message_id(self, service):
        """Regresión: reprocesar el mismo correo de respuesta (ej. tras
        un fallo de red entre procesar y marcar \\Seen) no debe
        duplicar el comentario."""
        owner = _user("USUARIO", 1)
        original = service.create_ticket(
            title="Problema de acceso", description="No puedo entrar", category="ACCESOS",
            requester=owner, requester_email="pedro.perez@uchile.cl",
        )

        first = service.create_ticket_from_email(
            external_message_id="<reply-dup@correo.cmm.uchile.cl>",
            sender_email="pedro.perez@uchile.cl", sender_name="Pedro",
            subject=f"Re: [{original.code}] Problema de acceso",
            body="¿Alguna novedad?",
        )
        second = service.create_ticket_from_email(
            external_message_id="<reply-dup@correo.cmm.uchile.cl>",
            sender_email="pedro.perez@uchile.cl", sender_name="Pedro",
            subject=f"Re: [{original.code}] Problema de acceso",
            body="¿Alguna novedad?",
        )

        assert second.id == first.id == original.id

    def test_empty_body_and_subject_get_placeholder_instead_of_failing(self, service):
        """Regresión: un correo sin texto plano legible (HTML-only tras
        el fallback, o vacío) no debe reventar con ValidationError —
        eso dejaba el correo sin marcar \\Seen en el poller y lo
        reprocesaba para siempre."""
        ticket = service.create_ticket_from_email(
            external_message_id="<vacio@correo.cmm.uchile.cl>",
            sender_email="ana@uchile.cl", sender_name="Ana",
            subject="", body="",
        )
        assert ticket.title == "Sin asunto"
        assert ticket.description

    def test_long_subject_and_message_id_are_truncated(self, service):
        """Regresión: SQLite (dev/tests) acepta strings más largos que
        `max_length`, pero Postgres/MySQL (producción) los rechaza —
        truncar en la ingesta evita ese fallo silencioso en prod."""
        ticket = service.create_ticket_from_email(
            external_message_id="<" + "x" * 300 + "@correo.cmm.uchile.cl>",
            sender_email="ana@uchile.cl", sender_name="Ana",
            subject="A" * 500, body="cuerpo",
        )
        assert len(ticket.title) == 200
        assert len(ticket.external_message_id) == 255


class TestAddCommentInternal:
    def test_default_comment_is_not_internal(self, service):
        requester = _user("USUARIO", 1)
        ticket = service.create_ticket(title="t", description="d", category="OTRO", requester=requester)
        comment = service.add_comment(ticket_id=ticket.id, author=requester, body="hola")
        assert comment.is_internal is False

    def test_can_mark_comment_as_internal(self, service):
        requester = _user("USUARIO", 1)
        technician = _user("TECNICO", 2)
        ticket = service.create_ticket(title="t", description="d", category="OTRO", requester=requester)
        comment = service.add_comment(
            ticket_id=ticket.id, author=technician, body="nota interna", is_internal=True,
        )
        assert comment.is_internal is True
