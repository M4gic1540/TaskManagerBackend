from rest_framework import serializers

from tickets.models import Ticket, TicketAttachment, TicketComment, TicketTimeLog


def _user_ref(id_value, username_value):
    """Referencia liviana {id, username} a un usuario de otro servicio
    (accounts), reconstruida desde los campos denormalizados guardados
    al escribir — sin joins ni llamadas HTTP. Mismo shape que antes
    exponía el UserSerializer anidado (el frontend solo consume `.id`
    y `.username`)."""
    if id_value is None:
        return None
    return {"id": id_value, "username": username_value}


class TicketCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = TicketComment
        fields = ["id", "author", "body", "created_at"]
        read_only_fields = ["id", "author", "created_at"]

    def get_author(self, obj):
        return _user_ref(obj.author_id, obj.author_username)


class TicketTimeLogSerializer(serializers.ModelSerializer):
    technician = serializers.SerializerMethodField()

    class Meta:
        model = TicketTimeLog
        fields = ["id", "technician", "minutes_spent", "notes", "logged_at"]
        read_only_fields = ["id", "technician", "logged_at"]

    def get_technician(self, obj):
        return _user_ref(obj.technician_id, obj.technician_username)


class TicketAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = ["id", "uploaded_by", "file", "original_filename", "uploaded_at"]
        read_only_fields = ["id", "uploaded_by", "uploaded_at"]

    def get_uploaded_by(self, obj):
        return _user_ref(obj.uploaded_by_id, obj.uploaded_by_username)


class TicketListSerializer(serializers.ModelSerializer):
    requester = serializers.SerializerMethodField()
    assigned_technician = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id", "code", "title", "category", "priority", "status",
            "requester", "assigned_technician", "created_at", "updated_at",
        ]

    def get_requester(self, obj):
        return _user_ref(obj.requester_id, obj.requester_username)

    def get_assigned_technician(self, obj):
        return _user_ref(obj.assigned_technician_id, obj.assigned_technician_username)


class TicketDetailSerializer(serializers.ModelSerializer):
    requester = serializers.SerializerMethodField()
    assigned_technician = serializers.SerializerMethodField()
    comments = TicketCommentSerializer(many=True, read_only=True)
    time_logs = TicketTimeLogSerializer(many=True, read_only=True)
    attachments = TicketAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id", "code", "title", "description", "category", "priority", "status",
            "requester", "assigned_technician", "resolution_notes",
            "comments", "time_logs", "attachments",
            "created_at", "updated_at", "closed_at",
        ]

    def get_requester(self, obj):
        return _user_ref(obj.requester_id, obj.requester_username)

    def get_assigned_technician(self, obj):
        return _user_ref(obj.assigned_technician_id, obj.assigned_technician_username)


class TicketCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField()
    category = serializers.ChoiceField(choices=Ticket._meta.get_field("category").choices)
    priority = serializers.ChoiceField(
        choices=Ticket._meta.get_field("priority").choices, required=False, allow_null=True
    )


class TicketAssignSerializer(serializers.Serializer):
    """El admin ya obtuvo id+username del técnico desde GET /technicians/
    (accounts) antes de asignar — evita que tickets tenga que consultar
    accounts por request para resolver el id."""

    technician_id = serializers.IntegerField()
    technician_username = serializers.CharField(max_length=150)


class TicketStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket._meta.get_field("status").choices)


class TicketCloseSerializer(serializers.Serializer):
    resolution_notes = serializers.CharField()


class TicketCommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField()


class TicketTimeLogCreateSerializer(serializers.Serializer):
    minutes_spent = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class DashboardSLASerializer(serializers.Serializer):
    sla_hours_config = serializers.DictField(child=serializers.IntegerField())
    breached_by_priority = serializers.DictField(child=serializers.IntegerField())
    total_breached = serializers.IntegerField()


class DashboardSummarySerializer(serializers.Serializer):
    by_status = serializers.DictField(child=serializers.IntegerField())
    by_priority = serializers.DictField(child=serializers.IntegerField())
    by_category = serializers.DictField(child=serializers.IntegerField())
    total = serializers.IntegerField()
    open_total = serializers.IntegerField()
    avg_resolution_hours = serializers.DictField(
        child=serializers.FloatField(allow_null=True), allow_null=True
    )
    sla = DashboardSLASerializer()
