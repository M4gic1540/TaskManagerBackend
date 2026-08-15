"""Fase 1 del BFF (ver plan): proxy transparente puro hacia el Gateway,
mismo comportamiento que gateway/views.py hoy pero con un único
upstream. Reenvía Authorization tal cual — todavía no maneja sesión ni
cookie (eso llega en la fase de auth), así que por ahora el frontend
sigue sin tocar este servicio."""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse
from django.views import View

from core.proxy.httpx_forward import filter_forward_headers, forward_request


class BFFProxyView(View):
    http_method_names = ["get", "post", "put", "patch", "delete", "options"]

    def dispatch(self, request, *args, **kwargs):
        gateway_url = getattr(settings, "GATEWAY_URL", None)
        if not gateway_url:
            return HttpResponse(status=404)

        timeout = getattr(settings, "BFF_UPSTREAM_TIMEOUT", 10.0)
        return forward_request(
            method=request.method,
            url=gateway_url.rstrip("/") + request.path,
            params=request.GET,
            headers=filter_forward_headers(request.headers),
            content=request.body,
            timeout=timeout,
        )
