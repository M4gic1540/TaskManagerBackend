"""Modelos de dominio de Tickets. Estados y transiciones válidas se
resuelven vía Strategy Pattern en tickets/strategies/, no aquí.

Los campos de usuario (requester, assigned_technician, author, etc.) NO
son ForeignKey a accounts.User: este servicio no tiene la tabla de
usuarios en su propia BD (microservicio con BD separada). Se guarda un
par id+username denormalizado, poblado desde los claims del JWT del
actor (o del payload de asignación) en el momento de la escritura —
ver core/auth/jwt_claims_authentication.py."""
import uuid

from django.db import models


class TicketStatus(models.TextChoices):
    ABIERTO = "ABIERTO", "Abierto"
    ASIGNADO = "ASIGNADO", "Asignado"
    EN_PROGRESO = "EN_PROGRESO", "En Progreso"
    RESUELTO = "RESUELTO", "Resuelto"
    CERRADO = "CERRADO", "Cerrado"
    CANCELADO = "CANCELADO", "Cancelado"


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
    status = models.CharField(
        max_length=20, choices=TicketStatus.choices, default=TicketStatus.ABIERTO, db_index=True
    )

    requester_id = models.PositiveBigIntegerField()
    requester_username = models.CharField(max_length=150)
    requester_email = models.EmailField(blank=True, default="")
    external_message_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True,
        help_text="Message-ID del correo entrante que originó el ticket (idempotencia del poller).",
    )
    assigned_technician_id = models.PositiveBigIntegerField(null=True, blank=True)
    assigned_technician_username = models.CharField(max_length=150, blank=True, default="")

    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tickets_ticket"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["assigned_technician_id", "status"]),
            models.Index(fields=["requester_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} - {self.title}"


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author_id = models.PositiveBigIntegerField()
    author_username = models.CharField(max_length=150)
    body = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        help_text="Nota interna (solo Técnico/Admin) — nunca se reenvía por correo al solicitante.",
    )
    external_message_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True,
        help_text="Message-ID del correo entrante que originó este comentario "
                   "(idempotencia del poller — evita duplicar la respuesta si el mismo correo se reprocesa).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_comment"
        ordering = ["created_at"]


class ResponseTemplate(models.Model):
    """Plantilla de respuesta reutilizable para responder tickets por
    correo. `{code}`/`{title}` se interpolan en el frontend con los
    datos del ticket antes de enviar."""

    name = models.CharField(max_length=150, unique=True)
    subject_template = models.CharField(max_length=255)
    body_template = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_response_template"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class TicketAttachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by_id = models.PositiveBigIntegerField()
    uploaded_by_username = models.CharField(max_length=150)
    file = models.FileField(upload_to="ticket_attachments/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_attachment"
        ordering = ["-uploaded_at"]


class TicketTimeLog(models.Model):
    """Tiempo trabajado por técnico (requerimiento explícito de rol Técnico)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="time_logs")
    technician_id = models.PositiveBigIntegerField()
    technician_username = models.CharField(max_length=150)
    minutes_spent = models.PositiveIntegerField()
    notes = models.CharField(max_length=255, blank=True)
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_timelog"
        ordering = ["-logged_at"]
