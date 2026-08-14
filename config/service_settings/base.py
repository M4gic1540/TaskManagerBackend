"""Base común para settings de microservicio: reexporta todo lo del
monolito (config.settings) y cada servicio recorta/sobreescribe lo que
no necesita (INSTALLED_APPS, MIDDLEWARE, DATABASES, ROOT_URLCONF,
autenticación). No se usa directamente como DJANGO_SETTINGS_MODULE."""
import os

# config.settings construye incondicionalmente DATABASES["glpi"] (con
# credenciales reales, sin default — fail-closed a propósito) al
# importarse, sin importar qué servicio lo esté importando. Solo
# inventory.py necesita esas credenciales de verdad, y las vuelve a
# leer por su cuenta más abajo con el mismo criterio fail-closed — acá
# solo se evita que accounts/tickets/gateway (que reemplazan DATABASES
# por completo después de este import) revienten en el arranque por no
# tener credenciales de una BD externa que ni siquiera van a usar.
os.environ.setdefault("DB_HOST", "unused")
os.environ.setdefault("DB_USER", "unused")
os.environ.setdefault("DB_PASSWORD", "unused")

from config.settings import *  # noqa: F401,F403,E402  # NOSONAR (patrón estándar de settings por herencia)
