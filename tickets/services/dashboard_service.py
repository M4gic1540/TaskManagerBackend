"""Dashboard ejecutivo: KPIs agregados para el rol Administrador.

No usa Repository Pattern clásico (no hay un solo "objeto de dominio"
que retornar) — es una capa de agregación de solo lectura sobre el
mismo modelo Ticket, construida con Django ORM aggregation (Count,
Avg) para evitar N+1 queries y traer todo en pocas queries.
"""
from __future__ import annotations

from django.conf import settings
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F
from django.utils import timezone

from tickets.models import Ticket, TicketStatus

_CLOSED_STATUSES = (TicketStatus.CERRADO, TicketStatus.CANCELADO)


class DashboardService:
    """Agregaciones de solo lectura. Sin efectos secundarios, sin
    eventos — es un reporte, no una operación de negocio."""

    def get_summary(self) -> dict:
        return {
            "by_status": self._counts_by(Ticket.objects.all(), "status"),
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
    def _avg_resolution_hours() -> float | None:
        """Tiempo promedio entre creación y cierre, para tickets ya
        cerrados (SLA plano — ver settings.TICKET_SLA_HOURS)."""
        duration_expr = ExpressionWrapper(
            F("closed_at") - F("created_at"), output_field=DurationField()
        )
        result = (
            Ticket.objects.filter(status=TicketStatus.CERRADO, closed_at__isnull=False)
            .annotate(resolution_time=duration_expr)
            .aggregate(avg_duration=Avg("resolution_time"))
        )
        avg: timezone.timedelta | None = result["avg_duration"]
        return round(avg.total_seconds() / 3600, 1) if avg else None

    @staticmethod
    def _sla_breach_summary() -> dict:
        """Tickets vencidos: abiertos (no cerrados) cuyo tiempo
        transcurrido desde creación supera `settings.TICKET_SLA_HOURS`
        (umbral plano, ya no por prioridad). Cierre a tiempo no cuenta
        como vencido aunque haya tardado, porque el SLA mide "sigue
        abierto más allá del límite", no el tiempo de resolución en sí."""
        sla_hours = settings.TICKET_SLA_HOURS
        deadline = timezone.now() - timezone.timedelta(hours=sla_hours)
        total_breached = Ticket.objects.filter(
            created_at__lt=deadline,
        ).exclude(status__in=_CLOSED_STATUSES).count()

        return {"sla_hours": sla_hours, "total_breached": total_breached}
