"""Observers de accounts. Registrados en accounts/apps.py (ready)."""
import logging

from core.events.base import EventObserver
from accounts.events import UserRoleChanged

logger = logging.getLogger("ticketera")


class UserAuditObserver(EventObserver):
    """Auditoría de cambios de rol (requisito explícito del rol Admin)."""

    def handle(self, event) -> None:
        if isinstance(event, UserRoleChanged):
            logger.info(
                "AUDIT user_role_changed id=%s %s->%s by=%s req=%s",
                event.user_id, event.old_role, event.new_role,
                event.changed_by_id, event.request_id,
            )
