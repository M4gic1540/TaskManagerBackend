"""Specifications concretas de Ticket, componibles con &, |, ~."""
from django.db.models import Q

from core.specifications.base import Specification


class TicketByStatusSpec(Specification):
    def __init__(self, status: str):
        self.status = status

    def to_query(self) -> Q:
        return Q(status=self.status)


class TicketByPrioritySpec(Specification):
    def __init__(self, priority: str):
        self.priority = priority

    def to_query(self) -> Q:
        return Q(priority=self.priority)


class TicketByCategorySpec(Specification):
    def __init__(self, category: str):
        self.category = category

    def to_query(self) -> Q:
        return Q(category=self.category)


class TicketAssignedToSpec(Specification):
    def __init__(self, technician_id: int):
        self.technician_id = technician_id

    def to_query(self) -> Q:
        return Q(assigned_technician_id=self.technician_id)


class TicketRequestedBySpec(Specification):
    def __init__(self, requester_id: int):
        self.requester_id = requester_id

    def to_query(self) -> Q:
        return Q(requester_id=self.requester_id)


class TicketUnassignedSpec(Specification):
    def to_query(self) -> Q:
        return Q(assigned_technician_id__isnull=True)


class TicketSearchTextSpec(Specification):
    """Búsqueda simple sobre título/descripción/código."""

    def __init__(self, text: str):
        self.text = text

    def to_query(self) -> Q:
        return (
            Q(title__icontains=self.text)
            | Q(description__icontains=self.text)
            | Q(code__icontains=self.text)
        )
