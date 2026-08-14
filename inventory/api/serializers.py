from rest_framework import serializers

from inventory.models import Asset, AssetHistory


def _user_ref(id_value, username_value):
    """Referencia liviana {id, username} a un usuario de otro servicio
    (accounts), reconstruida desde los campos denormalizados guardados
    al escribir — sin joins ni llamadas HTTP. Mismo shape que antes
    exponía el UserSerializer anidado (el frontend solo consume `.id`
    y `.username`)."""
    if id_value is None:
        return None
    return {"id": id_value, "username": username_value}


class AssetHistorySerializer(serializers.ModelSerializer):
    changed_by = serializers.SerializerMethodField()

    class Meta:
        model = AssetHistory
        fields = ["id", "changed_by", "action", "created_at"]
        read_only_fields = fields

    def get_changed_by(self, obj):
        return _user_ref(obj.changed_by_id, obj.changed_by_username)


class AssetListSerializer(serializers.ModelSerializer):
    responsible = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = [
            "id", "code", "public_uuid", "name", "category", "status",
            "serial_number", "brand", "model", "location", "responsible",
            "qr_image", "legacy_id", "created_at",
        ]
        read_only_fields = fields

    def get_responsible(self, obj):
        return _user_ref(obj.responsible_id, obj.responsible_username)


class AssetDetailSerializer(serializers.ModelSerializer):
    responsible = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
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

    def get_responsible(self, obj):
        return _user_ref(obj.responsible_id, obj.responsible_username)

    def get_created_by(self, obj):
        return _user_ref(obj.created_by_id, obj.created_by_username)


class AssetCreateSerializer(serializers.ModelSerializer):
    responsible_id = serializers.IntegerField(required=False, allow_null=True)
    responsible_username = serializers.CharField(
        max_length=150, required=False, allow_blank=True, default=""
    )

    class Meta:
        model = Asset
        fields = [
            "name", "description", "category", "status", "serial_number",
            "brand", "model", "location", "responsible_id", "responsible_username",
            "purchase_date", "warranty_until", "notes", "purchase_company", "invoice_number",
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
        return obj.responsible_username or ""


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
