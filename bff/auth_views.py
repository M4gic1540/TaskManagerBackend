"""Fase 2 del BFF (ver plan): login/logout/me propios. El BFF nunca
devuelve el JWT al browser — lo guarda en la sesión server-side
(Redis) y el browser solo recibe la cookie de sesión httpOnly + la
cookie CSRF (double-submit, ver MIDDLEWARE en
config/service_settings/bff.py)."""
from __future__ import annotations

import json

import httpx
from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie

from bff.session import SessionExpired, get_valid_access_token, store_tokens


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
