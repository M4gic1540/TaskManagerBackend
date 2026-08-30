#!/bin/sh
set -e

# Clasificador local de tickets (ver tickets/ml/): se entrena acá, no
# en el build de la imagen (ahí SECRET_KEY/DB_* todavía no existen
# como env vars) — con el dataset semilla + los tickets reales que ya
# haya en la BD. Solo aplica a los servicios que instalan la app
# 'tickets' (monolito, el microservicio tickets, y el poller de
# correo, que comparte imagen con tickets pero es OTRO contenedor sin
# volumen de modelo compartido — sin este paso el poller nunca tendría
# el artefacto y la clasificación de tickets creados por correo
# quedaría siempre en no-op).
train_classifier_if_applicable() {
    if [ "$DJANGO_SETTINGS_MODULE" = "config.settings" ] || [ "$DJANGO_SETTINGS_MODULE" = "config.service_settings.tickets" ]; then
        echo "Entrenando clasificador de tickets..."
        python manage.py train_ticket_classifier
    fi
}

# Si docker-compose pasa un comando explícito (ver servicio
# 'tickets-email-poller' en docker-compose.yml), correrlo en vez de
# seguir con el arranque normal de gunicorn.
#
# NO migra en este camino: el servicio web del mismo microservicio
# (tickets) ya migra esta misma base al arrancar. Si el poller también
# migrara, dos contenedores aplicarían `manage.py migrate` en paralelo
# contra la misma BD — sin lock de migración en Postgres, eso puede
# dejar una migración a medio aplicar. docker-compose.yml debe
# declarar `depends_on: tickets: condition: service_healthy` en
# 'tickets-email-poller' para garantizar que las migraciones ya
# corrieron antes de que este contenedor arranque.
if [ "$#" -gt 0 ]; then
    train_classifier_if_applicable
    echo "Ejecutando comando: $*"
    exec "$@"
fi

echo "Aplicando migraciones..."
python manage.py migrate --noinput

train_classifier_if_applicable

echo "Recolectando archivos estáticos..."
python manage.py collectstatic --noinput

echo "Iniciando gunicorn (uvicorn worker, sirve rutas sync y async)..."
exec gunicorn config.asgi:application \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers ${WEB_CONCURRENCY:-2} \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
