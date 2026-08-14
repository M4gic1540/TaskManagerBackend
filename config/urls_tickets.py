from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core.health.registry import check_default_db, register_readiness_check
from core.health.views import LivenessView, ReadinessView

register_readiness_check("database", check_default_db)

urlpatterns = [
    path("api/v1/tickets/", include("tickets.urls")),

    path("healthz/", LivenessView.as_view(), name="healthz"),
    path("readyz/", ReadinessView.as_view(), name="readyz"),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
