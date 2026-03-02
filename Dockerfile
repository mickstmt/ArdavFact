FROM python:3.11-slim

# Dependencias del sistema para ReportLab, lxml, psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libpq-dev \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Crear directorios de archivos persistentes (los volúmenes los sobrescribirán en runtime)
RUN mkdir -p comprobantes uploads certificados

# Variables de entorno para producción
ENV FLASK_ENV=production
ENV FLASK_APP=wsgi.py

EXPOSE 80

# El entrypoint corre migraciones y luego arranca Gunicorn
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
