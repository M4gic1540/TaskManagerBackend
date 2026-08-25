"""Settings del BFF (Backend-For-Frontend): único punto de entrada
pensado para el SPA (Vite/React) — ver plan en
.claude/plans/zippy-bubbling-pumpkin.md. Fase 2 (este archivo hoy):
sesión server-side con cookie httpOnly (el JWT nunca llega al browser,
vive en la sesión, guardada en Redis) + CSRF double-submit para las
mutaciones. Solo django.contrib.sessions, no el stack completo de
django.contrib.auth/admin: el BFF no resuelve un User de Django, solo
guarda claims que ya validó el Gateway/accounts (mismo criterio que
tickets.py/inventory.py para no instalar accounts)."""
from .base import *  # NOSONAR

SERVICE_NAME = "bff"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
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

# --- Sesión server-side (fase 2) --------------------------------------
# La sesión vive en Redis (CACHES abajo), nunca en la BD del BFF —
# SESSION_ENGINE cache-backed no toca DATABASES para nada. En test se
# pisa a locmem: los tests no dependen de un Redis real corriendo
# (mismo criterio que el IS_TESTING de DATABASES arriba).
if IS_TESTING:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": config("REDIS_URL", default="redis://localhost:6379/0"),
        }
    }

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
# Mismo TTL que el refresh token (ver SIMPLE_JWT en config/settings.py):
# no tiene sentido que la cookie de sesión sobreviva más que el token
# que guarda adentro.
SESSION_COOKIE_AGE = int(SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())
SESSION_SAVE_EVERY_REQUEST = True
# httpOnly ya es el default de Django (SESSION_COOKIE_HTTPONLY) — el
# punto entero de esta fase es que el JWT nunca sea legible por JS.
# "Lax" alcanza: browser/BFF quedan same-site en dev (mismo host
# "localhost", solo cambia el puerto) y en el despliegue recomendado
# (BFF detrás del mismo dominio que el SPA) — nunca hace falta "None".
SESSION_COOKIE_SAMESITE = "Lax"

# --- CSRF (double-submit cookie) --------------------------------------
# CSRF_COOKIE_HTTPONLY=False es intencional: el frontend necesita leer
# esta cookie por JS para mandarla de vuelta en el header X-CSRFToken
# (axios xsrfCookieName/xsrfHeaderName, valores default de Django —
# sin necesidad de renombrar nada acá). CORS_ALLOW_CREDENTIALS ya es
# True globalmente (config/settings.py), heredado por este archivo.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
# El browser manda Origin en toda request "unsafe" cross-origin (SPA
# en :5173 pegándole al BFF en :8010 son orígenes distintos aunque
# same-site) y Django valida ese Origin contra esta lista antes que
# nada — sin esto, el login siempre da 403 aunque cookie/header de CSRF
# coincidan perfecto.
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS", default="http://localhost:5173", cast=Csv()
)

# --- Login con Google (Authorization Code, ver bff/auth_views.py) -----
# Client ID/Secret con default vacío: el BFF arranca igual sin esto
# configurado (la feature simplemente responde 503 hasta que se setee),
# no tiene sentido que tumbe el servicio entero por un login opcional.
GOOGLE_CLIENT_ID = config("GOOGLE_CLIENT_ID", default="")
GOOGLE_CLIENT_SECRET = config("GOOGLE_CLIENT_SECRET", default="")
# Tiene que ser EXACTAMENTE la misma URL registrada como "Authorized
# redirect URI" en Google Cloud Console, esquema+host+puerto+path.
GOOGLE_REDIRECT_URI = config(
    "GOOGLE_REDIRECT_URI",
    default="http://localhost:8010/api/v1/bff/auth/google/callback/",
)
# FRONTEND_URL (a dónde manda el browser tras el callback) ya viene de
# config/settings.py — compartido con tickets.py para el link del
# correo de "ticket creado".
# Mismo secreto que accounts.py — ver el comentario ahí. Acá SÍ es
# requerido (sin default): sin él el BFF no podría llamar al endpoint
# protegido de accounts para mintear el JWT tras verificar Google.
INTERNAL_AUTH_SECRET = config("INTERNAL_AUTH_SECRET")
