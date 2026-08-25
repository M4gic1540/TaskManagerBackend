"""Fase 2 del BFF (ver plan): login/logout/me propios. El BFF nunca
devuelve el JWT al browser — lo guarda en la sesión server-side
(Redis) y el browser solo recibe la cookie de sesión httpOnly + la
cookie CSRF (double-submit, ver MIDDLEWARE en
config/service_settings/bff.py)."""
from __future__ import annotations

import json
import secrets
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from bff.session import SessionExpired, get_valid_access_token, store_tokens

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_STATE_SESSION_KEY = "google_oauth_state"


def _gateway_client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.GATEWAY_URL.rstrip("/"),
        timeout=getattr(settings, "BFF_UPSTREAM_TIMEOUT", 10.0),
    )


def _safe_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"detail": response.text or "Error del servicio de autenticación."}


class LoginView(View):
    http_method_names = ["post"]

    def post(self, request):
        try:
            payload = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"detail": "JSON inválido."}, status=400)

        with _gateway_client() as client:
            login_response = client.post("/api/v1/auth/login/", json=payload)

        if login_response.status_code != 200:
            return JsonResponse(_safe_json(login_response), status=login_response.status_code)

        tokens = _safe_json(login_response)

        with _gateway_client() as client:
            me_response = client.get(
                "/api/v1/me/", headers={"Authorization": f"Bearer {tokens['access']}"}
            )
        if me_response.status_code != 200:
            return JsonResponse({"detail": "No se pudo obtener el perfil."}, status=502)

        user = _safe_json(me_response)
        store_tokens(request.session, access=tokens["access"], refresh=tokens["refresh"])

        return JsonResponse({"id": user["id"], "username": user["username"], "role": user["role"]})


class LogoutView(View):
    http_method_names = ["post"]

    def post(self, request):
        refresh_token = request.session.get("refresh")
        if refresh_token:
            with _gateway_client() as client:
                try:
                    client.post("/api/v1/auth/logout/", json={"refresh": refresh_token})
                except httpx.HTTPError:
                    pass  # logout es best-effort contra el Gateway: la sesión se flushea igual
        request.session.flush()
        return JsonResponse({"detail": "ok"})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class MeView(View):
    http_method_names = ["get"]

    def get(self, request):
        try:
            access = get_valid_access_token(request)
        except SessionExpired:
            request.session.flush()
            return JsonResponse({"detail": "session_expired"}, status=401)

        if access is None:
            return JsonResponse({"detail": "No autenticado."}, status=401)

        with _gateway_client() as client:
            me_response = client.get("/api/v1/me/", headers={"Authorization": f"Bearer {access}"})

        if me_response.status_code != 200:
            request.session.flush()
            return JsonResponse({"detail": "session_expired"}, status=401)

        return JsonResponse(_safe_json(me_response))


class GoogleLoginStartView(View):
    """Arranca el flujo: redirige el browser a la pantalla de consentimiento
    de Google. `state` se guarda en la sesión (que ya existe aunque el
    usuario no esté logueado — Django crea la cookie de sesión igual) y
    se vuelve a chequear en el callback, como defensa CSRF del propio
    flujo OAuth (que alguien más no pueda "regalarle" su login a la
    víctima con un callback armado a mano)."""

    http_method_names = ["get"]

    def get(self, request):
        if not settings.GOOGLE_CLIENT_ID:
            return JsonResponse({"detail": "Login con Google no configurado."}, status=503)

        state = secrets.token_urlsafe(24)
        request.session[GOOGLE_OAUTH_STATE_SESSION_KEY] = state

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return HttpResponseRedirect(f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}")


class GoogleLoginCallbackView(View):
    """Google redirige acá con `code` (o `error`). Intercambia el code
    por tokens directo con Google (server-to-server, con el client
    secret), verifica la firma del id_token contra las llaves públicas
    de Google, y solo con eso ya verificado le pide a accounts que
    mintee un JWT para ese email (auth/google-mint/, protegido por
    secreto interno). Nunca expone nada de esto al frontend salvo un
    redirect final — igual que el resto del BFF, el browser solo ve la
    cookie de sesión."""

    http_method_names = ["get"]

    def _redirect_error(self, code: str) -> HttpResponseRedirect:
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/login?error={code}")

    def get(self, request):
        if request.GET.get("error"):
            return self._redirect_error("google_denied")

        state = request.GET.get("state")
        expected_state = request.session.pop(GOOGLE_OAUTH_STATE_SESSION_KEY, None)
        code = request.GET.get("code")
        if not code or not expected_state or state != expected_state:
            return self._redirect_error("google_invalid_state")

        try:
            with httpx.Client(timeout=getattr(settings, "BFF_UPSTREAM_TIMEOUT", 10.0)) as client:
                token_response = client.post(
                    GOOGLE_TOKEN_ENDPOINT,
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    },
                )
        except httpx.HTTPError:
            return self._redirect_error("google_token_exchange")

        token_data = _safe_json(token_response)
        if token_response.status_code != 200 or "id_token" not in token_data:
            return self._redirect_error("google_token_exchange")

        try:
            claims = google_id_token.verify_oauth2_token(
                token_data["id_token"], google_requests.Request(), settings.GOOGLE_CLIENT_ID
            )
        except ValueError:
            return self._redirect_error("google_verify_failed")

        email = claims.get("email")
        if not email or not claims.get("email_verified"):
            return self._redirect_error("google_email_unverified")

        with _gateway_client() as client:
            mint_response = client.post(
                "/api/v1/auth/google-mint/",
                json={
                    "email": email,
                    "first_name": claims.get("given_name", ""),
                    "last_name": claims.get("family_name", ""),
                },
                headers={"X-Internal-Auth": settings.INTERNAL_AUTH_SECRET},
            )
        if mint_response.status_code != 200:
            return self._redirect_error("google_mint_failed")

        tokens = _safe_json(mint_response)
        store_tokens(request.session, access=tokens["access"], refresh=tokens["refresh"])
        return HttpResponseRedirect(f"{settings.FRONTEND_URL}/tickets")
