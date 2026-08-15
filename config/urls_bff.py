from django.urls import path, re_path

from bff.views import BFFProxyView
from core.health.views import LivenessView, ReadinessView

# El BFF no tiene BD propia con datos reales (ver
# config/service_settings/bff.py) — su único readiness check razonable
# es "el proceso puede conectarse a su propia BD sqlite placeholder",
# así que no registra checks adicionales acá (mismo criterio que
# config/urls_gateway.py).
#
# Fase 1: todo /api/v1/... pasa por el proxy puro hacia el Gateway. Los
# endpoints propios del BFF (auth de sesión, agregación de dashboard)
# se agregan bajo /api/v1/bff/... en las siguientes fases, ANTES de
# este catch-all (mismo criterio de especificidad que
# gateway/views.py._ROUTE_TABLE).
urlpatterns = [
    re_path(r"^api/v1/.*$", BFFProxyView.as_view()),

    path("healthz/", LivenessView.as_view(), name="healthz"),
    path("readyz/", ReadinessView.as_view(), name="readyz"),
]
