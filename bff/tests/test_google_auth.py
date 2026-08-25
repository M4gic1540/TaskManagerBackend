"""Tests del login con Google del BFF (Authorization Code flow, ver
bff/auth_views.py). httpx.Client se mockea dos veces (intercambio de
code con Google, y el mint contra accounts vía Gateway) y
google.oauth2.id_token.verify_oauth2_token también — no hay red real
ni credenciales reales de Google en los tests."""
import json
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import Client


def _response(*, status_code=200, body=None, text=""):
    mock = MagicMock(status_code=status_code, text=text)
    mock.json.return_value = body if body is not None else {}
    return mock


@pytest.fixture(autouse=True)
def _google_settings(settings):
    settings.GATEWAY_URL = "http://gateway-test:8000"
    settings.GOOGLE_CLIENT_ID = "client-id-test"
    settings.GOOGLE_CLIENT_SECRET = "client-secret-test"
    settings.GOOGLE_REDIRECT_URI = "http://bff-test:8010/api/v1/bff/auth/google/callback/"
    settings.FRONTEND_URL = "http://frontend-test:5173"
    settings.INTERNAL_AUTH_SECRET = "shared-secret-test"


class TestGoogleLoginStart:
    def test_returns_503_when_not_configured(self, settings):
        settings.GOOGLE_CLIENT_ID = ""
        response = Client().get("/api/v1/bff/auth/google/start/")
        assert response.status_code == 503

    def test_redirects_to_google_with_expected_params_and_stores_state(self):
        client = Client()
        response = client.get("/api/v1/bff/auth/google/start/")

        assert response.status_code == 302
        parsed = urlparse(response["Location"])
        assert parsed.netloc == "accounts.google.com"
        qs = parse_qs(parsed.query)
        assert qs["client_id"] == ["client-id-test"]
        assert qs["redirect_uri"] == ["http://bff-test:8010/api/v1/bff/auth/google/callback/"]
        assert qs["response_type"] == ["code"]
        assert qs["scope"] == ["openid email profile"]
        assert "state" in qs

        stored_state = client.session["google_oauth_state"]
        assert stored_state == qs["state"][0]


def _post_side_effect(*, token_response, mint_response):
    def _side_effect(url, **kwargs):
        if "oauth2.googleapis.com" in str(url):
            return token_response
        return mint_response
    return _side_effect


class TestGoogleLoginCallback:
    def _start_and_get_state(self, client):
        client.get("/api/v1/bff/auth/google/start/")
        return client.session["google_oauth_state"]

    def test_google_error_param_redirects_with_error(self):
        response = Client().get("/api/v1/bff/auth/google/callback/", {"error": "access_denied"})
        assert response.status_code == 302
        assert response["Location"] == "http://frontend-test:5173/login?error=google_denied"

    def test_missing_or_mismatched_state_redirects_with_error(self):
        client = Client()
        self._start_and_get_state(client)
        response = client.get(
            "/api/v1/bff/auth/google/callback/", {"code": "abc", "state": "wrong-state"}
        )
        assert response.status_code == 302
        assert response["Location"] == "http://frontend-test:5173/login?error=google_invalid_state"

    def test_token_exchange_failure_redirects_with_error(self):
        client = Client()
        state = self._start_and_get_state(client)

        with patch("bff.auth_views.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _response(status_code=400, body={"error": "invalid_grant"})

            response = client.get(
                "/api/v1/bff/auth/google/callback/", {"code": "abc", "state": state}
            )

        assert response["Location"] == "http://frontend-test:5173/login?error=google_token_exchange"

    def test_id_token_verification_failure_redirects_with_error(self):
        client = Client()
        state = self._start_and_get_state(client)

        with patch("bff.auth_views.httpx.Client") as mock_client_cls, \
             patch("bff.auth_views.google_id_token.verify_oauth2_token") as mock_verify:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _response(body={"id_token": "fake.jwt.token"})
            mock_verify.side_effect = ValueError("bad signature")

            response = client.get(
                "/api/v1/bff/auth/google/callback/", {"code": "abc", "state": state}
            )

        assert response["Location"] == "http://frontend-test:5173/login?error=google_verify_failed"

    def test_unverified_email_redirects_with_error(self):
        client = Client()
        state = self._start_and_get_state(client)

        with patch("bff.auth_views.httpx.Client") as mock_client_cls, \
             patch("bff.auth_views.google_id_token.verify_oauth2_token") as mock_verify:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _response(body={"id_token": "fake.jwt.token"})
            mock_verify.return_value = {"email": "x@example.com", "email_verified": False}

            response = client.get(
                "/api/v1/bff/auth/google/callback/", {"code": "abc", "state": state}
            )

        assert response["Location"] == "http://frontend-test:5173/login?error=google_email_unverified"

    def test_mint_failure_redirects_with_error(self):
        client = Client()
        state = self._start_and_get_state(client)

        with patch("bff.auth_views.httpx.Client") as mock_client_cls, \
             patch("bff.auth_views.google_id_token.verify_oauth2_token") as mock_verify:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = _post_side_effect(
                token_response=_response(body={"id_token": "fake.jwt.token"}),
                mint_response=_response(status_code=403, body={"detail": "No autorizado."}),
            )
            mock_verify.return_value = {
                "email": "ana@example.com", "email_verified": True,
                "given_name": "Ana", "family_name": "Soto",
            }

            response = client.get(
                "/api/v1/bff/auth/google/callback/", {"code": "abc", "state": state}
            )

        assert response["Location"] == "http://frontend-test:5173/login?error=google_mint_failed"

    def test_full_success_stores_session_and_redirects_to_app(self):
        client = Client()
        state = self._start_and_get_state(client)

        with patch("bff.auth_views.httpx.Client") as mock_client_cls, \
             patch("bff.auth_views.google_id_token.verify_oauth2_token") as mock_verify:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.side_effect = _post_side_effect(
                token_response=_response(body={"id_token": "fake.jwt.token"}),
                mint_response=_response(body={"access": "acc-tok", "refresh": "ref-tok"}),
            )
            mock_verify.return_value = {
                "email": "ana@example.com", "email_verified": True,
                "given_name": "Ana", "family_name": "Soto",
            }

            response = client.get(
                "/api/v1/bff/auth/google/callback/", {"code": "abc", "state": state}
            )

            # El mint contra accounts se llama con el header de secreto
            # compartido y el email ya verificado por Google.
            mint_call = [
                c for c in mock_client.post.call_args_list
                if "google-mint" in str(c.args[0]) or "google-mint" in str(c.kwargs.get("url", ""))
            ][0]
            assert mint_call.kwargs["headers"]["X-Internal-Auth"] == "shared-secret-test"
            assert mint_call.kwargs["json"]["email"] == "ana@example.com"

        assert response.status_code == 302
        assert response["Location"] == "http://frontend-test:5173/tickets"
        assert client.session["access"] == "acc-tok"
        assert client.session["refresh"] == "ref-tok"
        # El state de un solo uso no debe sobrevivir al callback.
        assert "google_oauth_state" not in client.session
