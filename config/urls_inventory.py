import re

from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve as serve_static
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from core.health.registry import (
    check_default_db,
    check_glpi_circuit_breaker,
    register_readiness_check,
)
from core.health.views import LivenessView, ReadinessView

register_readiness_check("database", check_default_db)
register_readiness_check("glpi_circuit_breaker", check_glpi_circuit_breaker)

urlpatterns = [
    path("api/v1/inventory/", include("inventory.urls")),

    path("healthz/", LivenessView.as_view(), name="healthz"),
    path("readyz/", ReadinessView.as_view(), name="readyz"),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

# Servir media (QRs) siempre, no solo en DEBUG: no hay nginx/servidor de
# estáticos delante de este contenedor, y DEBUG no se reenvía como env var
# al servicio inventory en docker-compose.yml. `static()` de Django hace un
# no-op si DEBUG=False pase lo que pase, así que acá se registra la vista
# `serve` directamente para no depender de DEBUG.
urlpatterns += [
    re_path(
        r"^%s(?P<path>.*)$" % re.escape(settings.MEDIA_URL.lstrip("/")),
        serve_static,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
