from django.urls import path, re_path

from core.health.registry import register_readiness_check
from core.health.views import LivenessView, ReadinessView
from gateway.views import GatewayProxyView

# El gateway no tiene BD propia con datos reales (ver
# config/service_settings/gateway.py) — su único readiness check
# razonable es "el proceso puede conectarse a su propia BD sqlite
# placeholder", así que no registra checks adicionales acá.

urlpatterns = [
    re_path(r"^api/v1/.*$", GatewayProxyView.as_view()),

    path("healthz/", LivenessView.as_view(), name="healthz"),
    path("readyz/", ReadinessView.as_view(), name="readyz"),
]
