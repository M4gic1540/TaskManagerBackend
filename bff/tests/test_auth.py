"""Tests de los endpoints de auth propios del BFF (fase 2: login/
logout/me con sesión server-side, ver plan). httpx.Client se mockea —
no hay Gateway real corriendo en el test."""
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client


def _response(*, status_code=200, body=None, text=""):
    mock = MagicMock(status_code=status_code, text=text)
    mock.json.return_value = body if body is not None else {}
    return mock


@pytest.fixture(autouse=True)
def _upstream_url(settings):
    settings.GATEWAY_URL = "http://gateway-test:8000"


class TestBFFLogin:
    def test_login_success_stores_session_and_returns_profile(self):
        with patch("bff.auth_views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _response(body={"access": "acc", "refresh": "ref"})
            mock_client.get.return_value = _response(
                body={"id": 1, "username": "juan", "email": "j@x.com", "role": "TECNICO"}
            )

            client = Client()
            response = client.post(
                "/api/v1/bff/auth/login/",
                data=json.dumps({"username": "juan", "password": "x"}),
                content_type="application/json",
            )

            assert response.status_code == 200
            assert response.json() == {"id": 1, "username": "juan", "role": "TECNICO"}
            assert client.session["access"] == "acc"
            assert client.session["refresh"] == "ref"

    def test_login_invalid_credentials_passes_through_gateway_status(self):
        with patch("bff.auth_views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _response(
                status_code=401, body={"detail": "No active account found"}
            )

            response = Client().post(
                "/api/v1/bff/auth/login/",
                data=json.dumps({"username": "juan", "password": "bad"}),
                content_type="application/json",
            )

            assert response.status_code == 401
            assert response.json() == {"detail": "No active account found"}

    def test_login_requires_csrf_when_enforced(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/v1/bff/auth/login/",
            data=json.dumps({"username": "juan", "password": "x"}),
            content_type="application/json",
        )
        assert response.status_code == 403


class TestBFFLogout:
    def test_logout_flushes_session_and_notifies_gateway(self):
        with patch("bff.auth_views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _response(status_code=200)

            client = Client()
            session = client.session
            session["access"] = "acc"
            session["refresh"] = "ref"
            session.save()

            response = client.post("/api/v1/bff/auth/logout/")

            assert response.status_code == 200
            assert "access" not in client.session

    def test_logout_flushes_session_even_if_gateway_unreachable(self):
        import httpx

        with patch("bff.auth_views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = httpx.ConnectError("refused")

            client = Client()
            session = client.session
            session["access"] = "acc"
            session["refresh"] = "ref"
            session.save()

            response = client.post("/api/v1/bff/auth/logout/")

            assert response.status_code == 200
            assert "access" not in client.session


class TestBFFMe:
    def test_me_returns_401_when_no_session(self):
        response = Client().get("/api/v1/bff/auth/me/")
        assert response.status_code == 401
        assert response.json() == {"detail": "No autenticado."}

    def test_me_sets_csrf_cookie_even_when_unauthenticated(self):
        response = Client().get("/api/v1/bff/auth/me/")
        assert "csrftoken" in response.cookies

    def test_me_returns_profile_when_session_valid(self):
        with patch("bff.auth_views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.get.return_value = _response(body={"id": 1, "username": "juan"})

            client = Client()
            session = client.session
            session["access"] = "acc"
            session["access_expires_at"] = time.time() + 900
            session.save()

            response = client.get("/api/v1/bff/auth/me/")

            assert response.status_code == 200
            assert response.json() == {"id": 1, "username": "juan"}
