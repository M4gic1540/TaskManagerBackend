from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        from core.events.base import EventBus
        from accounts.events import UserRoleChanged
        from accounts.observers import UserAuditObserver

        EventBus.subscribe(UserRoleChanged, UserAuditObserver())
