"""
Django settings — ASDP Ticketera.
Config centralizada via variables de entorno (Twelve Factor App).
"""
import sys
from datetime import timedelta
from pathlib import Path


from decouple import Csv, config

try:
    import pymysql

    pymysql.install_as_MySQLdb()
    pymysql.version_info = (2, 2, 1, "final", 0)
except ImportError:
    pass


BASE_DIR = Path(__file__).resolve().parent.parent

# --- Core -------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

AUTH_USER_MODEL = "accounts.User"

# --- Apps ---------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 3rd party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "adrf",
    "drf_spectacular",
    "corsheaders",
    "django_ratelimit",
    # local
    "core",
    "accounts",
    "tickets",
    "inventory",
]

MIDDLEWARE = [
    "core.tracing.middleware.RequestTracingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Databases (default: SQLite local; glpi: MariaDB remota de solo lectura) ---
IS_TESTING = "pytest" in sys.modules or "test" in sys.argv or any("pytest" in arg for arg in sys.argv)
SQLITE_ENGINE = "django.db.backends.sqlite3"

if IS_TESTING:
    DATABASES = {
        "default": {
            "ENGINE": SQLITE_ENGINE,
            "NAME": BASE_DIR / "test_db.sqlite3",
        },
        "glpi": {
            "ENGINE": SQLITE_ENGINE,
            "NAME": BASE_DIR / "test_db.sqlite3",
        },
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": SQLITE_ENGINE,
            "NAME": BASE_DIR / "db.sqlite3",
        },
        "glpi": {
            # Sin defaults para host/user/password: si no están en el .env,
            # falla explícito (UndefinedValueError) en vez de intentar
            # conectarse en silencio a una IP interna hardcodeada.
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





# --- Password validation --------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n -------------------------------------------------------------
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# URL base pública (frontend) donde el QR redirige. Ej: PUBLIC_ASSET_BASE_URL=https://ticketera.cmm.uchile.cl/inventario
PUBLIC_ASSET_BASE_URL = config(
    "PUBLIC_ASSET_BASE_URL", default="http://localhost:5173/inventario"
)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Cache (usado por django-ratelimit; cambiar a Redis en prod) ------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003", "django_ratelimit.W001"]

# --- DRF ----------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "user": "120/min",
        "anon": "20/min",
        "login": "5/min",
    },
    "EXCEPTION_HANDLER": "core.api.exception_handler.domain_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# --- drf-spectacular (OpenAPI/Swagger) -------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "ASDP Ticketera API",
    "DESCRIPTION": (
        "API de gestión de tickets IT con 3 roles (Administrador, Técnico, "
        "Usuario). Auth JWT vía Bearer token — usar /api/v1/auth/login/ "
        "para obtener access/refresh."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1"

}

# --- JWT ------------------------------------------------------------------
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --- CORS -----------------------------------------------------------------
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS", default="http://localhost:5173", cast=Csv()
)
CORS_ALLOW_CREDENTIALS = True

# --- Security headers (reforzado en core/middleware.py) -------------------
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=False, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=False, cast=bool)
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# --- SLA (horas máximas por prioridad, desde creación hasta cierre/ahora) --
TICKET_SLA_HOURS = {
    "CRITICA": 2,
    "ALTA": 4,
    "MEDIA": 8,
    "BAJA": 24,
}

# --- Inventario: ventana de aviso de garantías próximas a vencer (días) ---
INVENTORY_WARRANTY_WARNING_DAYS = 30

# --- Circuit breaker (llamadas de inventory a la BD externa GLPI) ---------
GLPI_BREAKER_FAIL_MAX = config("GLPI_BREAKER_FAIL_MAX", default=5, cast=int)
GLPI_BREAKER_RESET_TIMEOUT = config("GLPI_BREAKER_RESET_TIMEOUT", default=30, cast=int)

# --- Cache-aside de lecturas a GLPI (list_assets / get_dashboard_summary) --
# 0 desactiva el cacheo (cada llamada golpea la BD externa de nuevo).
GLPI_CACHE_TTL_SECONDS = config("GLPI_CACHE_TTL_SECONDS", default=60, cast=int)

# --- Email (notificación de ticket creado, ver tickets/observers.py) ------
# Backend por default = consola: sin credenciales SMTP reales configuradas,
# el correo se imprime al log en vez de fallar o quedar silenciosamente sin
# enviarse — hace falta setear EMAIL_HOST_USER/PASSWORD reales para que
# salga de verdad.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="no-reply@cmm.uchile.cl")

# A quién avisar cada vez que se crea un ticket, sin importar prioridad.
TICKET_NOTIFICATION_EMAIL = config(
    "TICKET_NOTIFICATION_EMAIL", default="sistemas@cmm.uchile.cl"
)

# Para armar un link clickeable al ticket dentro del correo.
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:5173")

# --- Logging ----------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_tracing": {"()": "core.tracing.logging_filter.RequestTracingFilter"},
    },
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} [req={request_id} user={user_id}] {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["request_tracing"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "ticketera": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
