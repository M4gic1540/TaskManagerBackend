from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrador"
    TECNICO = "TECNICO", "Técnico"
    USUARIO = "USUARIO", "Usuario"


class User(AbstractUser):
    """Usuario con rol único (RBAC simple). Password hasheado por
    Django (PBKDF2-SHA256 default) — no se toca manualmente el hash.
    """

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.USUARIO,
        db_index=True,
    )
    phone = models.CharField(max_length=20, blank=True)
    is_active_technician = models.BooleanField(
        default=True,
        help_text="Permite desactivar técnico sin borrar cuenta.",
    )

    class Meta:
        db_table = "accounts_user"
        indexes = [models.Index(fields=["role", "is_active"])]

    def __str__(self) -> str:
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_technician(self) -> bool:
        return self.role == Role.TECNICO

    @property
    def is_requester(self) -> bool:
        return self.role == Role.USUARIO
