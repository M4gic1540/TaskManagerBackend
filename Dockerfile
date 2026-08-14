FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# build-essential: por si alguna dependencia necesita compilar (pymysql
# usa el driver puro-Python, pero Pillow/otras pueden requerir headers).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt gunicorn uvicorn[standard]

COPY . .
COPY entrypoint.sh /app/entrypoint.sh

# No correr como root: usuario dedicado sin privilegios para el proceso
# de la app (gunicorn/entrypoint). Solo staticfiles/media quedan a su
# nombre (lo único que escribe en runtime); el resto del código y el
# entrypoint quedan root:root de solo lectura, para que un proceso
# comprometido no pueda modificar su propio código de arranque.
RUN mkdir -p /app/staticfiles /app/media \
    && chmod +x /app/entrypoint.sh \
    && groupadd --system app \
    && useradd --system --gid app --home /app app \
    && chown -R app:app /app/staticfiles /app/media
USER app

EXPOSE 8000

# Entrypoint aplica migraciones y collectstatic antes de arrancar
# gunicorn — un solo camino de arranque, sin importar dónde corra.
ENTRYPOINT ["/app/entrypoint.sh"]
