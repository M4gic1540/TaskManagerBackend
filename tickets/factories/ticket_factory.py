"""Factory Pattern: construye el payload de creación de un Ticket,
manteniendo al Service ciego a los detalles de construcción."""
from __future__ import annotations


class TicketFactory:
    @staticmethod
    def build_creation_payload(
        *,
        title: str,
        description: str,
        category: str,
        requester,
        requester_email: str | None = None,
        external_message_id: str | None = None,
    ) -> dict:
        payload = {
            "title": title.strip(),
            "description": description.strip(),
            "category": category,
            "requester_id": requester.id,
            "requester_username": requester.username,
        }
        if requester_email is not None:
            payload["requester_email"] = requester_email
        if external_message_id is not None:
            payload["external_message_id"] = external_message_id
        return payload
