from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrador"
    TECNICO = "TECNICO", "Técnico"
    USUARIO = "USUARIO", "Usuario"
