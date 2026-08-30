from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.models import Role, User


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Agrega `role` y `username` al payload del JWT para que el
    frontend no necesite un request extra para conocer el rol."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["username"] = user.username
        # Usado por tickets (self_assign) para no dejar auto-tomar tickets
        # a un técnico desactivado, sin que tickets tenga que consultar
        # la BD de accounts para saberlo (core/auth/jwt_claims_authentication.py).
        token["is_active_technician"] = user.is_active_technician
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        # El usuario final ya no tiene cuenta en el sistema — solo
        # interactúa por correo (ver tickets/management/commands/
        # poll_inbound_email.py). Bloquear acá cubre tanto /auth/login/
        # directo como bff/auth_views.py::LoginView (que solo lo proxya).
        if self.user.role == Role.USUARIO:
            raise serializers.ValidationError("Este rol no tiene acceso al sistema.")
        return data


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "role", "phone"]
        read_only_fields = ["id"]


class TechnicianCreationSerializer(serializers.ModelSerializer):
    """Solo accesible por Admin: crea usuarios con rol Técnico o Admin."""

    password = serializers.CharField(write_only=True, min_length=10)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "phone", "password", "role"]
        read_only_fields = ["id"]

    def validate_role(self, value):
        if value not in (Role.TECNICO, Role.ADMIN):
            raise serializers.ValidationError("Rol debe ser TECNICO o ADMIN.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class RoleChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)
