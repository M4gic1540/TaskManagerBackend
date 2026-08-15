"""Settings del BFF (Backend-For-Frontend): único punto de entrada
pensado para el SPA (Vite/React) — ver plan en
.claude/plans/zippy-bubbling-pumpkin.md. Fase 1 (este archivo hoy):
proxy transparente puro hacia el Gateway, mismo criterio que
gateway.py (sin auth propia, reenvía Authorization tal cual). Las
fases siguientes agregan sesión server-side (cookie httpOnly, JWT
guardado en Redis) y el endpoint de agregación del dashboard — en ese
momento este archivo suma django.contrib.sessions + CsrfViewMiddleware
+ CACHES apuntando a Redis."""
from .base import *  # NOSONAR

SERVICE_NAME = "bff"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core",
    "bff",
]

MIDDLEWARE = [
    "core.tracing.middleware.RequestTracingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls_bff"

# Fase 1: el BFF todavía no autentica nada, solo reenvía Authorization
# tal cual (igual que el Gateway hoy). Mismo motivo que
# config/service_settings/gateway.py para pisar estos tres valores.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": (),
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
}

# El BFF no tiene datos propios que persistir en BD relacional (la
# sesión, cuando se agregue, vive en Redis vía CACHES — ver plan);
# DATABASES existe solo porque Django lo exige para arrancar, mismo
# placeholder (y mismo motivo para leer BFF_DB_NAME de env en vez de
# hardcodear BASE_DIR) que usa gateway.py.
DATABASES = {
    "default": {
        "ENGINE": SQLITE_ENGINE,
        "NAME": (
            BASE_DIR / "test_bff_db.sqlite3"
            if IS_TESTING
            else config("BFF_DB_NAME", default=str(BASE_DIR / "bff_db.sqlite3"))
        ),
    },
}

# Único upstream del BFF: el Gateway (que a su vez rutea a
# accounts/tickets/inventory). docker-compose lo resuelve por nombre
# de servicio; en dev local, por puerto.
GATEWAY_URL = config("GATEWAY_URL", default="http://localhost:8000")
BFF_UPSTREAM_TIMEOUT = config("BFF_UPSTREAM_TIMEOUT", default=10.0, cast=float)
