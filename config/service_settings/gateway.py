"""Settings del API Gateway: único punto de entrada expuesto al
browser/frontend. No monta ninguna app de dominio (accounts/tickets/
inventory) — solo reenvía por prefijo de path (gateway/views.py) a las
URLs de los otros servicios, leídas de variables de entorno. CORS vive
acá y solo acá: los servicios internos no son alcanzables directo
desde el browser."""
from .base import *  # NOSONAR

SERVICE_NAME = "gateway"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core",
    "gateway",
]

MIDDLEWARE = [
    "core.tracing.middleware.RequestTracingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls_gateway"

# El gateway no autentica nada: reenvía el header Authorization tal
# cual al servicio destino, que es quien valida el JWT. Sin auth
# classes evita depender de django.contrib.auth (que rest_framework_simplejwt
# importa a nivel de módulo) solo para no usarlo nunca acá. `UNAUTHENTICATED_USER`
# también hay que pisarlo a None explícito: DRF lo resuelve por default a
# `django.contrib.auth.models.AnonymousUser` en cuanto algo toca `request.user`
# (ej. los health checks, que son APIView) — sin esto, igual dispara el mismo
# import de django.contrib.auth.models pese a authentication_classes vacío.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": (),
    "UNAUTHENTICATED_USER": None,
    "UNAUTHENTICATED_TOKEN": None,
}

# El gateway no tiene datos propios que persistir; DATABASES existe
# solo porque Django lo exige para arrancar (locmem cache/ratelimit no
# lo necesitan, y ninguna app instalada acá tiene modelos/migraciones).
# El default de GATEWAY_DB_NAME sigue en BASE_DIR para dev local sin
# Docker (ahí es escribible); en contenedor, docker-compose lo pisa a
# /app/data/gateway_db.sqlite3 — el resto de /app queda de solo lectura
# para el usuario 'app' (ver Dockerfile), así que crear el sqlite ahí
# desde cero falla en un clone limpio sin este archivo ya generado.
DATABASES = {
    "default": {
        "ENGINE": SQLITE_ENGINE,
        "NAME": (
            BASE_DIR / "test_gateway_db.sqlite3"
            if IS_TESTING
            else config("GATEWAY_DB_NAME", default=str(BASE_DIR / "gateway_db.sqlite3"))
        ),
    },
}

# URLs de los servicios upstream (docker-compose los resuelve por
# nombre de servicio; en dev local, por puerto).
ACCOUNTS_SERVICE_URL = config("ACCOUNTS_SERVICE_URL", default="http://localhost:8001")
TICKETS_SERVICE_URL = config("TICKETS_SERVICE_URL", default="http://localhost:8002")
INVENTORY_SERVICE_URL = config("INVENTORY_SERVICE_URL", default="http://localhost:8003")
GATEWAY_UPSTREAM_TIMEOUT = config("GATEWAY_UPSTREAM_TIMEOUT", default=10.0, cast=float)
