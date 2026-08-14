"""Tests HTTP (vía APIClient) de las vistas de tickets. Hasta ahora
solo se testeaba la capa de Service directo (test_ticket_service.py,
test_self_assign.py) — esto cubre el ruteo, permisos por rol a nivel
de vista y el contrato de los serializers de entrada/salida."""
import pytest
from rest_framework.test import APIClient

from accounts.enums import Role
from core.auth.jwt_claims_authentication import TokenClaimsUser
from tickets.models import Ticket, TicketCategory, TicketPriority, TicketStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


def _user(user_id, role, *, username=None):
    return TokenClaimsUser(id=user_id, username=username or f"user{user_id}", role=role)


@pytest.fixture
def admin():
    return _user(1, Role.ADMIN)


@pytest.fixture
def tecnico():
    return _user(2, Role.TECNICO)


@pytest.fixture
def usuario():
    return _user(3, Role.USUARIO)


def _create_ticket(*, requester, technician=None, status=TicketStatus.ABIERTO):
    return Ticket.objects.create(
        title="Impresora no imprime",
        description="La impresora del piso 2 no responde.",
        category=TicketCategory.HARDWARE,
        priority=TicketPriority.MEDIA,
        status=status,
        requester_id=requester.id,
        requester_username=requester.username,
        assigned_technician_id=technician.id if technician else None,
        assigned_technician_username=technician.username if technician else "",
    )


class TestTicketListCreate:
    def test_usuario_sees_only_own_tickets(self, api_client, usuario, tecnico):
        _create_ticket(requester=usuario)
        _create_ticket(requester=tecnico)
        api_client.force_authenticate(user=usuario)

        response = api_client.get("/api/v1/tickets/")

        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_admin_sees_all_tickets(self, api_client, admin, usuario, tecnico):
        _create_ticket(requester=usuario)
        _create_ticket(requester=tecnico)
        api_client.force_authenticate(user=admin)

        response = api_client.get("/api/v1/tickets/")

        assert response.data["count"] == 2

    def test_create_ticket_sets_requester_from_authenticated_user(self, api_client, usuario):
        api_client.force_authenticate(user=usuario)

        response = api_client.post(
            "/api/v1/tickets/",
            {"title": "No enciende el PC", "description": "x", "category": TicketCategory.HARDWARE},
            format="json",
        )

        assert response.status_code == 201
        assert response.data["requester"]["id"] == usuario.id


class TestTicketAvailableList:
    def test_tecnico_sees_unassigned_open_tickets(self, api_client, tecnico, usuario):
        _create_ticket(requester=usuario)
        api_client.force_authenticate(user=tecnico)

        response = api_client.get("/api/v1/tickets/available/")

        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_usuario_cannot_see_available_pool(self, api_client, usuario):
        api_client.force_authenticate(user=usuario)
        response = api_client.get("/api/v1/tickets/available/")
        assert response.status_code == 403


class TestTicketDetail:
    def test_requester_can_view_own_ticket(self, api_client, usuario):
        ticket = _create_ticket(requester=usuario)
        api_client.force_authenticate(user=usuario)

        response = api_client.get(f"/api/v1/tickets/{ticket.pk}/")

        assert response.status_code == 200
        assert response.data["code"] == ticket.code

    def test_unrelated_usuario_cannot_view_ticket(self, api_client, usuario):
        other = _user(99, Role.USUARIO, username="otro")
        ticket = _create_ticket(requester=other)
        api_client.force_authenticate(user=usuario)

        response = api_client.get(f"/api/v1/tickets/{ticket.pk}/")

        assert response.status_code == 403


class TestTicketAssign:
    def test_admin_can_assign_technician(self, api_client, admin, usuario, tecnico):
        ticket = _create_ticket(requester=usuario)
        api_client.force_authenticate(user=admin)

        response = api_client.post(
            f"/api/v1/tickets/{ticket.pk}/assign/",
            {"technician_id": tecnico.id, "technician_username": tecnico.username},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == TicketStatus.ASIGNADO

    def test_tecnico_cannot_assign(self, api_client, tecnico, usuario):
        ticket = _create_ticket(requester=usuario)
        api_client.force_authenticate(user=tecnico)

        response = api_client.post(
            f"/api/v1/tickets/{ticket.pk}/assign/",
            {"technician_id": tecnico.id, "technician_username": tecnico.username},
            format="json",
        )

        assert response.status_code == 403


class TestTicketStatusChange:
    def test_assigned_technician_can_change_status(self, api_client, tecnico, usuario):
        ticket = _create_ticket(requester=usuario, technician=tecnico, status=TicketStatus.ASIGNADO)
        api_client.force_authenticate(user=tecnico)

        response = api_client.post(
            f"/api/v1/tickets/{ticket.pk}/status/",
            {"status": TicketStatus.EN_PROGRESO},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == TicketStatus.EN_PROGRESO


class TestTicketClose:
    def test_close_requires_resolution_notes(self, api_client, tecnico, usuario):
        ticket = _create_ticket(requester=usuario, technician=tecnico, status=TicketStatus.RESUELTO)
        api_client.force_authenticate(user=tecnico)

        response = api_client.post(f"/api/v1/tickets/{ticket.pk}/close/", {}, format="json")

        assert response.status_code == 400

    def test_close_with_notes_succeeds(self, api_client, tecnico, usuario):
        ticket = _create_ticket(requester=usuario, technician=tecnico, status=TicketStatus.RESUELTO)
        api_client.force_authenticate(user=tecnico)

        response = api_client.post(
            f"/api/v1/tickets/{ticket.pk}/close/",
            {"resolution_notes": "Se reemplazó el cable de red."},
            format="json",
        )

        assert response.status_code == 200
        assert response.data["status"] == TicketStatus.CERRADO


class TestTicketComments:
    def test_requester_can_add_comment(self, api_client, usuario):
        ticket = _create_ticket(requester=usuario)
        api_client.force_authenticate(user=usuario)

        response = api_client.post(
            f"/api/v1/tickets/{ticket.pk}/comments/", {"body": "¿Alguna novedad?"}, format="json"
        )

        assert response.status_code == 201
        assert response.data["author"]["id"] == usuario.id


class TestTicketTimeLogs:
    def test_technician_can_log_time(self, api_client, tecnico, usuario):
        ticket = _create_ticket(requester=usuario, technician=tecnico, status=TicketStatus.ASIGNADO)
        api_client.force_authenticate(user=tecnico)

        response = api_client.post(
            f"/api/v1/tickets/{ticket.pk}/time-logs/",
            {"minutes_spent": 30, "notes": "Diagnóstico inicial"},
            format="json",
        )

        assert response.status_code == 201
        assert response.data["minutes_spent"] == 30


class TestDashboardSummary:
    def test_admin_can_view_dashboard(self, api_client, admin):
        api_client.force_authenticate(user=admin)
        response = api_client.get("/api/v1/tickets/dashboard/")
        assert response.status_code == 200

    def test_usuario_cannot_view_dashboard(self, api_client, usuario):
        api_client.force_authenticate(user=usuario)
        response = api_client.get("/api/v1/tickets/dashboard/")
        assert response.status_code == 403
