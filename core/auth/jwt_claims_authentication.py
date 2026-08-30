"""Autenticación JWT sin acceso a BD: construye la identidad del actor
100% desde los claims del token (`user_id`, `username`, `role`, ya
inyectados por CustomTokenObtainPairSerializer en accounts), en vez de
resolver un `User` real contra una tabla local.

Pensada para microservicios que no tienen la tabla de usuarios en su
propia BD (tickets, inventory, gateway) — consultarla implicaría una
llamada de red al servicio accounts por request, descartada
explícitamente en favor de claims locales autocontenidos en el token.

No hereda de `JWTAuthentication` (que llama a `get_user()` -> BD) sino
que reusa por composición `AccessToken` de simplejwt solo para validar
firma/expiración."""
from __future__ import annotations

from dataclasses import dataclass

from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken


@dataclass(frozen=True)
class TokenClaimsUser:
    """Reemplazo liviano de `accounts.models.User` para servicios sin
    tabla `User` local. Expone la misma superficie mínima que usa el
    resto del código de negocio (permisos, servicios): `.id`,
    `.username`, `.role`, `.is_authenticated`, `.is_anonymous`,
    `.is_active`, `.is_active_technician`, `.is_superuser`, `.pk`.

    No es un modelo Django: no se puede pasar a un FK ni guardar en BD
    (por diseño, evita reintroducir un join accidental)."""

    id: int
    username: str
    role: str
    is_active: bool = True
    is_active_technician: bool = True

    is_authenticated: bool = True
    is_anonymous: bool = False
    is_superuser: bool = False

    @property
    def pk(self) -> int:
        """DRF's UserRateThrottle (y otros lugares que asumen un modelo
        Django) leen `.pk`, no `.id` — sin esto, cualquier endpoint con
        throttling revienta con AttributeError al autenticar vía claims."""
        return self.id


class JWTClaimsAuthentication(BaseAuthentication):
    www_authenticate_realm = "api"

    def get_header(self, request):
        header = request.META.get("HTTP_AUTHORIZATION")
        return header.encode("iso-8859-1") if isinstance(header, str) else header

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        parts = header.split()
        if not parts or parts[0].decode() not in api_settings.AUTH_HEADER_TYPES:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Header de Authorization mal formado.")

        raw_token = parts[1]

        try:
            # AccessToken(...) valida firma (HS256/SIGNING_KEY compartido),
            # exp/nbf y que sea un token de tipo access — sin ninguna
            # consulta a BD.
            validated_token = AccessToken(raw_token)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        return (self._build_user(validated_token), validated_token)

    def _build_user(self, validated_token) -> TokenClaimsUser:
        try:
            # simplejwt >= 5.5 siempre serializa USER_ID_CLAIM como str
            # (Token.for_user hace `str(user_id)` incondicional), así que
            # sin este int() cualquier comparación == / != contra un
            # IntegerField de la BD (assigned_technician_id, requester_id)
            # falla siempre ("6" != 6), tumbando en silencio permisos y
            # reglas de negocio que comparan por id.
            user_id = int(validated_token[api_settings.USER_ID_CLAIM])
            username = validated_token["username"]
            role = validated_token["role"]
        except KeyError as exc:
            # Token válido pero sin un claim requerido (ej. emitido antes
            # de este cambio, o por otro cliente): se rechaza explícito en
            # vez de crear un usuario a medias con role=None, que rompería
            # IsAdmin/IsTechnician silenciosamente.
            raise exceptions.AuthenticationFailed(
                f"Token sin claim requerido: {exc.args[0]}"
            ) from exc

        return TokenClaimsUser(
            id=user_id,
            username=username,
            role=role,
            is_active_technician=validated_token.get("is_active_technician", True),
        )

    def authenticate_header(self, request):
        return f'Bearer realm="{self.www_authenticate_realm}"'
