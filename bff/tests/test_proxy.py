"""Tests del reverse proxy del BFF: passthrough hacia el Gateway
(fase 1) + inyección/refresco del access token de sesión cuando el
login se hizo vía /api/v1/bff/auth/login/ (fase 2, ver plan).
httpx.Client se mockea — no hay servicios reales corriendo en el test.
Mismo criterio que gateway/tests/test_proxy.py, solo que acá hay un
único upstream en vez de una tabla de ruteo."""
import time
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
def _upstream_url(settings):
    settings.GATEWAY_URL = "http://gateway-test:8000"


class TestBFFProxy:
    def test_routes_to_gateway_preserving_path(self):
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()

            response = Client().get("/api/v1/tickets/5/")

            assert response.status_code == 200
            called_url = mock_client.request.call_args.kwargs["url"]
            assert called_url == "http://gateway-test:8000/api/v1/tickets/5/"

    def test_forwards_authorization_header(self):
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()

            Client().get("/api/v1/tickets/", HTTP_AUTHORIZATION="Bearer abc123")

            forwarded_headers = mock_client.request.call_args.kwargs["headers"]
            assert forwarded_headers.get("Authorization") == "Bearer abc123"

    def test_response_body_and_status_passed_through(self):
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response(
                status_code=201, content=b'{"id": 1}'
            )

            response = Client().post("/api/v1/tickets/")

            assert response.status_code == 201
            assert response.content == b'{"id": 1}'

    def test_upstream_timeout_returns_504(self):
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.side_effect = httpx.TimeoutException("timeout")

            response = Client().get("/api/v1/tickets/")

            assert response.status_code == 504

    def test_upstream_connection_error_returns_503(self):
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.side_effect = httpx.ConnectError("refused")

            response = Client().get("/api/v1/tickets/")

            assert response.status_code == 503

    def test_missing_upstream_setting_returns_404(self, settings):
        settings.GATEWAY_URL = None
        response = Client().get("/api/v1/tickets/")
        assert response.status_code == 404


class TestBFFProxySessionAuth:
    """Fase 2: si hubo login vía el BFF, el token de sesión pisa
    cualquier Authorization que mande el cliente."""

    def test_valid_session_token_overrides_client_authorization(self):
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()

            client = Client()
            session = client.session
            session["access"] = "session-access-token"
            session["access_expires_at"] = time.time() + 900
            session.save()

            client.get("/api/v1/tickets/", HTTP_AUTHORIZATION="Bearer client-sent-token")

            forwarded_headers = mock_client.request.call_args.kwargs["headers"]
            assert forwarded_headers.get("Authorization") == "Bearer session-access-token"

    def test_expired_access_token_refreshes_before_forwarding(self):
        # "core.proxy.httpx_forward.httpx.Client" y "bff.session.httpx.Client"
        # apuntan al mismo atributo (ambos módulos comparten el mismo
        # objeto `httpx` importado) — un solo patch cubre las dos
        # llamadas (refresh vía .post, forward vía .request) sobre el
        # mismo mock de cliente.
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.request.return_value = _mock_response()
            mock_client.post.return_value = MagicMock(
                status_code=200, json=lambda: {"access": "new-access", "refresh": "new-refresh"}
            )

            client = Client()
            session = client.session
            session["access"] = "old-access"
            session["refresh"] = "old-refresh"
            session["access_expires_at"] = time.time() - 10
            session.save()

            client.get("/api/v1/tickets/")

            forwarded_headers = mock_client.request.call_args.kwargs["headers"]
            assert forwarded_headers.get("Authorization") == "Bearer new-access"
            assert client.session["access"] == "new-access"
            assert client.session["refresh"] == "new-refresh"

    def test_expired_refresh_token_returns_401_and_flushes_session(self):
        with patch("core.proxy.httpx_forward.httpx.Client") as mock_client_cls:
            mock_refresh = mock_client_cls.return_value.__enter__.return_value
            mock_refresh.post.return_value = MagicMock(status_code=401, json=lambda: {})

            client = Client()
            session = client.session
            session["access"] = "old-access"
            session["refresh"] = "dead-refresh"
            session["access_expires_at"] = time.time() - 10
            session.save()

            response = client.get("/api/v1/tickets/")

            assert response.status_code == 401
            assert response.json() == {"detail": "session_expired"}
            assert "access" not in client.session
