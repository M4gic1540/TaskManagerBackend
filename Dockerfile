FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# build-essential: por si alguna dependencia necesita compilar (pymysql
# usa el driver puro-Python, pero Pillow/otras pueden requerir headers).
# libldap2-dev/libsasl2-dev: headers que python-ldap (django-auth-ldap,
# ver config/settings.py) necesita para compilar contra OpenLDAP.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libldap2-dev \
    libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn uvicorn[standard]

# ARG/ENV de SERVICE_SETTINGS van DESPUÉS de pip install a propósito:
# así esa capa (la más pesada del build) queda idéntica y cacheada entre
# las 4 variantes (monolito + accounts/tickets/inventory/gateway) — antes
# vivía antes del pip install y el cache se invalidaba en cascada para
# las 4, forzando reinstalar requirements.txt en cada una.
# Default = monolito completo (config.settings): así `docker build .`
# sin --build-arg (exactamente como lo llama el Jenkinsfile hoy) sigue
# produciendo la misma imagen de siempre. Para un microservicio:
# `docker build --build-arg SERVICE_SETTINGS=config.service_settings.tickets .`
ARG SERVICE_SETTINGS=config.settings
ENV DJANGO_SETTINGS_MODULE=${SERVICE_SETTINGS}

COPY . .
COPY entrypoint.sh /app/entrypoint.sh

# No correr como root: usuario dedicado sin privilegios para el proceso
# de la app (gunicorn/entrypoint). Solo staticfiles/media/data/tickets/ml/model
# quedan a su nombre (lo único que escribe en runtime — 'data' es donde
# docker-compose monta el volumen con la sqlite de cada microservicio;
# tickets/ml/model/ es donde entrypoint.sh escribe el artefacto del
# clasificador de tickets al arrancar, ver train_ticket_classifier);
# el resto del código y el entrypoint quedan root:root de solo lectura,
# para que un proceso comprometido no pueda modificar su propio código
# de arranque.
RUN mkdir -p /app/staticfiles /app/media /app/data /app/tickets/ml/model \
    && chmod +x /app/entrypoint.sh \
    && groupadd --system app \
    && useradd --system --gid app --home /app app \
    && chown -R app:app /app/staticfiles /app/media /app/data /app/tickets/ml/model
USER app

EXPOSE 8000

# Entrypoint aplica migraciones y collectstatic antes de arrancar
# gunicorn — un solo camino de arranque, sin importar dónde corra.
ENTRYPOINT ["/app/entrypoint.sh"]
