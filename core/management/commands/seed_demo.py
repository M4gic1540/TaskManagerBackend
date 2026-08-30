"""Comando de seed: crea usuarios demo (admin/tecnico/usuario) + un
ticket de ejemplo. Uso: python manage.py seed_demo"""
import secrets
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role, User
from tickets.models import TicketCategory
from tickets.services.ticket_service import TicketService


class Command(BaseCommand):
    help = "Crea datos demo: admin, técnico, usuario y un ticket de ejemplo."

    @transaction.atomic
    def handle(self, *args, **options):
        admin_pwd = secrets.token_urlsafe(16)
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@cmm.cl", "role": Role.ADMIN, "is_staff": True, "is_superuser": True},
        )
        if created:
            admin.set_password(admin_pwd)
            admin.save()
            self.stdout.write(self.style.SUCCESS(f"Usuario admin creado. Contraseña: {admin_pwd}"))

        tecnico_pwd = secrets.token_urlsafe(16)
        tecnico, created = User.objects.get_or_create(
            username="tecnico1",
            defaults={"email": "tecnico1@cmm.cl", "role": Role.TECNICO},
        )
        if created:
            tecnico.set_password(tecnico_pwd)
            tecnico.save()
            self.stdout.write(self.style.SUCCESS(f"Usuario tecnico1 creado. Contraseña: {tecnico_pwd}"))

        usuario_pwd = secrets.token_urlsafe(16)
        usuario, created = User.objects.get_or_create(
            username="usuario1",
            defaults={"email": "usuario1@cmm.cl", "role": Role.USUARIO},
        )
        if created:
            usuario.set_password(usuario_pwd)
            usuario.save()
            self.stdout.write(self.style.SUCCESS(f"Usuario usuario1 creado. Contraseña: {usuario_pwd}"))

        service = TicketService()
        ticket = service.create_ticket(
            title="No enciende el computador de sala 204",
            description="El equipo no enciende desde esta mañana, luz de fuente parpadea.",
            category=TicketCategory.HARDWARE,
            requester=usuario,
        )
        service.assign_technician(
            ticket_id=ticket.id,
            technician_id=tecnico.id,
            technician_username=tecnico.username,
            actor=admin,
        )
        self.stdout.write(self.style.SUCCESS(f"Ticket demo creado: {ticket.code}"))
