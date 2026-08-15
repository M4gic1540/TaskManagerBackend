"""Fase 2 del BFF (ver plan): los JWT viven solo en la sesión
server-side (Redis vía SESSION_ENGINE cache-backed, ver
config/service_settings/bff.py), nunca en el browser. Este módulo
centraliza guardar/leer/refrescar esos tokens — lo comparten
bff/auth_views.py (login/logout/me) y bff/views.py (proxy, refresco
transparente antes de reenviar al Gateway)."""
from __future__ import annotations

import time

import httpx
from django.conf import settings
from django.core.cache import cache

REFRESH_LOCK_TIMEOUT = 5
REFRESH_LOCK_RETRY_DELAY = 0.1
REFRESH_LOCK_MAX_ATTEMPTS = 20


class SessionExpired(Exception):
    """El refresh token también venció (o el Gateway lo rechazó): la
    sesión ya no sirve, quien llama debe flushearla y devolver 401."""


def _access_lifetime_seconds() -> float:
    return settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()


def store_tokens(session, *, access: str, refresh: str) -> None:
    session["access"] = access
    session["refresh"] = refresh
    session["access_expires_at"] = time.time() + _access_lifetime_seconds()


def _is_expired(session) -> bool:
    expires_at = session.get("access_expires_at")
    return expires_at is None or time.time() >= expires_at


def _call_refresh(refresh_token: str) -> dict:
    gateway_url = settings.GATEWAY_URL.rstrip("/")
    timeout = getattr(settings, "BFF_UPSTREAM_TIMEOUT", 10.0)
    try:
        with httpx.Client(base_url=gateway_url, timeout=timeout) as client:
            response = client.post("/api/v1/auth/refresh/", json={"refresh": refresh_token})
    except httpx.HTTPError:
        raise SessionExpired from None
    if response.status_code != 200:
        raise SessionExpired
    return response.json()


def get_valid_access_token(request) -> str | None:
    """Access token vigente para la sesión actual, o None si la sesión
    no tiene tokens (nunca pasó por /bff/auth/login/ — el passthrough
    sigue reenviando lo que haya mandado el cliente directo). Lanza
    SessionExpired si hace falta refrescar y el refresh token también
    venció."""
    session = request.session
    if "access" not in session:
        return None
    if not _is_expired(session):
        return session["access"]

    lock_key = f"bff:refresh-lock:{session.session_key}"
    if cache.add(lock_key, "1", timeout=REFRESH_LOCK_TIMEOUT):
        try:
            data = _call_refresh(session["refresh"])
            store_tokens(session, access=data["access"], refresh=data.get("refresh", session["refresh"]))
            return session["access"]
        finally:
            cache.delete(lock_key)

    # Otro request concurrente ya está refrescando esta misma sesión:
    # esperar a que termine en vez de disparar un segundo refresh en
    # paralelo (evita quemar el refresh token con ROTATE_REFRESH_TOKENS).
    session_store_cls = type(session)
    for _ in range(REFRESH_LOCK_MAX_ATTEMPTS):
        time.sleep(REFRESH_LOCK_RETRY_DELAY)
        fresh = session_store_cls(session.session_key)
        if not _is_expired(fresh):
            session["access"] = fresh["access"]
            session["refresh"] = fresh["refresh"]
            session["access_expires_at"] = fresh["access_expires_at"]
            return session["access"]
    raise SessionExpired
