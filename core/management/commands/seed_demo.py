"""Comando de seed: crea usuarios demo (admin/tecnico/usuario) + un
ticket de ejemplo. Uso: python manage.py seed_demo"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role, User
from tickets.models import TicketCategory
from tickets.services.ticket_service import TicketService


class Command(BaseCommand):
    help = "Crea datos demo: admin, técnico, usuario y un ticket de ejemplo."

    @transaction.atomic
    def handle(self, *args, **options):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={"email": "admin@cmm.cl", "role": Role.ADMIN, "is_staff": True, "is_superuser": True},
        )
        if created:
            admin.set_password("Admin12345!")
            admin.save()
            self.stdout.write(self.style.SUCCESS("Usuario admin creado (admin / Admin12345!)"))

        tecnico, created = User.objects.get_or_create(
            username="tecnico1",
            defaults={"email": "tecnico1@cmm.cl", "role": Role.TECNICO},
        )
        if created:
            tecnico.set_password("Tecnico12345!")
            tecnico.save()
            self.stdout.write(self.style.SUCCESS("Usuario tecnico1 creado (tecnico1 / Tecnico12345!)"))

        usuario, created = User.objects.get_or_create(
            username="usuario1",
            defaults={"email": "usuario1@cmm.cl", "role": Role.USUARIO},
        )
        if created:
            usuario.set_password("Usuario12345!")
            usuario.save()
            self.stdout.write(self.style.SUCCESS("Usuario usuario1 creado (usuario1 / Usuario12345!)"))

        service = TicketService()
        ticket = service.create_ticket(
            title="No enciende el computador de sala 204",
            description="El equipo no enciende desde esta mañana, luz de fuente parpadea.",
            category=TicketCategory.HARDWARE,
            priority=None,
            requester=usuario,
        )
        service.assign_technician(ticket_id=ticket.id, technician=tecnico, actor=admin)
        self.stdout.write(self.style.SUCCESS(f"Ticket demo creado: {ticket.code}"))
