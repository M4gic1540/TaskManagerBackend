"""Helpers de reverse-proxy vía httpx compartidos entre gateway/views.py
y bff/views.py: filtrado de headers hop-by-hop y mapeo de errores de
red (timeout/conexión) a respuestas HTTP consistentes con el resto de
la API. Ambos son proxies httpx.Client — solo cambia el upstream al
que apuntan (Gateway reenvía a accounts/tickets/inventory por prefijo
de path; BFF reenvía todo a un único upstream, el Gateway)."""
from __future__ import annotations

import httpx
from django.http import HttpResponse

HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
    # No son hop-by-hop en sentido estricto, pero Django/el servidor ASGI
    # ya los genera para la respuesta del proxy — copiar también los
    # del upstream los duplica en la respuesta final.
    "date", "server",
}


def filter_forward_headers(headers) -> dict:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def forward_request(*, method: str, url: str, params, headers: dict, content: bytes, timeout: float) -> HttpResponse:
    """Reenvía una request vía httpx.Client y arma la HttpResponse,
    mapeando TimeoutException -> 504 y ConnectError -> 503."""
    try:
        with httpx.Client(timeout=timeout) as client:
            upstream_response = client.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                content=content,
            )
    except httpx.TimeoutException:
        return HttpResponse(
            b'{"detail": "El servicio tard\xc3\xb3 demasiado en responder.", "error_type": "GatewayTimeout"}',
            status=504,
            content_type="application/json",
        )
    except httpx.ConnectError:
        return HttpResponse(
            b'{"detail": "Servicio no disponible.", "error_type": "GatewayUnavailable"}',
            status=503,
            content_type="application/json",
        )

    response = HttpResponse(
        content=upstream_response.content,
        status=upstream_response.status_code,
    )
    for header, value in upstream_response.headers.items():
        if header.lower() not in HOP_BY_HOP_HEADERS:
            response[header] = value
    return response
