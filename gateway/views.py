"""Reverse proxy transparente: preserva exactamente las rutas
/api/v1/... que el frontend ya consume, reenviando por prefijo de path
al microservicio correspondiente (accounts, tickets o inventory). No
hay circuit breaker acá (decisión explícita del usuario, limitado a las
llamadas de inventory hacia GLPI) — solo timeout + mapeo de errores de
red a respuestas HTTP consistentes con el resto de la API.

El filtrado de headers y el manejo de errores de red viven en
core/proxy/httpx_forward.py, compartido con bff/views.py — acá solo
queda la tabla de ruteo por prefijo, específica del gateway."""
from __future__ import annotations

from django.conf import settings
from django.http import HttpResponse
from django.views import View

from core.proxy.httpx_forward import filter_forward_headers, forward_request

# Prefijos bajo /api/v1/, en orden de especificidad: 'tickets/' e
# 'inventory/' antes que el catch-all de accounts (que monta en la raíz
# de /api/v1/: auth/, me/, technicians/, users/).
_ROUTE_TABLE = (
    ("/api/v1/tickets/", "TICKETS_SERVICE_URL"),
    ("/api/v1/inventory/", "INVENTORY_SERVICE_URL"),
    ("/api/v1/", "ACCOUNTS_SERVICE_URL"),
    # QRs de inventario (Asset.qr_image) — el único servicio con media hoy.
    ("/media/", "INVENTORY_SERVICE_URL"),
)


def _resolve_upstream(path: str) -> str | None:
    for prefix, setting_name in _ROUTE_TABLE:
        if path.startswith(prefix):
            base = getattr(settings, setting_name, None)
            if not base:
                return None
            return base.rstrip("/") + path
    return None


class GatewayProxyView(View):
    http_method_names = ["get", "post", "put", "patch", "delete", "options"]

    def dispatch(self, request, *args, **kwargs):
        upstream_url = _resolve_upstream(request.path)
        if upstream_url is None:
            return HttpResponse(status=404)

        timeout = getattr(settings, "GATEWAY_UPSTREAM_TIMEOUT", 10.0)
        return forward_request(
            method=request.method,
            url=upstream_url,
            params=request.GET,
            headers=filter_forward_headers(request.headers),
            content=request.body,
            timeout=timeout,
        )
