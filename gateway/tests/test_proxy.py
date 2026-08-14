"""Tests del reverse proxy del gateway: enrutamiento por prefijo,
reenvío de headers/body, y mapeo de errores de red a respuestas HTTP
consistentes. httpx.Client se mockea — no hay servicios reales
corriendo en el test."""
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.test import Client


def _mock_response(*, status_code=200, content=b'{"ok": true}', headers=None):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.content = content
    response.headers = headers or {"Content-Type": "application/json"}
    return response


@pytest.fixture(autouse=True)
def _upstream_urls(settings):
    settings.ACCOUNTS_SERVICE_URL = "http://accounts-test:8000"
    settings.TICKETS_SERVICE_URL = "http://tickets-test:8000"
    settings.INVENTORY_SERVICE_URL = "http://inventory-test:8000"


class TestGatewayRouting:
    def test_routes_tickets_prefix_to_tickets_service(self):
        with patch("gateway.views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()

            response = Client().get("/api/v1/tickets/5/")

            assert response.status_code == 200
            called_url = mock_client.request.call_args.kwargs["url"]
            assert called_url == "http://tickets-test:8000/api/v1/tickets/5/"

    def test_routes_inventory_prefix_to_inventory_service(self):
        with patch("gateway.views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()

            Client().get("/api/v1/inventory/")

            called_url = mock_client.request.call_args.kwargs["url"]
            assert called_url == "http://inventory-test:8000/api/v1/inventory/"

    def test_routes_everything_else_to_accounts_service(self):
        with patch("gateway.views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()

            Client().post("/api/v1/auth/login/")

            called_url = mock_client.request.call_args.kwargs["url"]
            assert called_url == "http://accounts-test:8000/api/v1/auth/login/"

    def test_forwards_authorization_header(self):
        with patch("gateway.views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()

            Client().get("/api/v1/tickets/", HTTP_AUTHORIZATION="Bearer abc123")

            forwarded_headers = mock_client.request.call_args.kwargs["headers"]
            assert forwarded_headers.get("Authorization") == "Bearer abc123"

    def test_response_body_and_status_passed_through(self):
        with patch("gateway.views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response(
                status_code=201, content=b'{"id": 1}'
            )

            response = Client().post("/api/v1/tickets/")

            assert response.status_code == 201
            assert response.content == b'{"id": 1}'

    def test_upstream_timeout_returns_504(self):
        with patch("gateway.views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.side_effect = httpx.TimeoutException("timeout")

            response = Client().get("/api/v1/tickets/")

            assert response.status_code == 504

    def test_upstream_connection_error_returns_503(self):
        with patch("gateway.views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.side_effect = httpx.ConnectError("refused")

            response = Client().get("/api/v1/tickets/")

            assert response.status_code == 503

    def test_missing_upstream_setting_returns_404(self, settings):
        settings.TICKETS_SERVICE_URL = None
        response = Client().get("/api/v1/tickets/")
        assert response.status_code == 404
