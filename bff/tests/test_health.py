"""Tests de /healthz/ y /readyz/ del BFF. Ver
gateway/tests/test_health.py para el porqué de necesitar
UNAUTHENTICATED_USER=None cuando django.contrib.auth no está
instalado — el BFF (fase 1) comparte ese mismo criterio."""
from django.test import Client


class TestBFFHealth:
    def test_liveness_returns_200(self):
        response = Client().get("/healthz/")
        assert response.status_code == 200

    def test_readiness_returns_200(self):
        response = Client().get("/readyz/")
        assert response.status_code == 200
