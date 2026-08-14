"""Registro de checks de readiness por servicio. Cada `config/urls_*.py`
registra los checks que le corresponden (todo servicio chequea su
propia BD; solo inventory además conoce el circuit breaker de GLPI) —
así el monolito y cada microservicio comparten las mismas vistas de
core/health/views.py sin acoplarse a checks que no les aplican."""
from __future__ import annotations

from typing import Callable

from django.db import connections
from django.db.utils import OperationalError


def check_default_db(alias: str = "default") -> dict:
    try:
        connections[alias].cursor()
        return {"ok": True}
    except OperationalError as exc:
        return {"ok": False, "detail": str(exc)}


def check_glpi_circuit_breaker() -> dict:
    """No abre conexión nueva a GLPI: solo lee el estado ya cacheado del
    breaker (CLOSED/OPEN/HALF_OPEN), para que un readiness probe no
    dispare tráfico real hacia una BD que ya sabemos caída."""
    from core.resilience.circuit_breaker import glpi_breaker

    state = glpi_breaker.current_state
    return {"ok": state != "open", "state": state}


_REGISTRY: dict[str, Callable[[], dict]] = {}


def register_readiness_check(name: str, check_fn: Callable[[], dict]) -> None:
    _REGISTRY[name] = check_fn


def get_readiness_checks() -> dict[str, Callable[[], dict]]:
    return dict(_REGISTRY)
