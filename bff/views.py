"""Proxy transparente hacia el Gateway. Fase 1: reenviaba Authorization
tal cual. Fase 2 (ver plan): si la sesión del BFF tiene tokens (login
hecho vía /api/v1/bff/auth/login/), pisa Authorization con el access
token de la sesión — refrescándolo primero si venció — así el frontend
ya no necesita mandar el header. Quien todavía pega directo con un
Bearer propio (sin pasar por el login del BFF) sigue funcionando igual
que en fase 1: sin sesión, no hay nada que pisar."""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse
from django.views import View

from bff.session import SessionExpired, get_valid_access_token
from core.proxy.httpx_forward import filter_forward_headers, forward_request


class BFFProxyView(View):
    http_method_names = ["get", "post", "put", "patch", "delete", "options"]

    def dispatch(self, request, *args, **kwargs):
        gateway_url = getattr(settings, "GATEWAY_URL", None)
        if not gateway_url:
            return HttpResponse(status=404)

        headers = filter_forward_headers(request.headers)
        try:
            access_token = get_valid_access_token(request)
        except SessionExpired:
            request.session.flush()
            return HttpResponse(
                b'{"detail": "session_expired"}', status=401, content_type="application/json"
            )
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        timeout = getattr(settings, "BFF_UPSTREAM_TIMEOUT", 10.0)
        return forward_request(
            method=request.method,
            url=gateway_url.rstrip("/") + request.path,
            params=request.GET,
            headers=headers,
            content=request.body,
            timeout=timeout,
        )
