from django.urls import path

from tickets.api.views import (
    DashboardSummaryView,
    ResponseTemplateDetailView,
    ResponseTemplateListCreateView,
    TicketAssignView,
    TicketAvailableListView,
    TicketCloseView,
    TicketCommentListCreateView,
    TicketDetailView,
    TicketListCreateView,
    TicketStatusChangeView,
    TicketTakeView,
    TicketTimeLogListCreateView,
)

urlpatterns = [
    path("", TicketListCreateView.as_view(), name="ticket-list-create"),
    path("dashboard/", DashboardSummaryView.as_view(), name="ticket-dashboard"),
    path("available/", TicketAvailableListView.as_view(), name="ticket-available"),
    path("templates/", ResponseTemplateListCreateView.as_view(), name="response-template-list-create"),
    path("templates/<int:template_id>/", ResponseTemplateDetailView.as_view(), name="response-template-detail"),
    path("<int:ticket_id>/", TicketDetailView.as_view(), name="ticket-detail"),
    path("<int:ticket_id>/take/", TicketTakeView.as_view(), name="ticket-take"),
    path("<int:ticket_id>/assign/", TicketAssignView.as_view(), name="ticket-assign"),
    path("<int:ticket_id>/status/", TicketStatusChangeView.as_view(), name="ticket-status"),
    path("<int:ticket_id>/close/", TicketCloseView.as_view(), name="ticket-close"),
    path("<int:ticket_id>/comments/", TicketCommentListCreateView.as_view(), name="ticket-comments"),
    path("<int:ticket_id>/time-logs/", TicketTimeLogListCreateView.as_view(), name="ticket-timelogs"),
]
