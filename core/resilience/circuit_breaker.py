"""Circuit breaker para las llamadas de inventory a la BD externa GLPI
(MariaDB de solo lectura, alias 'glpi' en settings.DATABASES). No hay
circuit breaker entre microservicios propios — decisión explícita, el
JWT validado localmente no depende de disponibilidad de red."""
from __future__ import annotations

import logging

import pybreaker
from django.conf import settings
from django.db.utils import OperationalError

from core.exceptions import DomainError

logger = logging.getLogger("ticketera.resilience")


class GLPIUnavailableError(DomainError):
    """El circuito hacia GLPI está abierto, o la llamada real falló."""

    default_message = "El sistema de inventario GLPI no está disponible en este momento."


class _GLPIBreakerListener(pybreaker.CircuitBreakerListener):
    def state_change(self, cb, old_state, new_state):
        logger.warning(
            "GLPI circuit breaker: %s -> %s",
            old_state.name if old_state else "?",
            new_state.name,
            extra={"event": "circuit_breaker_state_change"},
        )


glpi_breaker = pybreaker.CircuitBreaker(
    fail_max=getattr(settings, "GLPI_BREAKER_FAIL_MAX", 5),
    reset_timeout=getattr(settings, "GLPI_BREAKER_RESET_TIMEOUT", 30),
    listeners=[_GLPIBreakerListener()],
)


def call_with_breaker(fn, *args, **kwargs):
    """Wrapper usado por GLPIInventoryService para toda llamada que toca
    connections['glpi']. Traduce fallos reales y de circuito abierto a
    GLPIUnavailableError (DomainError), que el exception_handler global
    ya sabe mapear a una respuesta HTTP consistente."""
    try:
        return glpi_breaker.call(fn, *args, **kwargs)
    except pybreaker.CircuitBreakerError as exc:
        raise GLPIUnavailableError() from exc
    except OperationalError as exc:
        raise GLPIUnavailableError(f"Error de conexión a GLPI: {exc}") from exc
