"""Dashboard ejecutivo de Inventario: KPIs agregados para el rol
Administrador. Mismo enfoque que tickets/services/dashboard_service.py
— capa de solo lectura sobre Django ORM aggregation (Count, Sum,
Case/When), sin Repository Pattern porque no retorna un objeto de
dominio único sino un reporte agregado."""
from __future__ import annotations

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from inventory.models import Asset, AssetStatus

_UNAVAILABLE_STATUSES = (AssetStatus.BAJA, AssetStatus.MANTENIMIENTO)


class InventoryDashboardService:
    """Agregaciones de solo lectura sobre Asset. Sin efectos
    secundarios, sin eventos — es un reporte, no una operación de negocio."""

    def get_summary(self) -> dict:
        return {
            "by_status": self._counts_by(Asset.objects.all(), "status"),
            "by_category": self._counts_by(Asset.objects.all(), "category"),
            "total": Asset.objects.count(),
            "available_total": Asset.objects.exclude(status__in=_UNAVAILABLE_STATUSES).count(),
            "unassigned_responsible_total": Asset.objects.filter(
                responsible__isnull=True
            ).exclude(status__in=_UNAVAILABLE_STATUSES).count(),
            "top_locations": self._top_locations(),
            "warranty": self._warranty_summary(),
        }

    @staticmethod
    def _counts_by(queryset, field: str) -> dict:
        rows = queryset.values(field).annotate(count=Count("id")).order_by(field)
        return {row[field]: row["count"] for row in rows}

    @staticmethod
    def _top_locations(limit: int = 5) -> dict:
        """Ubicaciones con más activos (ignora vacías: activo sin
        ubicación asignada no es una 'ubicación' real)."""
        rows = (
            Asset.objects.exclude(location="")
            .values("location")
            .annotate(count=Count("id"))
            .order_by("-count")[:limit]
        )
        return {row["location"]: row["count"] for row in rows}

    @staticmethod
    def _warranty_summary() -> dict:
        """Activos con garantía ya vencida y activos cuya garantía vence
        dentro de la ventana configurada (`INVENTORY_WARRANTY_WARNING_DAYS`).
        Solo cuenta activos con `warranty_until` cargado: no tener el dato
        no es lo mismo que estar vencido."""
        today = timezone.localdate()
        warning_window = today + timezone.timedelta(days=settings.INVENTORY_WARRANTY_WARNING_DAYS)

        with_warranty = Asset.objects.filter(warranty_until__isnull=False)
        expired = with_warranty.filter(warranty_until__lt=today).count()
        expiring_soon = with_warranty.filter(
            warranty_until__gte=today, warranty_until__lte=warning_window
        ).count()

        return {
            "warning_window_days": settings.INVENTORY_WARRANTY_WARNING_DAYS,
            "expired_total": expired,
            "expiring_soon_total": expiring_soon,
            "with_warranty_data_total": with_warranty.count(),
        }
