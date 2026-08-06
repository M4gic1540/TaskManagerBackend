from rest_framework import serializers

from accounts.api.serializers import UserSerializer
from tickets.models import Ticket, TicketAttachment, TicketComment, TicketTimeLog


class TicketCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = TicketComment
        fields = ["id", "author", "body", "created_at"]
        read_only_fields = ["id", "author", "created_at"]


class TicketTimeLogSerializer(serializers.ModelSerializer):
    technician = UserSerializer(read_only=True)

    class Meta:
        model = TicketTimeLog
        fields = ["id", "technician", "minutes_spent", "notes", "logged_at"]
        read_only_fields = ["id", "technician", "logged_at"]


class TicketAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = UserSerializer(read_only=True)

    class Meta:
        model = TicketAttachment
        fields = ["id", "uploaded_by", "file", "original_filename", "uploaded_at"]
        read_only_fields = ["id", "uploaded_by", "uploaded_at"]


class TicketListSerializer(serializers.ModelSerializer):
    requester = UserSerializer(read_only=True)
    assigned_technician = UserSerializer(read_only=True)

    class Meta:
        model = Ticket
        fields = [
            "id", "code", "title", "category", "priority", "status",
            "requester", "assigned_technician", "created_at", "updated_at",
        ]


class TicketDetailSerializer(serializers.ModelSerializer):
    requester = UserSerializer(read_only=True)
    assigned_technician = UserSerializer(read_only=True)
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


class TicketCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField()
    category = serializers.ChoiceField(choices=Ticket._meta.get_field("category").choices)
    priority = serializers.ChoiceField(
        choices=Ticket._meta.get_field("priority").choices, required=False, allow_null=True
    )


class TicketAssignSerializer(serializers.Serializer):
    technician_id = serializers.IntegerField()


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
