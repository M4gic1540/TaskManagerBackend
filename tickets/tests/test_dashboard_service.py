"""Tests de DashboardService. A diferencia de TicketService, acá SÍ se
usa la DB real (vía pytest-django) porque el Service hace agregación
ORM (Count/Avg) que no tiene sentido fakear — se estaría testeando una
reimplementación manual de la lógica, no el comportamiento real.

`usuario` es un objeto liviano, no `accounts.models.User`: DashboardService
solo lee `requester_id`/`requester_username` (campos planos, sin FK —
ver core/auth/jwt_claims_authentication.py), así que este test corre
igual bajo el monolito y bajo el servicio de tickets aislado."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from tickets.models import Ticket, TicketCategory, TicketPriority, TicketStatus
from tickets.services.dashboard_service import DashboardService

pytestmark = pytest.mark.django_db


@pytest.fixture
def usuario():
    return SimpleNamespace(id=1, username="user1")


class TestDashboardSummary:
    def test_counts_by_status_and_priority(self, usuario):
        Ticket.objects.create(
            title="a", description="d", category=TicketCategory.HARDWARE,
            priority=TicketPriority.ALTA, status=TicketStatus.ABIERTO, requester_id=usuario.id, requester_username=usuario.username,
        )
        Ticket.objects.create(
            title="b", description="d", category=TicketCategory.SOFTWARE,
            priority=TicketPriority.BAJA, status=TicketStatus.ABIERTO, requester_id=usuario.id, requester_username=usuario.username,
        )
        summary = DashboardService().get_summary()

        assert summary["total"] == 2
        assert summary["by_status"]["ABIERTO"] == 2
        assert summary["by_priority"]["ALTA"] == 1
        assert summary["by_priority"]["BAJA"] == 1

    def test_avg_resolution_hours_only_counts_closed(self, usuario):
        now = timezone.now()
        closed = Ticket.objects.create(
            title="closed", description="d", category=TicketCategory.OTRO,
            priority=TicketPriority.MEDIA, status=TicketStatus.CERRADO, requester_id=usuario.id, requester_username=usuario.username,
        )
        Ticket.objects.filter(pk=closed.pk).update(
            created_at=now - timedelta(hours=10), closed_at=now - timedelta(hours=4)
        )
        Ticket.objects.create(
            title="open", description="d", category=TicketCategory.OTRO,
            priority=TicketPriority.MEDIA, status=TicketStatus.ABIERTO, requester_id=usuario.id, requester_username=usuario.username,
        )

        summary = DashboardService().get_summary()
        assert summary["avg_resolution_hours"]["MEDIA"] == 6.0

    def test_sla_breach_detects_overdue_open_ticket(self, usuario):
        now = timezone.now()
        overdue = Ticket.objects.create(
            title="overdue", description="d", category=TicketCategory.RED,
            priority=TicketPriority.CRITICA, status=TicketStatus.ASIGNADO, requester_id=usuario.id, requester_username=usuario.username,
        )
        # SLA CRITICA = 2h; este ticket lleva 5h abierto
        Ticket.objects.filter(pk=overdue.pk).update(created_at=now - timedelta(hours=5))

        on_time = Ticket.objects.create(
            title="on_time", description="d", category=TicketCategory.RED,
            priority=TicketPriority.CRITICA, status=TicketStatus.ASIGNADO, requester_id=usuario.id, requester_username=usuario.username,
        )
        Ticket.objects.filter(pk=on_time.pk).update(created_at=now - timedelta(hours=1))

        summary = DashboardService().get_summary()
        assert summary["sla"]["breached_by_priority"]["CRITICA"] == 1
        assert summary["sla"]["total_breached"] == 1

    def test_closed_tickets_never_count_as_sla_breach(self, usuario):
        now = timezone.now()
        old_but_closed = Ticket.objects.create(
            title="old_closed", description="d", category=TicketCategory.RED,
            priority=TicketPriority.CRITICA, status=TicketStatus.CERRADO, requester_id=usuario.id, requester_username=usuario.username,
        )
        Ticket.objects.filter(pk=old_but_closed.pk).update(
            created_at=now - timedelta(hours=100), closed_at=now - timedelta(hours=50)
        )

        summary = DashboardService().get_summary()
        assert summary["sla"]["breached_by_priority"]["CRITICA"] == 0
