"""Tests de self_assign (Técnico toma ticket sin asignar). Usa DB real
(pytest-django) porque el método usa `select_for_update()` — igual que
DashboardService, fakear el locking testearía una reimplementación
manual, no el comportamiento real.

Los actores (requester/technician) son objetos livianos, no
`accounts.models.User`: TicketService ya no toca ninguna tabla de
usuarios (microservicio con BD separada — ver
core/auth/jwt_claims_authentication.py), así que este test corre igual
bajo el monolito (config.settings) y bajo el servicio de tickets
aislado (config.service_settings.tickets, sin `accounts` instalado)."""
from itertools import count
from types import SimpleNamespace

import pytest

from accounts.enums import Role
from core.events.base import EventBus
from core.exceptions import (
    InvalidStateTransitionError,
    PermissionDeniedError,
    ValidationError,
)
from tickets.models import Ticket, TicketCategory, TicketPriority, TicketStatus
from tickets.services.ticket_service import TicketService

pytestmark = pytest.mark.django_db

_next_id = count(1)


def _actor(role, *, is_active_technician=True):
    n = next(_next_id)
    return SimpleNamespace(
        id=n, username=f"user{n}", role=role, is_active_technician=is_active_technician,
    )


@pytest.fixture(autouse=True)
def _reset_event_bus():
    EventBus.reset()
    yield
    EventBus.reset()


@pytest.fixture
def requester():
    return _actor(Role.USUARIO)


@pytest.fixture
def technician():
    return _actor(Role.TECNICO)


@pytest.fixture
def unassigned_ticket(requester):
    return Ticket.objects.create(
        title="Ticket sin asignar", description="d", category=TicketCategory.HARDWARE,
        priority=TicketPriority.MEDIA, status=TicketStatus.ABIERTO,
        requester_id=requester.id, requester_username=requester.username,
    )


class TestSelfAssign:
    def test_technician_takes_unassigned_ticket(self, technician, unassigned_ticket):
        updated = TicketService().self_assign(ticket_id=unassigned_ticket.id, technician=technician)
        assert updated.status == TicketStatus.ASIGNADO
        assert updated.assigned_technician_id == technician.id

    def test_non_technician_cannot_take_ticket(self, requester, unassigned_ticket):
        with pytest.raises(PermissionDeniedError):
            TicketService().self_assign(ticket_id=unassigned_ticket.id, technician=requester)

    def test_deactivated_technician_cannot_take_ticket(self, technician, unassigned_ticket):
        technician.is_active_technician = False
        with pytest.raises(PermissionDeniedError):
            TicketService().self_assign(ticket_id=unassigned_ticket.id, technician=technician)

    def test_cannot_take_already_assigned_ticket(self, technician, unassigned_ticket):
        other_tech = _actor(Role.TECNICO)
        TicketService().self_assign(ticket_id=unassigned_ticket.id, technician=other_tech)

        with pytest.raises(ValidationError):
            TicketService().self_assign(ticket_id=unassigned_ticket.id, technician=technician)

    def test_cannot_take_ticket_not_in_abierto_status(self, technician, unassigned_ticket):
        unassigned_ticket.status = TicketStatus.CANCELADO
        unassigned_ticket.save(update_fields=["status"])

        with pytest.raises(InvalidStateTransitionError):
            TicketService().self_assign(ticket_id=unassigned_ticket.id, technician=technician)
