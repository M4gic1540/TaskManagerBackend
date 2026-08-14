"""Tests de /healthz/ (liveness) y /readyz/ (readiness), montados en
config/urls.py con los checks del monolito (BD default + breaker GLPI)."""
import pytest
from rest_framework.test import APIClient

from core.health import registry

pytestmark = pytest.mark.django_db


class TestLiveness:
    def test_always_returns_200(self):
        response = APIClient().get("/healthz/")
        assert response.status_code == 200
        assert response.data["status"] == "alive"


class TestReadiness:
    def test_ok_when_all_checks_healthy(self):
        response = APIClient().get("/readyz/")
        assert response.status_code == 200
        assert response.data["status"] == "ready"
        assert response.data["checks"]["database"]["ok"] is True
        assert response.data["checks"]["glpi_circuit_breaker"]["ok"] is True

    def test_503_when_a_check_fails(self, monkeypatch):
        monkeypatch.setitem(
            registry._REGISTRY, "database", lambda: {"ok": False, "detail": "boom"}
        )
        response = APIClient().get("/readyz/")
        assert response.status_code == 503
        assert response.data["status"] == "not_ready"
        assert response.data["checks"]["database"]["ok"] is False

    def test_503_when_a_check_raises(self, monkeypatch):
        def _raises():
            raise RuntimeError("dependencia inesperada caída")

        monkeypatch.setitem(registry._REGISTRY, "database", _raises)
        response = APIClient().get("/readyz/")
        assert response.status_code == 503
        assert "dependencia inesperada caída" in response.data["checks"]["database"]["detail"]
