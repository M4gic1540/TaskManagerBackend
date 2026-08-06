"""Contexto de trazabilidad por petición HTTP.

Usa contextvars (stdlib) para que cualquier capa (Service, Repository,
Observer) pueda leer el request_id actual sin recibirlo como parámetro
explícito — útil porque TicketService no debería saber de HTTP.
"""
from __future__ import annotations

import contextvars
import uuid

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_user_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id", default="anonymous"
)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(request_id: str) -> None:
    _request_id_ctx.set(request_id)


def get_request_id() -> str:
    return _request_id_ctx.get()


def set_user_id(user_id: str) -> None:
    _user_id_ctx.set(user_id)


def get_user_id() -> str:
    return _user_id_ctx.get()


def reset() -> None:
    """Solo para tests: limpia el contexto entre casos."""
    _request_id_ctx.set("-")
    _user_id_ctx.set("anonymous")
