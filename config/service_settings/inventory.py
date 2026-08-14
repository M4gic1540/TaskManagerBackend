"""Settings del microservicio Inventory. Su propia BD default + la
conexión externa 'glpi' (MariaDB de solo lectura) — es el único
servicio que la usa. Sin `accounts` instalado: la identidad se resuelve
desde los claims del JWT, igual que tickets (ver tickets.py para el
porqué de mantener `django.contrib.auth` instalado con `auth.User`)."""
from .base import *  # noqa: F401,F403

SERVICE_NAME = "inventory"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "adrf",
    "drf_spectacular",
    "core",
    "inventory",
]

AUTH_USER_MODEL = "auth.User"

MIDDLEWARE = [
    "core.tracing.middleware.RequestTracingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls_inventory"

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
            "NAME": BASE_DIR / "test_inventory_db.sqlite3",
        },
        "glpi": {
            "ENGINE": SQLITE_ENGINE,
            "NAME": BASE_DIR / "test_inventory_db.sqlite3",
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": config("INVENTORY_DB_ENGINE", default=SQLITE_ENGINE),
            "NAME": config("INVENTORY_DB_NAME", default=str(BASE_DIR / "inventory_db.sqlite3")),
        },
        "glpi": {
            "ENGINE": config("DB_ENGINE", default="django.db.backends.mysql"),
            "NAME": config("DB_NAME", default="glpi"),
            "USER": config("DB_USER"),
            "PASSWORD": config("DB_PASSWORD"),
            "HOST": config("DB_HOST"),
            "PORT": config("DB_PORT", default="3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        },
    }
