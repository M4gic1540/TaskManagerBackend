"""Entrena el clasificador local de tickets (ver tickets/ml/). Uso:

    python manage.py train_ticket_classifier
    python manage.py train_ticket_classifier --seed-only

Por defecto entrena con el dataset semilla sintético
(tickets/ml/dataset/seed_tickets.csv) + todos los tickets reales que
existan en la BD (ya categorizados por un humano al crearlos — señal
real, mejor que la sintética). `--seed-only` entrena solo con el
dataset semilla: se usa en el build de la imagen Docker (sin BD
disponible todavía) y en tests, para no depender de datos reales ni de
que la BD esté migrada."""
from django.core.management.base import BaseCommand

from tickets.ml.train import train_and_save
from tickets.models import Ticket


class Command(BaseCommand):
    help = "Entrena el clasificador local de tickets (categoría, ver tickets/ml/)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed-only", action="store_true",
            help="Entrenar solo con el dataset semilla, sin sumar tickets reales de la BD.",
        )

    def handle(self, *args, **options):
        extra_rows = None
        if not options["seed_only"]:
            extra_rows = list(Ticket.objects.values("title", "description", "category"))
            if extra_rows:
                self.stdout.write(f"Sumando {len(extra_rows)} tickets reales de la BD al entrenamiento.")

        report = train_and_save(extra_rows=extra_rows)

        self.stdout.write(self.style.SUCCESS(f"Modelo entrenado con {report.n_samples} filas."))
        self.stdout.write(f"  accuracy categoría: {report.category_accuracy:.3f}")
