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

RUN mkdir -p /app/staticfiles /app/media

EXPOSE 8000

# Entrypoint aplica migraciones y collectstatic antes de arrancar
# gunicorn — un solo camino de arranque, sin importar dónde corra.
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
