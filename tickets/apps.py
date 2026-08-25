from django.apps import AppConfig


class TicketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tickets"

    def ready(self):
        from core.events.base import EventBus
        from tickets.events import (
            TicketAssigned,
            TicketCommented,
            TicketCreated,
            TicketStatusChanged,
        )
        from tickets.observers import TicketAuditObserver, TicketNotificationObserver

        audit = TicketAuditObserver()
        notify = TicketNotificationObserver()

        for event_type in (TicketCreated, TicketAssigned, TicketStatusChanged, TicketCommented):
            EventBus.subscribe(event_type, audit)

        for event_type in (TicketCreated, TicketAssigned, TicketStatusChanged):
            EventBus.subscribe(event_type, notify)
