from rest_framework import serializers

from accounts.api.serializers import UserSerializer
from inventory.models import Asset, AssetHistory


class AssetHistorySerializer(serializers.ModelSerializer):
    changed_by = UserSerializer(read_only=True)

    class Meta:
        model = AssetHistory
        fields = ["id", "changed_by", "action", "created_at"]
        read_only_fields = fields


class AssetListSerializer(serializers.ModelSerializer):
    responsible = UserSerializer(read_only=True)

    class Meta:
        model = Asset
        fields = [
            "id", "code", "public_uuid", "name", "category", "status",
            "serial_number", "brand", "model", "location", "responsible",
            "qr_image", "legacy_id", "created_at",
        ]
        read_only_fields = fields


class AssetDetailSerializer(serializers.ModelSerializer):
    responsible = UserSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    history = AssetHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Asset
        fields = [
            "id", "code", "public_uuid", "name", "description", "category", "status",
            "serial_number", "brand", "model", "location", "responsible",
            "purchase_date", "warranty_until", "notes", "purchase_company",
            "invoice_number", "raw_type", "legacy_id", "qr_image",
            "created_by", "created_at", "updated_at", "history",
        ]
        read_only_fields = ["id", "code", "public_uuid", "qr_image", "created_by", "created_at", "updated_at", "history", "legacy_id"]


class AssetCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = [
            "name", "description", "category", "status", "serial_number",
            "brand", "model", "location", "responsible", "purchase_date",
            "warranty_until", "notes", "purchase_company", "invoice_number",
        ]

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("El nombre no puede estar vacío.")
        return value


class AssetUpdateSerializer(AssetCreateSerializer):
    """Mismos campos que creación, todos opcionales para PATCH."""

    class Meta(AssetCreateSerializer.Meta):
        extra_kwargs = {f: {"required": False} for f in AssetCreateSerializer.Meta.fields}


class AssetPublicSerializer(serializers.ModelSerializer):
    """Lo que ve cualquiera al escanear el QR. Sin datos sensibles de
    usuarios (solo nombre de responsable, sin email/username)."""

    responsible_name = serializers.SerializerMethodField()
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Asset
        fields = [
            "code", "name", "description", "category_display", "status_display",
            "serial_number", "brand", "model", "location",
            "responsible_name", "purchase_date", "warranty_until",
        ]
        read_only_fields = fields

    def get_responsible_name(self, obj) -> str:
        if obj.responsible:
            return obj.responsible.get_full_name() or obj.responsible.username
        return ""


class InventoryDashboardWarrantySerializer(serializers.Serializer):
    warning_window_days = serializers.IntegerField()
    expired_total = serializers.IntegerField()
    expiring_soon_total = serializers.IntegerField()
    with_warranty_data_total = serializers.IntegerField()


class InventoryDashboardSummarySerializer(serializers.Serializer):
    by_status = serializers.DictField(child=serializers.IntegerField())
    by_category = serializers.DictField(child=serializers.IntegerField())
    total = serializers.IntegerField()
    available_total = serializers.IntegerField()
    unassigned_responsible_total = serializers.IntegerField()
    top_locations = serializers.DictField(child=serializers.IntegerField())
    warranty = InventoryDashboardWarrantySerializer()
