"""Modelos de dominio de Tickets. Estados y transiciones válidas se
resuelven vía Strategy Pattern en tickets/strategies/, no aquí."""
import uuid

from django.conf import settings
from django.db import models


class TicketStatus(models.TextChoices):
    ABIERTO = "ABIERTO", "Abierto"
    ASIGNADO = "ASIGNADO", "Asignado"
    EN_PROGRESO = "EN_PROGRESO", "En Progreso"
    RESUELTO = "RESUELTO", "Resuelto"
    CERRADO = "CERRADO", "Cerrado"
    CANCELADO = "CANCELADO", "Cancelado"


class TicketPriority(models.TextChoices):
    BAJA = "BAJA", "Baja"
    MEDIA = "MEDIA", "Media"
    ALTA = "ALTA", "Alta"
    CRITICA = "CRITICA", "Crítica"


class TicketCategory(models.TextChoices):
    HARDWARE = "HARDWARE", "Hardware"
    SOFTWARE = "SOFTWARE", "Software"
    RED = "RED", "Red / Conectividad"
    ACCESOS = "ACCESOS", "Accesos y Cuentas"
    RESERVA_DE_SALAS = "RESERVA_DE_SALAS", "Reserva de Salas"
    RECLAMOS = "RECLAMOS", "Reclamos"
    SUGERENCIAS = "SUGERENCIAS", "Sugerencias"
    OTRO = "OTRO", "Otro"


def _ticket_code() -> str:
    return f"TCK-{uuid.uuid4().hex[:8].upper()}"


class Ticket(models.Model):
    code = models.CharField(max_length=20, unique=True, default=_ticket_code, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=TicketCategory.choices)
    priority = models.CharField(
        max_length=20, choices=TicketPriority.choices, default=TicketPriority.MEDIA
    )
    status = models.CharField(
        max_length=20, choices=TicketStatus.choices, default=TicketStatus.ABIERTO, db_index=True
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets_created"
    )
    assigned_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets_assigned",
    )

    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tickets_ticket"
        indexes = [
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["assigned_technician", "status"]),
            models.Index(fields=["requester"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} - {self.title}"


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_comment"
        ordering = ["created_at"]


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    file = models.FileField(upload_to="ticket_attachments/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_attachment"
        ordering = ["-uploaded_at"]


class TicketTimeLog(models.Model):
    """Tiempo trabajado por técnico (requerimiento explícito de rol Técnico)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="time_logs")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    minutes_spent = models.PositiveIntegerField()
    notes = models.CharField(max_length=255, blank=True)
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_timelog"
        ordering = ["-logged_at"]
