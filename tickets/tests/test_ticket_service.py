"""Tests de TicketService usando un FakeRepository en memoria.
Demuestra Dependency Injection real: el Service no sabe si habla con
Django ORM o con un dict en memoria (Dependency Inversion Principle)."""
from types import SimpleNamespace

import pytest

from core.events.base import EventBus
from core.exceptions import InvalidStateTransitionError, PermissionDeniedError, ValidationError
from tickets.models import TicketStatus
from tickets.services.ticket_service import TicketService


class FakeTicketRepository:
    """Doble de test: implementa el mismo contrato que TicketRepository
    sin tocar la base de datos."""

    def __init__(self):
        self._store = {}
        self._next_id = 1

    def create(self, **fields):
        ticket = SimpleNamespace(
            id=self._next_id, status=TicketStatus.ABIERTO,
            code=f"TCK-TEST{self._next_id:04d}", assigned_technician=None, **fields,
        )
        self._store[ticket.id] = ticket
        self._next_id += 1
        return ticket

    def get_by_id(self, entity_id):
        return self._store[entity_id]

    def update(self, entity, **fields):
        for k, v in fields.items():
            setattr(entity, k, v)
        return entity

    def add_comment(self, ticket, author, body):
        return SimpleNamespace(ticket=ticket, author=author, body=body)

    def add_time_log(self, ticket, technician, minutes_spent, notes=""):
        return SimpleNamespace(
            ticket=ticket, technician=technician, minutes_spent=minutes_spent, notes=notes
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
    return SimpleNamespace(id=user_id, role=role, is_superuser=False)


class TestTicketCreation:
    def test_creates_ticket_with_inferred_priority(self, service):
        requester = _user("USUARIO")
        ticket = service.create_ticket(
            title="Sin internet", description="No hay conexión en sala 3",
            category="RED", priority=None, requester=requester,
        )
        assert ticket.priority == "ALTA"  # RED infiere ALTA por factory
        assert ticket.status == TicketStatus.ABIERTO

    def test_rejects_empty_title(self, service):
        requester = _user("USUARIO")
        with pytest.raises(ValidationError):
            service.create_ticket(
                title="", description="desc", category="OTRO",
                priority=None, requester=requester,
            )


class TestAssignment:
    def test_only_admin_can_assign(self, service):
        requester = _user("USUARIO", 1)
        technician = _user("TECNICO", 2)
        ticket = service.create_ticket(
            title="Falla impresora", description="No imprime", category="HARDWARE",
            priority=None, requester=requester,
        )
        actor_usuario = _user("USUARIO", 1)
        with pytest.raises(PermissionDeniedError):
            service.assign_technician(ticket_id=ticket.id, technician=technician, actor=actor_usuario)

    def test_admin_assigns_successfully(self, service):
        requester = _user("USUARIO", 1)
        technician = _user("TECNICO", 2)
        admin = _user("ADMIN", 3)
        ticket = service.create_ticket(
            title="Falla impresora", description="No imprime", category="HARDWARE",
            priority=None, requester=requester,
        )
        updated = service.assign_technician(ticket_id=ticket.id, technician=technician, actor=admin)
        assert updated.status == TicketStatus.ASIGNADO
        assert updated.assigned_technician == technician


class TestStatusTransitionStrategy:
    def test_cannot_skip_states(self, service):
        requester = _user("USUARIO", 1)
        admin = _user("ADMIN", 3)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", priority=None, requester=requester,
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
            title="t", description="d", category="OTRO", priority=None, requester=requester,
        )
        service.assign_technician(ticket_id=ticket.id, technician=technician, actor=admin)
        service.change_status(ticket_id=ticket.id, new_status=TicketStatus.EN_PROGRESO, actor=technician)
        service.change_status(ticket_id=ticket.id, new_status=TicketStatus.RESUELTO, actor=technician)

        with pytest.raises(ValidationError):
            service.close_ticket(ticket_id=ticket.id, resolution_notes="   ", actor=technician)


class TestTimeLogRestrictedToTechnician:
    def test_requester_cannot_log_time(self, service):
        requester = _user("USUARIO", 1)
        ticket = service.create_ticket(
            title="t", description="d", category="OTRO", priority=None, requester=requester,
        )
        with pytest.raises(PermissionDeniedError):
            service.log_time(ticket_id=ticket.id, technician=requester, minutes_spent=10)
