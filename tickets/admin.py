from django.contrib import admin

from tickets.models import (
    ResponseTemplate,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketTimeLog,
)


class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0


class TicketTimeLogInline(admin.TabularInline):
    model = TicketTimeLog
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "status", "category", "requester_username", "assigned_technician_username")
    list_filter = ("status", "category")
    search_fields = ("code", "title", "description")
    inlines = [TicketCommentInline, TicketTimeLogInline]


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "original_filename", "uploaded_by_username", "uploaded_at")


@admin.register(ResponseTemplate)
class ResponseTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "subject_template", "updated_at")
    search_fields = ("name", "subject_template", "body_template")
