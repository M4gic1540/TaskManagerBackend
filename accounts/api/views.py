from adrf.views import APIView as AsyncAPIView
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.models import User
from accounts.permissions import IsAdmin
from accounts.services.user_service import UserService
from core.async_support.bridge import to_async
from core.async_support.mixins import LoopRegisteringMixin
from accounts.api.serializers import (
    CustomTokenObtainPairSerializer,
    RoleChangeSerializer,
    TechnicianCreationSerializer,
    UserRegistrationSerializer,
    UserSerializer,
)


class CustomTokenObtainPairView(TokenObtainPairView):
    """Login: emite access + refresh token con claims de rol."""

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = (permissions.AllowAny,)
    throttle_scope = "login"

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RegisterView(generics.CreateAPIView):
    """Registro público. Siempre crea rol USUARIO (Solicitante)."""

    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = (permissions.AllowAny,)

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


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
