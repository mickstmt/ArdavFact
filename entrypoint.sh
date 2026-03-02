#!/bin/bash
set -e

echo "=== ArdavFact: Iniciando contenedor ==="

# Aplicar migraciones de base de datos (seguro de correr en cada deploy)
echo "--- Aplicando migraciones de BD..."
flask db upgrade

echo "--- Iniciando Gunicorn..."
exec gunicorn \
    --bind 0.0.0.0:80 \
    --workers 1 \
    --timeout 600 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
