"""Settings del microservicio Accounts (identidad/auth). Es el único
servicio que conserva `django.contrib.auth`/`admin`/`sessions`/
`messages` y `rest_framework_simplejwt` instalados: es dueño de la
tabla `User` real y sigue emitiendo/refrescando/revocando JWT contra
su propia BD, con la autenticación normal de simplejwt (no por claims).

CORS no vive acá: el único punto expuesto al browser es el API Gateway
(config/service_settings/gateway.py)."""
from .base import *  # NOSONAR

SERVICE_NAME = "accounts"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "adrf",
    "drf_spectacular",
    "django_ratelimit",
    "core",
    "accounts",
]

MIDDLEWARE = [
    "core.tracing.middleware.RequestTracingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls_accounts"

if IS_TESTING:
    DATABASES = {
        "default": {
            "ENGINE": SQLITE_ENGINE,
            "NAME": BASE_DIR / "test_accounts_db.sqlite3",
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": config("ACCOUNTS_DB_ENGINE", default=SQLITE_ENGINE),
            "NAME": config("ACCOUNTS_DB_NAME", default=str(BASE_DIR / "accounts_db.sqlite3")),
            "USER": config("ACCOUNTS_DB_USER", default=""),
            "PASSWORD": config("ACCOUNTS_DB_PASSWORD", default=""),
            "HOST": config("ACCOUNTS_DB_HOST", default=""),
            "PORT": config("ACCOUNTS_DB_PORT", default=""),
        },
    }
