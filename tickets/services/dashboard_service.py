"""Dashboard ejecutivo: KPIs agregados para el rol Administrador.

No usa Repository Pattern clásico (no hay un solo "objeto de dominio"
que retornar) — es una capa de agregación de solo lectura sobre el
mismo modelo Ticket, construida con Django ORM aggregation (Count,
Avg, Case/When) para evitar N+1 queries y traer todo en pocas queries.
"""
from __future__ import annotations

from django.conf import settings
from django.db.models import Avg, Case, Count, DurationField, ExpressionWrapper, F, Q, When
from django.utils import timezone

from tickets.models import Ticket, TicketPriority, TicketStatus

_CLOSED_STATUSES = (TicketStatus.CERRADO, TicketStatus.CANCELADO)


class DashboardService:
    """Agregaciones de solo lectura. Sin efectos secundarios, sin
    eventos — es un reporte, no una operación de negocio."""

    def get_summary(self) -> dict:
        return {
            "by_status": self._counts_by(Ticket.objects.all(), "status"),
            "by_priority": self._counts_by(Ticket.objects.all(), "priority"),
            "by_category": self._counts_by(Ticket.objects.all(), "category"),
            "total": Ticket.objects.count(),
            "open_total": Ticket.objects.exclude(status__in=_CLOSED_STATUSES).count(),
            "avg_resolution_hours": self._avg_resolution_hours(),
            "sla": self._sla_breach_summary(),
        }

    @staticmethod
    def _counts_by(queryset, field: str) -> dict:
        rows = queryset.values(field).annotate(count=Count("id")).order_by(field)
        return {row[field]: row["count"] for row in rows}

    @staticmethod
    def _avg_resolution_hours() -> dict:
        """Tiempo promedio entre creación y cierre, para tickets ya
        cerrados, desglosado por prioridad."""
        duration_expr = ExpressionWrapper(
            F("closed_at") - F("created_at"), output_field=DurationField()
        )
        rows = (
            Ticket.objects.filter(status=TicketStatus.CERRADO, closed_at__isnull=False)
            .annotate(resolution_time=duration_expr)
            .values("priority")
            .annotate(avg_duration=Avg("resolution_time"))
        )
        result = {}
        for row in rows:
            avg: timezone.timedelta | None = row["avg_duration"]
            result[row["priority"]] = round(avg.total_seconds() / 3600, 1) if avg else None
        return result

    @staticmethod
    def _sla_breach_summary() -> dict:
        """Tickets vencidos por prioridad: abiertos (no cerrados) cuyo
        tiempo transcurrido desde creación supera el SLA configurado
        (`settings.TICKET_SLA_HOURS`). Cierre a tiempo no cuenta como
        vencido aunque haya tardado, porque el SLA mide "sigue abierto
        más allá del límite", no el tiempo de resolución en sí."""
        now = timezone.now()
        sla_hours = settings.TICKET_SLA_HOURS

        breaches = {}
        for priority, hours in sla_hours.items():
            deadline = now - timezone.timedelta(hours=hours)
            breaches[priority] = Ticket.objects.filter(
                priority=priority,
                created_at__lt=deadline,
            ).exclude(status__in=_CLOSED_STATUSES).count()

        return {
            "sla_hours_config": sla_hours,
            "breached_by_priority": breaches,
            "total_breached": sum(breaches.values()),
        }
