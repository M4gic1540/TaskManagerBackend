from django.contrib import admin

from inventory.models import Asset, AssetHistory


class AssetHistoryInline(admin.TabularInline):
    model = AssetHistory
    extra = 0
    readonly_fields = ["changed_by", "action", "created_at"]
    can_delete = False


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "category", "status", "serial_number", "location", "responsible", "legacy_id"]
    list_filter = ["category", "status"]
    search_fields = ["code", "name", "serial_number", "location", "legacy_id"]
    readonly_fields = ["code", "public_uuid", "qr_image", "created_by", "created_at", "updated_at"]
    inlines = [AssetHistoryInline]
