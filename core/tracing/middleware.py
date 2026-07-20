"""Middleware de trazabilidad: request_id único por petición.

- Reusa `X-Request-ID` del cliente si viene (útil si el frontend o un
  gateway externo ya generó uno), si no, genera uno nuevo.
- Lo guarda en contextvars (accesible desde Service/Repository/Observer
  sin pasarlo como parámetro) y lo devuelve en la respuesta.
- Loggea inicio y fin de cada request con método, path, status, duración.
"""
import logging
import time

from core.tracing.context import get_request_id, new_request_id, reset, set_request_id, set_user_id

logger = logging.getLogger("ticketera.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestTracingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming_id = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming_id or new_request_id()
        set_request_id(request_id)
        request.request_id = request_id  # disponible en vistas si se necesita

        start = time.monotonic()
        logger.info(
            "-> %s %s",
            request.method,
            request.get_full_path(),
            extra={"event": "request_start"},
        )

        try:
            response = self.get_response(request)

            # user solo se conoce después de que AuthenticationMiddleware/DRF corrió
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                set_user_id(str(user.id))

            duration_ms = (time.monotonic() - start) * 1000
            logger.info(
                "<- %s %s %s %.1fms",
                request.method,
                request.get_full_path(),
                response.status_code,
                duration_ms,
                extra={"event": "request_end", "status_code": response.status_code,
                       "duration_ms": round(duration_ms, 1)},
            )

            response[REQUEST_ID_HEADER] = get_request_id()
            return response
        finally:
            reset()  # evita fuga de contexto entre requests (mismo worker/thread)
