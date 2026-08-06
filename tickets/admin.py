from django.contrib import admin

from tickets.models import Ticket, TicketAttachment, TicketComment, TicketTimeLog


class TicketCommentInline(admin.TabularInline):
    model = TicketComment
    extra = 0


class TicketTimeLogInline(admin.TabularInline):
    model = TicketTimeLog
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "status", "priority", "category", "requester", "assigned_technician")
    list_filter = ("status", "priority", "category")
    search_fields = ("code", "title", "description")
    inlines = [TicketCommentInline, TicketTimeLogInline]


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "original_filename", "uploaded_by", "uploaded_at")
