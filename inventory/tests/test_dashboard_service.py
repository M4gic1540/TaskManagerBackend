"""Tests de InventoryDashboardService. Igual que tickets/tests/test_dashboard_service.py:
usa la DB real (pytest-django) porque el Service hace agregación ORM
(Count) que no tiene sentido fakear."""
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from accounts.models import Role, User
from inventory.models import Asset, AssetCategory, AssetStatus
from inventory.services.dashboard_service import InventoryDashboardService

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return User.objects.create_user(username="admin1", password="x", role=Role.ADMIN)


class TestInventoryDashboardSummary:
    def test_counts_by_status_and_category(self, admin):
        Asset.objects.create(
            name="Notebook 1", category=AssetCategory.LAPTOP,
            status=AssetStatus.ACTIVO, created_by=admin,
        )
        Asset.objects.create(
            name="Monitor 1", category=AssetCategory.MONITOR,
            status=AssetStatus.BODEGA, created_by=admin,
        )
        summary = InventoryDashboardService().get_summary()

        assert summary["total"] == 2
        assert summary["by_status"]["ACTIVO"] == 1
        assert summary["by_status"]["BODEGA"] == 1
        assert summary["by_category"]["LAPTOP"] == 1
        assert summary["by_category"]["MONITOR"] == 1

    def test_available_total_excludes_baja_and_mantenimiento(self, admin):
        Asset.objects.create(name="ok", status=AssetStatus.ACTIVO, created_by=admin)
        Asset.objects.create(name="baja", status=AssetStatus.BAJA, created_by=admin)
        Asset.objects.create(name="mant", status=AssetStatus.MANTENIMIENTO, created_by=admin)

        summary = InventoryDashboardService().get_summary()
        assert summary["total"] == 3
        assert summary["available_total"] == 1

    def test_unassigned_responsible_ignores_unavailable_assets(self, admin):
        Asset.objects.create(name="sin resp activo", status=AssetStatus.ACTIVO, created_by=admin)
        Asset.objects.create(name="sin resp baja", status=AssetStatus.BAJA, created_by=admin)
        Asset.objects.create(
            name="con resp", status=AssetStatus.ACTIVO, responsible=admin, created_by=admin
        )

        summary = InventoryDashboardService().get_summary()
        # Solo cuenta el "sin resp activo": el de baja está excluido, el
        # tercero sí tiene responsable.
        assert summary["unassigned_responsible_total"] == 1

    def test_top_locations_ignores_blank_location(self, admin):
        Asset.objects.create(name="a", location="Oficina 602", created_by=admin)
        Asset.objects.create(name="b", location="Oficina 602", created_by=admin)
        Asset.objects.create(name="c", location="", created_by=admin)

        summary = InventoryDashboardService().get_summary()
        assert summary["top_locations"]["Oficina 602"] == 2
        assert "" not in summary["top_locations"]

    @override_settings(INVENTORY_WARRANTY_WARNING_DAYS=30)
    def test_warranty_summary_classifies_expired_and_expiring_soon(self, admin):
        today = timezone.localdate()
        Asset.objects.create(
            name="vencida", warranty_until=today - timedelta(days=5), created_by=admin
        )
        Asset.objects.create(
            name="por vencer", warranty_until=today + timedelta(days=10), created_by=admin
        )
        Asset.objects.create(
            name="lejana", warranty_until=today + timedelta(days=200), created_by=admin
        )
        Asset.objects.create(name="sin dato", warranty_until=None, created_by=admin)

        summary = InventoryDashboardService().get_summary()
        warranty = summary["warranty"]

        assert warranty["expired_total"] == 1
        assert warranty["expiring_soon_total"] == 1
        assert warranty["with_warranty_data_total"] == 3
        assert warranty["warning_window_days"] == 30
