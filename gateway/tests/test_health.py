"""Tests de /healthz/ y /readyz/ del gateway. Existen aparte de
core/tests/test_health.py porque el gateway es el único servicio sin
`django.contrib.auth` instalado — un simple `authentication_classes =
()` en la vista NO alcanza para evitar que DRF importe
`django.contrib.auth.models.AnonymousUser` al resolver `request.user`
(vía UNAUTHENTICATED_USER); hay que pisar ese setting a `None` también
(config/service_settings/gateway.py). Este test existe para no volver
a romper eso en silencio."""
from django.test import Client


class TestGatewayHealth:
    def test_liveness_returns_200(self):
        response = Client().get("/healthz/")
        assert response.status_code == 200

    def test_readiness_returns_200(self):
        response = Client().get("/readyz/")
        assert response.status_code == 200
