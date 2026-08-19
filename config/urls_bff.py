from django.urls import path, re_path

from bff.auth_views import LoginView, LogoutView, MeView
from bff.views import BFFProxyView
from core.health.views import LivenessView, ReadinessView

# El BFF no tiene BD propia con datos reales (ver
# config/service_settings/bff.py) — su único readiness check razonable
# es "el proceso puede conectarse a su propia BD sqlite placeholder",
# así que no registra checks adicionales acá (mismo criterio que
# config/urls_gateway.py).
#
# Fase 2: los endpoints propios del BFF (auth de sesión) van ANTES del
# catch-all /api/v1/... (mismo criterio de especificidad que
# gateway/views.py._ROUTE_TABLE) — si no, el catch-all se los comería.
# La agregación de dashboard (fase 3) se agrega acá mismo, también
# antes del catch-all.
urlpatterns = [
    path("api/v1/bff/auth/login/", LoginView.as_view(), name="bff-login"),
    path("api/v1/bff/auth/logout/", LogoutView.as_view(), name="bff-logout"),
    path("api/v1/bff/auth/me/", MeView.as_view(), name="bff-me"),

    re_path(r"^api/v1/.*$", BFFProxyView.as_view()),
    re_path(r"^media/.*$", BFFProxyView.as_view()),

    path("healthz/", LivenessView.as_view(), name="healthz"),
    path("readyz/", ReadinessView.as_view(), name="readyz"),
]
