from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_active", "is_active_technician")
    list_filter = ("role", "is_active", "is_active_technician")
    fieldsets = UserAdmin.fieldsets + (
        ("Ticketera", {"fields": ("role", "phone", "is_active_technician")}),
    )
