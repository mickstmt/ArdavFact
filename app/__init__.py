"""Factory principal de ArdavFact."""
import os
import logging
import structlog
from flask import Flask
from .config import config_map
from .extensions import db, migrate, login_manager, csrf, limiter


def create_app(config_name: str = None) -> Flask:
    """Crea y configura la aplicación Flask."""
    app = Flask(__name__)

    # Configuración
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    app.config.from_object(config_map.get(config_name, config_map['default']))

    # Crear directorios de archivos si no existen
    os.makedirs(app.config['COMPROBANTES_PATH'], exist_ok=True)
    os.makedirs(app.config['UPLOADS_PATH'], exist_ok=True)

    # Inicializar extensiones
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Importar modelos para que Flask-Migrate los detecte
    with app.app_context():
        from . import models  # noqa: F401

    # Configurar logging estructurado
    _configure_logging(app)

    # Registrar blueprints
    _register_blueprints(app)

    # Registrar health check
    _register_health(app)

    # Inicializar scheduler (no corre en TESTING)
    from .services.scheduler_service import init_scheduler
    init_scheduler(app)

    # Headers de seguridad HTTP
    _register_security_headers(app)

    return app


def _configure_logging(app: Flask) -> None:
    """Configura logging estructurado con structlog."""
    log_level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(message)s')

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt='iso'),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def _register_blueprints(app: Flask) -> None:
    """Registra todos los blueprints de la aplicación."""
    from .blueprints.auth import auth_bp
    from .blueprints.dashboard import dashboard_bp
    from .blueprints.ventas import ventas_bp
    from .blueprints.comprobantes import comprobantes_bp
    from .blueprints.notas import notas_bp
    from .blueprints.bulk import bulk_bp
    from .blueprints.productos import productos_bp
    from .blueprints.reportes import reportes_bp
    from .blueprints.admin import admin_bp
    from .blueprints.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(comprobantes_bp)
    app.register_blueprint(notas_bp)
    app.register_blueprint(bulk_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(reportes_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)


def _register_security_headers(app: Flask) -> None:
    """Agrega headers de seguridad HTTP a todas las respuestas."""
    from flask import request as _req

    @app.after_request
    def set_security_headers(response):
        # Evita MIME-sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Protección básica XSS (IE/Edge legacy)
        response.headers['X-XSS-Protection'] = '1; mode=block'
        # Evita embeber en iframes de otros dominios
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Referrer seguro
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Permissions Policy
        response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
        # Content Security Policy
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://code.jquery.com https://cdn.jsdelivr.net/npm/sweetalert2@11; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "frame-ancestors 'self';"
        )
        # HSTS solo en producción (no en dev/test para evitar problemas con HTTP local)
        if not app.debug and not app.testing:
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        return response


def _register_health(app: Flask) -> None:
    """Registra el endpoint de health check y el redirect del favicon."""
    from flask import jsonify, redirect, url_for
    from sqlalchemy import text

    @app.route('/health')
    def health():
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify({'status': 'ok', 'database': 'connected'}), 200
        except Exception as e:
            return jsonify({'status': 'error', 'database': str(e)}), 500

    @app.route('/favicon.ico')
    def favicon():
        return redirect(url_for('static', filename='favicon.ico'))
