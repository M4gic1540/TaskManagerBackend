"""Settings del microservicio Tickets. Su propia BD, sin `accounts`
instalado: la identidad del usuario se resuelve 100% desde los claims
del JWT (core/auth/jwt_claims_authentication.py), nunca contra una
tabla `User` local — este servicio no tiene una.

`django.contrib.auth` se mantiene instalado (con `AUTH_USER_MODEL`
apuntando al `auth.User` stock de Django, nunca usado) porque
`rest_framework_simplejwt.tokens` importa `django.contrib.auth.models`
a nivel de módulo — sin la app instalada, ese import revienta el
arranque aunque `JWTClaimsAuthentication` jamás llame a
`get_user_model()`."""
from .base import *  # NOSONAR

SERVICE_NAME = "tickets"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "adrf",
    "drf_spectacular",
    "core",
    "tickets",
]

AUTH_USER_MODEL = "auth.User"

MIDDLEWARE = [
    "core.tracing.middleware.RequestTracingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls_tickets"

REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "core.auth.jwt_claims_authentication.JWTClaimsAuthentication",
    ),
}

if IS_TESTING:
    DATABASES = {
        "default": {
            "ENGINE": SQLITE_ENGINE,
            "NAME": BASE_DIR / "test_tickets_db.sqlite3",
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": config("TICKETS_DB_ENGINE", default=SQLITE_ENGINE),
            "NAME": config("TICKETS_DB_NAME", default=str(BASE_DIR / "tickets_db.sqlite3")),
            "USER": config("TICKETS_DB_USER", default=""),
            "PASSWORD": config("TICKETS_DB_PASSWORD", default=""),
            "HOST": config("TICKETS_DB_HOST", default=""),
            "PORT": config("TICKETS_DB_PORT", default=""),
        },
    }
