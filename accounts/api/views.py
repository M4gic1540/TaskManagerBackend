from adrf.views import APIView as AsyncAPIView
from django.conf import settings
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import Role, User
from accounts.permissions import IsAdmin
from accounts.services.user_service import UserService
from core.async_support.bridge import to_async
from core.async_support.mixins import LoopRegisteringMixin
from accounts.api.serializers import (
    CustomTokenObtainPairSerializer,
    RoleChangeSerializer,
    TechnicianCreationSerializer,
    UserSerializer,
)

_UNAUTHORIZED_DETAIL = "No autorizado."


class CustomTokenObtainPairView(TokenObtainPairView):
    """Login: emite access + refresh token con claims de rol."""

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = (permissions.AllowAny,)
    throttle_scope = "login"

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class GoogleAuthMintView(APIView):
    """Mintea un JWT (mismo formato que login normal) para un email ya
    verificado por Google — el BFF llega acá DESPUÉS de validar el
    id_token con las llaves públicas de Google, este endpoint no vuelve
    a hablar con Google. Sin contraseña: la identidad la garantiza el
    header interno, nunca expuesto al frontend.

    No auto-provisiona cuentas: el usuario final ya no tiene acceso al
    sistema (solo interactúa por correo), así que solo las cuentas de
    staff ya provisionadas a mano (rol TECNICO/ADMIN) pueden entrar por
    Gmail — un email desconocido o con rol USUARIO se rechaza."""

    permission_classes = (permissions.AllowAny,)
    throttle_scope = "login"

    @method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=True))
    def post(self, request):
        # getattr, no settings.INTERNAL_AUTH_SECRET directo: el monolito
        # (config/settings.py) no declara este secreto — solo lo hacen
        # accounts.py/bff.py — y sin esto reventaría con AttributeError
        # ahí en vez de simplemente rechazar la request.
        expected = getattr(settings, "INTERNAL_AUTH_SECRET", None)
        if not expected or request.headers.get("X-Internal-Auth") != expected:
            return Response({"detail": _UNAUTHORIZED_DETAIL}, status=status.HTTP_403_FORBIDDEN)

        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "email requerido."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": _UNAUTHORIZED_DETAIL}, status=status.HTTP_403_FORBIDDEN)

        if user.role == Role.USUARIO:
            return Response({"detail": _UNAUTHORIZED_DETAIL}, status=status.HTTP_403_FORBIDDEN)

        token = CustomTokenObtainPairSerializer.get_token(user)
        return Response({"access": str(token.access_token), "refresh": str(token)})


class MeView(APIView):
    """Perfil del usuario autenticado."""

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(summary="Perfil propio", responses=UserSerializer)
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class TechnicianListCreateView(generics.ListCreateAPIView):
    """Solo Admin: crea/lista técnicos y administradores (RBAC)."""

    permission_classes = (IsAdmin,)
    serializer_class = TechnicianCreationSerializer

    def get_queryset(self):
        return User.objects.exclude(role="USUARIO").order_by("username")

    @extend_schema(summary="Listar técnicos/admins (solo Admin)", responses=UserSerializer(many=True))
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        return Response(UserSerializer(qs, many=True).data)


class TechnicianDeactivateView(APIView):
    """Solo Admin: activa/desactiva técnico sin borrar cuenta."""

    permission_classes = (IsAdmin,)

    @extend_schema(
        summary="Activar/desactivar técnico (solo Admin)",
        request=None,
        responses=UserSerializer,
    )
    def patch(self, request, user_id: int):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({"detail": "Usuario no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        user.is_active_technician = not user.is_active_technician
        user.save(update_fields=["is_active_technician"])
        return Response(UserSerializer(user).data)


class UserRoleChangeView(LoopRegisteringMixin, AsyncAPIView):
    """Cambia el rol de un usuario existente. Solo Admin. Reglas de
    negocio (no auto-degradarse, no dejar el sistema sin admins) viven
    en UserService, no acá."""

    permission_classes = (IsAdmin,)

    @extend_schema(
        summary="Cambiar rol de usuario (solo Admin)",
        description=(
            "No se puede cambiar el propio rol, ni quitar ADMIN al "
            "último administrador activo del sistema."
        ),
        request=RoleChangeSerializer,
        responses=UserSerializer,
    )
    async def patch(self, request, user_id: int):
        serializer = RoleChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        change_role = to_async(UserService().change_role)
        user = await change_role(
            user_id=user_id, new_role=serializer.validated_data["role"], actor=request.user
        )
        return Response(UserSerializer(user).data)
