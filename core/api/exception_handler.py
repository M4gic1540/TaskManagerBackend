"""Manejo global de excepciones: traduce DomainError -> respuesta HTTP
consistente, sin que cada vista tenga try/except repetido (DRY)."""
import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.exceptions import (
    DomainError,
    EntityNotFoundError,
    InvalidStateTransitionError,
    PermissionDeniedError,
    ValidationError,
)
from core.tracing.context import get_request_id

logger = logging.getLogger("ticketera")

_STATUS_MAP = {
    EntityNotFoundError: status.HTTP_404_NOT_FOUND,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    InvalidStateTransitionError: status.HTTP_409_CONFLICT,
    ValidationError: status.HTTP_422_UNPROCESSABLE_ENTITY,
}


def domain_exception_handler(exc, context):
    if isinstance(exc, DomainError):
        code = _STATUS_MAP.get(type(exc), status.HTTP_400_BAD_REQUEST)
        logger.warning("DomainError %s: %s", type(exc).__name__, exc.message)
        return Response(
            {
                "detail": exc.message,
                "error_type": type(exc).__name__,
                "request_id": get_request_id(),
            },
            status=code,
        )

    response = exception_handler(exc, context)
    if response is not None:
        response.data["request_id"] = get_request_id()
    return response
