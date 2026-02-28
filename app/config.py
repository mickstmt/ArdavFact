"""Configuraciones por entorno para ArdavFact."""
import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuración base compartida por todos los entornos."""

    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-cambiar-en-produccion')

    # Base de datos
    DB_USER = os.environ.get('DB_USER', 'postgres')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME', 'ardavfact')
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # WooCommerce
    WOO_URL = os.environ.get('WOO_URL', '')
    WOO_CONSUMER_KEY = os.environ.get('WOO_CONSUMER_KEY', '')
    WOO_CONSUMER_SECRET = os.environ.get('WOO_CONSUMER_SECRET', '')

    # APIs Peru
    APISPERU_TOKEN = os.environ.get('APISPERU_TOKEN', '')

    # SUNAT / MiPSE
    SUNAT_AMBIENTE = os.environ.get('SUNAT_AMBIENTE', 'BETA')
    CERT_PATH = os.environ.get('CERT_PATH', 'certificados/certificado_ml.pfx')
    CERT_PASSWORD = os.environ.get('CERT_PASSWORD', '')
    MIPSE_URL = os.environ.get('MIPSE_URL', 'https://api.mipse.pe')
    MIPSE_SYSTEM = os.environ.get('MIPSE_SYSTEM', 'beta')
    MIPSE_USUARIO = os.environ.get('MIPSE_USUARIO', '')
    MIPSE_PASSWORD = os.environ.get('MIPSE_PASSWORD', '')

    # Empresa
    EMPRESA_RUC = os.environ.get('EMPRESA_RUC', '20605555790')
    EMPRESA_RAZON_SOCIAL = os.environ.get(
        'EMPRESA_RAZON_SOCIAL', 'M & L IMPORT EXPORT PERU S.A.C.'
    )
    EMPRESA_NOMBRE_COMERCIAL = os.environ.get(
        'EMPRESA_NOMBRE_COMERCIAL', 'M & L Import Export'
    )
    EMPRESA_DIRECCION = os.environ.get('EMPRESA_DIRECCION', '')
    EMPRESA_TELEFONO = os.environ.get('EMPRESA_TELEFONO', '')
    EMPRESA_EMAIL = os.environ.get('EMPRESA_EMAIL', '')
    EMPRESA_UBIGEO = os.environ.get('EMPRESA_UBIGEO', '')

    # Series de comprobantes
    SERIE_FACTURA = os.environ.get('SERIE_FACTURA', 'F001')
    SERIE_BOLETA = os.environ.get('SERIE_BOLETA', 'B001')
    SERIE_NC_FACTURA = os.environ.get('SERIE_NC_FACTURA', 'FC01')
    SERIE_NC_BOLETA = os.environ.get('SERIE_NC_BOLETA', 'BC01')
    SERIE_ND_FACTURA = os.environ.get('SERIE_ND_FACTURA', 'FD01')
    SERIE_ND_BOLETA = os.environ.get('SERIE_ND_BOLETA', 'BD01')

    # Rutas de archivos
    COMPROBANTES_PATH = os.environ.get('COMPROBANTES_PATH', 'comprobantes')
    UPLOADS_PATH = os.environ.get('UPLOADS_PATH', 'uploads')

    # Scheduler
    HORARIOS_ENVIO = os.environ.get('HORARIOS_ENVIO', '21:00')

    # Correos autorizados para registro
    AUTHORIZED_EMAILS = [
        e.strip()
        for e in os.environ.get('AUTHORIZED_EMAILS', '').split(',')
        if e.strip()
    ]

    # Rate limiting
    RATELIMIT_STORAGE_URL = 'memory://'
    RATELIMIT_DEFAULT = '200 per day;60 per hour'


class DevelopmentConfig(Config):
    """Configuración para desarrollo local."""
    DEBUG = True
    SQLALCHEMY_ECHO = False  # Cambiar a True para ver SQL en consola


class ProductionConfig(Config):
    """Configuración para producción."""
    DEBUG = False
    SQLALCHEMY_ECHO = False

    # En producción, SESSION_COOKIE_SECURE debe ser True (HTTPS)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True


class TestingConfig(Config):
    """Configuración para tests automatizados."""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}
