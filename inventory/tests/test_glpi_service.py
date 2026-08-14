"""Tests de GLPIInventoryService contra un schema GLPI mínimo montado en
la DB sqlite de test (alias 'glpi' apunta a la misma sqlite de test que
'default', ver IS_TESTING en config/settings.py). No usaba ningún test
hasta ahora: list_assets/get_dashboard_summary/generate_qr_*
construyen SQL cruzando las 6 tablas de TABLE_MAPPING, así que se
verifica acá tanto el resultado como que _safe_table_identifier()
rechace nombres fuera de la whitelist."""
import pytest
from django.core.cache import cache
from django.db import connections

from inventory.services.glpi_service import GLPIInventoryService, _safe_table_identifier

pytestmark = pytest.mark.django_db(databases=["default", "glpi"])

_ASSET_COLUMNS = """
    id INTEGER PRIMARY KEY, name TEXT, serial TEXT, otherserial TEXT,
    comment TEXT, contact TEXT, manufacturers_id INTEGER, states_id INTEGER,
    locations_id INTEGER, date_mod TEXT, is_deleted INTEGER
"""


@pytest.fixture(autouse=True)
def _clear_glpi_cache():
    """El cache-aside de GLPIInventoryService usa el cache por defecto de
    Django, que persiste entre tests dentro del mismo proceso de pytest."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def glpi_schema():
    """Crea el schema mínimo de GLPI (todas las tablas de TABLE_MAPPING +
    sus joins) en la sqlite de test, con un único PC de prueba."""
    connection = connections["glpi"]
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TABLE IF NOT EXISTS glpi_computers ({_ASSET_COLUMNS})")
        cursor.execute(f"CREATE TABLE IF NOT EXISTS glpi_monitors ({_ASSET_COLUMNS})")
        cursor.execute(f"CREATE TABLE IF NOT EXISTS glpi_printers ({_ASSET_COLUMNS})")
        cursor.execute(f"CREATE TABLE IF NOT EXISTS glpi_networkequipments ({_ASSET_COLUMNS})")
        cursor.execute(f"CREATE TABLE IF NOT EXISTS glpi_peripherals ({_ASSET_COLUMNS})")
        cursor.execute(f"CREATE TABLE IF NOT EXISTS glpi_phones ({_ASSET_COLUMNS})")
        cursor.execute("CREATE TABLE IF NOT EXISTS glpi_manufacturers (id INTEGER PRIMARY KEY, name TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS glpi_states (id INTEGER PRIMARY KEY, name TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS glpi_locations (id INTEGER PRIMARY KEY, completename TEXT)")
        cursor.execute("DELETE FROM glpi_computers")
        cursor.execute(
            "INSERT INTO glpi_computers (id, name, serial, otherserial, is_deleted) "
            "VALUES (1, 'PC-1', 'SN123', 'INV-001', 0)"
        )
    yield
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM glpi_computers")


class TestSafeTableIdentifier:
    def test_rejects_name_outside_whitelist(self):
        connection = connections["glpi"]
        with pytest.raises(ValueError):
            _safe_table_identifier(connection, "glpi_computers; DROP TABLE users;--")

    def test_accepts_known_table(self):
        connection = connections["glpi"]
        assert "glpi_computers" in _safe_table_identifier(connection, "glpi_computers")


class TestListAssets:
    def test_returns_matching_asset_with_inventory_number(self, glpi_schema):
        results = GLPIInventoryService().list_assets(search="sn123")
        assert len(results) == 1
        assert results[0]["serial"] == "SN123"
        assert results[0]["inventory_number"] == "INV-001"
        assert results[0]["category"] == "PC"

    def test_category_filter_excludes_other_categories(self, glpi_schema):
        results = GLPIInventoryService().list_assets(category="MONITOR")
        assert results == []

    def test_limit_is_clamped_and_used_as_bind_param(self, glpi_schema):
        results = GLPIInventoryService().list_assets(limit=1)
        assert len(results) == 1


class TestDashboardSummary:
    def test_aggregates_counts_across_tables(self, glpi_schema):
        summary = GLPIInventoryService().get_dashboard_summary()
        assert summary["total"] == 1
        assert summary["by_category"]["PC"] == 1
        assert summary["by_category"]["MONITOR"] == 0


class TestQRGeneration:
    def test_generate_qr_images_zip_includes_matched_asset(self, glpi_schema):
        content = GLPIInventoryService().generate_qr_images_zip(asset_ids=["pc_1"])
        assert content[:2] == b"PK"


class TestCaching:
    """Cache-aside sobre list_assets/get_dashboard_summary: la segunda
    llamada con los mismos parámetros no debe volver a golpear la BD."""

    def _spy(self, monkeypatch, service, method_name):
        original = getattr(service, method_name)
        calls = []

        def wrapper(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(service, method_name, wrapper)
        return calls

    def test_list_assets_second_call_hits_cache(self, glpi_schema, monkeypatch):
        service = GLPIInventoryService()
        calls = self._spy(monkeypatch, service, "_list_assets_impl")

        first = service.list_assets(search="sn123")
        second = service.list_assets(search="sn123")

        assert first == second
        assert len(calls) == 1

    def test_list_assets_different_params_are_not_shared(self, glpi_schema, monkeypatch):
        service = GLPIInventoryService()
        calls = self._spy(monkeypatch, service, "_list_assets_impl")

        service.list_assets(category="PC")
        service.list_assets(category="MONITOR")

        assert len(calls) == 2

    def test_dashboard_summary_second_call_hits_cache(self, glpi_schema, monkeypatch):
        service = GLPIInventoryService()
        calls = self._spy(monkeypatch, service, "_get_dashboard_summary_impl")

        first = service.get_dashboard_summary()
        second = service.get_dashboard_summary()

        assert first == second
        assert len(calls) == 1

    def test_ttl_zero_disables_caching(self, glpi_schema, monkeypatch, settings):
        settings.GLPI_CACHE_TTL_SECONDS = 0
        service = GLPIInventoryService()
        calls = self._spy(monkeypatch, service, "_get_dashboard_summary_impl")

        service.get_dashboard_summary()
        service.get_dashboard_summary()

        assert len(calls) == 2

    def test_open_breaker_is_not_masked_by_a_cache_hit_from_a_different_key(
        self, glpi_schema, monkeypatch
    ):
        """Un miss (parámetros nunca antes cacheados) con GLPI caído debe
        seguir propagando el error del circuit breaker, no una respuesta
        vacía silenciosa."""
        from core.resilience.circuit_breaker import GLPIUnavailableError

        service = GLPIInventoryService()

        def _boom(*args, **kwargs):
            raise GLPIUnavailableError()

        monkeypatch.setattr(service, "_get_dashboard_summary_impl", _boom)

        with pytest.raises(GLPIUnavailableError):
            service.get_dashboard_summary()
