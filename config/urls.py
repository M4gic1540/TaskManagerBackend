from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core.health.registry import check_default_db, check_glpi_circuit_breaker, register_readiness_check
from core.health.views import LivenessView, ReadinessView

# El monolito corre las 3 apps en un único proceso/BD, así que registra
# ambos checks (DB propia + circuit breaker de GLPI) en el mismo lugar.
# Cada microservicio (config/urls_*.py, Fase C) registra solo el suyo.
register_readiness_check("database", check_default_db)
register_readiness_check("glpi_circuit_breaker", check_glpi_circuit_breaker)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/tickets/", include("tickets.urls")),
    path("api/v1/inventory/", include("inventory.urls")),

    path("healthz/", LivenessView.as_view(), name="healthz"),
    path("readyz/", ReadinessView.as_view(), name="readyz"),

    # OpenAPI / documentación interactiva
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
